"""Runtime settings, read once from the environment and the project's .env file."""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_EXE = ".exe" if sys.platform == "win32" else ""
load_dotenv(PROJECT_ROOT / ".env")


def _path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value) if value else default


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: _path("DATA_DIR", PROJECT_ROOT / "data"))
    web_dist: Path = field(default_factory=lambda: _path("WEB_DIST", PROJECT_ROOT / "web" / "dist"))

    ffmpeg: str = field(default_factory=lambda: os.getenv("FFMPEG_BIN", "ffmpeg"))
    ffprobe: str = field(default_factory=lambda: os.getenv("FFPROBE_BIN", "ffprobe"))
    whisper_dir: Path = field(default_factory=lambda: _path("WHISPER_DIR", PROJECT_ROOT / "tools" / "whisper"))
    whisper_model: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL", "ggml-large-v3-turbo-q5_0.bin"))
    vad_model: str = field(default_factory=lambda: os.getenv("VAD_MODEL", "ggml-silero-v5.1.2.bin"))
    whisper_threads: int = field(default_factory=lambda: int(os.getenv("WHISPER_THREADS", str(os.cpu_count() or 4))))

    # "claude" | "openai" | "mock" (mock is for tests and local UI work only)
    translator: str = field(default_factory=lambda: os.getenv("TRANSLATOR_PROVIDER", "claude").lower())
    claude_model: str = field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-opus-5-5"))
    claude_effort: str = field(default_factory=lambda: os.getenv("CLAUDE_EFFORT", "medium"))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-5"))

    max_cue_seconds: float = field(default_factory=lambda: float(os.getenv("MAX_CUE_SECONDS", "7")))
    video_crf: int = field(default_factory=lambda: int(os.getenv("VIDEO_CRF", "20")))

    @property
    def whisper_cli(self) -> Path:
        return self.whisper_dir / "bin" / f"whisper-cli{_EXE}"

    @property
    def vad_cli(self) -> Path:
        return self.whisper_dir / "bin" / f"whisper-vad-speech-segments{_EXE}"

    @property
    def whisper_model_path(self) -> Path:
        return self.whisper_dir / "models" / self.whisper_model

    @property
    def vad_model_path(self) -> Path:
        return self.whisper_dir / "models" / self.vad_model

    @property
    def db_path(self) -> Path:
        return self.data_dir / "substudio.db"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"


settings = Settings()
