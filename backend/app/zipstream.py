"""Stream a ZIP archive straight to the client, without a temporary file on disk.

The archive is produced chunk by chunk while the client downloads it, so nothing is left
behind when the download finishes, is cancelled or the connection drops. Entries are stored
(no compression): videos and HLS segments are already compressed.
"""

import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from urllib.parse import quote

from fastapi.responses import StreamingResponse

CHUNK_SIZE = 1024 * 1024


class _Sink:
    """Write-only buffer handed to ZipFile; drained after every chunk.

    It has no tell()/seek(), so zipfile treats it as an unseekable stream and writes data
    descriptors instead of seeking back to patch headers.
    """

    def __init__(self) -> None:
        self._parts: list[bytes] = []

    def write(self, data: bytes) -> int:
        self._parts.append(bytes(data))
        return len(data)

    def flush(self) -> None:
        pass

    def drain(self) -> bytes:
        data = b"".join(self._parts)
        self._parts.clear()
        return data


def iter_zip(entries: Iterable[tuple[Path, str]]) -> Iterator[bytes]:
    """Yield the bytes of a ZIP holding each (file on disk, name inside the archive)."""
    sink = _Sink()
    with zipfile.ZipFile(sink, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        for path, arcname in entries:
            info = zipfile.ZipInfo.from_file(path, arcname)
            info.compress_type = zipfile.ZIP_STORED
            with open(path, "rb") as src, z.open(info, "w") as dst:
                while chunk := src.read(CHUNK_SIZE):
                    dst.write(chunk)
                    if data := sink.drain():
                        yield data
            if data := sink.drain():
                yield data
    if data := sink.drain():
        yield data


def zip_response(entries: Iterable[tuple[Path, str]], filename: str) -> StreamingResponse:
    quoted = quote(filename)
    if quoted == filename:
        disposition = f'attachment; filename="{filename}"'
    else:
        disposition = f"attachment; filename*=utf-8''{quoted}"
    return StreamingResponse(
        iter_zip(entries),
        media_type="application/zip",
        headers={"Content-Disposition": disposition},
    )
