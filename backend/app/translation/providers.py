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


def _is_rate_limit_error(e_or_text: Any) -> bool:
    s = str(e_or_text).lower()
    if (
        "429" in s
        or "resource_exhausted" in s
        or "quota" in s
        or "rate limit" in s
        or "rate_limit" in s
        or "exceeded your current quota" in s
    ):
        return True
    code = getattr(e_or_text, "code", None)
    if code == 429:
        return True
    status = getattr(e_or_text, "status", None)
    if status and "RESOURCE_EXHAUSTED" in str(status).upper():
        return True
    return False


def _is_transient_error(e: Any) -> bool:
    s = str(e).lower()
    return "503" in s or "unavailable" in s or "500" in s or "internal" in s or "timeout" in s or "connection" in s


class GeminiProvider:
    name = "gemini"

    _shared_key_idx: int = 0
    _shared_model_idx: int = 0

    def __init__(self, model: str | None = None) -> None:
        import os
        from google import genai

        primary_key = (
            settings.gemini_api_key if isinstance(getattr(settings, "gemini_api_key", None), str) else ""
        ) or os.getenv("GEMINI_API_KEY", "")
        if not primary_key:
            raise ProviderError("Chưa cấu hình GEMINI_API_KEY. Vui lòng thêm GEMINI_API_KEY vào file .env")

        backup_key = (
            (settings.gemini_backup_api_key if isinstance(getattr(settings, "gemini_backup_api_key", None), str) else "")
            or os.getenv("GEMINI_BACKUP_API_KEY", "AQ.Ab8RN6Jyje8P9LoUt0_GAIMigRIOfOXddkP6WO9-1bi1ofISgQ")
        )

        keys: list[str] = [primary_key]
        if backup_key and backup_key.strip() and backup_key.strip() not in keys:
            keys.append(backup_key.strip())

        self._keys = keys
        self._current_key_idx = min(GeminiProvider._shared_key_idx, len(keys) - 1)
        self._client = genai.Client(api_key=self._keys[self._current_key_idx])

        base_model = model or getattr(settings, "gemini_model", None) or "gemini-3.1-flash-lite"
        raw_fallbacks = getattr(settings, "gemini_fallback_models", "gemini-3.5-flash-lite,gemini-3.6-flash")
        if isinstance(raw_fallbacks, str):
            fallback_models = [m.strip() for m in raw_fallbacks.split(",") if m.strip()]
        else:
            fallback_models = ["gemini-3.5-flash-lite", "gemini-3.6-flash"]

        models: list[str] = [base_model]
        for m in fallback_models:
            if m not in models:
                models.append(m)

        self._models = models
        self._current_model_idx = min(GeminiProvider._shared_model_idx, len(models) - 1)
        self._model = self._models[self._current_model_idx]

    def _generate_with_retry(self, **kwargs) -> Any:
        import logging
        import time
        from google import genai

        log = logging.getLogger("substudio.providers")
        total_keys = len(self._keys)
        total_models = len(self._models)

        while self._current_key_idx < total_keys:
            current_key = self._keys[self._current_key_idx]
            key_preview = f"{current_key[:10]}...{current_key[-4:]}" if len(current_key) > 14 else "***"

            while self._current_model_idx < total_models:
                current_model = self._models[self._current_model_idx]
                call_kwargs = dict(kwargs)
                call_kwargs["model"] = current_model

                transient_retries = 2
                for attempt in range(1, transient_retries + 1):
                    try:
                        resp = self._client.models.generate_content(**call_kwargs)
                        raw_text = getattr(resp, "text", "") or ""
                        if raw_text and _is_rate_limit_error(raw_text) and not (raw_text.startswith("{") or raw_text.startswith("[")):
                            raise RuntimeError(f"Rate limit exceeded trong response text: {raw_text}")

                        # Success: persist working state
                        self._model = current_model
                        GeminiProvider._shared_key_idx = self._current_key_idx
                        GeminiProvider._shared_model_idx = self._current_model_idx
                        return resp
                    except Exception as e:
                        if _is_rate_limit_error(e):
                            log.warning(
                                "Gemini Rate Limit (429/Quota) trên key [%s] với model '%s'. "
                                "Đang xử lý chuyển đổi...",
                                key_preview, current_model
                            )
                            break
                        elif _is_transient_error(e) and attempt < transient_retries:
                            delay = 2.0 * attempt
                            log.warning(
                                "Gemini transient error (%s) trên model '%s', thử lại sau %.1fs (lần %d/%d)...",
                                e, current_model, delay, attempt, transient_retries
                            )
                            time.sleep(delay)
                            continue
                        else:
                            raise

                # Hit rate limit on current model: try next fallback model
                if self._current_model_idx + 1 < total_models:
                    self._current_model_idx += 1
                    next_model = self._models[self._current_model_idx]
                    log.warning(
                        "Gặp lỗi rate limit: Tự động chuyển từ model '%s' sang model '%s' (API key: [%s])",
                        current_model, next_model, key_preview
                    )
                    continue
                else:
                    log.warning(
                        "API key hiện tại [%s] đã thử hết các model fallback (%s) và đều chạm rate limit.",
                        key_preview, ", ".join(self._models)
                    )
                    break

            # If all models on current key exhausted, switch to backup key
            if self._current_key_idx + 1 < total_keys:
                self._current_key_idx += 1
                new_key = self._keys[self._current_key_idx]
                new_key_preview = f"{new_key[:10]}...{new_key[-4:]}" if len(new_key) > 14 else "***"
                self._client = genai.Client(api_key=new_key)
                self._current_model_idx = 0
                self._model = self._models[0]
                GeminiProvider._shared_key_idx = self._current_key_idx
                GeminiProvider._shared_model_idx = self._current_model_idx
                log.warning(
                    "Đổi sang API key dự phòng [%s], bắt đầu lại từ model '%s'...",
                    new_key_preview, self._model
                )
                continue
            else:
                raise ProviderError(
                    f"Tất cả {total_keys} API keys và {total_models} models Gemini đều bị vượt quá Rate Limit / Quota."
                )

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
    def complete_batch(self, system: str, user: str) -> list[BatchItem]:
        res = self.complete(system, user, BatchTranslateResult)
        return res.items


class OpenAIProvider:
    name = "openai"

    def __init__(self, model: str | None = None) -> None:
        import os
        import openai

        api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ProviderError("Chưa cấu hình OPENAI_API_KEY. Vui lòng thêm OPENAI_API_KEY vào file .env")
        self._client = openai.OpenAI(api_key=api_key)
        self._model = model or settings.openai_model

    def _call_with_retry(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        import logging
        import time

        max_retries = 5
        delay = 2.0
        log_fn = logging.getLogger("substudio.providers").warning
        for attempt in range(1, max_retries + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                err_str = str(e).lower()
                is_transient = (
                    "429" in err_str
                    or "rate_limit" in err_str
                    or "ratelimit" in err_str
                    or "503" in err_str
                    or "502" in err_str
                    or "500" in err_str
                    or "unavailable" in err_str
                    or "connection" in err_str
                    or "timeout" in err_str
                )
                if is_transient and attempt < max_retries:
                    log_fn(
                        "OpenAI API transient error (%s), retrying in %.1fs (attempt %d/%d)...",
                        e, delay, attempt, max_retries,
                    )
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            response = self._call_with_retry(
                self._client.chat.completions.parse,
                model=self._model,
                messages=messages,
                response_format=schema,
                temperature=0.2,
            )
        except Exception as e:
            raise ProviderError(f"Lỗi khi gọi OpenAI API ({self._model}): {e}") from e

        choice = response.choices[0] if (response and response.choices) else None
        if not choice or not choice.message:
            raise ProviderError("OpenAI không trả về nội dung")

        refusal = getattr(choice.message, "refusal", None)
        if refusal:
            raise ProviderError(f"OpenAI từ chối yêu cầu do bộ lọc an toàn: {refusal}")

        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason == "length":
            raise TokenOverflowError("Phản hồi của OpenAI bị cắt ngắn (max_tokens/length)")

        if choice.message.parsed is not None:
            return choice.message.parsed

        raw_text = (choice.message.content or "").strip()
        if not raw_text:
            raise ProviderError("OpenAI không trả về nội dung")

        clean_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.IGNORECASE)
        clean_text = re.sub(r"\s*```$", "", clean_text).strip()

        try:
            return schema.model_validate_json(clean_text)
        except Exception as e:
            raise ProviderError(f"OpenAI không trả về JSON hợp lệ theo schema: {e}") from e

    def extract_global_context(self, system: str, user: str) -> str:
        try:
            res = self._call_with_retry(
                self._client.chat.completions.create,
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
                max_tokens=1024,
            )
            return (res.choices[0].message.content or "").strip()
        except Exception as e:
            raise ProviderError(f"Lỗi khi trích xuất ngữ cảnh toàn cục qua OpenAI: {e}") from e

    def complete_batch(self, system: str, user: str) -> list[BatchItem]:
        res = self.complete(system, user, BatchTranslateResult)
        return res.items


class MockProvider:
    """Offline stand-in for tests and UI work: echoes the source, writes placeholder target script."""

    name = "mock"
    _SAMPLE = {"lo": "ທົດສອບ", "my": "စမ်းသပ်", "km": "សាកລ្បង", "th": "ทดสอบ", "zh": "测试"}

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


def make_provider(name: str | None = None, model: str | None = None) -> LLMProvider:
    name = (name or settings.translator).lower()
    if name == "gemini":
        return GeminiProvider(model=model)
    if name == "claude":
        return ClaudeProvider()
    if name == "openai":
        return OpenAIProvider(model=model)
    if name == "mock":
        return MockProvider()
    raise ValueError(f"TRANSLATOR_PROVIDER không hợp lệ: {name} (gemini | claude | openai | mock)")

