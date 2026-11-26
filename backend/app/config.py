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
    _env_file = PROJECT_ROOT / ".env"
    if _env_file.is_file():
        for _line in _env_file.read_text(encoding="utf-8").splitlines():
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            _k = _k.strip()
            _v = _v.strip().strip("'\"")
            if _k not in os.environ:
                os.environ[_k] = _v


def _path(names: str | list[str], default: Path) -> Path:
    if isinstance(names, str):
        names = [names]
    value = None
    for name in names:
        val = os.getenv(name)
        if val and val.strip():
            value = val.strip()
            break
    if not value:
        return default
    p = Path(value)
    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    return p


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

    # Test mode: skip transcription + translation and use the subtitles from TEST_SUBTITLE_FILE
    # for every selected language (only extract → render runs). For checking subtitle styling/burning.
    test_mode: bool = field(
        default_factory=lambda: os.getenv("TEST_MODE", "false").lower() in ("true", "1", "yes")
    )
    test_subtitle_file: Path = field(
        default_factory=lambda: _path("TEST_SUBTITLE_FILE", PROJECT_ROOT / "EP1 (Reborn with rival).my.srt")
    )

    # "deepseek" | "gemini" | "claude" | "openai" | "mock" (mock is for tests and local UI work only)
    translator: str = field(default_factory=lambda: os.getenv("TRANSLATOR_PROVIDER", "deepseek").lower())

    # DeepSeek configuration
    deepseek_api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    deepseek_base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"))
    deepseek_model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-flash"))
    deepseek_fallback_models: str = field(
        default_factory=lambda: os.getenv("DEEPSEEK_FALLBACK_MODELS", "deepseek-v4-pro")
    )
    translate_chunk_size: int = field(default_factory=lambda: int(os.getenv("TRANSLATE_CHUNK_SIZE", "50")))
    translate_temperature: float = field(default_factory=lambda: float(os.getenv("TRANSLATE_TEMPERATURE", "0.3")))
    translate_max_tokens: int = field(default_factory=lambda: int(os.getenv("TRANSLATE_MAX_TOKENS", "8192")))

    # Google Gemini
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_backup_api_key: str = field(
        default_factory=lambda: os.getenv("GEMINI_BACKUP_API_KEY", "")
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
    video_encoder: str = field(default_factory=lambda: os.getenv("VIDEO_ENCODER", "libx264"))
    gemini_batch_size: int = field(default_factory=lambda: int(os.getenv("GEMINI_BATCH_SIZE", "70")))
    gemini_concurrency: int = field(default_factory=lambda: int(os.getenv("GEMINI_CONCURRENCY", "2")))
    gemini_rpm_limit: int = field(default_factory=lambda: int(os.getenv("GEMINI_RPM_LIMIT", "14")))

    # HLS conversion settings
    hls_storage_path: Path = field(
        default_factory=lambda: _path(
            ["HLS_STORAGE_PATH", "OUTPUT_DIR"],
            _path("DATA_DIR", PROJECT_ROOT / "data") / "hls",
        )
    )
    hls_upload_dir: Path = field(
        default_factory=lambda: _path(
            ["HLS_UPLOAD_DIR", "UPLOAD_DIR"],
            _path("DATA_DIR", PROJECT_ROOT / "data") / "hls_uploads",
        )
    )
    hls_preset: str = field(
        default_factory=lambda: os.getenv("HLS_PRESET", os.getenv("FFMPEG_PRESET", "veryfast"))
    )
    hls_segment_duration: int = field(
        default_factory=lambda: int(os.getenv("HLS_SEGMENT_DURATION", "6"))
    )
    hls_keyint: int = field(
        default_factory=lambda: int(os.getenv("HLS_KEYINT", "48"))
    )
    hls_max_concurrent: int = field(
        default_factory=lambda: int(os.getenv("HLS_MAX_CONCURRENT", "1"))
    )
    hls_ffmpeg_threads: int = field(
        default_factory=lambda: int(os.getenv("HLS_FFMPEG_THREADS", "4"))
    )

    @property
    def output_dir(self) -> Path:
        return self.hls_storage_path

    @property
    def upload_dir(self) -> Path:
        return self.hls_upload_dir

    @property
    def db_path(self) -> Path:
        return self.data_dir / "substudio.db"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"


settings = Settings()
if "MODELSCOPE_CACHE" not in os.environ:
    os.environ["MODELSCOPE_CACHE"] = str(settings.models_dir)

