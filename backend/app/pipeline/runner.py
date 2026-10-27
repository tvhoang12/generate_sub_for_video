"""Background worker: runs one job at a time through extract → transcribe → clean → translate → render."""

import logging
import queue
import re
import shutil
import threading
from pathlib import Path
from typing import Callable

from sqlmodel import Session, select

from ..config import settings
from ..db import Film, GlossaryTerm, Job, JobStatus, engine, utcnow
from ..languages import get_language
from ..translation.providers import LLMProvider, make_provider
from ..translation.translator import FilmContext, Translator, merge_term_suggestions
from . import media
from .subtitles import Cue, format_timestamp, tighten_timing, to_ass, to_srt

log = logging.getLogger("substudio.runner")


def job_dir(job_id: int) -> Path:
    return settings.jobs_dir / str(job_id)


def safe_name(title: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")
    return name or "video"


def _update(job_id: int, **fields) -> None:
    with Session(engine) as s:
        job = s.get(Job, job_id)
        for key, value in fields.items():
            setattr(job, key, value)
        s.add(job)
        s.commit()


def _film_context(s: Session, job: Job) -> tuple[FilmContext, str]:
    film = s.get(Film, job.film_id) if job.film_id else None
    if film is None:
        return FilmContext(name=job.title, episode_notes=job.episode_notes), "auto"
    terms = s.exec(
        select(GlossaryTerm).where(GlossaryTerm.film_id == film.id, GlossaryTerm.suggested == False)  # noqa: E712
    ).all()
    glossary = {t.term: {"note": t.note, "translations": t.translations or {}} for t in terms}
    ctx = FilmContext(
        name=film.name, synopsis=film.synopsis, characters=film.characters, style_notes=film.style_notes,
        episode_notes=job.episode_notes, glossary=glossary,
    )
    return ctx, film.source_language or "auto"


def _save_suggestions(job: Job, suggestions) -> list[dict]:
    if not job.film_id or not suggestions:
        return []
    with Session(engine) as s:
        existing = {t.term for t in s.exec(select(GlossaryTerm).where(GlossaryTerm.film_id == job.film_id)).all()}
        fresh = merge_term_suggestions(existing, suggestions)
        for t in fresh:
            s.add(GlossaryTerm(film_id=job.film_id, term=t.term.strip(), note=t.note, suggested=True))
        s.commit()
    return [t.model_dump() for t in fresh]


def run_job(job_id: int, provider_factory: Callable[[], LLMProvider] = make_provider) -> None:
    with Session(engine) as s:
        job = s.get(Job, job_id)
        film_ctx, source_language = _film_context(s, job)
        languages = [get_language(code) for code in job.languages]

    base = job_dir(job_id)
    video = base / "input" / job.video_filename
    work, out = base / "work", base / "out"
    shutil.rmtree(out, ignore_errors=True)  # a re-run (e.g. after a restart) starts clean
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    stem = safe_name(job.title)
    report: dict = {"dropped": [], "warnings": [], "outputs": [], "suggested_terms": [], "homophone_corrections": []}

    provider = provider_factory()
    _update(job_id, status=JobStatus.RUNNING, step="extract", progress=2, error=None, provider=provider.name,
            report=report, finished_at=None)

    wav = work / "audio.wav"
    media.extract_audio(video, wav)

    _update(job_id, step="transcribe", progress=8)
    speech = media.detect_speech(wav)
    detected, cues = media.transcribe(wav, source_language, work / "asr")
    if not cues:
        raise RuntimeError("Không phát hiện lời thoại nào trong video")
    cues = tighten_timing(cues, speech, int(settings.max_cue_seconds * 1000))
    report["source_language"] = detected

    _update(job_id, step="clean", progress=25, report=report)
    translator = Translator(provider, film_ctx)
    raw_transcript = " ".join(c.text for c in cues)
    global_context = translator.extract_global_context(raw_transcript)
    report["global_context"] = global_context
    log.info("Job %d: Trích xuất ngữ cảnh toàn cục: %s", job_id, global_context[:200])

    burn_files: dict[str, Path] = {}
    homophone_fixed_source: dict[int, str] = {}

    for i, lang in enumerate(languages):
        _update(job_id, step="translate", progress=35 + int(30 * i / len(languages)), report=report)
        fixed_src_by_id, trans_by_id = translator.translate_in_batches(
            cues,
            lang=lang,
            source_language=detected,
            global_context=global_context,
            batch_size=35,
        )

        if not homophone_fixed_source:
            homophone_fixed_source = fixed_src_by_id
            for c in cues:
                fixed = fixed_src_by_id.get(c.id, c.text)
                if fixed != c.text:
                    report["homophone_corrections"].append({
                        "id": c.id,
                        "original": c.text,
                        "corrected": fixed,
                    })
            if report["homophone_corrections"]:
                log.info("Job %d: Phát hiện và sửa %d lỗi đồng âm", job_id, len(report["homophone_corrections"]))

        translated = [Cue(c.id, c.start_ms, c.end_ms, trans_by_id.get(c.id, "")) for c in cues]
        srt = out / f"{stem}.{lang.code}.srt"
        srt.write_text(to_srt(translated), encoding="utf-8")
        ass = work / f"{lang.code}.ass"
        ass.write_text(to_ass(translated, lang.font), encoding="utf-8")
        burn_files[lang.code] = ass
        report["outputs"].append({"file": srt.name, "kind": "srt", "lang": lang.code})

    # Write source SRT with corrected homophones
    source_cues = [
        Cue(c.id, c.start_ms, c.end_ms, homophone_fixed_source.get(c.id, c.text))
        for c in cues
    ]
    source_srt = out / f"{stem}.{detected}.srt"
    source_srt.write_text(to_srt(source_cues), encoding="utf-8")
    report["outputs"].append({"file": source_srt.name, "kind": "srt", "lang": detected})
    _update(job_id, progress=65, report=report)

    for i, lang in enumerate(languages):
        _update(job_id, step="render", progress=65 + int(35 * i / len(languages)))
        mp4 = out / f"{stem} - {lang.code}.mp4"
        media.burn_subtitles(video, burn_files[lang.code], mp4)
        report["outputs"].append({"file": mp4.name, "kind": "video", "lang": lang.code})
        _update(job_id, report=report)

    _update(job_id, status=JobStatus.DONE, step=None, progress=100, report=report, finished_at=utcnow())


class JobRunner:
    """A single worker thread: CPU-bound FunASR/ffmpeg runs are not worth parallelising on one machine."""

    def __init__(self, provider_factory: Callable[[], LLMProvider] = make_provider) -> None:
        self._queue: queue.Queue[int] = queue.Queue()
        self._provider_factory = provider_factory
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        with Session(engine) as s:
            pending = s.exec(
                select(Job).where(Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING])).order_by(Job.id)
            ).all()
            for job in pending:  # interrupted by a restart: run again from the start
                job.status, job.step, job.progress = JobStatus.QUEUED, None, 0
                s.add(job)
            s.commit()
            ids = [j.id for j in pending]
        self._thread = threading.Thread(target=self._loop, name="job-runner", daemon=True)
        self._thread.start()
        for job_id in ids:
            self.submit(job_id)

    def submit(self, job_id: int) -> None:
        self._queue.put(job_id)

    def _loop(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                run_job(job_id, self._provider_factory)
            except Exception as e:  # noqa: BLE001 - any failure ends the job, never the worker
                log.exception("job %s failed", job_id)
                _update(job_id, status=JobStatus.FAILED, error=str(e) or type(e).__name__, finished_at=utcnow())
