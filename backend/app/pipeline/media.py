"""ffmpeg / whisper.cpp process wrappers."""

import json
import re
import subprocess
from pathlib import Path

from ..config import settings
from .subtitles import Cue, is_non_speech

_VAD_LINE_RE = re.compile(r"start = ([\d.]+), end = ([\d.]+)")


class MediaError(RuntimeError):
    pass


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
        )
    except FileNotFoundError as e:
        raise MediaError(f"Không tìm thấy chương trình: {cmd[0]}") from e
    except subprocess.TimeoutExpired as e:
        raise MediaError(f"{Path(cmd[0]).name} chạy quá {timeout}s") from e
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-5:]
        raise MediaError(f"{Path(cmd[0]).name} lỗi (mã {proc.returncode}): " + " | ".join(tail))
    return proc


def probe_duration(video: Path) -> float:
    proc = _run(
        [settings.ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)],
        timeout=60,
    )
    return float(proc.stdout.strip() or 0)


def extract_audio(video: Path, wav: Path) -> None:
    """16 kHz mono PCM, the format whisper.cpp expects."""
    _run([settings.ffmpeg, "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
          "-c:a", "pcm_s16le", str(wav)], timeout=600)


def detect_speech(wav: Path) -> list[tuple[int, int]]:
    """Voice-activity regions in milliseconds on the original timeline."""
    proc = _run([str(settings.vad_cli), "-f", str(wav), "-vm", str(settings.vad_model_path), "-vp", "200",
                 "-t", str(settings.whisper_threads), "-np"], timeout=600)
    regions = []
    for match in _VAD_LINE_RE.finditer(proc.stdout):
        # The tool prints centiseconds.
        regions.append((int(float(match.group(1)) * 10), int(float(match.group(2)) * 10)))
    return regions


def transcribe(wav: Path, language: str, out_base: Path) -> tuple[str, list[Cue]]:
    """Run whisper.cpp with VAD so music-only stretches are skipped instead of hallucinated over."""
    cmd = [
        str(settings.whisper_cli), "-m", str(settings.whisper_model_path), "-f", str(wav),
        "-l", language, "-t", str(settings.whisper_threads),
        "-bs", "1", "-bo", "1",  # greedy: ~10x faster on CPU with no visible quality loss on dialogue
        "-mc", "0",  # no cross-segment context: stops "Let's go." repetition loops
        "-sns", "--vad", "-vm", str(settings.vad_model_path), "-vp", "200",
        "-oj", "-of", str(out_base), "-np",
    ]
    _run(cmd, timeout=3600)
    data = json.loads(out_base.with_suffix(".json").read_text(encoding="utf-8"))
    detected = data.get("result", {}).get("language") or language
    cues: list[Cue] = []
    for seg in data.get("transcription", []):
        text = seg.get("text", "").strip()
        if is_non_speech(text):
            continue
        cues.append(Cue(len(cues) + 1, int(seg["offsets"]["from"]), int(seg["offsets"]["to"]), text))
    return detected, cues


def _filter_path(path: Path) -> str:
    """Escape a path for use inside an ffmpeg filtergraph (Windows drive colons, quotes)."""
    return str(path).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def burn_subtitles(video: Path, ass: Path, out: Path, fonts_dir: Path | None = None) -> None:
    # Complex shaping is required for Khmer/Myanmar/Lao clusters; see subtitles.to_ass.
    vf = f"ass='{_filter_path(ass)}':shaping=complex"
    if fonts_dir:
        vf += f":fontsdir='{_filter_path(fonts_dir)}'"
    _run([settings.ffmpeg, "-v", "error", "-y", "-i", str(video), "-vf", vf,
          "-c:v", "libx264", "-preset", "medium", "-crf", str(settings.video_crf),
          "-c:a", "copy", "-movflags", "+faststart", str(out)], timeout=7200)
