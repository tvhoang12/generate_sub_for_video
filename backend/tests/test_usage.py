"""Cost records: pricing, provider reporting, run tracking and GET /api/usage."""

from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.db import Job, LlmUsage, ProcessingRun, engine, init_db
from app.main import create_app
from app.pipeline import runner
from app.pipeline.subtitles import Cue
from app.pricing import is_peak, price_call
from app.translation.providers import DeepSeekProvider, MockProvider
from app.translation.usage import LlmCall, UsageReporter, _token_counts


def call(model="deepseek-flash", at=datetime(2026, 11, 26, 2, 0, tzinfo=timezone.utc)):
    return LlmCall("deepseek", model, "batch", 1_000_000, 400_000, 0, 1_000_000, 0, 1.0, at)


def test_peak_hours_are_vietnam_weekdays():
    utc = lambda day, hour: datetime(2026, 11, day, hour, tzinfo=timezone.utc)
    assert is_peak(utc(26, 1))  # Thursday 08:00 VN
    assert not is_peak(utc(26, 4))  # 11:00 VN
    assert is_peak(utc(26, 6))  # 13:00 VN
    assert not is_peak(utc(26, 10))  # 17:00 VN
    assert not is_peak(utc(28, 2))  # Saturday


def test_price_call():
    cost, tier = price_call(call())
    assert tier == "peak"
    assert cost == pytest.approx(0.4 * 0.006 + 0.6 * 0.3 + 1.2)
    cost, tier = price_call(call(at=datetime(2026, 11, 28, 2, tzinfo=timezone.utc)))
    assert tier == "off_peak"
    assert cost == pytest.approx(0.4 * 0.003 + 0.6 * 0.15 + 0.6)
    assert price_call(call(model="unknown-model")) == (None, None)


def test_token_counts_per_provider():
    claude = NS(usage=NS(input_tokens=10, cache_read_input_tokens=5, cache_creation_input_tokens=3, output_tokens=7))
    assert _token_counts("claude", claude) == (18, 5, 3, 7, 0)
    gemini = NS(usage_metadata=NS(prompt_token_count=20, cached_content_token_count=None,
                                  candidates_token_count=8, thoughts_token_count=2))
    assert _token_counts("gemini", gemini) == (20, 0, 0, 10, 2)
    openai = NS(usage=NS(prompt_tokens=30, completion_tokens=9, prompt_tokens_details=NS(cached_tokens=4),
                         completion_tokens_details=NS(reasoning_tokens=6)))
    assert _token_counts("openai", openai) == (30, 4, 0, 9, 6)


def test_failing_recorder_does_not_retry_a_billed_request(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    client = MagicMock()
    client.chat.completions.create.return_value = NS(
        usage=NS(prompt_tokens=5, completion_tokens=2),
        choices=[NS(message=NS(content="context"), finish_reason="stop")],
    )
    with patch("openai.OpenAI", return_value=client):
        DeepSeekProvider._shared_model_idx = 0
        provider = DeepSeekProvider()
        provider.on_usage = MagicMock(side_effect=RuntimeError("db is locked"))
        assert provider.extract_global_context("s", "u") == "context"
    assert client.chat.completions.create.call_count == 1
    provider.on_usage.assert_called_once()


class BilledMock(MockProvider, UsageReporter):
    """MockProvider that reports DeepSeek-shaped usage for every request."""

    def _bill(self, label):
        self.on_usage(LlmCall("mock", "deepseek-flash", label, 100, 40, 0, 50, 10, 0.1))

    def extract_global_context(self, system, user):
        self._bill("context")
        return super().extract_global_context(system, user)

    def complete_batch(self, system, user):
        self._bill("batch")
        return super().complete_batch(system, user)


@pytest.fixture
def fake_media(monkeypatch):
    monkeypatch.setattr(runner.media, "extract_audio", lambda *a, **k: None)
    monkeypatch.setattr(runner.media, "probe_video_dimensions", lambda *a: (1280, 720))
    monkeypatch.setattr(runner.media, "probe_duration", lambda *a: 60.0)
    monkeypatch.setattr(runner.media, "detect_speech", lambda *a: [(0, 2000)])
    monkeypatch.setattr(runner.media, "transcribe", lambda *a, **k: ("zh", [Cue(1, 0, 2000, "你好")]))
    monkeypatch.setattr(runner.media, "burn_subtitles", lambda video, ass, out: out.write_bytes(b"x"))


def new_job() -> int:
    init_db()
    with Session(engine) as s:
        job = Job(title="Tập 1", video_filename="a.mp4", languages=["my"])
        s.add(job)
        s.commit()
        return job.id


def test_run_is_recorded_and_survives_job_deletion(fake_media):
    job_id = new_job()
    runner.run_job(job_id, BilledMock)

    with TestClient(create_app(runner=MagicMock(), hls_runner=MagicMock())) as client:
        report = client.get("/api/usage", params={"job_id": job_id}).json()
        [run] = report["runs"]
        assert (run["status"], run["source_language"], run["video_seconds"], run["cue_count"]) == ("done", "zh", 60, 1)
        assert {"extract", "transcribe", "clean", "translate", "render"} <= set(run["step_seconds"])
        assert report["totals"]["calls"] == 2
        assert report["totals"]["total_tokens"] == 300
        assert report["totals"]["llm_cost_usd"] > 0
        assert report["by_model"][0]["model"] == "deepseek-flash"
        assert client.get("/api/usage", params={"job_id": job_id, "source_language": "en"}).json()["runs"] == []
        assert client.get("/api/usage", params={"date_to": "2000-01-01"}).json()["totals"]["calls"] == 0

        before = client.get("/api/usage").json()["totals"]["calls"]
        with Session(engine) as s:
            job = s.get(Job, job_id)
            job.status = "done"
            s.add(job)
            s.commit()
        assert client.delete(f"/api/jobs/{job_id}").status_code == 204
        assert client.get("/api/usage").json()["totals"]["calls"] == before
        assert client.get("/api/usage", params={"job_id": job_id}).json()["runs"] == []


def test_failed_run_keeps_the_tokens_already_billed(fake_media):
    class Failing(BilledMock):
        def complete_batch(self, system, user):
            self._bill("batch")
            raise RuntimeError("API down")

    job_id = new_job()
    with pytest.raises(RuntimeError, match="API down"):
        runner.run_job(job_id, Failing)

    with Session(engine) as s:
        run = s.exec(select(ProcessingRun).order_by(ProcessingRun.id.desc())).first()
        assert (run.job_id, run.status, run.error) == (job_id, "failed", "API down")
        assert run.finished_at is not None
        assert len(s.exec(select(LlmUsage).where(LlmUsage.run_id == run.id)).all()) >= 2
