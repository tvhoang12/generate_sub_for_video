"""Records what one run of a job cost: LLM tokens per request and wall time per pipeline step."""

import logging
import time

from sqlmodel import Session, select

from ..config import settings
from ..db import Job, LlmUsage, ProcessingRun, engine, utcnow
from ..pricing import price_call
from ..translation.usage import LlmCall

log = logging.getLogger("substudio.tracking")

# Steps that keep this machine busy; "clean" and "translate" mostly wait for the LLM API.
COMPUTE_STEPS = ("extract", "transcribe", "render")


class RunTracker:
    """Context manager around one job run. Does nothing until start() is called.

    Statistics are secondary: every database error here is logged and swallowed.
    """

    def __init__(self) -> None:
        self.run_id: int | None = None
        self._job_id = 0
        self._step: str | None = None
        self._step_started = 0.0
        self._step_seconds: dict[str, float] = {}

    def __enter__(self) -> "RunTracker":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._close_step()
        self.update(
            status="failed" if exc else "done",
            error=(str(exc) or exc_type.__name__) if exc else None,
            finished_at=utcnow(),
        )

    def start(self, job: Job, provider: str, source_language: str) -> None:
        self._job_id = job.id
        try:
            with Session(engine) as s:
                run = ProcessingRun(
                    job_id=job.id, job_title=job.title, film_id=job.film_id, languages=list(job.languages),
                    provider=provider, source_language=source_language,
                )
                s.add(run)
                s.commit()
                self.run_id = run.id
        except Exception as e:  # noqa: BLE001
            log.warning("Job %d: không tạo được bản ghi chi phí: %s", job.id, e)

    def step(self, name: str) -> None:
        """Close the current step and start timing the next one."""
        if name == self._step:
            return
        self._close_step()
        self._step, self._step_started = name, time.monotonic()

    def _close_step(self) -> None:
        if self._step is None:
            return
        elapsed = time.monotonic() - self._step_started
        self._step_seconds[self._step] = round(self._step_seconds.get(self._step, 0) + elapsed, 3)
        self._step = None
        compute = round(sum(self._step_seconds.get(n, 0) for n in COMPUTE_STEPS), 3)
        rate = settings.compute_cost_per_hour_usd
        self.update(
            step_seconds=dict(self._step_seconds),
            compute_seconds=compute,
            compute_cost_usd=compute / 3600 * rate if rate > 0 else None,
        )

    def update(self, **fields) -> None:
        if self.run_id is None:
            return
        try:
            with Session(engine) as s:
                run = s.get(ProcessingRun, self.run_id)
                for key, value in fields.items():
                    setattr(run, key, value)
                s.add(run)
                s.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("Job %d: không cập nhật được bản ghi chi phí: %s", self._job_id, e)

    def record_llm(self, call: LlmCall) -> None:
        """May be called from several translation threads at once; each call uses its own session."""
        if self.run_id is None:
            return
        try:
            cost, tier = price_call(call)
            with Session(engine) as s:
                s.add(LlmUsage(
                    run_id=self.run_id, provider=call.provider, model=call.model, label=call.label,
                    prompt_tokens=call.prompt_tokens, cache_hit_tokens=call.cache_hit_tokens,
                    cache_write_tokens=call.cache_write_tokens, completion_tokens=call.completion_tokens,
                    reasoning_tokens=call.reasoning_tokens, total_tokens=call.total_tokens,
                    seconds=round(call.seconds, 3), cost_usd=cost, price_tier=tier, created_at=call.created_at,
                ))
                s.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("Job %d: không lưu được token usage: %s", self._job_id, e)


def mark_interrupted_runs() -> None:
    """Runs still "running" at startup died with the previous process."""
    with Session(engine) as s:
        for run in s.exec(select(ProcessingRun).where(ProcessingRun.status == "running")).all():
            run.status = "interrupted"
            s.add(run)
        s.commit()
