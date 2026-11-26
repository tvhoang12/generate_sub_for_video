"""Aggregates the recorded runs for GET /api/usage."""

from datetime import date, datetime, time, timedelta, timezone

from sqlmodel import Session, select

from .db import LlmUsage, ProcessingRun
from .pricing import VN_TZ

TOKEN_FIELDS = (
    "prompt_tokens", "cache_hit_tokens", "cache_write_tokens", "completion_tokens", "reasoning_tokens",
    "total_tokens",
)


def _day_start_utc(day: date) -> datetime:
    return datetime.combine(day, time(), VN_TZ).astimezone(timezone.utc)


def _llm_totals(calls: list[LlmUsage]) -> dict:
    return {
        "calls": len(calls),
        **{f: sum(getattr(c, f) for c in calls) for f in TOKEN_FIELDS},
        "llm_cost_usd": round(sum(c.cost_usd or 0 for c in calls), 6),
        # Calls of models without a price: llm_cost_usd is incomplete when this is not 0.
        "unpriced_calls": sum(c.cost_usd is None for c in calls),
    }


def _totals(runs: list[ProcessingRun], calls: list[LlmUsage]) -> dict:
    llm = _llm_totals(calls)
    compute_cost = sum(r.compute_cost_usd or 0 for r in runs)
    return {
        **llm,
        "runs": len(runs),
        "video_seconds": round(sum(r.video_seconds or 0 for r in runs), 3),
        "compute_seconds": round(sum(r.compute_seconds for r in runs), 3),
        "compute_cost_usd": round(compute_cost, 6),
        "total_cost_usd": round(llm["llm_cost_usd"] + compute_cost, 6),
    }


def build_report(
    s: Session,
    date_from: date | None = None,
    date_to: date | None = None,
    source_language: str | None = None,
    job_id: int | None = None,
) -> dict:
    """Dates are inclusive and in Vietnam time. Runs of deleted jobs count, except in a job_id query."""
    query = select(ProcessingRun).order_by(ProcessingRun.id.desc())
    if date_from:
        query = query.where(ProcessingRun.started_at >= _day_start_utc(date_from))
    if date_to:
        query = query.where(ProcessingRun.started_at < _day_start_utc(date_to + timedelta(days=1)))
    if source_language:
        query = query.where(ProcessingRun.source_language == source_language)
    if job_id is not None:
        # SQLite can hand a deleted job's id to a new job.
        query = query.where(ProcessingRun.job_id == job_id, ProcessingRun.job_deleted == False)  # noqa: E712
    runs = s.exec(query).all()

    run_ids = query.with_only_columns(ProcessingRun.id).order_by(None)
    calls = s.exec(select(LlmUsage).where(LlmUsage.run_id.in_(run_ids))).all()
    by_run: dict[int, list[LlmUsage]] = {}
    by_model: dict[tuple[str, str], list[LlmUsage]] = {}
    for c in calls:
        by_run.setdefault(c.run_id, []).append(c)
        by_model.setdefault((c.provider, c.model), []).append(c)

    return {
        "totals": _totals(runs, calls),
        "by_model": [
            {"provider": provider, "model": model, **_llm_totals(group)}
            for (provider, model), group in sorted(by_model.items())
        ],
        "runs": [{**r.model_dump(), **_totals([r], by_run.get(r.id, []))} for r in runs],
    }
