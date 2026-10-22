"""Source clean-up and translation of subtitle lines, with validation and retry."""

import json
from dataclasses import dataclass, field

from ..languages import Language
from .providers import LLMProvider, ProviderError
from .schemas import CleanResult, TermSuggestion, TranslateResult

MAX_ATTEMPTS = 3


class TranslationError(RuntimeError):
    pass


@dataclass
class FilmContext:
    name: str
    synopsis: str = ""
    characters: str = ""
    style_notes: str = ""
    episode_notes: str = ""
    # term -> {"note": str, "translations": {lang_code: str}}
    glossary: dict[str, dict] = field(default_factory=dict)


def build_system_prompt(film: FilmContext) -> str:
    glossary_rows = [
        {"term": term, "note": entry.get("note", ""), "translations": entry.get("translations", {})}
        for term, entry in sorted(film.glossary.items())
    ]
    return f"""You are the subtitle editor and translator for a short drama series. You correct speech-recognition transcripts and translate them into subtitles viewers read at speed.

<film>
Title: {film.name}
Synopsis: {film.synopsis or "(not provided)"}
Characters: {film.characters or "(not provided)"}
Tone and style: {film.style_notes or "(not provided)"}
</film>

<glossary>
{json.dumps(glossary_rows, ensure_ascii=False, indent=1) if glossary_rows else "(empty)"}
</glossary>

Glossary entries are binding: spell a term exactly as listed, and when a translation exists for the target language, use it every time. Names the glossary lacks must still be rendered the same way throughout the episode."""


def _lines_block(lines: list[dict]) -> str:
    return "<lines>\n" + json.dumps(lines, ensure_ascii=False) + "\n</lines>"


def _check_ids(expected: list[int], got: list[int]) -> str | None:
    if sorted(got) != sorted(expected):
        missing = sorted(set(expected) - set(got))
        extra = sorted(set(got) - set(expected))
        return f"ids must match the input exactly; missing={missing} extra={extra}"
    return None


class Translator:
    def __init__(self, provider: LLMProvider, film: FilmContext) -> None:
        self.provider = provider
        self.system = build_system_prompt(film)
        self.episode_notes = film.episode_notes
        self.glossary = film.glossary

    def _call(self, user: str, schema, validate):
        feedback = ""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            prompt = user if not feedback else f"{user}\n\nYour previous answer was rejected: {feedback}\nReturn the full corrected answer."
            try:
                result = self.provider.complete(self.system, prompt, schema)
            except ProviderError as e:
                feedback = str(e)
                continue
            feedback = validate(result)
            if feedback is None:
                return result
        raise TranslationError(f"Không nhận được kết quả hợp lệ sau {MAX_ATTEMPTS} lần thử: {feedback}")

    def clean(self, lines: list[dict]) -> CleanResult:
        """lines: [{"id", "text"}] straight from speech recognition."""
        user = f"""Below are subtitle lines produced by automatic speech recognition for one episode. Background music makes some lines wrong.
Episode notes from the editor: {self.episode_notes or "(none)"}

For every line, return the corrected text in the original spoken language:
- Fix misheard words and names using the film context, glossary and surrounding lines.
- Keep one output line per input line with the same id; do not merge, split, reorder or drop lines.
- Set unclear=true only when a line is unintelligible and you cannot reconstruct it with confidence; still return your best guess as text.
- In new_terms, list character names, places and recurring terms that appear in these lines but not in the glossary (empty list if none).

{_lines_block(lines)}"""
        expected = [l["id"] for l in lines]
        return self._call(user, CleanResult, lambda r: _check_ids(expected, [l.id for l in r.lines]))

    def translate(self, lines: list[dict], lang: Language) -> TranslateResult:
        user = f"""<target code="{lang.code}">{lang.english_name}</target>
Episode notes from the editor: {self.episode_notes or "(none)"}

Translate every subtitle line below into {lang.english_name} for viewers in that market:
- Natural spoken {lang.english_name} that fits the characters and the scene, not word-for-word.
- At most 2 lines per subtitle and about {lang.max_line_chars} characters per line; break with \\n at a natural phrase boundary (this matters for scripts written without spaces).
- Keep pronouns and forms of address consistent with each character's gender, age and relationship.
- Same ids as the input, one output line per input line.
- Output only the subtitle text: no notes, brackets, romanisation or text in other languages.

{_lines_block(lines)}"""
        expected = [l["id"] for l in lines]
        # A line may legitimately be just a name the glossary keeps in Latin letters ("Kestrel!").
        kept_terms = [t for term, e in self.glossary.items() for t in (term, e.get("translations", {}).get(lang.code, "")) if t]

        def needs_script(text: str) -> bool:
            for term in kept_terms:
                text = text.replace(term, "")
            return any(ch.isalpha() for ch in text)

        def validate(result: TranslateResult) -> str | None:
            problem = _check_ids(expected, [l.id for l in result.lines])
            if problem:
                return problem
            bad = []
            for line in result.lines:
                text = line.text.strip()
                if not text or "[" in text or len(text.split("\n")) > 2:
                    bad.append(line.id)
                elif lang.script and not lang.script.search(text) and needs_script(text):
                    bad.append(line.id)
            if bad:
                return f"lines {bad} are empty, longer than 2 lines, contain brackets, or are not written in {lang.english_name} script"
            return None

        return self._call(user, TranslateResult, validate)


def merge_term_suggestions(existing: set[str], suggestions: list[TermSuggestion]) -> list[TermSuggestion]:
    seen = {t.casefold() for t in existing}
    fresh = []
    for s in suggestions:
        key = s.term.strip().casefold()
        if key and key not in seen:
            seen.add(key)
            fresh.append(s)
    return fresh
