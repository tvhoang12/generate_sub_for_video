import pytest

from app.languages import get_language
from app.translation.schemas import TermSuggestion, TranslateResult, TranslatedLine
from app.translation.translator import (
    FilmContext,
    TranslationError,
    Translator,
    build_system_prompt,
    merge_term_suggestions,
)

LINES = [{"id": 1, "text": "Kestrel, right on schedule."}, {"id": 2, "text": "Kestrel!"}]


class ScriptedProvider:
    """Returns the queued answers in order and records the prompts it was given."""

    name = "scripted"

    def __init__(self, *answers):
        self.answers = list(answers)
        self.prompts = []

    def complete(self, system, user, schema):
        self.prompts.append(user)
        return self.answers.pop(0)


def lao(*pairs):
    return TranslateResult(lines=[TranslatedLine(id=i, text=t) for i, t in pairs])


def test_wrong_ids_are_retried_with_feedback():
    provider = ScriptedProvider(lao((1, "ເຄສເທຣລ, ມາຕົງເວລາ.")), lao((1, "ເຄສເທຣລ, ມາຕົງເວລາ."), (2, "ເຄສເທຣລ!")))
    result = Translator(provider, FilmContext(name="Mirror")).translate(LINES, get_language("lo"))
    assert [l.id for l in result.lines] == [1, 2]
    assert "missing=[2]" in provider.prompts[1]


def test_latin_text_is_rejected_for_lao():
    provider = ScriptedProvider(*[lao((1, "Kestrel, right on time."), (2, "Kestrel!"))] * 3)
    with pytest.raises(TranslationError):
        Translator(provider, FilmContext(name="Mirror")).translate(LINES, get_language("lo"))


def test_a_glossary_name_kept_in_latin_is_accepted():
    film = FilmContext(name="Mirror", glossary={"Kestrel": {"note": "courier", "translations": {"lo": "Kestrel"}}})
    provider = ScriptedProvider(lao((1, "Kestrel, ມາຕົງເວລາ."), (2, "Kestrel!")))
    result = Translator(provider, film).translate(LINES, get_language("lo"))
    assert result.lines[1].text == "Kestrel!"


def test_review_markers_never_reach_subtitles():
    provider = ScriptedProvider(*[lao((1, "[CẦN KIỂM TRA]"), (2, "ເຄສເທຣລ!"))] * 3)
    with pytest.raises(TranslationError):
        Translator(provider, FilmContext(name="Mirror")).translate(LINES, get_language("lo"))


def test_system_prompt_carries_film_context_and_glossary():
    film = FilmContext(name="The Mirror Between", synopsis="A courier returns to the Empire.",
                       glossary={"Kestrel": {"note": "female courier", "translations": {"lo": "ເຄສເທຣລ"}}})
    prompt = build_system_prompt(film)
    assert "A courier returns to the Empire." in prompt
    assert "ເຄສເທຣລ" in prompt


def test_term_suggestions_skip_known_terms_case_insensitively():
    fresh = merge_term_suggestions({"Kestrel"}, [TermSuggestion(term="kestrel", note=""),
                                                 TermSuggestion(term="Valor", note="young master"),
                                                 TermSuggestion(term="Valor", note="dup")])
    assert [t.term for t in fresh] == ["Valor"]
