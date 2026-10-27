"""Structured outputs exchanged with the LLM. Both providers are constrained to these schemas."""

from pydantic import BaseModel, Field


class CleanedLine(BaseModel):
    id: int
    text: str = Field(description="Corrected source-language text for this line")
    unclear: bool = Field(description="True when the line is unintelligible and cannot be reconstructed with confidence")


class TermSuggestion(BaseModel):
    term: str = Field(description="Proper noun or recurring term exactly as written in the corrected source")
    note: str = Field(description="Short note: who or what it is (e.g. 'female courier, main character')")


class HomophoneCorrection(BaseModel):
    id: int = Field(description="Subtitle line id where the homophone error was found")
    original: str = Field(description="Original misheard Chinese character(s) or word from ASR")
    corrected: str = Field(description="Corrected Chinese character(s) or word based on context")
    pinyin: str = Field(description="Pinyin of the homophone pair (e.g. 'gù zǒng')")
    explanation: str = Field(description="Short reason why this correction fits the context")


class CleanResult(BaseModel):
    lines: list[CleanedLine]
    new_terms: list[TermSuggestion] = Field(default_factory=list)
    homophone_corrections: list[HomophoneCorrection] = Field(
        default_factory=list,
        description="Detected and corrected Chinese homophone/near-homophone errors (同音字/近音字)",
    )


class TranslatedLine(BaseModel):
    id: int
    text: str = Field(description="Subtitle text in the target language; use \\n for a line break, at most 2 lines")


class TranslateResult(BaseModel):
    lines: list[TranslatedLine]

class BatchItem(BaseModel):
    id: int = Field(description="Exact ID of the subtitle line")
    fixed_src: str = Field(description="Original source text with homophone errors or typos corrected based on context")
    trans: str = Field(description="Natural translation in target language, at most 2 lines, using \\n for line breaks")


class BatchTranslateResult(BaseModel):
    items: list[BatchItem] = Field(default_factory=list)


