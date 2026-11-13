"""Runtime settings, read once from the environment and the project's .env file."""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_EXE = ".exe" if sys.platform == "win32" else ""

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass


def _path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value) if value else default


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=lambda: _path("DATA_DIR", PROJECT_ROOT / "data"))
    web_dist: Path = field(default_factory=lambda: _path("WEB_DIST", PROJECT_ROOT / "web" / "dist"))

    ffmpeg: str = field(default_factory=lambda: os.getenv("FFMPEG_BIN", "ffmpeg"))
    ffprobe: str = field(default_factory=lambda: os.getenv("FFPROBE_BIN", "ffprobe"))
    ffmpeg_threads: int = field(
        default_factory=lambda: int(os.getenv("FFMPEG_THREADS", str(min(os.cpu_count() or 4, 16))))
    )
    ffmpeg_filter_threads: int = field(
        default_factory=lambda: int(os.getenv("FFMPEG_FILTER_THREADS", "4"))
    )
    funasr_model: str = field(default_factory=lambda: os.getenv("FUNASR_MODEL", "iic/SenseVoiceSmall"))
    funasr_vad_model: str = field(default_factory=lambda: os.getenv("FUNASR_VAD_MODEL", "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"))
    funasr_punc_model: str = field(default_factory=lambda: os.getenv("FUNASR_PUNC_MODEL", ""))
    funasr_device: str = field(default_factory=lambda: os.getenv("FUNASR_DEVICE", "cpu"))
    funasr_threads: int = field(default_factory=lambda: int(os.getenv("FUNASR_THREADS", str(os.cpu_count() or 4))))
    models_dir: Path = field(default_factory=lambda: _path("MODELS_DIR", PROJECT_ROOT / "models"))

    # FunASR VAD & cadence splitting configuration
    funasr_merge_vad: bool = field(
        default_factory=lambda: os.getenv("FUNASR_MERGE_VAD", "false").lower() in ("true", "1", "yes")
    )
    funasr_merge_length_s: int = field(
        default_factory=lambda: int(os.getenv("FUNASR_MERGE_LENGTH_S", "4"))
    )
    funasr_vad_max_segment_ms: int = field(
        default_factory=lambda: int(os.getenv("FUNASR_VAD_MAX_SEGMENT_MS", "5000"))
    )
    funasr_vad_max_silence_ms: int = field(
        default_factory=lambda: int(os.getenv("FUNASR_VAD_MAX_SILENCE_MS", "450"))
    )
    funasr_vad_speech_noise_thres: float = field(
        default_factory=lambda: float(os.getenv("FUNASR_VAD_SPEECH_NOISE_THRES", "0.8"))
    )

    # "gemini" | "claude" | "openai" | "mock" (mock is for tests and local UI work only)
    translator: str = field(default_factory=lambda: os.getenv("TRANSLATOR_PROVIDER", "gemini").lower())
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_backup_api_key: str = field(
        default_factory=lambda: os.getenv("GEMINI_BACKUP_API_KEY", "AQ.Ab8RN6Jyje8P9LoUt0_GAIMigRIOfOXddkP6WO9-1bi1ofISgQ")
    )
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"))
    gemini_fallback_models: str = field(
        default_factory=lambda: os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.5-flash-lite,gemini-3.6-flash,gemini-3.5-flash,gemini-3.8-flash")
    )
    claude_model: str = field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-opus-5-5"))
    claude_fallback_models: str = field(
        default_factory=lambda: os.getenv("CLAUDE_FALLBACK_MODELS", "claude-sonnet-4-5,claude-3-5-sonnet-20241022,claude-3-5-haiku-20241022")
    )
    claude_effort: str = field(default_factory=lambda: os.getenv("CLAUDE_EFFORT", "medium"))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_model: str = field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    openai_fallback_models: str = field(
        default_factory=lambda: os.getenv("OPENAI_FALLBACK_MODELS", "gpt-4o,gpt-4-turbo,gpt-3.5-turbo")
    )

    max_cue_seconds: float = field(default_factory=lambda: float(os.getenv("MAX_CUE_SECONDS", "4.0")))
    video_crf: int = field(default_factory=lambda: int(os.getenv("VIDEO_CRF", "20")))
    video_preset: str = field(default_factory=lambda: os.getenv("VIDEO_PRESET", "veryfast"))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "substudio.db"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"


settings = Settings()
if "MODELSCOPE_CACHE" not in os.environ:
    os.environ["MODELSCOPE_CACHE"] = str(settings.models_dir)

