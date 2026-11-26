"""LLM unit prices (USD per 1M tokens) and the cost of one request.

Costs are computed when a request is recorded and stored with it, so editing prices never
rewrites history. To add or override models, create DATA_DIR/llm_prices.json:

    {"gpt-4o-mini": {"cache_hit": 0.0, "input": 0.0, "output": 0.0},
     "some-model":  {"peak": {...}, "off_peak": {...}}}

"cache_write" is optional and defaults to "input". Models with no price get a NULL cost.
"""

import json
import logging
from datetime import datetime, time, timedelta, timezone

from .config import settings
from .translation.usage import LlmCall

log = logging.getLogger("substudio.pricing")

# DeepSeek peak hours are expressed in Vietnam time (no DST).
VN_TZ = timezone(timedelta(hours=7))
PEAK_WINDOWS = ((time(8), time(11)), (time(13), time(17)))

# Checked 26/11/2026. deepseek-flash: https://api-docs.deepseek.com/quick_start/pricing
# deepseek-v4-pro: third-party listings only, verify against the official page.
DEFAULT_PRICES: dict[str, dict] = {
    "deepseek-flash": {
        "peak": {"cache_hit": 0.006, "input": 0.3, "output": 1.2},
        "off_peak": {"cache_hit": 0.003, "input": 0.15, "output": 0.6},
    },
    "deepseek-v4-pro": {
        "peak": {"cache_hit": 0.044, "input": 1.32, "output": 3.96},
        "off_peak": {"cache_hit": 0.022, "input": 0.66, "output": 1.98},
    },
}


def is_peak(at: datetime) -> bool:
    local = at.astimezone(VN_TZ)
    if local.weekday() >= 5 or local.date().isoformat() in settings.llm_off_peak_dates:
        return False
    return any(start <= local.time() < end for start, end in PEAK_WINDOWS)


def load_prices() -> dict[str, dict]:
    path = settings.data_dir / "llm_prices.json"
    if not path.is_file():
        return DEFAULT_PRICES
    try:
        return {**DEFAULT_PRICES, **json.loads(path.read_text(encoding="utf-8"))}
    except Exception as e:  # noqa: BLE001
        log.warning("Bỏ qua %s vì không đọc được: %s", path, e)
        return DEFAULT_PRICES


def price_call(call: LlmCall) -> tuple[float | None, str | None]:
    """(cost in USD, price tier "peak"/"off_peak"/"flat"); (None, None) for an unpriced model."""
    entry = load_prices().get(call.model)
    if entry is None:
        return None, None
    tier = "flat"
    if "peak" in entry:
        tier = "peak" if is_peak(call.created_at) else "off_peak"
    try:
        p = entry if tier == "flat" else entry[tier]
        plain = max(call.prompt_tokens - call.cache_hit_tokens - call.cache_write_tokens, 0)
        cost = (
            call.cache_hit_tokens * p["cache_hit"]
            + call.cache_write_tokens * p.get("cache_write", p["input"])
            + plain * p["input"]
            + call.completion_tokens * p["output"]
        ) / 1_000_000
    except (KeyError, TypeError) as e:
        log.warning("Bảng giá của model %s không hợp lệ: %s", call.model, e)
        return None, None
    return cost, tier
