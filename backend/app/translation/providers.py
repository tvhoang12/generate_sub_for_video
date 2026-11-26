"""LLM backends. Each one turns (system, user, schema) into a validated schema instance."""

import collections
import json
import re
import threading
import time
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


class DeepSeekProvider:
    name = "deepseek"
    _shared_model_idx: int = 0

    def __init__(self, model: str | None = None) -> None:
        import os
        import openai

        api_key = (
            settings.deepseek_api_key
            if isinstance(getattr(settings, "deepseek_api_key", None), str)
            else ""
        ) or os.getenv("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise ProviderError("Chưa cấu hình DEEPSEEK_API_KEY. Vui lòng thêm DEEPSEEK_API_KEY vào file .env")

        base_url = (
            settings.deepseek_base_url
            if isinstance(getattr(settings, "deepseek_base_url", None), str)
            else ""
        ) or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

        base_model = model or getattr(settings, "deepseek_model", None) or "deepseek-flash"
        raw_fallbacks = getattr(settings, "deepseek_fallback_models", "deepseek-v4-pro")
        if isinstance(raw_fallbacks, str):
            fallback_models = [m.strip() for m in raw_fallbacks.split(",") if m.strip()]
        else:
            fallback_models = ["deepseek-v4-pro"]

        models = [base_model]
        for m in fallback_models:
            if m not in models:
                models.append(m)

        self._models = models
        self._current_model_idx = min(DeepSeekProvider._shared_model_idx, len(models) - 1)
        self._model = self._models[self._current_model_idx]
        self._temperature = float(getattr(settings, "translate_temperature", 0.3))
        self._max_tokens = int(getattr(settings, "translate_max_tokens", 8192))
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url)
        # Token totals per model for this instance; the runner creates one provider per job.
        self._usage_totals: dict[str, collections.Counter] = {}

    def _advance_to_next_model(self) -> bool:
        import logging
        log = logging.getLogger("substudio.providers")
        if self._current_model_idx + 1 < len(self._models):
            prev = self._models[self._current_model_idx]
            self._current_model_idx += 1
            self._model = self._models[self._current_model_idx]
            DeepSeekProvider._shared_model_idx = self._current_model_idx
            log.warning("Tự động fallback từ DeepSeek model '%s' sang '%s'", prev, self._model)
            return True
        return False

    def _log_usage(self, resp: Any, label: str, model: str, seconds: float) -> None:
        """Log token usage of one billed request, so real API cost can be measured."""
        import logging

        usage = getattr(resp, "usage", None)
        choices = getattr(resp, "choices", None)
        details = getattr(usage, "completion_tokens_details", None)
        logging.getLogger("substudio.providers").info(
            "DeepSeek usage call=%s model=%s prompt=%s cache_hit=%s cache_miss=%s "
            "completion=%s reasoning=%s total=%s finish=%s seconds=%.1f",
            label,
            model,
            getattr(usage, "prompt_tokens", None),
            getattr(usage, "prompt_cache_hit_tokens", None),
            getattr(usage, "prompt_cache_miss_tokens", None),
            getattr(usage, "completion_tokens", None),
            getattr(details, "reasoning_tokens", None),
            getattr(usage, "total_tokens", None),
            getattr(choices[0], "finish_reason", None) if choices else None,
            seconds,
        )

        totals = self._usage_totals.setdefault(model, collections.Counter())
        totals["calls"] += 1
        for key, source, attr in (
            ("prompt", usage, "prompt_tokens"),
            ("cache_hit", usage, "prompt_cache_hit_tokens"),
            ("cache_miss", usage, "prompt_cache_miss_tokens"),
            ("completion", usage, "completion_tokens"),
            ("reasoning", details, "reasoning_tokens"),
            ("total", usage, "total_tokens"),
        ):
            value = getattr(source, attr, None)
            totals[key] += value if isinstance(value, int) else 0

    def log_usage_summary(self, job_id: int) -> None:
        """Log one line per model with the tokens billed since this provider was created."""
        import logging

        for model, totals in self._usage_totals.items():
            logging.getLogger("substudio.providers").info(
                "DeepSeek usage TOTAL job=%s model=%s calls=%d prompt=%d cache_hit=%d cache_miss=%d "
                "completion=%d reasoning=%d total=%d",
                job_id,
                model,
                *(totals[k] for k in (
                    "calls", "prompt", "cache_hit", "cache_miss", "completion", "reasoning", "total"
                )),
            )

    def _call_with_retry(
        self,
        messages: list[dict[str, str]],
        response_format: dict | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        label: str = "complete",
    ) -> Any:
        import logging
        import time

        log = logging.getLogger("substudio.providers")
        total_models = len(self._models)
        last_exc: Exception | None = None

        for _ in range(total_models):
            current_model = self._models[self._current_model_idx]
            self._model = current_model

            params: dict[str, Any] = {
                "model": current_model,
                "messages": messages,
                "temperature": self._temperature if temperature is None else temperature,
                "max_tokens": self._max_tokens if max_tokens is None else max_tokens,
            }
            if response_format:
                params["response_format"] = response_format

            max_attempts = 3
            base_delay = 1.5

            for attempt in range(1, max_attempts + 1):
                try:
                    started = time.monotonic()
                    resp = self._client.chat.completions.create(**params)
                    self._log_usage(resp, label, current_model, time.monotonic() - started)
                    DeepSeekProvider._shared_model_idx = self._current_model_idx
                    return resp
                except Exception as e:
                    last_exc = e
                    err_str = str(e).lower()
                    is_rate_limit = _is_rate_limit_error(e)
                    is_transient = (
                        _is_transient_error(e)
                        or "502" in err_str
                        or "500" in err_str
                        or "503" in err_str
                        or "504" in err_str
                    )

                    if (is_rate_limit or is_transient) and attempt < max_attempts:
                        sleep_time = base_delay * (2 ** (attempt - 1))
                        log.warning(
                            "DeepSeek model '%s' gặp lỗi tạm thời (lần %d/%d: %s). Thử lại sau %.1fs...",
                            current_model, attempt, max_attempts, e, sleep_time,
                        )
                        time.sleep(sleep_time)
                        continue

                    log.warning("DeepSeek model '%s' thất bại (%s).", current_model, e)
                    break

            if not self._advance_to_next_model():
                break

        raise ProviderError(
            f"Tất cả models DeepSeek ({', '.join(self._models)}) đều không thể hoàn thành yêu cầu: {last_exc}"
        ) from last_exc

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        system_content = f"{system}\nYou must output strictly a valid JSON object matching the requested schema."
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user},
        ]

        response = self._call_with_retry(
            messages=messages,
            response_format={"type": "json_object"},
        )

        choice = response.choices[0] if (response and response.choices) else None
        if not choice or not choice.message:
            raise ProviderError(f"DeepSeek ({self._model}) không trả về nội dung")

        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason == "length":
            raise TokenOverflowError(f"Phản hồi của DeepSeek ({self._model}) bị cắt ngắn (max_tokens={self._max_tokens})")

        raw_text = (choice.message.content or "").strip()
        if not raw_text:
            raise ProviderError(f"DeepSeek ({self._model}) trả về văn bản rỗng")

        clean_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.IGNORECASE)
        clean_text = re.sub(r"\s*```$", "", clean_text).strip()

        try:
            return schema.model_validate_json(clean_text)
        except Exception as e:
            try:
                data = json.loads(clean_text)
                return schema.model_validate(data)
            except Exception:
                raise ProviderError(
                    f"DeepSeek ({self._model}) không trả về JSON đúng schema: {e}\nRaw output: {raw_text[:200]}"
                ) from e

    def extract_global_context(self, system: str, user: str) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        response = self._call_with_retry(
            messages=messages,
            max_tokens=1024,
            temperature=0.2,
            label="context",
        )
        choice = response.choices[0] if (response and response.choices) else None
        if not choice or not choice.message:
            raise ProviderError(f"DeepSeek ({self._model}) không trả về nội dung ngữ cảnh")

        text = (choice.message.content or "").strip()
        if not text:
            raise ProviderError(f"DeepSeek ({self._model}) trả về văn bản ngữ cảnh rỗng")
        return text

    def complete_batch(self, system: str, user: str) -> list[BatchItem]:
        from pydantic import TypeAdapter

        system_content = (
            f"{system}\nYou must output strictly a valid JSON object. "
            f'Format: {{"items": [{{"id": 1, "fixed_src": "...", "trans": "..."}}]}}'
        )
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": user},
        ]

        response = self._call_with_retry(
            messages=messages,
            response_format={"type": "json_object"},
            label="batch",
        )

        choice = response.choices[0] if (response and response.choices) else None
        if not choice or not choice.message:
            raise ProviderError(f"DeepSeek ({self._model}) không trả về nội dung batch")

        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason == "length":
            raise TokenOverflowError(f"Phản hồi batch của DeepSeek ({self._model}) bị cắt ngắn (max_tokens={self._max_tokens})")

        raw_text = (choice.message.content or "").strip()
        if not raw_text:
            raise ProviderError(f"DeepSeek ({self._model}) trả về văn bản batch rỗng")

        clean_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.IGNORECASE)
        clean_text = re.sub(r"\s*```$", "", clean_text).strip()

        try:
            data = json.loads(clean_text)
            if isinstance(data, dict) and "items" in data:
                items_data = data["items"]
            elif isinstance(data, list):
                items_data = data
            elif isinstance(data, dict) and "lines" in data:
                items_data = data["lines"]
            else:
                for v in data.values():
                    if isinstance(v, list):
                        items_data = v
                        break
                else:
                    raise ValueError("Không tìm thấy mảng danh sách items trong JSON trả về")

            adapter = TypeAdapter(list[BatchItem])
            return adapter.validate_python(items_data)
        except TokenOverflowError:
            raise
        except Exception as e:
            raise ProviderError(
                f"DeepSeek ({self._model}) không trả về batch JSON hợp lệ: {e}\nRaw output: {raw_text[:200]}"
            ) from e


class GeminiRateLimiter:
    """Thread-safe sliding-window rate limiter to strictly cap Gemini API calls per minute."""

    def __init__(self, max_rpm: int = 14) -> None:
        self.max_rpm = max_rpm
        self._lock = threading.Lock()
        self._timestamps: collections.deque[float] = collections.deque()
        self._min_interval = 60.0 / max_rpm if max_rpm > 0 else 0.0
        self._last_call = 0.0

    def wait(self) -> None:
        if self.max_rpm <= 0:
            return
        import logging

        log = logging.getLogger("substudio.providers")

        while True:
            sleep_time = 0.0
            with self._lock:
                now = time.time()
                # 1. Purge timestamps older than 60s
                while self._timestamps and now - self._timestamps[0] >= 60.0:
                    self._timestamps.popleft()

                # 2. Check if we reached max_rpm in the last 60 seconds
                if len(self._timestamps) >= self.max_rpm:
                    oldest = self._timestamps[0]
                    sleep_time = max(0.2, 60.0 - (now - oldest) + 0.5)
                    log.info(
                        "Gemini Rate Limiter: Đã đạt %d/%d calls trong 60s qua. Tạm hoãn %.1fs để tuân thủ quota...",
                        len(self._timestamps), self.max_rpm, sleep_time
                    )
                else:
                    # 3. Pacing: ensure minimum spacing between calls
                    elapsed = now - self._last_call
                    if elapsed < self._min_interval:
                        sleep_time = self._min_interval - elapsed
                    else:
                        # Safe to proceed!
                        self._timestamps.append(now)
                        self._last_call = now
                        return

            if sleep_time > 0:
                time.sleep(sleep_time)


_gemini_rate_limiter: GeminiRateLimiter | None = None


def get_gemini_rate_limiter() -> GeminiRateLimiter:
    global _gemini_rate_limiter
    if _gemini_rate_limiter is None:
        _gemini_rate_limiter = GeminiRateLimiter(max_rpm=settings.gemini_rpm_limit)
    return _gemini_rate_limiter


class GeminiProvider:
    name = "gemini"

    _shared_key_idx: int = 0
    _shared_model_idx: int = 0

    def __init__(self, model: str | None = None) -> None:
        import os
        from google import genai

        # Guards model/key fallback: translation batches may call this provider concurrently.
        self._fallback_lock = threading.Lock()

        primary_key = (
            settings.gemini_api_key if isinstance(getattr(settings, "gemini_api_key", None), str) else ""
        ) or os.getenv("GEMINI_API_KEY", "")
        if not primary_key:
            raise ProviderError("Chưa cấu hình GEMINI_API_KEY. Vui lòng thêm GEMINI_API_KEY vào file .env")

        backup_key = (
            (settings.gemini_backup_api_key if isinstance(getattr(settings, "gemini_backup_api_key", None), str) else "")
            or os.getenv("GEMINI_BACKUP_API_KEY", "")
        )

        keys: list[str] = [primary_key]
        if backup_key and backup_key.strip() and backup_key.strip() not in keys:
            keys.append(backup_key.strip())

        self._keys = keys
        self._current_key_idx = min(GeminiProvider._shared_key_idx, len(keys) - 1)
        self._client = genai.Client(api_key=self._keys[self._current_key_idx])

        base_model = model or getattr(settings, "gemini_model", None) or "gemini-3.1-flash-lite"
        raw_fallbacks = getattr(
            settings,
            "gemini_fallback_models",
            "gemini-3.5-flash-lite,gemini-3.6-flash,gemini-3.5-flash,gemini-3.8-flash",
        )
        if isinstance(raw_fallbacks, str):
            fallback_models = [m.strip() for m in raw_fallbacks.split(",") if m.strip()]
        else:
            fallback_models = ["gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.8-flash"]

        models: list[str] = [base_model]
        for m in fallback_models:
            if m not in models:
                models.append(m)

        self._models = models
        self._current_model_idx = min(GeminiProvider._shared_model_idx, len(models) - 1)
        self._model = self._models[self._current_model_idx]

    def _advance_to_next_model(self) -> bool:
        """Chuyển sang model tiếp theo trong danh sách fallback, hoặc sang API key dự phòng nếu đã thử hết models."""
        import logging
        from google import genai

        log = logging.getLogger("substudio.providers")
        total_models = len(self._models)
        total_keys = len(self._keys)

        current_model = self._models[self._current_model_idx]
        current_key = self._keys[self._current_key_idx]
        key_preview = f"{current_key[:10]}...{current_key[-4:]}" if len(current_key) > 14 else "***"

        if self._current_model_idx + 1 < total_models:
            self._current_model_idx += 1
            self._model = self._models[self._current_model_idx]
            GeminiProvider._shared_model_idx = self._current_model_idx
            log.warning(
                "Tự động fallback từ model Gemini '%s' sang model '%s' trong danh sách (API key: [%s])",
                current_model, self._model, key_preview,
            )
            return True
        elif self._current_key_idx + 1 < total_keys:
            self._current_key_idx += 1
            new_key = self._keys[self._current_key_idx]
            new_key_preview = f"{new_key[:10]}...{new_key[-4:]}" if len(new_key) > 14 else "***"
            self._client = genai.Client(api_key=new_key)
            self._current_model_idx = 0
            self._model = self._models[0]
            GeminiProvider._shared_key_idx = self._current_key_idx
            GeminiProvider._shared_model_idx = self._current_model_idx
            log.warning(
                "Đã thử hết %d models trên key [%s]. Chuyển sang API key dự phòng [%s], bắt đầu lại từ model '%s'...",
                total_models, key_preview, new_key_preview, self._model,
            )
            return True
        return False

    def _generate_with_retry(self, **kwargs) -> Any:
        import logging
        import time

        log = logging.getLogger("substudio.providers")
        total_attempts = len(self._keys) * len(self._models)
        errors_history: list[str] = []

        for _ in range(total_attempts):
            with self._fallback_lock:
                position = (self._current_key_idx, self._current_model_idx)
                client = self._client
            current_model = self._models[position[1]]
            current_key = self._keys[position[0]]
            key_preview = f"{current_key[:10]}...{current_key[-4:]}" if len(current_key) > 14 else "***"

            call_kwargs = dict(kwargs)
            call_kwargs["model"] = current_model

            transient_retries = 1
            for attempt in range(1, transient_retries + 2):
                try:
                    get_gemini_rate_limiter().wait()
                    resp = client.models.generate_content(**call_kwargs)
                    raw_text = getattr(resp, "text", "") or ""
                    if raw_text and _is_rate_limit_error(raw_text) and not (raw_text.startswith("{") or raw_text.startswith("[")):
                        raise RuntimeError(f"Rate limit exceeded trong response text: {raw_text}")

                    # Ghi nhớ model và key hoạt động thành công
                    self._model = current_model
                    GeminiProvider._shared_key_idx = position[0]
                    GeminiProvider._shared_model_idx = position[1]
                    return resp
                except Exception as e:
                    err_lower = str(e).lower()
                    # Lỗi mạng chập chờn (không phải 503 high demand hay 429 quota): thử lại 1 lần nhanh
                    if _is_transient_error(e) and attempt <= transient_retries and "503" not in err_lower and "demand" not in err_lower:
                        time.sleep(1.0)
                        continue

                    # BẤT KỲ LỖI NÀO (503 quá tải, 429 quota, 404 không tìm thấy, 400 sai cú pháp, 500, timeout, v.v.)
                    # đều lập tức kích hoạt fallback sang model tiếp theo trong danh sách!
                    err_msg = f"Model '{current_model}' [key {key_preview}] gặp lỗi: {e}"
                    errors_history.append(err_msg)
                    log.warning("%s. Đang chuyển sang model tiếp theo trong danh sách...", err_msg)
                    break

            # Chuyển sang model tiếp theo trong danh sách
            # Another thread may already have moved past the failed model; do not skip one.
            with self._fallback_lock:
                moved = (self._current_key_idx, self._current_model_idx) != position
                if not moved and not self._advance_to_next_model():
                    break

        summary_errors = "\n - ".join(errors_history[-6:])
        raise ProviderError(
            f"Tất cả {len(self._models)} models trong danh sách ({', '.join(self._models)}) và {len(self._keys)} API keys đều không gọi được API AI.\nChi tiết các lỗi:\n - {summary_errors}"
        )

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        from google.genai import types

        total_attempts = len(self._models) * len(self._keys)
        last_error = None

        for _ in range(total_attempts):
            try:
                response = self._generate_with_retry(
                    contents=user,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        response_mime_type="application/json",
                        response_schema=schema,
                        temperature=0.2,
                    ),
                )

                if response.candidates:
                    candidate = response.candidates[0]
                    finish_reason = getattr(candidate, "finish_reason", None)
                    if finish_reason:
                        fr_str = str(finish_reason).upper()
                        if "SAFETY" in fr_str:
                            raise RuntimeError(f"Gemini từ chối yêu cầu do bộ lọc an toàn trên model '{self._model}'")
                        if "MAX_TOKENS" in fr_str:
                            raise TokenOverflowError(f"Phản hồi của Gemini ({self._model}) bị cắt ngắn (max_tokens)")

                if hasattr(response, "parsed") and response.parsed is not None:
                    return response.parsed

                raw_text = (response.text or "").strip()
                if not raw_text:
                    raise RuntimeError(f"Gemini model '{self._model}' không trả về nội dung")

                clean_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.IGNORECASE)
                clean_text = re.sub(r"\s*```$", "", clean_text).strip()
                return schema.model_validate_json(clean_text)
            except TokenOverflowError:
                raise
            except Exception as e:
                last_error = e
                import logging
                logging.getLogger("substudio.providers").warning(
                    "Model Gemini '%s' không trả về kết quả hợp lệ (%s). Thử fallback sang model tiếp theo...",
                    self._model, e,
                )
                if not self._advance_to_next_model():
                    break

        raise ProviderError(f"Tất cả models trong danh sách đều không thể hoàn thành yêu cầu: {last_error}") from last_error

    def extract_global_context(self, system: str, user: str) -> str:
        from google.genai import types

        total_attempts = len(self._models) * len(self._keys)
        last_error = None

        for _ in range(total_attempts):
            try:
                response = self._generate_with_retry(
                    contents=user,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        temperature=0.2,
                        max_output_tokens=1024,
                    ),
                )
                text = (response.text or "").strip()
                if text:
                    return text
                raise RuntimeError(f"Model '{self._model}' trả về văn bản ngữ cảnh rỗng")
            except Exception as e:
                last_error = e
                import logging
                logging.getLogger("substudio.providers").warning(
                    "extract_global_context trên model '%s' thất bại (%s). Thử fallback sang model tiếp theo...",
                    self._model, e,
                )
                if not self._advance_to_next_model():
                    break

        raise ProviderError(f"Tất cả models trong danh sách đều không thể trích xuất ngữ cảnh: {last_error}") from last_error

    def complete_batch(self, system: str, user: str) -> list[BatchItem]:
        from google.genai import types
        from pydantic import TypeAdapter

        total_attempts = len(self._models) * len(self._keys)
        last_error = None

        for _ in range(total_attempts):
            try:
                response = self._generate_with_retry(
                    contents=user,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        response_mime_type="application/json",
                        response_schema=list[BatchItem],
                        temperature=0.2,
                        max_output_tokens=8192,
                    ),
                )

                if response.candidates:
                    candidate = response.candidates[0]
                    finish_reason = getattr(candidate, "finish_reason", None)
                    if finish_reason:
                        fr_str = str(finish_reason).upper()
                        if "SAFETY" in fr_str:
                            raise RuntimeError(f"Gemini từ chối yêu cầu do bộ lọc an toàn trên model '{self._model}'")
                        if "MAX_TOKENS" in fr_str:
                            raise TokenOverflowError(f"Phản hồi của Gemini ({self._model}) bị cắt ngắn (max_output_tokens=8192)")

                if hasattr(response, "parsed") and response.parsed is not None:
                    if isinstance(response.parsed, list):
                        return response.parsed

                raw_text = (response.text or "").strip()
                if not raw_text:
                    raise RuntimeError(f"Gemini model '{self._model}' không trả về nội dung")

                clean_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.IGNORECASE)
                clean_text = re.sub(r"\s*```$", "", clean_text).strip()

                adapter = TypeAdapter(list[BatchItem])
                return adapter.validate_json(clean_text)
            except TokenOverflowError:
                raise
            except Exception as e:
                last_error = e
                import logging
                logging.getLogger("substudio.providers").warning(
                    "complete_batch trên model '%s' thất bại (%s). Thử fallback sang model tiếp theo...",
                    self._model, e,
                )
                if not self._advance_to_next_model():
                    break

        raise ProviderError(f"Tất cả models trong danh sách đều không thể hoàn thành batch: {last_error}") from last_error



class ClaudeProvider:
    name = "claude"
    _shared_model_idx: int = 0

    def __init__(self, model: str | None = None) -> None:
        import os
        import anthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

        base_model = model or getattr(settings, "claude_model", None) or "claude-opus-5-5"
        raw_fallbacks = getattr(
            settings,
            "claude_fallback_models",
            "claude-sonnet-4-5,claude-3-5-sonnet-20241022,claude-3-5-haiku-20241022",
        )
        if isinstance(raw_fallbacks, str):
            fallback_models = [m.strip() for m in raw_fallbacks.split(",") if m.strip()]
        else:
            fallback_models = ["claude-sonnet-4-5", "claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"]

        models: list[str] = [base_model]
        for m in fallback_models:
            if m not in models:
                models.append(m)

        self._models = models
        self._current_model_idx = min(ClaudeProvider._shared_model_idx, len(models) - 1)
        self._model = self._models[self._current_model_idx]
        self._effort = getattr(settings, "claude_effort", "medium")

    def _advance_to_next_model(self) -> bool:
        import logging
        log = logging.getLogger("substudio.providers")
        if self._current_model_idx + 1 < len(self._models):
            prev_model = self._models[self._current_model_idx]
            self._current_model_idx += 1
            self._model = self._models[self._current_model_idx]
            ClaudeProvider._shared_model_idx = self._current_model_idx
            log.warning("Tự động fallback từ model Claude '%s' sang model '%s' trong danh sách", prev_model, self._model)
            return True
        return False

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        import logging
        log = logging.getLogger("substudio.providers")
        total_attempts = len(self._models)
        last_error = None

        for _ in range(total_attempts):
            current_model = self._models[self._current_model_idx]
            self._model = current_model
            try:
                response = self._client.messages.parse(
                    model=current_model,
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
                    raise ProviderError(f"Claude ({current_model}) từ chối yêu cầu dịch")
                if response.stop_reason == "max_tokens":
                    raise TokenOverflowError(f"Phản hồi của Claude ({current_model}) bị cắt (max_tokens)")
                if response.parsed_output is None:
                    raise ProviderError(f"Claude ({current_model}) không trả về JSON hợp lệ")

                ClaudeProvider._shared_model_idx = self._current_model_idx
                return response.parsed_output
            except TokenOverflowError:
                raise
            except Exception as e:
                last_error = e
                log.warning("Model Claude '%s' gặp lỗi (%s). Đang fallback sang model tiếp theo trong danh sách...", current_model, e)
                if not self._advance_to_next_model():
                    break

        raise ProviderError(f"Tất cả {len(self._models)} models Claude trong danh sách ({', '.join(self._models)}) đều không thể hoàn thành yêu cầu: {last_error}") from last_error

    def extract_global_context(self, system: str, user: str) -> str:
        import logging
        log = logging.getLogger("substudio.providers")
        total_attempts = len(self._models)
        last_error = None

        for _ in range(total_attempts):
            current_model = self._models[self._current_model_idx]
            self._model = current_model
            try:
                response = self._client.messages.create(
                    model=current_model,
                    max_tokens=1024,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                text = ""
                for blk in response.content:
                    if getattr(blk, "type", "") == "text":
                        text += getattr(blk, "text", "")
                text = text.strip()
                if text:
                    ClaudeProvider._shared_model_idx = self._current_model_idx
                    return text
                raise ProviderError(f"Claude ({current_model}) trả về văn bản ngữ cảnh rỗng")
            except Exception as e:
                last_error = e
                log.warning("extract_global_context trên model Claude '%s' thất bại (%s). Thử fallback...", current_model, e)
                if not self._advance_to_next_model():
                    break

        raise ProviderError(f"Tất cả models Claude trong danh sách đều không thể trích xuất ngữ cảnh: {last_error}") from last_error

    def complete_batch(self, system: str, user: str) -> list[BatchItem]:
        res = self.complete(system, user, BatchTranslateResult)
        return res.items


class OpenAIProvider:
    name = "openai"
    _shared_model_idx: int = 0
    _shared_key_idx: int = 0

    def __init__(self, model: str | None = None) -> None:
        import os
        import openai

        raw_key = (
            settings.openai_api_key if isinstance(getattr(settings, "openai_api_key", None), str) else ""
        ) or os.getenv("OPENAI_API_KEY", "")
        if not raw_key:
            raise ProviderError("Chưa cấu hình OPENAI_API_KEY. Vui lòng thêm OPENAI_API_KEY vào file .env")

        keys = [k.strip() for k in raw_key.split(",") if k.strip()]
        self._keys = keys
        self._current_key_idx = min(OpenAIProvider._shared_key_idx, len(keys) - 1)
        self._client = openai.OpenAI(api_key=self._keys[self._current_key_idx])

        base_model = model or getattr(settings, "openai_model", None) or "gpt-4o-mini"
        raw_fallbacks = getattr(
            settings,
            "openai_fallback_models",
            "gpt-4o,gpt-4-turbo,gpt-3.5-turbo",
        )
        if isinstance(raw_fallbacks, str):
            fallback_models = [m.strip() for m in raw_fallbacks.split(",") if m.strip()]
        else:
            fallback_models = ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"]

        models: list[str] = [base_model]
        for m in fallback_models:
            if m not in models:
                models.append(m)

        self._models = models
        self._current_model_idx = min(OpenAIProvider._shared_model_idx, len(models) - 1)
        self._model = self._models[self._current_model_idx]

    def _advance_to_next_model(self) -> bool:
        import logging
        import openai
        log = logging.getLogger("substudio.providers")
        total_models = len(self._models)
        total_keys = len(self._keys)

        if self._current_model_idx + 1 < total_models:
            prev_model = self._models[self._current_model_idx]
            self._current_model_idx += 1
            self._model = self._models[self._current_model_idx]
            OpenAIProvider._shared_model_idx = self._current_model_idx
            log.warning("Tự động fallback từ model OpenAI '%s' sang model '%s' trong danh sách", prev_model, self._model)
            return True
        elif self._current_key_idx + 1 < total_keys:
            self._current_key_idx += 1
            new_key = self._keys[self._current_key_idx]
            self._client = openai.OpenAI(api_key=new_key)
            self._current_model_idx = 0
            self._model = self._models[0]
            OpenAIProvider._shared_key_idx = self._current_key_idx
            OpenAIProvider._shared_model_idx = self._current_model_idx
            log.warning("Đã thử hết models OpenAI trên key hiện tại. Chuyển sang API key tiếp theo, thử lại từ '%s'", self._model)
            return True
        return False

    def complete(self, system: str, user: str, schema: type[T]) -> T:
        import logging
        log = logging.getLogger("substudio.providers")
        total_attempts = len(self._models) * len(self._keys)
        last_error = None

        for _ in range(total_attempts):
            current_model = self._models[self._current_model_idx]
            self._model = current_model
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            try:
                response = self._client.chat.completions.parse(
                    model=current_model,
                    messages=messages,
                    response_format=schema,
                    temperature=0.2,
                )
                choice = response.choices[0] if (response and response.choices) else None
                if not choice or not choice.message:
                    raise ProviderError(f"OpenAI ({current_model}) không trả về nội dung")

                refusal = getattr(choice.message, "refusal", None)
                if refusal:
                    raise ProviderError(f"OpenAI ({current_model}) từ chối yêu cầu do bộ lọc an toàn: {refusal}")

                finish_reason = getattr(choice, "finish_reason", None)
                if finish_reason == "length":
                    raise TokenOverflowError(f"Phản hồi của OpenAI ({current_model}) bị cắt ngắn (max_tokens/length)")

                if choice.message.parsed is not None:
                    OpenAIProvider._shared_model_idx = self._current_model_idx
                    return choice.message.parsed

                raw_text = (choice.message.content or "").strip()
                if not raw_text:
                    raise ProviderError(f"OpenAI ({current_model}) không trả về nội dung text")

                clean_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.IGNORECASE)
                clean_text = re.sub(r"\s*```$", "", clean_text).strip()

                parsed = schema.model_validate_json(clean_text)
                OpenAIProvider._shared_model_idx = self._current_model_idx
                return parsed
            except TokenOverflowError:
                raise
            except Exception as e:
                last_error = e
                log.warning("Model OpenAI '%s' gặp lỗi (%s). Thử fallback sang model tiếp theo trong danh sách...", current_model, e)
                if not self._advance_to_next_model():
                    break

        raise ProviderError(f"Tất cả {len(self._models)} models OpenAI trong danh sách ({', '.join(self._models)}) đều gặp lỗi: {last_error}") from last_error

    def extract_global_context(self, system: str, user: str) -> str:
        import logging
        log = logging.getLogger("substudio.providers")
        total_attempts = len(self._models) * len(self._keys)
        last_error = None

        for _ in range(total_attempts):
            current_model = self._models[self._current_model_idx]
            self._model = current_model
            try:
                res = self._client.chat.completions.create(
                    model=current_model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=0.2,
                    max_tokens=1024,
                )
                text = (res.choices[0].message.content or "").strip()
                if text:
                    OpenAIProvider._shared_model_idx = self._current_model_idx
                    return text
                raise ProviderError(f"OpenAI ({current_model}) trả về văn bản ngữ cảnh rỗng")
            except Exception as e:
                last_error = e
                log.warning("extract_global_context trên model OpenAI '%s' thất bại (%s). Thử fallback...", current_model, e)
                if not self._advance_to_next_model():
                    break

        raise ProviderError(f"Tất cả models OpenAI trong danh sách đều không thể trích xuất ngữ cảnh: {last_error}") from last_error

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
    if name == "deepseek":
        return DeepSeekProvider(model=model)
    if name == "gemini":
        return GeminiProvider(model=model)
    if name == "claude":
        return ClaudeProvider(model=model)
    if name == "openai":
        return OpenAIProvider(model=model)
    if name == "mock":
        return MockProvider()
    raise ValueError(f"TRANSLATOR_PROVIDER không hợp lệ: {name} (deepseek | gemini | claude | openai | mock)")

