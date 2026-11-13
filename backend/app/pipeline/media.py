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


def probe_video_dimensions(video: Path) -> tuple[int, int]:
    """Return (width, height) of the video, defaulting to (1920, 1080) on failure."""
    try:
        proc = _run(
            [settings.ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(video)],
            timeout=30,
        )
        parts = proc.stdout.strip().split("x")
        if len(parts) >= 2:
            w, h = int(parts[0]), int(parts[1])
            if w > 0 and h > 0:
                return w, h
    except Exception as e:
        log.warning("probe_video_dimensions thất bại với %s: %s", video, e)
    return 1920, 1080


def extract_audio(video: Path, wav: Path) -> None:
    """16 kHz mono PCM, the format FunASR expects."""
    cmd = [settings.ffmpeg, "-v", "error", "-y"]
    if settings.ffmpeg_threads > 0:
        cmd.extend(["-threads", str(settings.ffmpeg_threads)])
    cmd.extend([
        "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "pcm_s16le", str(wav)
    ])
    _run(cmd, timeout=600)


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
                    kwargs["vad_kwargs"] = {
                        "max_single_segment_time": settings.funasr_vad_max_segment_ms,
                        "max_end_silence_time": settings.funasr_vad_max_silence_ms,
                        "speech_noise_thres": settings.funasr_vad_speech_noise_thres,
                    }
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
                    max_single_segment_time=settings.funasr_vad_max_segment_ms,
                    max_end_silence_time=settings.funasr_vad_max_silence_ms,
                    speech_noise_thres=settings.funasr_vad_speech_noise_thres,
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


def split_segment_cues(
    start_ms: int,
    end_ms: int,
    text: str,
    max_dur_ms: int = 4000,
    speech_regions: list[tuple[int, int]] | None = None,
) -> list[tuple[int, int, str]]:
    """Split a long segment into natural cadence-level subtitle cues.

    Splits by speaker pauses, sentence terminators (。？！?!；;\n), and clause
    delimiters (，,、…) when the segment duration exceeds max_dur_ms or when
    internal silence gaps / pauses are detected.
    """
    dur = end_ms - start_ms
    cleaned = text.strip()
    if not cleaned:
        return []

    # Filter speech regions that overlap with this segment
    inside_speech: list[tuple[int, int]] = []
    if speech_regions:
        inside_speech = [
            (max(start_ms, s), min(end_ms, e))
            for s, e in speech_regions
            if s < end_ms and e > start_ms and min(end_ms, e) > max(start_ms, s)
        ]

    # Split text into candidate phrases/clauses
    # Step A: Sentence terminators: 。？！?!；;\n
    parts = re.split(r"([。？！?!；;\n]+)", cleaned)
    sents: list[str] = []
    for i in range(0, len(parts), 2):
        s = parts[i]
        delim = parts[i + 1] if i + 1 < len(parts) else ""
        t = (s + delim).strip()
        if t:
            sents.append(t)

    # Step B: If long or containing internal pauses, further break on commas/pauses
    phrases: list[str] = []
    for s in (sents or [cleaned]):
        comma_parts = re.split(r"([，,、…]+)", s)
        if len(comma_parts) > 2 and (dur > max_dur_ms or len(s) > 14 or len(inside_speech) > 1):
            for j in range(0, len(comma_parts), 2):
                cp = comma_parts[j]
                cp_delim = comma_parts[j + 1] if j + 1 < len(comma_parts) else ""
                sub_clause = (cp + cp_delim).strip()
                if sub_clause:
                    phrases.append(sub_clause)
        else:
            phrases.append(s)

    # If only 1 phrase
    if len(phrases) <= 1:
        if dur <= max_dur_ms:
            return [(start_ms, end_ms, cleaned)]
        # Long phrase without punctuation: split by space (Western languages) if available
        words = cleaned.split(" ")
        if len(words) >= 4 and dur > max_dur_ms:
            mid = len(words) // 2
            phrases = [" ".join(words[:mid]), " ".join(words[mid:])]
        else:
            return [(start_ms, end_ms, cleaned)]

    # Guard against over-splitting into sub-second blips if overall duration is too short
    if dur < 1600 and len(phrases) > 1:
        return [(start_ms, end_ms, cleaned)]

    # Case A: If inside_speech count matches phrases count exactly and > 1, align 1:1!
    if len(inside_speech) == len(phrases) and len(inside_speech) > 1:
        result: list[tuple[int, int, str]] = []
        for i, p in enumerate(phrases):
            s_st, s_en = inside_speech[i]
            if s_en - s_st < 800:
                s_en = min(end_ms, s_st + 800)
            result.append((s_st, s_en, p))
        return result

    # Case B: Proportional split with silence-boundary anchoring
    total_chars = max(sum(len(p) for p in phrases), 1)
    result = []
    curr_start = start_ms
    for i, p in enumerate(phrases):
        if i == len(phrases) - 1:
            curr_end = end_ms
        else:
            fraction = len(p) / total_chars
            curr_end = curr_start + int(dur * fraction)

        # If speech regions exist, anchor curr_end to closest pause/end of speech region
        if inside_speech and i < len(phrases) - 1:
            for _, s_en in inside_speech:
                if abs(s_en - curr_end) <= 800 and s_en > curr_start + 400:
                    curr_end = s_en
                    break

        if curr_end > curr_start:
            result.append((curr_start, curr_end, p))
        curr_start = curr_end

    return result or [(start_ms, end_ms, cleaned)]


def transcribe(
    wav: Path,
    language: str,
    out_base: Path,
    speech: list[tuple[int, int]] | None = None,
) -> tuple[str, list[Cue]]:
    """Run FunASR (SenseVoiceSmall) with VAD to produce timestamped cues."""
    model = get_asr_model()
    gen_kwargs: dict[str, Any] = {
        "input": str(wav),
        "use_itn": True,
        "batch_size_s": 60,
        "merge_vad": settings.funasr_merge_vad,
        "merge_length_s": settings.funasr_merge_length_s,
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
                for sub_start, sub_end, sub_text in split_segment_cues(
                    start_ms, end_ms, clean_text, max_dur_ms=max_cue_ms, speech_regions=speech
                ):
                    cues.append(Cue(len(cues) + 1, sub_start, sub_end, sub_text))

    if not cues and raw_full_text:
        clean_text = _clean_rich_text(raw_full_text)
        if clean_text and not is_non_speech(clean_text):
            duration_ms = int(probe_duration(wav) * 1000)
            for sub_start, sub_end, sub_text in split_segment_cues(
                0, duration_ms, clean_text, max_dur_ms=max_cue_ms, speech_regions=speech
            ):
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
    if fonts_dir is None:
        candidate = Path(__file__).resolve().parents[2] / "assets" / "fonts"
        if not candidate.exists():
            candidate = Path(__file__).resolve().parents[2] / "app" / "fonts"
        if candidate.exists():
            fonts_dir = candidate
    ass_path_escaped = _filter_path(ass)
    if fonts_dir:
        fonts_dir_escaped = _filter_path(fonts_dir)
        vf = f"ass='{ass_path_escaped}':fontsdir='{fonts_dir_escaped}':shaping=complex"
    else:
        vf = f"ass='{ass_path_escaped}':shaping=complex"
    cmd = [settings.ffmpeg, "-v", "error", "-y"]
    if settings.ffmpeg_threads > 0:
        cmd.extend(["-threads", str(settings.ffmpeg_threads)])
    if settings.ffmpeg_filter_threads > 0:
        cmd.extend(["-filter_threads", str(settings.ffmpeg_filter_threads)])
    cmd.extend([
        "-i", str(video), "-vf", vf,
        "-c:v", "libx264", "-preset", settings.video_preset, "-crf", str(settings.video_crf),
    ])
    if settings.ffmpeg_threads > 0:
        cmd.extend(["-threads", str(settings.ffmpeg_threads)])
    cmd.extend([
        "-c:a", "copy", "-movflags", "+faststart", str(out)
    ])
    _run(cmd, timeout=7200)
