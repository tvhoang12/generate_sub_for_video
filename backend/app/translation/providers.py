"""LLM backends. Each one turns (system, user, schema) into a validated schema instance."""

import json
import re
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from ..config import settings
from .schemas import BatchItem, BatchTranslateResult, CleanResult, CleanedLine, TranslateResult, TranslatedLine

T = TypeVar("T", bound=BaseModel)


class ProviderError(RuntimeError):
    """The provider answered but the answer is unusable (refusal, truncation, empty)."""


class TokenOverflowError(ProviderError):
    """The provider output was truncated because it exceeded max_output_tokens."""


class LLMProvider(Protocol):
    name: str

    def complete(self, system: str, user: str, schema: type[T]) -> T: ...
    def extract_global_context(self, system: str, user: str) -> str: ...
    def complete_batch(self, system: str, user: str) -> list[BatchItem]: ...


class GeminiProvider:
    name = "gemini"

    def __init__(self, model: str | None = None) -> None:
        import os
        from google import genai

        api_key = settings.gemini_api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ProviderError("Chưa cấu hình GEMINI_API_KEY. Vui lòng thêm GEMINI_API_KEY vào file .env")
        self._client = genai.Client(api_key=api_key)
        self._model = model or settings.gemini_model

    def _generate_with_retry(self, **kwargs) -> Any:
        import time
        max_retries = 5
        delay = 2.0
        current_kwargs = dict(kwargs)
        original_model = current_kwargs.get("model", self._model)
        for attempt in range(1, max_retries + 1):
            try:
                return self._client.models.generate_content(**current_kwargs)
            except Exception as e:
                err_str = str(e).lower()
                is_transient = "503" in err_str or "unavailable" in err_str or "429" in err_str or "resource_exhausted" in err_str
                if is_transient and attempt < max_retries:
                    import logging
                    log_fn = logging.getLogger("substudio.providers").warning
                    if attempt >= 3 and "flash" in original_model:
                        fallback_model = "gemini-flash-lite-latest" if "3.1" in original_model else "gemini-3.1-flash-lite"
                        current_kwargs["model"] = fallback_model
                        log_fn(
                            "Gemini API transient error (%s). Trying fallback model '%s' in %.1fs (attempt %d/%d)...",
                            e, fallback_model, delay, attempt, max_retries
                        )
                    else:
                        log_fn(
                            "Gemini API transient error (%s), retrying in %.1fs (attempt %d/%d)...",
                            e, delay, attempt, max_retries
                        )
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        from google.genai import types

        try:
            response = self._generate_with_retry(
                model=self._model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.2,
                ),
            )
        except Exception as e:
            raise ProviderError(f"Lỗi khi gọi Gemini API ({self._model}): {e}") from e

        if response.candidates:
            candidate = response.candidates[0]
            finish_reason = getattr(candidate, "finish_reason", None)
            if finish_reason:
                fr_str = str(finish_reason).upper()
                if "SAFETY" in fr_str:
                    raise ProviderError("Gemini từ chối yêu cầu do bộ lọc an toàn (safety filter)")
                if "MAX_TOKENS" in fr_str:
                    raise ProviderError("Phản hồi của Gemini bị cắt ngắn (max_tokens)")

        if hasattr(response, "parsed") and response.parsed is not None:
            return response.parsed

        raw_text = (response.text or "").strip()
        if not raw_text:
            raise ProviderError("Gemini không trả về nội dung")

        # Strip markdown ```json code fence if present
        clean_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.IGNORECASE)
        clean_text = re.sub(r"\s*```$", "", clean_text)

        try:
            return schema.model_validate_json(clean_text)
        except Exception as e:
            raise ProviderError(f"Gemini không trả về JSON hợp lệ theo schema: {e}") from e

    def extract_global_context(self, system: str, user: str) -> str:
        from google.genai import types

        try:
            response = self._generate_with_retry(
                model=self._model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0.2,
                    max_output_tokens=1024,
                ),
            )
            return (response.text or "").strip()
        except Exception as e:
            raise ProviderError(f"Lỗi khi trích xuất ngữ cảnh toàn cục qua Gemini: {e}") from e

    def complete_batch(self, system: str, user: str) -> list[BatchItem]:
        from google.genai import types
        from pydantic import TypeAdapter

        try:
            response = self._generate_with_retry(
                model=self._model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=list[BatchItem],
                    temperature=0.2,
                    max_output_tokens=8192,
                ),
            )
        except Exception as e:
            raise ProviderError(f"Lỗi khi gọi Gemini API ({self._model}): {e}") from e

        if response.candidates:
            candidate = response.candidates[0]
            finish_reason = getattr(candidate, "finish_reason", None)
            if finish_reason:
                fr_str = str(finish_reason).upper()
                if "SAFETY" in fr_str:
                    raise ProviderError("Gemini từ chối yêu cầu do bộ lọc an toàn (safety filter)")
                if "MAX_TOKENS" in fr_str:
                    raise TokenOverflowError("Phản hồi của Gemini bị cắt ngắn (max_output_tokens=8192)")

        if hasattr(response, "parsed") and response.parsed is not None:
            if isinstance(response.parsed, list):
                return response.parsed

        raw_text = (response.text or "").strip()
        if not raw_text:
            raise ProviderError("Gemini không trả về nội dung")

        clean_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.IGNORECASE)
        clean_text = re.sub(r"\s*```$", "", clean_text).strip()

        try:
            adapter = TypeAdapter(list[BatchItem])
            return adapter.validate_json(clean_text)
        except Exception as e:
            if clean_text.endswith("...") or not clean_text.endswith("]"):
                raise TokenOverflowError(f"JSON bị cắt ngắn (truncation): {e}") from e
            raise ProviderError(f"Gemini không trả về danh sách JSON hợp lệ: {e}") from e



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
            raise TokenOverflowError("Phản hồi của Claude bị cắt (max_tokens)")
        if response.parsed_output is None:
            raise ProviderError("Claude không trả về JSON hợp lệ")
        return response.parsed_output

    def extract_global_context(self, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text if response.content else ""

    def complete_batch(self, system: str, user: str) -> list[BatchItem]:
        res = self.complete(system, user, BatchTranslateResult)
        return res.items


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

    def extract_global_context(self, system: str, user: str) -> str:
        res = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=1024,
        )
        return res.choices[0].message.content or ""

    def complete_batch(self, system: str, user: str) -> list[BatchItem]:
        res = self.complete(system, user, BatchTranslateResult)
        return res.items


class MockProvider:
    """Offline stand-in for tests and UI work: echoes the source, writes placeholder target script."""

    name = "mock"
    _SAMPLE = {"lo": "ທົດສອບ", "my": "စမ်းသပ်", "km": "សាកល្បង", "th": "ทดสอบ", "zh": "测试"}

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        lines = json.loads(re.search(r"<lines>\s*(.*?)\s*</lines>", user, re.S).group(1))
        if schema is CleanResult:
            return CleanResult(
                lines=[CleanedLine(id=l["id"], text=l["text"], unclear=False) for l in lines],
                new_terms=[],
                homophone_corrections=[],
            )  # type: ignore[return-value]
        target = re.search(r'<target code="(\w+)"', user).group(1)
        word = self._SAMPLE.get(target, target.upper())
        suffix = f": {l['text']}" if target.startswith("zh") else ""
        return TranslateResult(
            lines=[TranslatedLine(id=l["id"], text=f"{word} {l['id']}{suffix}") for l in lines]
        )  # type: ignore[return-value]

    def extract_global_context(self, system: str, user: str) -> str:
        return "Genre: Period costume drama. Setting: Ancient China. Hierarchy: Master and guest. Proper nouns: [Mr. Pu], [Hong Yu]."

    def complete_batch(self, system: str, user: str) -> list[BatchItem]:
        match = re.search(r"<batch>\s*(.*?)\s*</batch>", user, re.S)
        items_data = json.loads(match.group(1)) if match else []
        target_m = re.search(r'<target code="(\w+)"', user)
        target = target_m.group(1) if target_m else "lo"
        word = self._SAMPLE.get(target, target.upper())
        suffix = lambda src: f": {src}" if target.startswith("zh") else ""
        return [
            BatchItem(id=it["id"], fixed_src=it.get("src", ""), trans=f"{word} {it['id']}{suffix(it.get('src', ''))}")
            for it in items_data
        ]


def make_provider(name: str | None = None) -> LLMProvider:
    name = (name or settings.translator).lower()
    if name == "gemini":
        return GeminiProvider()
    if name == "claude":
        return ClaudeProvider()
    if name == "openai":
        return OpenAIProvider()
    if name == "mock":
        return MockProvider()
    raise ValueError(f"TRANSLATOR_PROVIDER không hợp lệ: {name} (gemini | claude | openai | mock)")
