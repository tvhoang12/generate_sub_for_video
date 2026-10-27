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
    funasr_model: str = field(default_factory=lambda: os.getenv("FUNASR_MODEL", "iic/SenseVoiceSmall"))
    funasr_vad_model: str = field(default_factory=lambda: os.getenv("FUNASR_VAD_MODEL", "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"))
    funasr_punc_model: str = field(default_factory=lambda: os.getenv("FUNASR_PUNC_MODEL", ""))
    funasr_device: str = field(default_factory=lambda: os.getenv("FUNASR_DEVICE", "cpu"))
    funasr_threads: int = field(default_factory=lambda: int(os.getenv("FUNASR_THREADS", str(os.cpu_count() or 4))))
    models_dir: Path = field(default_factory=lambda: _path("MODELS_DIR", PROJECT_ROOT / "models"))

    # "gemini" | "claude" | "openai" | "mock" (mock is for tests and local UI work only)
    translator: str = field(default_factory=lambda: os.getenv("TRANSLATOR_PROVIDER", "gemini").lower())
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"))
    claude_model: str = field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-opus-5-5"))
    claude_effort: str = field(default_factory=lambda: os.getenv("CLAUDE_EFFORT", "medium"))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-5"))

    max_cue_seconds: float = field(default_factory=lambda: float(os.getenv("MAX_CUE_SECONDS", "7")))
    video_crf: int = field(default_factory=lambda: int(os.getenv("VIDEO_CRF", "20")))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "substudio.db"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"


settings = Settings()
if "MODELSCOPE_CACHE" not in os.environ:
    os.environ["MODELSCOPE_CACHE"] = str(settings.models_dir)

