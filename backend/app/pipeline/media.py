"""ffmpeg / FunASR process and model wrappers."""

import json
import logging
import os
import re
import subprocess
import threading
from pathlib import Path
from typing import Any

from ..config import settings
from .subtitles import Cue, is_non_speech

log = logging.getLogger("substudio.media")

_model_lock = threading.Lock()
_asr_model: Any = None
_vad_model: Any = None


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
    """16 kHz mono PCM, the format FunASR expects."""
    _run([settings.ffmpeg, "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
          "-c:a", "pcm_s16le", str(wav)], timeout=600)


def _ensure_models_dir() -> None:
    settings.models_dir.mkdir(parents=True, exist_ok=True)
    if "MODELSCOPE_CACHE" not in os.environ:
        os.environ["MODELSCOPE_CACHE"] = str(settings.models_dir)


def get_asr_model():
    global _asr_model
    if _asr_model is None:
        with _model_lock:
            if _asr_model is None:
                _ensure_models_dir()
                import torch
                if settings.funasr_threads > 0:
                    torch.set_num_threads(settings.funasr_threads)
                from funasr import AutoModel
                log.info("Loading FunASR model %s (device: %s)...", settings.funasr_model, settings.funasr_device)
                kwargs: dict[str, Any] = {
                    "model": settings.funasr_model,
                    "device": settings.funasr_device,
                    "disable_update": True,
                }
                if settings.funasr_vad_model:
                    kwargs["vad_model"] = settings.funasr_vad_model
                    kwargs["vad_kwargs"] = {"max_single_segment_time": 30000}
                if settings.funasr_punc_model:
                    kwargs["punc_model"] = settings.funasr_punc_model
                _asr_model = AutoModel(**kwargs)
    return _asr_model


def get_vad_model():
    global _vad_model
    if _vad_model is None:
        with _model_lock:
            if _vad_model is None:
                _ensure_models_dir()
                import torch
                if settings.funasr_threads > 0:
                    torch.set_num_threads(settings.funasr_threads)
                from funasr import AutoModel
                log.info("Loading FunASR VAD model %s (device: %s)...", settings.funasr_vad_model, settings.funasr_device)
                _vad_model = AutoModel(
                    model=settings.funasr_vad_model,
                    device=settings.funasr_device,
                    disable_update=True,
                )
    return _vad_model


def detect_speech(wav: Path) -> list[tuple[int, int]]:
    """Voice-activity regions in milliseconds on the original timeline."""
    try:
        vad = get_vad_model()
        res = vad.generate(input=str(wav))
        regions: list[tuple[int, int]] = []
        if res and isinstance(res, list) and len(res) > 0:
            value = res[0].get("value", [])
            for seg in value:
                if isinstance(seg, (list, tuple)) and len(seg) >= 2:
                    regions.append((int(seg[0]), int(seg[1])))
        return regions
    except Exception as e:
        log.warning("FunASR VAD error: %s, falling back to full audio duration", e)
        duration_ms = int(probe_duration(wav) * 1000)
        return [(0, max(duration_ms, 1000))]


def _clean_rich_text(text: str) -> str:
    """Strip rich transcription tags (<|BGM|>, <|Speech|>, emotion tags, etc.)."""
    try:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess
        cleaned = rich_transcription_postprocess(text)
    except Exception:
        cleaned = text
    # Safety regex fallback for any leftover tags like <|zh|>, <|BGM|>, etc.
    cleaned = re.sub(r"<\|[^|>]+\|>", "", cleaned)
    return cleaned.strip()


def split_segment_cues(start_ms: int, end_ms: int, text: str, max_dur_ms: int = 7000) -> list[tuple[int, int, str]]:
    """Split a long segment into natural sentence-level subtitle cues."""
    dur = end_ms - start_ms
    if dur <= max_dur_ms:
        return [(start_ms, end_ms, text)]

    # Split on sentence terminators: ? ! . ; and Chinese equivalents ？ ！ 。 ； \n
    parts = re.split(r"([。？！?!；;\n]+)", text)
    sentences = []
    for i in range(0, len(parts), 2):
        s = parts[i]
        delim = parts[i + 1] if i + 1 < len(parts) else ""
        t = (s + delim).strip()
        if t:
            sentences.append(t)

    if len(sentences) <= 1:
        # If no sentence punctuation and text is very long, try splitting on commas
        if dur > max_dur_ms * 1.5:
            parts = re.split(r"([，,]+)", text)
            sentences = []
            for i in range(0, len(parts), 2):
                s = parts[i]
                delim = parts[i + 1] if i + 1 < len(parts) else ""
                t = (s + delim).strip()
                if t:
                    sentences.append(t)

    if len(sentences) <= 1:
        return [(start_ms, end_ms, text)]

    total_chars = max(sum(len(s) for s in sentences), 1)
    result: list[tuple[int, int, str]] = []
    curr_start = start_ms
    for i, s in enumerate(sentences):
        if i == len(sentences) - 1:
            curr_end = end_ms
        else:
            fraction = len(s) / total_chars
            curr_end = curr_start + int(dur * fraction)
        if curr_end > curr_start:
            result.append((curr_start, curr_end, s))
        curr_start = curr_end
    return result or [(start_ms, end_ms, text)]


def transcribe(wav: Path, language: str, out_base: Path) -> tuple[str, list[Cue]]:
    """Run FunASR (SenseVoiceSmall) with VAD to produce timestamped cues."""
    model = get_asr_model()
    gen_kwargs: dict[str, Any] = {
        "input": str(wav),
        "use_itn": True,
        "batch_size_s": 60,
        "merge_vad": True,
        "merge_length_s": 15,
        "sentence_timestamp": True,
    }
    # Language: SenseVoice supports "auto", "zh", "en", "yue", "ja", "ko"
    if language and language != "auto":
        gen_kwargs["language"] = language
    else:
        gen_kwargs["language"] = "auto"

    try:
        res_list = model.generate(**gen_kwargs)
    except Exception as e:
        raise MediaError(f"Lỗi khi chạy FunASR nhận diện giọng nói: {e}") from e

    res = res_list[0] if res_list and isinstance(res_list, list) else {}
    raw_full_text = res.get("text", "")

    # Detect language if set to auto
    detected = language
    if not detected or detected == "auto":
        # Look for language tags like <|zh|>, <|en|>, <|ja|>, <|ko|>, <|yue|>
        m = re.search(r"<\|(zh|en|ja|ko|yue|vi|th)\|>", raw_full_text)
        if m:
            detected = m.group(1)
            if detected == "yue":
                detected = "zh"
        else:
            detected = "zh"  # default to Chinese for FunASR if unidentified

    sentence_info = res.get("sentence_info", [])
    cues: list[Cue] = []
    max_cue_ms = int(settings.max_cue_seconds * 1000)

    if sentence_info:
        for seg in sentence_info:
            raw_seg_text = seg.get("text") or seg.get("sentence", "")
            clean_text = _clean_rich_text(raw_seg_text)
            if is_non_speech(clean_text):
                continue
            start_ms = int(seg.get("start", 0))
            end_ms = int(seg.get("end", 0))
            if end_ms > start_ms and clean_text:
                for sub_start, sub_end, sub_text in split_segment_cues(start_ms, end_ms, clean_text, max_cue_ms):
                    cues.append(Cue(len(cues) + 1, sub_start, sub_end, sub_text))

    if not cues and raw_full_text:
        clean_text = _clean_rich_text(raw_full_text)
        if clean_text and not is_non_speech(clean_text):
            duration_ms = int(probe_duration(wav) * 1000)
            for sub_start, sub_end, sub_text in split_segment_cues(0, duration_ms, clean_text, max_cue_ms):
                cues.append(Cue(len(cues) + 1, sub_start, sub_end, sub_text))

    # Save debug / report JSON for traceability
    out_json = out_base.with_suffix(".json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    debug_data = {
        "detected_language": detected,
        "cue_count": len(cues),
        "raw_text": raw_full_text,
        "sentence_info": sentence_info,
        "cues": [{"id": c.id, "start_ms": c.start_ms, "end_ms": c.end_ms, "text": c.text} for c in cues],
    }
    out_json.write_text(json.dumps(debug_data, ensure_ascii=False, indent=2), encoding="utf-8")

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
