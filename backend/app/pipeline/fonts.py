"""Font lookup and OpenType vertical metrics, read with the standard library.

The browser preview and libass size text differently:
- CSS `font-size` is the em square, and the line box comes from `line-height`.
- libass treats the ASS `Fontsize` as usWinAscent + usWinDescent (libass issue #644),
  and lays each line out from the win ascent/descent.

Converting between the two needs the real metrics of the face libass will load, so they are
read from the font file itself instead of guessed per family.
"""

from __future__ import annotations

import functools
import logging
import shutil
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

FONT_EXTENSIONS = {".ttf", ".otf", ".ttc"}


@dataclass(frozen=True)
class FontMetrics:
    upem: float
    win_ascent: float
    win_descent: float
    css_ascent: float  # content-area ascent a browser uses (hhea, or typo with USE_TYPO_METRICS)
    css_descent: float
    path: str = ""

    @property
    def libass_scale(self) -> float:
        """ASS Fontsize needed per 1 px of CSS em."""
        return (self.win_ascent + self.win_descent) / self.upem

    @property
    def libass_ascent(self) -> float:
        return self.win_ascent / self.upem

    @property
    def libass_descent(self) -> float:
        return self.win_descent / self.upem

    @property
    def css_ascent_ratio(self) -> float:
        return self.css_ascent / self.upem

    @property
    def css_descent_ratio(self) -> float:
        return self.css_descent / self.upem


# Noto Sans: used when the face cannot be found or parsed.
DEFAULT_METRICS = FontMetrics(upem=1000, win_ascent=1069, win_descent=293, css_ascent=1069, css_descent=293)


def default_fonts_dir() -> Path | None:
    backend = Path(__file__).resolve().parents[2]
    for candidate in (backend / "assets" / "fonts", backend / "app" / "fonts"):
        if candidate.is_dir():
            return candidate
    return None


def _tables(data: bytes) -> dict[str, int]:
    base = 0
    if data[:4] == b"ttcf":
        base = struct.unpack(">I", data[12:16])[0]
    num = struct.unpack(">H", data[base + 4 : base + 6])[0]
    tables: dict[str, int] = {}
    for i in range(num):
        rec = base + 12 + 16 * i
        tag = data[rec : rec + 4].decode("latin-1")
        tables[tag] = struct.unpack(">I", data[rec + 8 : rec + 12])[0]
    return tables


def _names(data: bytes, tables: dict[str, int]) -> dict[int, set[str]]:
    out: dict[int, set[str]] = {}
    off = tables.get("name")
    if off is None:
        return out
    count, str_off = struct.unpack(">HH", data[off + 2 : off + 6])
    for i in range(count):
        pid, _eid, _lid, nid, length, noff = struct.unpack(">6H", data[off + 6 + 12 * i : off + 18 + 12 * i])
        if nid not in (1, 2, 4, 16, 17):
            continue
        raw = data[off + str_off + noff : off + str_off + noff + length]
        try:
            text = raw.decode("utf-16-be") if pid in (0, 3) else raw.decode("latin-1")
        except UnicodeDecodeError:
            continue
        out.setdefault(nid, set()).add(text.strip())
    return out


def read_metrics(path: Path) -> FontMetrics:
    data = path.read_bytes()
    t = _tables(data)
    upem = float(struct.unpack(">H", data[t["head"] + 18 : t["head"] + 20])[0])
    h = t["hhea"]
    hhea_asc, hhea_desc = struct.unpack(">hh", data[h + 4 : h + 8])
    typo_asc = typo_desc = win_asc = win_desc = 0
    use_typo = False
    o = t.get("OS/2")
    if o is not None:
        fs_selection = struct.unpack(">H", data[o + 62 : o + 64])[0]
        typo_asc, typo_desc = struct.unpack(">hh", data[o + 68 : o + 72])
        win_asc, win_desc = struct.unpack(">HH", data[o + 74 : o + 78])
        use_typo = bool(fs_selection & 0x80)

    # libass: win metrics, else hhea (FreeType's face->ascender/descender)
    if win_asc + win_desc > 0:
        lib_asc, lib_desc = float(win_asc), float(win_desc)
    else:
        lib_asc, lib_desc = float(hhea_asc), float(abs(hhea_desc))

    # Chromium / Skia: typo metrics with USE_TYPO_METRICS, else hhea, else win
    if use_typo and typo_asc - typo_desc > 0:
        css_asc, css_desc = float(typo_asc), float(abs(typo_desc))
    elif hhea_asc - hhea_desc > 0:
        css_asc, css_desc = float(hhea_asc), float(abs(hhea_desc))
    else:
        css_asc, css_desc = lib_asc, lib_desc

    if upem <= 0 or lib_asc + lib_desc <= 0:
        raise ValueError(f"invalid vertical metrics in {path}")
    return FontMetrics(upem, lib_asc, lib_desc, css_asc, css_desc, str(path))


@functools.lru_cache(maxsize=16)
def _index_dir(fonts_dir: str, _mtime: float) -> tuple[tuple[str, frozenset[str], frozenset[str]], ...]:
    """(path, family names, subfamily names) for every font file in fonts_dir."""
    entries = []
    for p in sorted(Path(fonts_dir).iterdir()):
        if p.suffix.lower() not in FONT_EXTENSIONS:
            continue
        try:
            data = p.read_bytes()
            names = _names(data, _tables(data))
        except Exception as e:  # unreadable font: libass would skip it too
            log.warning("Không đọc được font %s: %s", p, e)
            continue
        families = {n.lower() for n in names.get(16, set()) | names.get(1, set()) | names.get(4, set())}
        styles = {n.lower() for n in names.get(17, set()) | names.get(2, set())}
        entries.append((str(p), frozenset(families), frozenset(styles)))
    return tuple(entries)


def _find_in_dir(family: str, bold: bool, italic: bool, fonts_dir: Path) -> Path | None:
    want = family.strip().lower()
    best: tuple[int, str] | None = None
    for path, families, styles in _index_dir(str(fonts_dir), fonts_dir.stat().st_mtime):
        if want not in families:
            continue
        style = " ".join(styles)
        is_bold = "bold" in style and "semibold" not in style and "semi bold" not in style
        is_italic = "italic" in style or "oblique" in style
        is_regular = not is_italic and any(s in style for s in ("regular", "normal", "book"))
        score = (2 if is_bold == bold else 0) + (2 if is_italic == italic else 0) + (1 if is_regular else 0)
        if best is None or score > best[0]:
            best = (score, path)
    return Path(best[1]) if best else None


def _find_with_fontconfig(family: str, bold: bool, italic: bool) -> Path | None:
    fc = shutil.which("fc-match")
    if not fc:
        return None
    pattern = f"{family}:weight={'bold' if bold else 'regular'}:slant={'italic' if italic else 'roman'}"
    try:
        proc = subprocess.run([fc, "-f", "%{file}", pattern], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    path = Path(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else None
    return path if path and path.is_file() else None


def read_advances(path: Path) -> dict[int, float]:
    """Horizontal advance of each mapped code point, in em (hmtx via cmap, no shaping)."""
    data = path.read_bytes()
    t = _tables(data)
    upem = float(struct.unpack(">H", data[t["head"] + 18 : t["head"] + 20])[0])
    num_hmetrics = struct.unpack(">H", data[t["hhea"] + 34 : t["hhea"] + 36])[0]
    hmtx = t["hmtx"]

    def advance(gid: int) -> float:
        rec = hmtx + 4 * min(gid, num_hmetrics - 1)
        return struct.unpack(">H", data[rec : rec + 2])[0] / upem

    cmap = t["cmap"]
    n_sub = struct.unpack(">H", data[cmap + 2 : cmap + 4])[0]
    subtables: dict[tuple[int, int], int] = {}
    for i in range(n_sub):
        pid, eid, off = struct.unpack(">HHI", data[cmap + 4 + 8 * i : cmap + 12 + 8 * i])
        subtables[(pid, eid)] = cmap + off
    out: dict[int, float] = {}
    for key in ((3, 10), (0, 4), (0, 6), (3, 1), (0, 3), (0, 1), (0, 0)):
        st = subtables.get(key)
        if st is None:
            continue
        fmt = struct.unpack(">H", data[st : st + 2])[0]
        if fmt == 12:
            n_groups = struct.unpack(">I", data[st + 12 : st + 16])[0]
            for g in range(n_groups):
                start, end, gid0 = struct.unpack(">III", data[st + 16 + 12 * g : st + 28 + 12 * g])
                for cp in range(start, min(end, start + 0xFFFF) + 1):
                    out[cp] = advance(gid0 + cp - start)
            return out
        if fmt == 4:
            seg2 = struct.unpack(">H", data[st + 6 : st + 8])[0]
            ends, starts = st + 14, st + 16 + seg2
            deltas, ranges = starts + seg2, starts + 2 * seg2
            for s in range(seg2 // 2):
                end = struct.unpack(">H", data[ends + 2 * s : ends + 2 * s + 2])[0]
                start = struct.unpack(">H", data[starts + 2 * s : starts + 2 * s + 2])[0]
                delta = struct.unpack(">h", data[deltas + 2 * s : deltas + 2 * s + 2])[0]
                ro_pos = ranges + 2 * s
                ro = struct.unpack(">H", data[ro_pos : ro_pos + 2])[0]
                for cp in range(start, end + 1):
                    if cp == 0xFFFF:
                        continue
                    if ro == 0:
                        gid = (cp + delta) & 0xFFFF
                    else:
                        gpos = ro_pos + ro + 2 * (cp - start)
                        gid = struct.unpack(">H", data[gpos : gpos + 2])[0]
                        gid = (gid + delta) & 0xFFFF if gid else 0
                    if gid:
                        out[cp] = advance(gid)
            return out
    return out


def _resolve_font_path(family: str, bold: bool, italic: bool, fonts_dir: str | None) -> Path | None:
    path = None
    if fonts_dir and Path(fonts_dir).is_dir():
        path = _find_in_dir(family, bold, italic, Path(fonts_dir))
    if path is None:
        path = _find_with_fontconfig(family, bold, italic)
    return path


@functools.lru_cache(maxsize=64)
def _font_metrics_cached(family: str, bold: bool, italic: bool, fonts_dir: str | None) -> FontMetrics:
    path = _resolve_font_path(family, bold, italic, fonts_dir)
    if path is None:
        log.warning("Không tìm thấy font '%s', dùng metric mặc định", family)
        return DEFAULT_METRICS
    try:
        return read_metrics(path)
    except Exception as e:
        log.warning("Không đọc được metric của %s: %s", path, e)
        return DEFAULT_METRICS


@functools.lru_cache(maxsize=16)
def _advances_cached(path: str) -> dict[int, float]:
    try:
        return read_advances(Path(path))
    except Exception as e:
        log.warning("Không đọc được độ rộng glyph của %s: %s", path, e)
        return {}


def font_metrics(family: str, bold: bool = False, italic: bool = False, fonts_dir: Path | None = None) -> FontMetrics:
    """Vertical metrics of the face libass loads for this family (fonts_dir first, then fontconfig)."""
    return _font_metrics_cached(family, bold, italic, str(fonts_dir) if fonts_dir else None)


def glyph_advances(metrics: FontMetrics) -> dict[int, float]:
    """Advance per code point (in em) of the face behind these metrics; empty when unknown."""
    return _advances_cached(metrics.path) if metrics.path else {}
