"""Tests for HLS module and router."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.config import settings
from app.db import HlsJob, HlsJobStatus, engine, init_db
from app.hls.renditions import RENDITIONS, get_sorted_renditions
from app.hls.runner import generate_master_playlist
from app.main import create_app


@pytest.fixture(autouse=True)
def setup_db():
    init_db()


@pytest.fixture
def client():
    class DummyRunner:
        def start(self): pass
        def submit(self, *args, **kwargs): pass
        def get_status(self):
            return {"running": 0, "queued": 0, "max_concurrent": 1}

    app = create_app(runner=DummyRunner(), hls_runner=DummyRunner())
    return TestClient(app)


def test_queue_endpoints(client):
    res_hls = client.get("/api/hls/queue")
    assert res_hls.status_code == 200
    assert res_hls.json() == {"running": 0, "queued": 0, "max_concurrent": 1}

    res_sub = client.get("/api/queue")
    assert res_sub.status_code == 200
    assert res_sub.json() == {"running": 0, "queued": 0, "max_concurrent": 1}


def test_renditions_ordering():
    configs = get_sorted_renditions(["1080p", "360p", "720p"])
    assert [c.label for c in configs] == ["360p", "720p", "1080p"]
    assert configs[0].height == 360
    assert configs[1].height == 720
    assert configs[2].height == 1080


def test_upload_init(client):
    # Invalid extension
    res = client.post("/api/hls/upload/init", json={"filename": "test.txt", "fileSize": 100})
    assert res.status_code == 400

    # Valid extension
    res = client.post("/api/hls/upload/init", json={"filename": "sample.mp4", "fileSize": 1024, "renditions": ["720p"]})
    assert res.status_code == 201
    data = res.json()
    assert "id" in data
    assert data["filename"] == "sample.mp4"

    # Verify DB
    with Session(engine) as s:
        job = s.get(HlsJob, data["id"])
        assert job is not None
        assert job.status == HlsJobStatus.UPLOADING
        assert job.selected_renditions == ["720p"]


def test_upload_put(client):
    init_res = client.post("/api/hls/upload/init", json={"filename": "sample.mp4", "fileSize": 16})
    job_id = init_res.json()["id"]

    fake_video = b"0123456789abcdef"

    # Mock probe_height to simulate valid video stream
    with patch("app.hls.router.probe_height", return_value=720):
        res = client.put(f"/api/hls/upload/{job_id}", content=fake_video)
        assert res.status_code == 200
        assert res.json()["uploaded"] is True

    with Session(engine) as s:
        job = s.get(HlsJob, job_id)
        assert job.status == HlsJobStatus.UPLOADED


def test_master_playlist_generation(tmp_path):
    out_dir = tmp_path / "hls_out"
    out_dir.mkdir()
    valid = [RENDITIONS["480p"], RENDITIONS["720p"]]
    generate_master_playlist(out_dir, valid)

    master = (out_dir / "master.m3u8").read_text()
    assert "#EXTM3U" in master
    assert "480p/index.m3u8" in master
    assert "720p/index.m3u8" in master
    assert "BANDWIDTH=1400000" in master
    assert "BANDWIDTH=2800000" in master


def test_jobs_list_and_delete(client):
    init_res = client.post("/api/hls/upload/init", json={"filename": "test_del.mp4", "fileSize": 10})
    job_id = init_res.json()["id"]

    res = client.get("/api/hls/jobs")
    assert res.status_code == 200
    jobs = res.json()["jobs"]
    assert any(j["id"] == job_id for j in jobs)

    # Delete single
    del_res = client.delete(f"/api/hls/jobs/{job_id}")
    assert del_res.status_code == 200
    assert del_res.json()["success"] is True

    # Check 404
    get_res = client.get(f"/api/hls/jobs/{job_id}")
    assert get_res.status_code == 404


def test_stream_hls_cors_and_path_traversal(client, tmp_path):
    init_res = client.post("/api/hls/upload/init", json={"filename": "stream_test.mp4", "fileSize": 10})
    job_id = init_res.json()["id"]

    # Path traversal attempt
    res = client.get(f"/hls/{job_id}/..%2fsecret.txt")
    assert res.status_code == 400

    # OPTIONS preflight
    opt_res = client.options(f"/hls/{job_id}/master.m3u8")
    assert opt_res.status_code == 204
    assert opt_res.headers.get("access-control-allow-origin") == "*"

    # Prepare actual playlist file
    job_dir = settings.hls_storage_path / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    playlist = job_dir / "master.m3u8"
    playlist.write_text("#EXTM3U\n")

    res = client.get(f"/hls/{job_id}/master.m3u8")
    assert res.status_code == 200
    assert res.headers.get("content-type") == "application/vnd.apple.mpegurl"
    assert res.headers.get("access-control-allow-origin") == "*"
    assert "#EXTM3U" in res.text

    # Also test /api/hls route alias
    res_api = client.get(f"/api/hls/{job_id}/master.m3u8")
    assert res_api.status_code == 200
    assert "#EXTM3U" in res_api.text

    # Test player route
    res_player = client.get(f"/hls/{job_id}/player")
    assert res_player.status_code == 200
    assert "text/html" in res_player.headers.get("content-type", "")
    assert f"/hls/{job_id}/master.m3u8" in res_player.text

    res_api_player = client.get(f"/api/hls/{job_id}/player")
    assert res_api_player.status_code == 200
    assert "text/html" in res_api_player.headers.get("content-type", "")


def test_download_batch_and_single_routes(client, tmp_path):
    import io
    import zipfile

    # 1. Test batch endpoint does not get shadowed by single download route
    res_bad = client.get("/api/hls/download/batch")
    assert res_bad.status_code == 400

    res_missing = client.get("/api/hls/download/batch?ids=nonexistent-id")
    assert res_missing.status_code == 404
    assert "Không có file HLS nào đã hoàn tất để tải xuống" in res_missing.json()["detail"]

    # 2. Create mock completed job
    init_res = client.post("/api/hls/upload/init", json={"filename": "test_video.mp4", "fileSize": 100})
    job_id = init_res.json()["id"]

    job_dir = settings.hls_storage_path / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "master.m3u8").write_text("#EXTM3U\n")
    (job_dir / "index.m3u8").write_text("#EXTM3U\n")

    with Session(engine) as s:
        job = s.get(HlsJob, job_id)
        job.status = HlsJobStatus.DONE
        job.output_dir = str(job_dir)
        s.add(job)
        s.commit()

    # 3. Test single download
    res_single = client.get(f"/api/hls/download/{job_id}")
    assert res_single.status_code == 200
    assert res_single.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(res_single.content)) as z:
        names = z.namelist()
        assert any("master.m3u8" in n for n in names)

    # 4. Test batch download with ids
    res_batch_ids = client.get(f"/api/hls/download/batch?ids={job_id}")
    assert res_batch_ids.status_code == 200
    assert res_batch_ids.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(res_batch_ids.content)) as z:
        names = z.namelist()
        assert any("test_video_hls/master.m3u8" in n for n in names)

    # 5. Test batch download with all=true
    res_batch_all = client.get("/api/hls/download/batch?all=true")
    assert res_batch_all.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res_batch_all.content)) as z:
        names = z.namelist()
        assert any("test_video_hls/master.m3u8" in n for n in names)

    # 6. Test /hls/download/batch alias without /api prefix
    res_batch_alias = client.get(f"/hls/download/batch?ids={job_id}")
    assert res_batch_alias.status_code == 200


