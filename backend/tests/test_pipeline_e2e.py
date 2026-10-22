"""Full run through the HTTP API: real ffmpeg + whisper.cpp, mock translator.

Uses a 20 s dialogue clip cut from the sample episode in the project root; skipped when absent.
"""

import subprocess
import time
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import PROJECT_ROOT, settings
from app.main import create_app

SAMPLE = PROJECT_ROOT / "The Mirror Between (Ep3).mp4"
pytestmark = pytest.mark.skipif(
    not SAMPLE.exists() or not settings.whisper_cli.exists(), reason="sample video or whisper.cpp missing"
)


@pytest.fixture(scope="module")
def clip(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("clip") / "ep3 clip.mp4"
    subprocess.run([settings.ffmpeg, "-v", "error", "-y", "-ss", "80", "-t", "20", "-i", str(SAMPLE),
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(out)], check=True)
    return out


def wait_for(client: TestClient, job_id: int, timeout: float = 600) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(1)
    raise AssertionError("job did not finish")


def test_upload_to_download(clip: Path):
    with TestClient(create_app()) as client:
        film = client.post("/api/films", json={"name": "The Mirror Between", "source_language": "en",
                                               "synopsis": "A courier returns to the Empire."}).json()
        client.post(f"/api/films/{film['id']}/terms",
                    json={"term": "Kestrel", "note": "female courier", "translations": {"lo": "ເຄສເທຣລ"}})

        with clip.open("rb") as f:
            resp = client.post("/api/jobs", files={"file": (clip.name, f, "video/mp4")},
                               data={"languages": "lo,my", "film_id": str(film["id"]), "title": "Ep3 clip"})
        assert resp.status_code == 201, resp.text
        job = wait_for(client, resp.json()["id"])

        assert job["status"] == "done", job["error"]
        assert job["report"]["source_language"] == "en"
        files = {o["file"] for o in job["report"]["outputs"]}
        assert files == {"Ep3 clip.en.srt", "Ep3 clip.lo.srt", "Ep3 clip.my.srt",
                         "Ep3 clip - lo.mp4", "Ep3 clip - my.mp4"}

        srt = client.get(f"/api/jobs/{job['id']}/files/Ep3 clip.lo.srt").text
        assert "ທົດສອບ" in srt and "-->" in srt

        archive = zipfile.ZipFile(BytesIO(client.get(f"/api/jobs/{job['id']}/download").content))
        assert set(archive.namelist()) == files
