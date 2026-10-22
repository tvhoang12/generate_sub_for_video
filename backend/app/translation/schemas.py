"""Structured outputs exchanged with the LLM. Both providers are constrained to these schemas."""

from pydantic import BaseModel, Field


class CleanedLine(BaseModel):
    id: int
    text: str = Field(description="Corrected source-language text for this line")
    unclear: bool = Field(description="True when the line is unintelligible and cannot be reconstructed with confidence")


class TermSuggestion(BaseModel):
    term: str = Field(description="Proper noun or recurring term exactly as written in the corrected source")
    note: str = Field(description="Short note: who or what it is (e.g. 'female courier, main character')")


class CleanResult(BaseModel):
    lines: list[CleanedLine]
    new_terms: list[TermSuggestion]


class TranslatedLine(BaseModel):
    id: int
    text: str = Field(description="Subtitle text in the target language; use \\n for a line break, at most 2 lines")


class TranslateResult(BaseModel):
    lines: list[TranslatedLine]
