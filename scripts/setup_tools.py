"""Download whisper.cpp (Windows x64 CPU build) and its models into tools/whisper.

Run once on a new machine:  backend/.venv/Scripts/python.exe scripts/setup_tools.py
"""

import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tools" / "whisper"
BIN_ZIP = "https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip"
MODELS = {
    "ggml-large-v3-turbo-q5_0.bin": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q5_0.bin",
    "ggml-silero-v5.1.2.bin": "https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v5.1.2.bin",
}


def download(url: str, dest: Path) -> None:
    print(f"Downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as resp, open(tmp, "wb") as f:
        shutil.copyfileobj(resp, f, length=1024 * 1024)
    tmp.replace(dest)


def main() -> int:
    bin_dir, model_dir = TARGET / "bin", TARGET / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    if not (bin_dir / "whisper-cli.exe").exists():
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "whisper.zip"
            download(BIN_ZIP, archive)
            with zipfile.ZipFile(archive) as z:
                z.extractall(tmp)
            shutil.rmtree(bin_dir, ignore_errors=True)
            shutil.copytree(Path(tmp) / "Release", bin_dir)
    for name, url in MODELS.items():
        if not (model_dir / name).exists():
            download(url, model_dir / name)
    print(f"Ready: {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
