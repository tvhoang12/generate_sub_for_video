"""SQLite storage: films (context + glossary) and subtitle jobs."""

from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import JSON, Column
from sqlmodel import Field, Session, SQLModel, create_engine

from .config import settings


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Film(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    source_language: str = "auto"
    synopsis: str = ""
    characters: str = ""
    style_notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class GlossaryTerm(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    film_id: int = Field(foreign_key="film.id", index=True)
    term: str
    note: str = ""
    translations: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # Proposed by the LLM while cleaning an episode; only confirmed terms are sent to the translator.
    suggested: bool = False


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


# Ordered pipeline steps, also shown in the UI stepper.
STEPS = ["extract", "transcribe", "clean", "translate", "render"]


class Job(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    film_id: int | None = Field(default=None, foreign_key="film.id", index=True)
    title: str
    video_filename: str
    languages: list = Field(default_factory=list, sa_column=Column(JSON))
    episode_notes: str = ""
    status: str = JobStatus.QUEUED
    step: str | None = None
    progress: int = 0
    error: str | None = None
    provider: str | None = None
    # {"source_language", "dropped": [...], "warnings": [...], "outputs": [...], "suggested_terms": [...]}
    report: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


engine = create_engine(
    f"sqlite:///{settings.db_path.as_posix()}", connect_args={"check_same_thread": False}
)


def init_db() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
