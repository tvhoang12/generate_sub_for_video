"""Source clean-up and translation of subtitle lines, with validation and retry."""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..languages import Language
from .homophones import get_homophone_cleaning_prompt, get_homophone_translation_prompt
from .providers import LLMProvider, ProviderError, TokenOverflowError
from .schemas import BatchItem, BatchTranslateResult, CleanResult, HomophoneCorrection, TermSuggestion, TranslateResult

log = logging.getLogger("substudio.translator")

MAX_ATTEMPTS = 3

# Leak detection regexes
THAI_LEAK_RE = re.compile(r"[\u0E00-\u0E7F]")
CJK_LEAK_RE = re.compile(r"[\u4E00-\u9FFF]")

# Language-specific rules for 8 supported languages
LANGUAGE_RULES: dict[str, str] = {
    "lo": (
        "STRICT LAO LANGUAGE RULES:\n"
        "- Script: Write strictly in pure Lao script (ອັກສອນລາວ, Unicode 0E80-0EFF). Absolutely NEVER use any Thai script or characters (ภาษาไทย, Unicode 0E00-0E7F).\n"
        "- Vocabulary: Use pure Lao vocabulary. Do NOT use Thai words (e.g. use ເລື່ອງ not เรื่อง, use ຢູ່ not อยู่, use ບອກ not บอก, use ຫຍັງ not อะไร/หยัง).\n"
        "- Spacing: Do not put spaces between individual words in a phrase. Insert spaces ONLY between distinct phrases or clauses.\n"
        "- Pronouns & Register: Natural Lao conversational pronouns suited to the scene (ຂ້ອຍ/ເຈົ້າ, ອ້າຍ/ນ້ອງ, ເຮົາ/ໂຕ, ທ່ານ)."
    ),
    "my": (
        "STRICT BURMESE (MYANMAR) LANGUAGE RULES:\n"
        "- Style: MANDATORY colloquial/spoken style (စကားပြောဟန် using endings like တယ်, မယ်, တာ). Absolutely FORBID formal literary style (စာရေးဟန် using သည်, ၏, ၌).\n"
        "- Script & Spacing: Use standard Myanmar Unicode (never Zawgyi). Do NOT space between individual syllables within words; space only between phrase/clause boundaries.\n"
        "- Particles & Politeness: Use natural conversational sentence-final particles and pronouns matching character age and gender (ပါ, နော်, ဗျာ, ရှင့်)."
    ),
    "km": (
        "STRICT KHMER LANGUAGE RULES:\n"
        "- Spacing: Do NOT place spaces between words within a phrase or compound. Spaces in Khmer act ONLY as phrase/sentence punctuation.\n"
        "- Pronouns & Hierarchy: Strictly distinguish pronouns according to social status, age, and relationship (បង/អូន, ខ្ញុំ/អ្នក, លោក/នាង, ឯង).\n"
        "- Natural Phrasing: Natural spoken Khmer that flows rhythmically on screen."
    ),
    "th": (
        "STRICT THAI LANGUAGE RULES:\n"
        "- Spacing: Write continuously without spaces between words. Spaces are used ONLY between clauses and sentences.\n"
        "- Pronoun Consistency: Lock pronoun pairs according to character relationship and genre: modern (พี่/น้อง, ฉัน/เธอ, ผม/คุณ, กู/มึง) or period drama (ข้า/เจ้า/ท่าน). Never switch pronouns erratically.\n"
        "- Conversational Particles: Natural conversational ending particles matching tone and gender (ครับ, ค่ะ, นะ, สิ, วะ)."
    ),
    "vi": (
        "STRICT VIETNAMESE LANGUAGE RULES:\n"
        "- Pronoun Consistency: Lock pronoun pairs strictly based on genre: modern (anh/em, tôi/cậu, mày/tao) or period/costume drama (ta/ngươi, huynh/muội, bổn vương/thuộc hạ). Never switch pronouns erratically within a scene.\n"
        "- Natural Flow: Idiomatic conversational Vietnamese suited to short drama dialogue speed."
    ),
    "id": (
        "STRICT INDONESIAN LANGUAGE RULES:\n"
        "- Register: Strictly maintain register consistency throughout: colloquial/daily (aku/kamu, gue/lo, kak/dek) vs. formal/period drama (saya/Anda, aku/kau, tuan/nyonya). Do NOT mix slang with royal/period terms in the same dialogue."
    ),
    "en": (
        "STRICT ENGLISH LANGUAGE RULES:\n"
        "- Tone: Natural, concise spoken English suited to fast reading speed.\n"
        "- Honorifics: Naturally adapt Asian honorifics and forms of address into natural English phrasing or respectful tone rather than awkward literal transliterations."
    ),
    "zh": (
        "STRICT SIMPLIFIED CHINESE LANGUAGE RULES:\n"
        "- Script: Strictly Simplified Chinese (简体中文). Absolutely NO Traditional Chinese characters (繁體字).\n"
        "- Style: Natural spoken dialogue (口语化). Omit sentence-final periods or commas in subtitle lines.\n"
        "- Honorifics: Appropriately distinguish polite 您 from standard 你."
    ),
}


def get_language_specific_rules(lang_code: str) -> str:
    code = lang_code.lower().strip()
    if code in LANGUAGE_RULES:
        return LANGUAGE_RULES[code]
    if code.startswith("zh"):
        return LANGUAGE_RULES["zh"]
    for k, v in LANGUAGE_RULES.items():
        if code.startswith(k) or k.startswith(code):
            return v
    return ""


def clean_sub_text(text: str, lang_code: str = "") -> str:
    """Strip bracketed notes and lingering annotations like (Bồ) or [note], and sanitize script."""
    cleaned = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", text).strip()
    code = lang_code.lower().strip()
    if code == "lo":
        # Convert any lingering Thai unicode characters (0x0E00-0x0E7F) to Lao (0x0E80-0x0EFF)
        res = []
        for ch in cleaned:
            cp = ord(ch)
            if 0x0E01 <= cp <= 0x0E5B:
                lao_cp = cp + 0x80
                if 0x0E81 <= lao_cp <= 0x0EDD:
                    res.append(chr(lao_cp))
                else:
                    res.append("")
            else:
                res.append(ch)
        cleaned = "".join(res).strip()
    if not code.startswith("zh"):
        # Strip any un-translated Chinese characters from non-Chinese target subtitles
        cleaned = re.sub(r"[\u4E00-\u9FFF]", "", cleaned).strip()
    return cleaned or text.strip()


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

    def _build_target_glossary_block(self, lang_code: str) -> str:
        """Isolate glossary entries strictly to the target language to prevent cross-language leakage."""
        code = lang_code.lower().strip()
        rows = []
        for term, entry in sorted(self.glossary.items()):
            translations = entry.get("translations", {})
            target_trans = translations.get(code, "")
            note = entry.get("note", "")
            if target_trans or note:
                item: dict[str, str] = {"term": term}
                if target_trans:
                    item["translation"] = target_trans
                if note:
                    item["note"] = note
                rows.append(item)
        if not rows:
            return "(none)"
        return json.dumps(rows, ensure_ascii=False, indent=1)

    def _validate_translation_line(
        self, text: str, lang: Language, kept_terms: list[str]
    ) -> str | None:
        cleaned = text.strip()
        if not cleaned:
            return "line is empty"
        if "[" in cleaned or "]" in cleaned:
            return "contains square brackets"
        if len(cleaned.split("\n")) > 2:
            return "exceeds maximum of 2 lines"

        stripped = cleaned
        for term in kept_terms:
            if term:
                stripped = stripped.replace(term, "")

        code = lang.code.lower().strip()
        # Lao check: reject any Thai characters
        if code == "lo" and THAI_LEAK_RE.search(stripped):
            found_thai = "".join(THAI_LEAK_RE.findall(stripped)[:5])
            return f"contains Thai characters ({found_thai})"

        # Non-Chinese check: reject un-translated Chinese characters
        if not code.startswith("zh") and CJK_LEAK_RE.search(stripped):
            found_cjk = "".join(CJK_LEAK_RE.findall(stripped)[:5])
            return f"contains un-translated Chinese characters ({found_cjk})"

        # Script check if required
        if lang.script and not lang.script.search(stripped) and any(ch.isalpha() for ch in stripped):
            return f"not written in {lang.english_name} script"

        return None

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

    def clean(self, lines: list[dict], source_language: str = "zh") -> CleanResult:
        """lines: [{"id", "text"}] straight from speech recognition."""
        homophone_prompt = get_homophone_cleaning_prompt(source_language)
        homophone_section = f"\n\n{homophone_prompt}\n" if homophone_prompt else ""

        user = f"""Below are subtitle lines produced by automatic speech recognition for one episode. Background music makes some lines wrong.
Episode notes from the editor: {self.episode_notes or "(none)"}

For every line, return the corrected text in the original spoken language:
- Fix misheard words and names using the film context, glossary and surrounding lines.
- Keep one output line per input line with the same id; do not merge, split, reorder or drop lines.
- Set unclear=true only when a line is unintelligible and you cannot reconstruct it with confidence; still return your best guess as text.
- In new_terms, list character names, places and recurring terms that appear in these lines but not in the glossary (empty list if none).
{homophone_section}
{_lines_block(lines)}"""
        expected = [l["id"] for l in lines]
        return self._call(user, CleanResult, lambda r: _check_ids(expected, [l.id for l in r.lines]))

    def translate(self, lines: list[dict], lang: Language, source_language: str = "zh") -> TranslateResult:
        homophone_note = get_homophone_translation_prompt(source_language)
        homophone_rule = f"- {homophone_note}\n" if homophone_note else ""
        lang_rules = get_language_specific_rules(lang.code)
        lang_rules_section = f"\n<language_rules code=\"{lang.code}\">\n{lang_rules}\n</language_rules>\n" if lang_rules else ""
        glossary_block = self._build_target_glossary_block(lang.code)

        user = f"""<target code="{lang.code}">{lang.english_name}</target>
Episode notes from the editor: {self.episode_notes or "(none)"}

<target_glossary>
{glossary_block}
</target_glossary>
{lang_rules_section}
Translate every subtitle line below strictly and 100% into {lang.english_name} for viewers in that market:
- Natural spoken {lang.english_name} that fits the characters and the scene, not word-for-word.
- At most 2 lines per subtitle and about {lang.max_line_chars} characters per line; break with \\n at a natural phrase boundary.
- Keep pronouns and forms of address consistent with each character's gender, age and relationship.
{homophone_rule}- Same ids as the input, one output line per input line.
- Output ONLY the subtitle text in {lang.english_name}: absolutely no notes, no brackets, no romanisation, and no characters from other languages.

{_lines_block(lines)}"""
        expected = [l["id"] for l in lines]
        kept_terms = [
            t for term, e in self.glossary.items()
            for t in (term, e.get("translations", {}).get(lang.code, ""))
            if t
        ]

        def validate(result: TranslateResult) -> str | None:
            problem = _check_ids(expected, [l.id for l in result.lines])
            if problem:
                return problem
            bad_reasons = []
            for line in result.lines:
                err = self._validate_translation_line(line.text, lang, kept_terms)
                if err:
                    bad_reasons.append(f"line {line.id}: {err}")
            if bad_reasons:
                return "; ".join(bad_reasons[:5])
            return None

        return self._call(user, TranslateResult, validate)

    def extract_global_context(self, raw_transcript: str) -> str:
        """Step 1: Extract global context under 150 words strictly in technical English."""
        user = f"""Below is the raw speech transcript from the video/episode:
<raw_transcript>
{raw_transcript[:15000]}
</raw_transcript>

Episode notes from editor: {self.episode_notes or "(none)"}

Summarise the key context in UNDER 150 WORDS strictly in technical English:
1. Genre, Setting & Tone: Core genre, setting, atmosphere, and conversational dynamic.
2. Character Matrix & Hierarchy: Character identities, roles, genders, relationships, social hierarchy, and appropriate forms of address.
3. Key Proper Nouns & Recurring Terms: Core proper names, titles, and recurring terms with their original native spelling in square brackets (e.g., [蒲先生], [胡])."""
        return self.provider.extract_global_context(self.system, user)

    def translate_in_batches(
        self,
        cues: list[Any],
        lang: Language,
        source_language: str = "zh",
        global_context: str = "",
        batch_size: int = 35,
    ) -> tuple[dict[int, str], dict[int, str]]:
        """Steps 2, 3, 4: Chunk into batches of 35, use sliding window previous_context, auto-split retry."""
        fixed_src_by_id: dict[int, str] = {}
        trans_by_id: dict[int, str] = {}

        homophone_note = get_homophone_translation_prompt(source_language)
        homophone_rule = f"- {homophone_note}\n" if homophone_note else ""
        lang_rules = get_language_specific_rules(lang.code)
        lang_rules_section = f"\n<language_rules code=\"{lang.code}\">\n{lang_rules}\n</language_rules>\n" if lang_rules else ""
        glossary_block = self._build_target_glossary_block(lang.code)
        kept_terms = [
            t for term, e in self.glossary.items()
            for t in (term, e.get("translations", {}).get(lang.code, ""))
            if t
        ]

        def _process_chunk(items: list[Any], prev_cues: list[Any], attempt: int = 1) -> list[BatchItem]:
            batch_payload = [{"id": c.id, "src": c.text} for c in items]
            prev_payload = [
                {"id": c.id, "src": fixed_src_by_id.get(c.id, c.text), "trans": trans_by_id.get(c.id, "")}
                for c in prev_cues
            ]

            user_prompt = f"""<global_context>
{global_context or "(not provided)"}
</global_context>

<target_glossary>
{glossary_block}
</target_glossary>

<previous_context note="The last 3 lines for dialogue continuity. Do NOT translate them again.">
{json.dumps(prev_payload, ensure_ascii=False) if prev_payload else "(none - start of video)"}
</previous_context>
{lang_rules_section}
<target code="{lang.code}">{lang.english_name}</target>
Translate every subtitle line in <batch> strictly and 100% into natural {lang.english_name}:
- Natural spoken phrasing suited to the characters and scene.
- At most 2 lines per subtitle, about {lang.max_line_chars} characters per line; break with \\n at natural phrase boundaries.
- Keep pronouns and forms of address consistent with <global_context>.
{homophone_rule}- Output ONLY the translated subtitle text in {lang.english_name}: absolutely no notes, no brackets, no romanisation, and no foreign characters.
- In 'fixed_src', provide the corrected source text (fixing any misheard homophone/near-homophone errors).
- In 'trans', provide the target translation.
- Preserve exact ids for all input items.

<batch>
{json.dumps(batch_payload, ensure_ascii=False)}
</batch>"""

            expected_ids = [c.id for c in items]
            batch_items: list[BatchItem] = []
            try:
                batch_items = self.provider.complete_batch(self.system, user_prompt)
                got_ids = set(it.id for it in batch_items)
                missing = [c.id for c in items if c.id not in got_ids]
                if missing:
                    raise TokenOverflowError(f"Missing {len(missing)} items ({missing}) from batch response")

                # Validate every line in batch_items
                validation_errors = []
                for it in batch_items:
                    err = self._validate_translation_line(it.trans, lang, kept_terms)
                    if err:
                        validation_errors.append(f"item {it.id}: {err}")
                if validation_errors:
                    raise ValueError(f"Batch validation failed: {'; '.join(validation_errors[:5])}")

                return batch_items
            except (TokenOverflowError, ValueError, Exception) as e:
                err_msg = str(e).lower()
                if len(items) > 1 and (
                    isinstance(e, (TokenOverflowError, ValueError))
                    or "validation" in err_msg
                    or "max_token" in err_msg
                    or "json" in err_msg
                    or "overflow" in err_msg
                    or "missing" in err_msg
                ):
                    log.warning("Batch %d items failed (%s), auto-splitting in half...", len(items), e)
                    mid = len(items) // 2
                    first_half = items[:mid]
                    second_half = items[mid:]
                    res1 = _process_chunk(first_half, prev_cues)
                    for item in res1:
                        trans_by_id[item.id] = clean_sub_text(item.trans, lang.code)
                        fixed_src_by_id[item.id] = item.fixed_src.strip()
                    part2_prev = (prev_cues + first_half)[-3:]
                    res2 = _process_chunk(second_half, part2_prev)
                    return res1 + res2
                elif len(items) == 1 and attempt < 3:
                    log.warning("Single item %d failed validation (%s), retrying (attempt %d)...", items[0].id, e, attempt + 1)
                    return _process_chunk(items, prev_cues, attempt=attempt + 1)
                elif len(items) == 1 and batch_items:
                    log.warning("Single item %d failed validation after %d attempts, sanitizing...", items[0].id, attempt)
                    return [
                        BatchItem(id=it.id, fixed_src=it.fixed_src, trans=clean_sub_text(it.trans, lang.code))
                        for it in batch_items
                    ]
                raise

        # Iterate sequentially with sliding window of 35 items
        for i in range(0, len(cues), batch_size):
            chunk = cues[i : i + batch_size]
            prev_chunk = cues[max(0, i - 3) : i]
            items = _process_chunk(chunk, prev_chunk)
            for item in items:
                fixed_src_by_id[item.id] = item.fixed_src.strip()
                trans_by_id[item.id] = clean_sub_text(item.trans, lang.code)

        # Fallback for any missing IDs: NEVER copy raw foreign source text into trans!
        missing_cues = [c for c in cues if c.id not in trans_by_id]
        if missing_cues:
            log.warning("Translating %d missing cues with fallback single-batch translation...", len(missing_cues))
            missing_payload = [{"id": c.id, "text": fixed_src_by_id.get(c.id, c.text)} for c in missing_cues]
            try:
                res = self.translate(missing_payload, lang, source_language)
                for line in res.lines:
                    trans_by_id[line.id] = clean_sub_text(line.text, lang.code)
            except Exception as e:
                log.error("Fallback translation for missing cues failed: %s", e)

        # Ensure all cues have fixed_src_by_id and trans_by_id entries
        for c in cues:
            if c.id not in fixed_src_by_id:
                fixed_src_by_id[c.id] = c.text
            if c.id not in trans_by_id:
                trans_by_id[c.id] = ""

        return fixed_src_by_id, trans_by_id


def merge_term_suggestions(existing: set[str], suggestions: list[TermSuggestion]) -> list[TermSuggestion]:
    seen = {t.casefold() for t in existing}
    fresh = []
    for s in suggestions:
        key = s.term.strip().casefold()
        if key and key not in seen:
            seen.add(key)
            fresh.append(s)
    return fresh
