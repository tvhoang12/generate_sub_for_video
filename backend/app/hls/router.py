"""FastAPI routes for HLS converter."""

import io
import logging
import os
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from ..config import settings
from ..db import HlsJob, HlsJobStatus, get_session, utcnow
from .renditions import get_sorted_renditions
from .runner import get_existing_renditions, probe_height

log = logging.getLogger("substudio.hls.router")

SessionDep = Annotated[Session, Depends(get_session)]

hls_router = APIRouter()

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}

MIME_TYPES = {
    ".m3u8": "application/vnd.apple.mpegurl",
    ".ts": "video/mp2t",
    ".m4s": "video/iso.segment",
    ".mp4": "video/mp4",
    ".vtt": "text/vtt",
    ".key": "application/octet-stream",
}


# ── Request / Response models ───────────────────────────────────────────────

class UploadInitIn(BaseModel):
    filename: str
    fileSize: int | None = None
    renditions: list[str] | None = None


class JobsStartIn(BaseModel):
    ids: list[str]


class JobsDeleteIn(BaseModel):
    ids: list[str] | None = None
    all: bool | None = False


# ── Helper functions ────────────────────────────────────────────────────────

def resolve_job_output_dir(job: HlsJob | None, job_id: str, s: Session | None = None) -> Path:
    """Resolve actual existing output directory for an HLS job.

    Handles cases where storage path moved or was updated in .env (e.g. /var/www/hls vs /var/www/hls/hlsoutput).
    """
    candidates: list[Path] = []
    if job and job.output_dir:
        candidates.append(Path(job.output_dir))

    candidates.extend([
        settings.hls_storage_path / job_id,
        settings.hls_storage_path / "hlsoutput" / job_id,
        Path("/var/www/hls") / job_id,
        Path("/var/www/hls/hlsoutput") / job_id,
    ])

    for cand in candidates:
        if cand.is_dir():
            if job and s and job.output_dir != str(cand):
                job.output_dir = str(cand)
                s.add(job)
                try:
                    s.commit()
                except Exception:
                    pass
            return cand

    return Path(job.output_dir) if (job and job.output_dir) else (settings.hls_storage_path / job_id)


def _has_output_reference(s: Session, output_dir: str, exclude_ids: list[str]) -> bool:
    """Check if any job outside exclude_ids still references the same output_dir."""
    if not output_dir:
        return False
    candidates = s.exec(
        select(HlsJob).where(HlsJob.output_dir == output_dir)
    ).all()
    remaining = [j for j in candidates if j.id not in exclude_ids]
    return len(remaining) > 0


# ── Upload endpoints ────────────────────────────────────────────────────────

@hls_router.post("/api/hls/upload/init", status_code=201)
def upload_init(body: UploadInitIn, s: SessionDep):
    original_name = body.filename.strip()
    ext = Path(original_name).suffix.lower()
    if not original_name or ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Định dạng không hỗ trợ. Chỉ chấp nhận: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    job_id = str(uuid.uuid4())
    upload_path = settings.hls_upload_dir / job_id
    upload_path.mkdir(parents=True, exist_ok=True)

    renditions = body.renditions if (body.renditions and len(body.renditions) > 0) else ["480p", "720p"]

    job = HlsJob(
        id=job_id,
        filename=f"input{ext}",
        original_name=original_name,
        source_size=body.fileSize,
        status=HlsJobStatus.UPLOADING,
        progress=0,
        selected_renditions=renditions,
        skipped_renditions=[],
        completed_renditions=[],
        logs=["==> Bắt đầu tải file lên server..."],
        created_at=utcnow(),
        output_dir=str(settings.hls_storage_path / job_id),
    )
    s.add(job)
    s.commit()
    return {"id": job_id, "filename": original_name}


@hls_router.put("/api/hls/upload/{job_id}")
async def upload_put(job_id: str, request: Request, s: SessionDep):
    job = s.get(HlsJob, job_id)
    if not job:
        raise HTTPException(404, "Tác vụ không tồn tại")
    if job.status != HlsJobStatus.UPLOADING:
        raise HTTPException(409, "Tác vụ không ở trạng thái tải lên")

    upload_folder = settings.hls_upload_dir / job_id
    upload_folder.mkdir(parents=True, exist_ok=True)
    input_path = upload_folder / job.filename

    bytes_received = 0
    try:
        with open(input_path, "wb") as f:
            async for chunk in request.stream():
                bytes_received += len(chunk)
                f.write(chunk)

        file_size = input_path.stat().st_size
        expected_size = job.source_size or 0
        if expected_size > 0 and file_size != expected_size:
            raise HTTPException(
                400,
                f"Tải lên chưa hoàn chỉnh: nhận được {file_size} / {expected_size} bytes",
            )

        # Validate video integrity with ffprobe
        try:
            probe_height(input_path)
        except Exception as e:
            raise HTTPException(
                400, f"File video không hợp lệ hoặc thiếu luồng hình ảnh: {e}"
            )

        job.status = HlsJobStatus.UPLOADED
        job.progress = 0
        logs = list(job.logs or [])
        logs.append("==> Upload hoàn tất, chờ bắt đầu convert.")
        job.logs = logs
        s.add(job)
        s.commit()
        return {"id": job_id, "uploaded": True}

    except Exception as e:
        # Clean up partial upload on failure
        if input_path.is_file():
            input_path.unlink(missing_ok=True)
        job.status = HlsJobStatus.ERROR
        job.error_message = str(e)
        s.add(job)
        s.commit()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(500, f"Lỗi tải lên: {e}")


# ── Jobs endpoints ──────────────────────────────────────────────────────────

@hls_router.post("/api/hls/jobs/start")
def jobs_start(body: JobsStartIn, request: Request, s: SessionDep):
    ids = body.ids or []
    if not ids:
        raise HTTPException(400, "Không có tác vụ nào để chuyển đổi")

    started_ids: list[str] = []
    reused_ids: list[str] = []

    for job_id in ids:
        job = s.get(HlsJob, job_id)
        if not job or job.status != HlsJobStatus.UPLOADED:
            continue

        input_path = settings.hls_upload_dir / job_id / job.filename

        # Check for existing completed job with identical original_name and source_size
        existing = None
        if job.source_size:
            candidates = s.exec(
                select(HlsJob).where(
                    HlsJob.id != job.id,
                    HlsJob.status == HlsJobStatus.DONE,
                    HlsJob.original_name == job.original_name,
                    HlsJob.source_size == job.source_size,
                )
            ).all()
            for cand in candidates:
                if cand.output_dir and Path(cand.output_dir).is_dir():
                    existing = cand
                    break

        if existing and existing.output_dir:
            out_path = Path(existing.output_dir)
            available = get_existing_renditions(out_path)
            missing = [r for r in job.selected_renditions if r not in available]

            if not missing:
                # Fully reused!
                shutil.rmtree(input_path.parent, ignore_errors=True)
                job.status = HlsJobStatus.DONE
                job.progress = 100
                job.completed_renditions = available
                job.skipped_renditions = existing.skipped_renditions
                job.output_dir = existing.output_dir
                job.completed_at = utcnow()
                logs = list(job.logs or [])
                logs.append(f"==> Đã tìm thấy bản convert trên server từ job {existing.id}, dùng chung output.")
                job.logs = logs
                s.add(job)
                s.commit()
                reused_ids.append(job_id)
                continue
            else:
                # Partially reused; encode missing renditions into shared output
                job.status = HlsJobStatus.QUEUED
                job.output_dir = existing.output_dir
                job.completed_renditions = available
                job.skipped_renditions = existing.skipped_renditions
                logs = list(job.logs or [])
                logs.append(f"==> Dùng chung output từ job {existing.id}, convert bổ sung: {', '.join(missing)}")
                job.logs = logs
                s.add(job)
                s.commit()
                request.app.state.hls_runner.submit(job.id, input_path, missing)
                started_ids.append(job_id)
                continue

        # Standard new job
        job.status = HlsJobStatus.QUEUED
        logs = list(job.logs or [])
        logs.append("==> Đã upload đủ, đưa vào queue convert.")
        job.logs = logs
        s.add(job)
        s.commit()
        request.app.state.hls_runner.submit(job.id, input_path, job.selected_renditions)
        started_ids.append(job_id)

    return {"started": len(started_ids), "reused": reused_ids}


@hls_router.get("/api/hls/queue")
def hls_queue_status(request: Request):
    runner = getattr(request.app.state, "hls_runner", None)
    if runner and hasattr(runner, "get_status"):
        return runner.get_status()
    return {"running": 0, "queued": 0, "max_concurrent": settings.hls_max_concurrent}


@hls_router.get("/api/hls/jobs")
def list_jobs(s: SessionDep):
    jobs = s.exec(select(HlsJob).order_by(HlsJob.created_at.desc())).all()
    return {"jobs": jobs}


@hls_router.get("/api/hls/jobs/{job_id}")
def get_job(job_id: str, s: SessionDep):
    job = s.get(HlsJob, job_id)
    if not job:
        raise HTTPException(404, "Không tìm thấy tác vụ")
    return job


@hls_router.delete("/api/hls/jobs/{job_id}")
def delete_single_job(job_id: str, s: SessionDep):
    job = s.get(HlsJob, job_id)
    if not job:
        raise HTTPException(404, "Không tìm thấy tác vụ")

    upload_folder = settings.hls_upload_dir / job_id
    shutil.rmtree(upload_folder, ignore_errors=True)

    output_dir = job.output_dir or str(settings.hls_storage_path / job_id)
    if not _has_output_reference(s, output_dir, [job_id]):
        out_p = Path(output_dir).resolve()
        storage_root = settings.hls_storage_path.resolve()
        if out_p != storage_root and out_p.is_relative_to(storage_root):
            shutil.rmtree(out_p, ignore_errors=True)

    s.delete(job)
    s.commit()
    return {"success": True, "message": "Đã xóa tác vụ thành công"}


@hls_router.delete("/api/hls/jobs")
def delete_jobs(body: JobsDeleteIn, s: SessionDep):
    storage_root = settings.hls_storage_path.resolve()
    if body.all:
        all_jobs = s.exec(select(HlsJob)).all()
        output_dirs = {j.output_dir for j in all_jobs if j.output_dir}
        for j in all_jobs:
            shutil.rmtree(settings.hls_upload_dir / j.id, ignore_errors=True)
            s.delete(j)
        for out in output_dirs:
            out_p = Path(out).resolve()
            if out_p != storage_root and out_p.is_relative_to(storage_root):
                shutil.rmtree(out_p, ignore_errors=True)
        s.commit()
        return {"success": True, "count": len(all_jobs), "message": f"Đã xóa {len(all_jobs)} tác vụ"}

    ids = body.ids or []
    if not ids:
        raise HTTPException(400, "Vui lòng cung cấp danh sách ids hoặc all: true để xóa")

    count = 0
    for j_id in ids:
        job = s.get(HlsJob, j_id)
        if not job:
            continue
        shutil.rmtree(settings.hls_upload_dir / j_id, ignore_errors=True)
        output_dir = job.output_dir or str(settings.hls_storage_path / j_id)
        if not _has_output_reference(s, output_dir, ids):
            out_p = Path(output_dir).resolve()
            if out_p != storage_root and out_p.is_relative_to(storage_root):
                shutil.rmtree(out_p, ignore_errors=True)
        s.delete(job)
        count += 1

    s.commit()
    return {"success": True, "count": count, "message": f"Đã xóa {count} tác vụ thành công"}


# ── Download endpoints ──────────────────────────────────────────────────────

@hls_router.get("/api/hls/download/{job_id}")
def download_single(job_id: str, s: SessionDep, rendition: str | None = None):
    job = s.get(HlsJob, job_id)
    if not job:
        raise HTTPException(404, "Không tìm thấy tác vụ")
    if job.status != HlsJobStatus.DONE:
        raise HTTPException(400, "Tác vụ chưa hoàn thành")

    output_dir = resolve_job_output_dir(job, job_id, s)
    source_dir = output_dir / rendition if rendition else output_dir

    if rendition and not (source_dir / "index.m3u8").is_file():
        raise HTTPException(404, f"Độ phân giải {rendition} không tồn tại")

    stem = Path(job.original_name).stem
    zip_name = f"{stem}_{rendition}_hls.zip" if rendition else f"{stem}_hls.zip"

    # Create temporary zip archive
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp_path = Path(tmp.name)
    tmp.close()

    folder_prefix = f"{stem}_{rendition}_hls" if rendition else f"{stem}_hls"
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as z:
        for file_path in source_dir.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(source_dir)
                z.write(file_path, f"{folder_prefix}/{rel_path.as_posix()}")

    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename=zip_name,
        background=None,  # Or cleanup after download
    )


@hls_router.get("/api/hls/download/batch")
def download_batch(
    s: SessionDep,
    ids: str | None = None,
    all: bool | None = False,
):
    if all:
        target_jobs = s.exec(select(HlsJob).where(HlsJob.status == HlsJobStatus.DONE)).all()
    elif ids:
        id_list = [i.strip() for i in ids.split(",") if i.strip()]
        target_jobs = s.exec(
            select(HlsJob).where(HlsJob.id.in_(id_list), HlsJob.status == HlsJobStatus.DONE)
        ).all()
    else:
        raise HTTPException(400, "Vui lòng cung cấp danh sách ids hoặc all=true")

    valid_jobs: list[tuple[HlsJob, Path]] = []
    for j in target_jobs:
        p = resolve_job_output_dir(j, j.id, s)
        if p.is_dir():
            valid_jobs.append((j, p))

    if not valid_jobs:
        raise HTTPException(404, "Không có file HLS nào đã hoàn tất để tải xuống")

    date_str = datetime.now().strftime("%Y-%m-%d")
    zip_name = f"hls_batch_{len(valid_jobs)}_videos_{date_str}.zip"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp_path = Path(tmp.name)
    tmp.close()

    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as z:
        for job, out_dir in valid_jobs:
            stem = Path(job.original_name).stem
            for file_path in out_dir.rglob("*"):
                if file_path.is_file():
                    rel_path = file_path.relative_to(out_dir)
                    z.write(file_path, f"{stem}_hls/{rel_path.as_posix()}")

    return FileResponse(tmp_path, media_type="application/zip", filename=zip_name)


# ── Streaming route for HLS ─────────────────────────────────────────────────

@hls_router.api_route("/hls/{job_id}/{file_path:path}", methods=["GET", "HEAD", "OPTIONS"])
@hls_router.api_route("/api/hls/{job_id}/{file_path:path}", methods=["GET", "HEAD", "OPTIONS"])
def stream_hls(job_id: str, file_path: str, request: Request, s: SessionDep):
    # CORS Preflight
    if request.method == "OPTIONS":
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                "Access-Control-Allow-Headers": "Range, Accept-Encoding, Origin, X-Requested-With, Content-Type, Accept",
                "Access-Control-Expose-Headers": "Content-Length, Content-Range",
            },
        )

    # Directory Traversal defense
    if ".." in file_path or "\0" in file_path:
        raise HTTPException(400, "Đường dẫn file không hợp lệ")

    job = s.get(HlsJob, job_id)
    base_dir = resolve_job_output_dir(job, job_id, s)
    target = (base_dir / file_path).resolve()

    resolved_base = base_dir.resolve()
    if not (target == resolved_base or target.is_relative_to(resolved_base)):
        raise HTTPException(403, "Forbidden: Truy cập ngoài thư mục HLS")

    if not target.is_file():
        raise HTTPException(404, "Không tìm thấy file HLS")

    ext = target.suffix.lower()
    content_type = MIME_TYPES.get(ext, "application/octet-stream")

    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "Range, Accept-Encoding, Origin, X-Requested-With, Content-Type, Accept",
        "Access-Control-Expose-Headers": "Content-Length, Content-Range",
        "Content-Type": content_type,
    }

    if ext == ".m3u8":
        headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    elif ext in (".ts", ".m4s"):
        headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        headers["Cache-Control"] = "public, max-age=3600"

    if request.method == "HEAD":
        headers["Content-Length"] = str(target.stat().st_size)
        return Response(status_code=200, headers=headers)

    return FileResponse(target, headers=headers, media_type=content_type)


@hls_router.get("/hls/{job_id}/player", response_class=HTMLResponse)
@hls_router.get("/api/hls/{job_id}/player", response_class=HTMLResponse)
def player_hls(job_id: str, s: SessionDep):
    job = s.get(HlsJob, job_id)
    if not job:
        raise HTTPException(404, "Không tìm thấy tác vụ HLS")
    stream_url = f"/hls/{job_id}/master.m3u8"
    title = job.original_name or f"HLS Stream {job_id}"
    html = f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} - HLS Player</title>
  <script src="https://cdn.jsdelivr.net/npm/hls.js@1.5.8/dist/hls.min.js"></script>
  <style>
    body {{ margin: 0; background: #0f172a; color: #f8fafc; font-family: system-ui, -apple-system, sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; padding: 16px; box-sizing: border-box; }}
    .container {{ width: 100%; max-width: 900px; background: #1e293b; border-radius: 12px; padding: 20px; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.4); }}
    h1 {{ font-size: 1.15rem; margin-top: 0; margin-bottom: 12px; font-weight: 600; color: #14b8a6; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    video {{ width: 100%; max-height: 70vh; background: #000; border-radius: 8px; outline: none; }}
    .info {{ margin-top: 14px; font-size: 0.85rem; color: #94a3b8; display: flex; flex-direction: column; gap: 8px; }}
    .url-bar {{ display: flex; align-items: center; gap: 8px; background: #0f172a; padding: 6px 10px; border-radius: 6px; }}
    .url-text {{ flex: 1; font-family: monospace; color: #38bdf8; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    button {{ background: #0d9488; color: #fff; border: none; border-radius: 4px; padding: 6px 12px; font-size: 0.8rem; cursor: pointer; font-weight: 600; transition: background 0.2s; }}
    button:hover {{ background: #0f766e; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>{title}</h1>
    <video id="video" controls autoplay playsinline></video>
    <div class="info">
      <div class="url-bar">
        <span class="url-text" id="streamUrl"></span>
        <button onclick="navigator.clipboard.writeText(document.getElementById('streamUrl').innerText); this.innerText='Đã chép!'; setTimeout(()=>this.innerText='Copy', 2000)">Copy</button>
      </div>
    </div>
  </div>
  <script>
    const streamPath = '{stream_url}';
    const fullUrl = window.location.origin + streamPath;
    document.getElementById('streamUrl').innerText = fullUrl;
    const video = document.getElementById('video');
    if (window.Hls && Hls.isSupported()) {{
      const hls = new Hls();
      hls.loadSource(streamPath);
      hls.attachMedia(video);
    }} else if (video.canPlayType('application/vnd.apple.mpegurl')) {{
      video.src = streamPath;
    }}
  </script>
</body>
</html>"""
    return HTMLResponse(content=html)

