"""SQLite storage: films (context + glossary) and subtitle jobs."""

import logging
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import JSON, Column, event
from sqlmodel import Field, Session, SQLModel, create_engine

from .config import settings

log = logging.getLogger("substudio.db")


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
    subtitle_config: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


class HlsJobStatus:
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


class HlsJob(SQLModel, table=True):
    id: str = Field(primary_key=True)  # UUID v4 string
    filename: str                      # Stored temp input filename e.g. input.mp4
    original_name: str                 # Original file name from user
    source_size: int | None = None     # Size in bytes
    status: str = HlsJobStatus.UPLOADING
    progress: int = 0                  # 0 to 100
    current_rendition: str | None = None
    selected_renditions: list = Field(default_factory=list, sa_column=Column(JSON))
    skipped_renditions: list = Field(default_factory=list, sa_column=Column(JSON))
    completed_renditions: list = Field(default_factory=list, sa_column=Column(JSON))
    logs: list = Field(default_factory=list, sa_column=Column(JSON))
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
    src_height: int | None = None
    output_dir: str | None = None
    queue_position: int | None = None


engine = create_engine(
    f"sqlite:///{settings.db_path.as_posix()}", connect_args={"check_same_thread": False}
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def init_db() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.jobs_dir.mkdir(parents=True, exist_ok=True)
    try:
        settings.hls_storage_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.warning("Không thể tạo hls_storage_path (%s): %s", settings.hls_storage_path, e)
    try:
        settings.hls_upload_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log.warning("Không thể tạo hls_upload_dir (%s): %s", settings.hls_upload_dir, e)
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
