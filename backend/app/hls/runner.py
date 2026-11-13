"""Background worker for MP4 to HLS conversion."""

import logging
import queue
import re
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from sqlmodel import Session, select

from ..config import settings
from ..db import HlsJob, HlsJobStatus, engine, utcnow
from .renditions import RenditionConfig, get_sorted_renditions

log = logging.getLogger("substudio.hls.runner")

TIME_REGEX = re.compile(r"time=(\d+:\d+:\d+\.\d+)")


def parse_time(time_str: str) -> float:
    """Parse time string HH:MM:SS.ss to seconds."""
    parts = time_str.split(":")
    if len(parts) != 3:
        return 0.0
    try:
        h, m, s = map(float, parts)
        return h * 3600 + m * 60 + s
    except ValueError:
        return 0.0


def probe_height(input_path: Path) -> int:
    """Use ffprobe to get video stream height."""
    cmd = [
        settings.ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=height",
        "-of", "csv=p=0",
        str(input_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe failed (code {res.returncode}): {res.stderr.strip()}")
    height_str = res.stdout.strip()
    try:
        height = int(height_str)
        if height <= 0:
            raise ValueError()
        return height
    except ValueError:
        raise RuntimeError(f"Cannot read video height from ffprobe: '{height_str}'")


def probe_duration(input_path: Path) -> float:
    """Use ffprobe to get format duration in seconds."""
    cmd = [
        settings.ffprobe,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        str(input_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        raise RuntimeError(f"ffprobe duration failed (code {res.returncode}): {res.stderr.strip()}")
    dur_str = res.stdout.strip()
    try:
        dur = float(dur_str)
        if dur <= 0:
            raise ValueError()
        return dur
    except ValueError:
        raise RuntimeError(f"Cannot read video duration from ffprobe: '{dur_str}'")


def _update_job(job_id: str, **fields) -> None:
    with Session(engine) as s:
        job = s.get(HlsJob, job_id)
        if not job:
            return
        for key, value in fields.items():
            setattr(job, key, value)
        s.add(job)
        s.commit()


def _append_log(job_id: str, message: str) -> None:
    with Session(engine) as s:
        job = s.get(HlsJob, job_id)
        if not job:
            return
        logs = list(job.logs or [])
        logs.append(message)
        if len(logs) > 200:
            logs = logs[-200:]
        job.logs = logs
        s.add(job)
        s.commit()


def get_existing_renditions(output_dir: Path) -> list[str]:
    """Check directory for existing rendition subfolders with index.m3u8."""
    if not output_dir.is_dir():
        return []
    available = []
    for entry in output_dir.iterdir():
        if entry.is_dir() and (entry / "index.m3u8").is_file():
            available.append(entry.name)
    return available


def encode_rendition(
    job_id: str,
    input_path: Path,
    output_base: Path,
    rendition: RenditionConfig,
    duration: float,
    phase_start: float,
    phase_size: float,
) -> None:
    """Encode a single rendition using ffmpeg with real-time stderr progress tracking."""
    rendition_dir = output_base / rendition.label
    rendition_dir.mkdir(parents=True, exist_ok=True)
    segment_pattern = rendition_dir / "seg_%03d.ts"
    playlist_path = rendition_dir / "index.m3u8"

    cmd = [
        settings.ffmpeg,
        "-y",
        "-i", str(input_path),
        "-vf", f"scale=-2:{rendition.height}",
        "-c:v", "libx264",
        "-preset", settings.hls_preset,
        "-crf", str(rendition.crf),
        "-c:a", "aac",
        "-b:a", rendition.audio_bitrate,
        "-ac", "2",
        "-sc_threshold", "0",
        "-g", str(settings.hls_keyint),
        "-keyint_min", str(settings.hls_keyint),
        "-threads", str(settings.hls_ffmpeg_threads),
        "-hls_time", str(settings.hls_segment_duration),
        "-hls_list_size", "0",
        "-hls_playlist_type", "vod",
        "-hls_segment_filename", str(segment_pattern),
        str(playlist_path),
        "-loglevel", "error",
        "-stats",
    ]

    log.debug("[HLS %s] Lệnh ffmpeg %s: %s", job_id, rendition.label, " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )

    last_pct = -1
    stderr_lines = []

    if proc.stderr:
        for line in proc.stderr:
            stderr_lines.append(line)
            m = TIME_REGEX.search(line)
            if m and duration > 0:
                encoded_sec = parse_time(m.group(1))
                phase_pct = min(encoded_sec / duration, 1.0)
                total_pct = int(phase_start + phase_pct * phase_size)
                if total_pct != last_pct and total_pct <= 95:
                    last_pct = total_pct
                    _update_job(job_id, progress=total_pct)

    proc.wait()
    if proc.returncode != 0:
        err_msg = "".join(stderr_lines[-20:]).strip()
        raise RuntimeError(f"ffmpeg failed (code {proc.returncode}) for {rendition.label}: {err_msg}")


def generate_master_playlist(output_dir: Path, valid_renditions: list[RenditionConfig]) -> None:
    """Generate master.m3u8 and index.m3u8 containing all valid stream variants."""
    lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
    for r in valid_renditions:
        lines.append(f"#EXT-X-STREAM-INF:BANDWIDTH={r.bandwidth},RESOLUTION={r.resolution}")
        lines.append(f"{r.label}/index.m3u8")
    content = "\n".join(lines) + "\n"

    (output_dir / "master.m3u8").write_text(content, encoding="utf-8")
    (output_dir / "index.m3u8").write_text(content, encoding="utf-8")


def run_convert(job_id: str, input_path: Path, selected_renditions: list[str]) -> None:
    """Run full conversion pipeline for a single HLS job."""
    upload_folder = input_path.parent
    with Session(engine) as s:
        current_job = s.get(HlsJob, job_id)
        if not current_job:
            return
        output_dir_str = current_job.output_dir

    job_output_dir = Path(output_dir_str) if output_dir_str else (settings.hls_storage_path / job_id)
    _update_job(job_id, output_dir=str(job_output_dir))

    log.info("[HLS %s] Bắt đầu convert: %s", job_id, input_path.name)

    try:
        job_output_dir.mkdir(parents=True, exist_ok=True)
        _append_log(job_id, "==> Đang đọc thông tin video nguồn...")
        _update_job(job_id, status=HlsJobStatus.PROCESSING, current_rendition=None)

        src_height = probe_height(input_path)
        duration = probe_duration(input_path)

        _update_job(job_id, src_height=src_height)
        _append_log(job_id, f"==> Độ phân giải nguồn: {src_height}px | Thời lượng: {duration:.1f}s")
        log.info("[HLS %s] [Stage 1/4] Đọc thông tin video nguồn: %spx, thời lượng: %.1fs", job_id, src_height, duration)

        existing_labels = get_existing_renditions(job_output_dir)
        target_labels = list(dict.fromkeys(existing_labels + selected_renditions))
        all_configs = get_sorted_renditions(target_labels)

        valid_renditions: list[RenditionConfig] = []
        skipped: list[str] = []

        for r in all_configs:
            if src_height < r.height:
                skipped.append(r.label)
                _append_log(job_id, f"==> Bỏ qua {r.label} (nguồn chỉ {src_height}px, không upscale)")
            else:
                valid_renditions.append(r)

        _update_job(job_id, skipped_renditions=skipped)

        if not valid_renditions:
            raise RuntimeError(f"Không có độ phân giải nào phù hợp. Video nguồn {src_height}px quá nhỏ.")

        pending_renditions = [r for r in valid_renditions if r.label not in existing_labels]
        phase_size = 90.0 / len(pending_renditions) if pending_renditions else 0.0

        for i, r in enumerate(pending_renditions):
            phase_start = i * phase_size
            _update_job(job_id, current_rendition=r.label)
            _append_log(job_id, f"==> Encode {r.label} (CRF {r.crf}, audio {r.audio_bitrate})...")
            log.info("[HLS %s] [Stage 2/4 - %d/%d] Bắt đầu encode %s...", job_id, i + 1, len(pending_renditions), r.label)

            encode_rendition(
                job_id, input_path, job_output_dir, r, duration, phase_start, phase_size
            )

            with Session(engine) as s:
                j = s.get(HlsJob, job_id)
                done_list = list(j.completed_renditions or [])
                if r.label not in done_list:
                    done_list.append(r.label)
                j.completed_renditions = done_list
                s.add(j)
                s.commit()

            _append_log(job_id, f"==> Hoàn tất {r.label} ✓")
            log.info("[HLS %s] [Stage 2/4 - %d/%d] Hoàn tất encode %s ✓", job_id, i + 1, len(pending_renditions), r.label)

        _update_job(job_id, progress=95, current_rendition=None)
        _append_log(job_id, "==> Tạo master.m3u8 và index.m3u8...")
        generate_master_playlist(job_output_dir, valid_renditions)
        log.info("[HLS %s] [Stage 3/4] Đã tạo playlist master.m3u8", job_id)

        _update_job(
            job_id,
            status=HlsJobStatus.DONE,
            progress=100,
            completed_at=utcnow(),
        )
        _append_log(job_id, "==> Hoàn tất! File HLS đã sẵn sàng để stream và tải về.")
        log.info("[HLS %s] [Stage 4/4] Hoàn tất toàn bộ chuyển đổi HLS thành công!", job_id)

    except Exception as e:
        log.error("[HLS %s] Convert thất bại: %s", job_id, e)
        _update_job(
            job_id,
            status=HlsJobStatus.ERROR,
            error_message=str(e),
            completed_at=utcnow(),
        )
        _append_log(job_id, f"==> LỖI: {e}")
    finally:
        # Cleanup uploaded source file to save disk space
        if upload_folder.is_dir():
            try:
                shutil.rmtree(upload_folder, ignore_errors=True)
                _append_log(job_id, "==> Đã tự động dọn dẹp file MP4 gốc để giải phóng dung lượng ổ đĩa.")
            except Exception as clean_err:
                log.warning("[HLS %s] Không thể dọn dẹp file upload tạm: %s", job_id, clean_err)


class HlsRunner:
    """Independent worker thread pool and queue for HLS conversion jobs."""

    def __init__(self, concurrency: int | None = None) -> None:
        self.concurrency = concurrency or max(1, settings.hls_max_concurrent)
        self._queue: queue.Queue[tuple[str, Path, list[str]]] = queue.Queue()
        self._threads: list[threading.Thread] = []
        self._active_jobs: set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Recover pending jobs from SQLite and start background processing loop with independent workers."""
        with Session(engine) as s:
            pending = s.exec(
                select(HlsJob).where(
                    HlsJob.status.in_([HlsJobStatus.QUEUED, HlsJobStatus.PROCESSING])
                ).order_by(HlsJob.created_at)
            ).all()
            for job in pending:
                job.status = HlsJobStatus.QUEUED
                job.progress = 0
                job.current_rendition = None
                s.add(job)
            s.commit()

        for i in range(self.concurrency):
            thread = threading.Thread(
                target=self._loop,
                name=f"hls-worker-{i + 1}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()
        log.info("HLS Runner started with %d independent worker(s)", self.concurrency)

    def submit(self, job_id: str, input_path: Path, renditions: list[str]) -> None:
        with self._lock:
            self._queue.put((job_id, input_path, renditions))
            _update_job(job_id, status=HlsJobStatus.QUEUED)

    def get_status(self) -> dict:
        """Return independent queue statistics."""
        with self._lock:
            return {
                "running": len(self._active_jobs),
                "queued": self._queue.qsize(),
                "max_concurrent": self.concurrency,
                "active_job_ids": list(self._active_jobs),
            }

    def _loop(self) -> None:
        while True:
            job_id, input_path, renditions = self._queue.get()
            with self._lock:
                self._active_jobs.add(job_id)
            try:
                run_convert(job_id, input_path, renditions)
            except Exception as e:
                log.exception("HLS runner loop error on %s: %s", job_id, e)
            finally:
                with self._lock:
                    self._active_jobs.discard(job_id)
                self._queue.task_done()

