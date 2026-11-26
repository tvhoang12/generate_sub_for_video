"""Token usage of one billed LLM request, normalised across providers."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

log = logging.getLogger("substudio.providers")


@dataclass(frozen=True)
class LlmCall:
    provider: str
    model: str
    label: str
    prompt_tokens: int  # all input tokens, cache hits and cache writes included
    cache_hit_tokens: int
    cache_write_tokens: int
    completion_tokens: int  # all output tokens, reasoning included
    reasoning_tokens: int
    seconds: float
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _int(obj: Any, name: str) -> int:
    value = getattr(obj, name, None)
    return value if isinstance(value, int) else 0


def _token_counts(provider: str, resp: Any) -> tuple[int, int, int, int, int]:
    """(prompt, cache_hit, cache_write, completion, reasoning) from one raw API response."""
    if provider == "gemini":
        u = getattr(resp, "usage_metadata", None)
        thoughts = _int(u, "thoughts_token_count")
        # Gemini reports thinking tokens apart from the answer, but bills both as output.
        return (_int(u, "prompt_token_count"), _int(u, "cached_content_token_count"), 0,
                _int(u, "candidates_token_count") + thoughts, thoughts)
    u = getattr(resp, "usage", None)
    if provider == "claude":
        hit, write = _int(u, "cache_read_input_tokens"), _int(u, "cache_creation_input_tokens")
        # Claude's input_tokens excludes the cached part.
        return _int(u, "input_tokens") + hit + write, hit, write, _int(u, "output_tokens"), 0
    hit = _int(u, "prompt_cache_hit_tokens") or _int(getattr(u, "prompt_tokens_details", None), "cached_tokens")
    return (_int(u, "prompt_tokens"), hit, 0, _int(u, "completion_tokens"),
            _int(getattr(u, "completion_tokens_details", None), "reasoning_tokens"))


class UsageReporter:
    """Mixin for providers: hands every billed request to `on_usage`, if the caller set one."""

    on_usage: Callable[[LlmCall], None] | None = None

    def _report_usage(self, resp: Any, model: str, label: str, seconds: float) -> None:
        if self.on_usage is None:
            return
        # Accounting must never fail a request that has already been billed (it would be retried).
        try:
            prompt, hit, write, completion, reasoning = _token_counts(self.name, resp)
            if prompt or completion:
                self.on_usage(LlmCall(self.name, model, label, prompt, hit, write, completion, reasoning, seconds))
        except Exception as e:  # noqa: BLE001
            log.warning("Không ghi được token usage (%s %s): %s", self.name, model, e)
