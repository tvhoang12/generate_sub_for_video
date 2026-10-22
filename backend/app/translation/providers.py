"""LLM backends. Each one turns (system, user, schema) into a validated schema instance."""

import json
import re
from typing import Protocol, TypeVar

from pydantic import BaseModel

from ..config import settings
from .schemas import CleanResult, CleanedLine, TranslateResult, TranslatedLine

T = TypeVar("T", bound=BaseModel)


class ProviderError(RuntimeError):
    """The provider answered but the answer is unusable (refusal, truncation, empty)."""


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str, schema: type[T]) -> T: ...


class ClaudeProvider:
    name = "claude"

    def __init__(self) -> None:
        import anthropic

        self._client = anthropic.Anthropic()
        self._model = settings.claude_model
        self._effort = settings.claude_effort

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=16000,
            # The system prompt carries the film context and glossary, identical for every call of a job.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_format=schema,
            output_config={"effort": self._effort},
            # On a safety-classifier decline the API retries on the model Anthropic recommends.
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={"fallbacks": "default"},
        )
        if response.stop_reason == "refusal":
            raise ProviderError("Claude từ chối yêu cầu dịch")
        if response.stop_reason == "max_tokens":
            raise ProviderError("Phản hồi của Claude bị cắt (max_tokens)")
        if response.parsed_output is None:
            raise ProviderError("Claude không trả về JSON hợp lệ")
        return response.parsed_output


class OpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        import openai

        self._client = openai.OpenAI()
        self._model = settings.openai_model

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        response = self._client.responses.parse(
            model=self._model, instructions=system, input=user, text_format=schema
        )
        if response.output_parsed is None:
            raise ProviderError("OpenAI không trả về JSON hợp lệ")
        return response.output_parsed


class MockProvider:
    """Offline stand-in for tests and UI work: echoes the source, writes placeholder target script."""

    name = "mock"
    _SAMPLE = {"lo": "ທົດສອບ", "my": "စမ်းသပ်", "km": "សាកល្បង", "th": "ทดสอบ", "zh": "测试"}

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        lines = json.loads(re.search(r"<lines>\s*(.*?)\s*</lines>", user, re.S).group(1))
        if schema is CleanResult:
            return CleanResult(
                lines=[CleanedLine(id=l["id"], text=l["text"], unclear=False) for l in lines], new_terms=[]
            )  # type: ignore[return-value]
        target = re.search(r'<target code="(\w+)"', user).group(1)
        word = self._SAMPLE.get(target, target.upper())
        return TranslateResult(
            lines=[TranslatedLine(id=l["id"], text=f"{word} {l['id']}: {l['text']}") for l in lines]
        )  # type: ignore[return-value]


def make_provider(name: str | None = None) -> LLMProvider:
    name = (name or settings.translator).lower()
    if name == "claude":
        return ClaudeProvider()
    if name == "openai":
        return OpenAIProvider()
    if name == "mock":
        return MockProvider()
    raise ValueError(f"TRANSLATOR_PROVIDER không hợp lệ: {name} (claude | openai | mock)")
