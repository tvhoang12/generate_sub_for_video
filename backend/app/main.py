"""HTTP API and static web UI."""

import logging
import shutil
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import Session, select

from .config import settings
from .db import Film, GlossaryTerm, Job, JobStatus, STEPS, get_session, init_db
from .languages import LANGUAGES, SOURCE_LANGUAGES
from .pipeline.runner import JobRunner, job_dir, safe_name

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
SessionDep = Annotated[Session, Depends(get_session)]


def create_app(runner: JobRunner | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()
        app.state.runner = runner or JobRunner()
        app.state.runner.start()
        yield

    app = FastAPI(title="SubStudio", lifespan=lifespan)
    app.include_router(_api_routes())
    if settings.web_dist.is_dir():
        app.mount("/assets", StaticFiles(directory=settings.web_dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            file = settings.web_dist / path
            if path and file.is_file():
                return FileResponse(file)
            return FileResponse(settings.web_dist / "index.html")

    return app


# ---- request bodies ---------------------------------------------------------------------------

class FilmIn(BaseModel):
    name: str
    source_language: str = "auto"
    synopsis: str = ""
    characters: str = ""
    style_notes: str = ""


class TermIn(BaseModel):
    term: str
    note: str = ""
    translations: dict[str, str] = {}
    suggested: bool = False


def _api_routes():
    from fastapi import APIRouter

    api = APIRouter(prefix="/api")

    def get_or_404(s: Session, model, obj_id: int):
        obj = s.get(model, obj_id)
        if obj is None:
            raise HTTPException(404, "Không tìm thấy")
        return obj

    @api.get("/meta")
    def meta():
        model = {"claude": settings.claude_model, "openai": settings.openai_model}.get(settings.translator, "")
        return {
            "languages": [{"code": l.code, "label": l.label} for l in LANGUAGES.values()],
            "source_languages": [{"code": c, "label": n} for c, n in SOURCE_LANGUAGES.items()],
            "provider": settings.translator,
            "model": model,
            "steps": STEPS,
        }

    # ---- films & glossary ----

    @api.get("/films")
    def list_films(s: SessionDep):
        films = s.exec(select(Film).order_by(Film.name)).all()
        counts = {}
        for t in s.exec(select(GlossaryTerm)).all():
            c = counts.setdefault(t.film_id, {"term_count": 0, "suggested_count": 0})
            c["suggested_count" if t.suggested else "term_count"] += 1
        return [{**f.model_dump(), **counts.get(f.id, {"term_count": 0, "suggested_count": 0})} for f in films]

    @api.post("/films", status_code=201)
    def create_film(body: FilmIn, s: SessionDep):
        if not body.name.strip():
            raise HTTPException(422, "Tên phim không được để trống")
        film = Film(**body.model_dump())
        s.add(film)
        s.commit()
        s.refresh(film)
        return film

    @api.get("/films/{film_id}")
    def get_film(film_id: int, s: SessionDep):
        film = get_or_404(s, Film, film_id)
        terms = s.exec(select(GlossaryTerm).where(GlossaryTerm.film_id == film_id).order_by(GlossaryTerm.term)).all()
        return {**film.model_dump(), "terms": terms}

    @api.put("/films/{film_id}")
    def update_film(film_id: int, body: FilmIn, s: SessionDep):
        film = get_or_404(s, Film, film_id)
        for key, value in body.model_dump().items():
            setattr(film, key, value)
        s.add(film)
        s.commit()
        s.refresh(film)
        return film

    @api.delete("/films/{film_id}", status_code=204)
    def delete_film(film_id: int, s: SessionDep):
        film = get_or_404(s, Film, film_id)
        for t in s.exec(select(GlossaryTerm).where(GlossaryTerm.film_id == film_id)).all():
            s.delete(t)
        for j in s.exec(select(Job).where(Job.film_id == film_id)).all():
            j.film_id = None  # jobs and their outputs are kept
            s.add(j)
        s.delete(film)
        s.commit()

    @api.post("/films/{film_id}/terms", status_code=201)
    def add_term(film_id: int, body: TermIn, s: SessionDep):
        get_or_404(s, Film, film_id)
        if not body.term.strip():
            raise HTTPException(422, "Thuật ngữ không được để trống")
        term = GlossaryTerm(film_id=film_id, **body.model_dump())
        s.add(term)
        s.commit()
        s.refresh(term)
        return term

    @api.put("/terms/{term_id}")
    def update_term(term_id: int, body: TermIn, s: SessionDep):
        term = get_or_404(s, GlossaryTerm, term_id)
        for key, value in body.model_dump().items():
            setattr(term, key, value)
        term.translations = {k: v for k, v in body.translations.items() if v.strip()}
        s.add(term)
        s.commit()
        s.refresh(term)
        return term

    @api.delete("/terms/{term_id}", status_code=204)
    def delete_term(term_id: int, s: SessionDep):
        s.delete(get_or_404(s, GlossaryTerm, term_id))
        s.commit()

    # ---- jobs ----

    @api.post("/jobs", status_code=201)
    def create_job(
        request: Request,
        s: SessionDep,
        file: UploadFile = File(...),
        languages: str = Form(...),
        title: str = Form(""),
        film_id: int | None = Form(None),
        episode_notes: str = Form(""),
    ):
        filename = Path(file.filename or "video.mp4").name
        if Path(filename).suffix.lower() not in VIDEO_EXTENSIONS:
            raise HTTPException(422, "Chỉ nhận file video: " + ", ".join(sorted(VIDEO_EXTENSIONS)))
        codes = [c.strip() for c in languages.split(",") if c.strip()]
        if not codes or any(c not in LANGUAGES for c in codes):
            raise HTTPException(422, "Chọn ít nhất một ngôn ngữ hợp lệ")
        if film_id is not None:
            get_or_404(s, Film, film_id)

        job = Job(title=title.strip() or Path(filename).stem, video_filename=filename, film_id=film_id,
                  languages=list(dict.fromkeys(codes)), episode_notes=episode_notes)
        s.add(job)
        s.commit()
        s.refresh(job)
        dest = job_dir(job.id) / "input"
        dest.mkdir(parents=True, exist_ok=True)
        with open(dest / filename, "wb") as f:
            shutil.copyfileobj(file.file, f, length=4 * 1024 * 1024)
        request.app.state.runner.submit(job.id)
        return job

    @api.get("/jobs")
    def list_jobs(s: SessionDep):
        return s.exec(select(Job).order_by(Job.id.desc())).all()

    @api.get("/jobs/{job_id}")
    def get_job(job_id: int, s: SessionDep):
        return get_or_404(s, Job, job_id)

    @api.post("/jobs/{job_id}/retry")
    def retry_job(job_id: int, request: Request, s: SessionDep):
        job = get_or_404(s, Job, job_id)
        if job.status not in (JobStatus.FAILED, JobStatus.DONE):
            raise HTTPException(409, "Job đang chạy hoặc đang chờ")
        job.status, job.step, job.progress, job.error = JobStatus.QUEUED, None, 0, None
        s.add(job)
        s.commit()
        request.app.state.runner.submit(job.id)
        return job

    @api.delete("/jobs/{job_id}", status_code=204)
    def delete_job(job_id: int, s: SessionDep):
        job = get_or_404(s, Job, job_id)
        if job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            raise HTTPException(409, "Không thể xoá job đang chạy hoặc đang chờ")
        shutil.rmtree(job_dir(job_id), ignore_errors=True)
        s.delete(job)
        s.commit()

    def _output_files(job: Job) -> list[Path]:
        out = job_dir(job.id) / "out"
        return [out / o["file"] for o in job.report.get("outputs", []) if (out / o["file"]).is_file()]

    @api.get("/jobs/{job_id}/files/{name}")
    def download_file(job_id: int, name: str, s: SessionDep):
        job = get_or_404(s, Job, job_id)
        for path in _output_files(job):
            if path.name == name:
                return FileResponse(path, filename=name)
        raise HTTPException(404, "Không tìm thấy file")

    @api.get("/jobs/{job_id}/download")
    def download_all(job_id: int, s: SessionDep):
        job = get_or_404(s, Job, job_id)
        files = _output_files(job)
        if job.status != JobStatus.DONE or not files:
            raise HTTPException(409, "Job chưa hoàn thành")
        archive = job_dir(job_id) / f"{job_id}.zip"
        # Videos are already compressed; storing is as small and much faster.
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as z:
            for path in files:
                z.write(path, path.name)
        return FileResponse(archive, filename=f"{safe_name(job.title)}.zip")

    return api


app = create_app()
