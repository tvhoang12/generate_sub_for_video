"""Subtitle cues: SRT read/write and timing clean-up."""

import math
import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

from .fonts import default_fonts_dir, font_metrics, glyph_advances

MIN_CUE_MS = 800
TRIM_SLACK_MS = 600

_TS = r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
_CUE_RE = re.compile(rf"{_TS}\s*-->\s*{_TS}")
# Whole-line sound tags ASR models sometimes emit: [Music], (laughs), ♪ ... ♪
_NON_SPEECH_RE = re.compile(r"^\s*(\[[^\]]*\]|\([^)]*\)|[♪♫\s]+)\s*$")


@dataclass(frozen=True)
class Cue:
    id: int
    start_ms: int
    end_ms: int
    text: str

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def format_timestamp(ms: int) -> str:
    ms = max(0, ms)
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    seconds, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def to_srt(cues: list[Cue]) -> str:
    blocks = [
        f"{n}\n{format_timestamp(c.start_ms)} --> {format_timestamp(c.end_ms)}\n{c.text.strip()}\n"
        for n, c in enumerate(cues, start=1)
    ]
    return "\n".join(blocks)


def _ass_time(ms: int) -> str:
    cs = max(0, ms) // 10
    hours, rem = divmod(cs, 360_000)
    minutes, rem = divmod(rem, 6000)
    seconds, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"


def hex_to_ass_color(hex_color: str, alpha: int = 0) -> str:
    """Convert CSS hex color (#RRGGBB) to ASS color format (&HAABBGGRR)."""
    c = hex_color.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        c = "FFFFFF"
    r, g, b = c[0:2], c[2:4], c[4:6]
    return f"&H{alpha:02X}{b.upper()}{g.upper()}{r.upper()}"


# Zero-width marks, dependent vowels above/below, tone marks, and combining diacritics
# Lao: vowels above/below and tone marks (sitting above/below base consonant)
# Spacing vowels (width > 0): 0x0EB0 (ະ), 0x0EB2 (າ), 0x0EB3 (ຳ), 0x0EC0-0x0EC4 (ເ, ແ, ໂ, ໃ, ໄ), 0x0EC6 (ໆ)
LAO_ZERO_WIDTH_CODES = {
    0x0EB1, 0x0EB4, 0x0EB5, 0x0EB6, 0x0EB7, 0x0EB8, 0x0EB9, 0x0EBA, 0x0EBB, 0x0EBC, 0x0ECD,
    0x0EC8, 0x0EC9, 0x0ECA, 0x0ECB, 0x0ECC,
}

# Thai: vowels above/below and tone marks
# Spacing vowels (width > 0): 0x0E30 (ะ), 0x0E32 (า), 0x0E33 (ำ), 0x0E40-0x0E45 (เ, แ, โ, ใ, ไ, ๅ), 0x0E46 (ๆ)
THAI_ZERO_WIDTH_CODES = {
    0x0E31, 0x0E34, 0x0E35, 0x0E36, 0x0E37, 0x0E38, 0x0E39, 0x0E3A,
    0x0E47, 0x0E48, 0x0E49, 0x0E4A, 0x0E4B, 0x0E4C, 0x0E4D, 0x0E4E,
}

# Myanmar: vowels above/below, virama, asat, medial signs
# Spacing vowels (width > 0): 0x102B, 0x102C (tall AA, AA), 0x1031 (E), 0x1038 (visarga)
MYANMAR_ZERO_WIDTH_CODES = {
    0x102D, 0x102E, 0x102F, 0x1030, 0x1032, 0x1033, 0x1034, 0x1035,
    0x1036, 0x1037, 0x1039, 0x103A, 0x103D, 0x103E,
}

# Khmer: dependent vowels above/below, diacritics, and signs
KHMER_ZERO_WIDTH_CODES = (
    set(range(0x17B7, 0x17BE))
    | {0x17C6}
    | set(range(0x17C9, 0x17D4))
    | {0x17DD}
)

OVERFLOW_TOLERANCE = 1.05  # 5% margin to prevent premature wrapping of slightly overflowing lines
PUNCTUATION_CHARS = set("，,、。！？!?…;；:：ฯๆ។")


def is_zero_width_mark(ch: str, prev_ch: str = "") -> bool:
    """True if character has no advance width (renders above, below, or attaches without space)."""
    if unicodedata.combining(ch) > 0:
        return True
    code = ord(ch)
    if code in LAO_ZERO_WIDTH_CODES or code in THAI_ZERO_WIDTH_CODES:
        return True
    if code in MYANMAR_ZERO_WIDTH_CODES or code in KHMER_ZERO_WIDTH_CODES:
        return True
    # Subjoined consonants in Khmer (after coeng U+17D2) or Myanmar (after virama U+1039)
    if prev_ch in ("\u17D2", "\u1039"):
        return True
    return False


def is_pre_vowel(ch: str) -> bool:
    """True if character is a leading/pre-vowel in Lao or Thai written before base consonant."""
    code = ord(ch)
    return (0x0EC0 <= code <= 0x0EC4) or (0x0E40 <= code <= 0x0E44)


def is_dependent_mark(ch: str) -> bool:
    """True if character is a combining mark, dependent vowel, tone, or diacritic that attaches to preceding char."""
    if unicodedata.combining(ch) > 0:
        return True
    code = ord(ch)
    # Lao vowels & tone marks (excluding pre-vowels U+0EC0..U+0EC4)
    if code in LAO_ZERO_WIDTH_CODES or code in (0x0EB0, 0x0EB2, 0x0EB3):
        return True
    # Thai vowels & tone marks (excluding pre-vowels U+0E40..U+0E44)
    if code in THAI_ZERO_WIDTH_CODES or code in (0x0E30, 0x0E32, 0x0E33, 0x0E45):
        return True
    # Myanmar signs
    if code in MYANMAR_ZERO_WIDTH_CODES or code in (0x102B, 0x102C, 0x1038):
        return True
    # Khmer dependent vowels & diacritics: U+17B4..U+17D3
    if 0x17B4 <= code <= 0x17D3:
        return True
    return False


Advances = dict[int, float] | None  # code point -> advance in em, read from the font file


def char_width(ch: str, font_size: float, prev_ch: str = "", advances: Advances = None) -> float:
    if is_zero_width_mark(ch, prev_ch):
        return 0.0
    code = ord(ch)
    if advances and code in advances:
        return advances[code] * font_size
    if 0x1780 <= code <= 0x17FF:
        return font_size * 0.58
    w = unicodedata.east_asian_width(ch)
    if w in ("F", "W"):
        return font_size * 0.95
    if 0x0E80 <= code <= 0x0EFF:
        return font_size * 0.52
    if 0x0E00 <= code <= 0x0E7F:
        return font_size * 0.52
    if 0x1000 <= code <= 0x109F:
        return font_size * 0.55
    if ch in "ijlI1.,:;!'\"| ":
        return font_size * 0.28
    if ch in "mwMW@%#&":
        return font_size * 0.78
    return font_size * 0.50


def measure_text_width(text: str, font_size: float, advances: Advances = None) -> float:
    """Measure total advance width of text using char_width."""
    total_w = 0.0
    prev_c = ""
    for c in text:
        total_w += char_width(c, font_size, prev_c, advances)
        prev_c = c
    return total_w


def split_clusters(text: str) -> list[str]:
    """Split text into orthographic clusters so vowels, tone marks, and subjoined consonants stay glued."""
    clusters: list[str] = []
    chars = list(text)
    n = len(chars)
    i = 0
    while i < n:
        c = [chars[i]]
        i += 1
        # Pre-vowels in Lao and Thai bind to the following base consonant
        if is_pre_vowel(c[0]) and i < n:
            c.append(chars[i])
            i += 1
        while i < n:
            if is_dependent_mark(chars[i]):
                c.append(chars[i])
                i += 1
            elif c[-1] in ("\u17D2", "\u1039"):  # Khmer coeng / Myanmar virama glues to following consonant
                c.append(chars[i])
                i += 1
            else:
                break
        clusters.append("".join(c))
    return clusters


def split_balanced_clusters(text: str, max_width: float, font_size: float, advances: Advances = None) -> list[str]:
    """Split a text without spaces into visually balanced lines, avoiding tiny orphan fragments."""
    clusters = split_clusters(text)
    if not clusters:
        return []
    c_widths: list[float] = []
    last_c = ""
    for cl in clusters:
        cw = 0.0
        prev_c = last_c
        for c in cl:
            cw += char_width(c, font_size, prev_c, advances)
            prev_c = c
        c_widths.append(cw)
        last_c = cl[-1] if cl else ""

    total_w = sum(c_widths)
    if total_w <= max_width * OVERFLOW_TOLERANCE:
        return [text]

    k = max(2, int(math.ceil(total_w / max_width)))
    target_w = total_w / k

    sub_lines: list[str] = []
    cur_chunk: list[str] = []
    cur_chunk_w = 0.0

    for i, (cl, cw) in enumerate(zip(clusters, c_widths)):
        cur_chunk.append(cl)
        cur_chunk_w += cw
        remaining_w = total_w - sum(c_widths[: i + 1])
        is_punct = any(ch in PUNCTUATION_CHARS for ch in cl)

        should_break = False
        if len(sub_lines) < k - 1 and remaining_w > 0:
            if is_punct and cur_chunk_w >= target_w * 0.8:
                should_break = True
            elif cur_chunk_w >= target_w:
                should_break = True

        if should_break:
            sub_lines.append("".join(cur_chunk))
            cur_chunk = []
            cur_chunk_w = 0.0

    if cur_chunk:
        sub_lines.append("".join(cur_chunk))
    return sub_lines


def wrap_single_line(line: str, max_width: float, font_size: float, advances: Advances = None) -> list[str]:
    """Wrap a single line of text to fit within max_width with overflow tolerance and orphan prevention."""
    line = line.strip()
    if not line:
        return []
    total_w = measure_text_width(line, font_size, advances)
    if total_w <= max_width * OVERFLOW_TOLERANCE:
        return [line]

    if " " not in line:
        return split_balanced_clusters(line, max_width, font_size, advances)

    words = [w for w in line.split(" ") if w]
    expanded_words: list[str] = []
    for w in words:
        w_w = measure_text_width(w, font_size, advances)
        if w_w > max_width * OVERFLOW_TOLERANCE:
            expanded_words.extend(split_balanced_clusters(w, max_width, font_size, advances))
        else:
            expanded_words.append(w)

    space_w = char_width(" ", font_size, "", advances)
    lines: list[str] = []
    cur_line: list[str] = []
    cur_w = 0.0

    for word in expanded_words:
        word_w = measure_text_width(word, font_size, advances)
        added_w = word_w if not cur_line else space_w + word_w
        if cur_line and (cur_w + added_w > max_width * OVERFLOW_TOLERANCE):
            lines.append(" ".join(cur_line))
            cur_line = [word]
            cur_w = word_w
        else:
            cur_line.append(word)
            cur_w += added_w

    if cur_line:
        lines.append(" ".join(cur_line))

    # Orphan prevention: if the last line has only 1 word and previous line has 2+ words,
    # pull the last word of previous line down if it still fits within max_width * OVERFLOW_TOLERANCE
    if len(lines) >= 2:
        last_line_words = lines[-1].split(" ")
        prev_line_words = lines[-2].split(" ")
        if len(last_line_words) == 1 and len(prev_line_words) >= 2:
            candidate_last = prev_line_words[-1] + " " + lines[-1]
            if measure_text_width(candidate_last, font_size, advances) <= max_width * OVERFLOW_TOLERANCE:
                lines[-2] = " ".join(prev_line_words[:-1])
                lines[-1] = candidate_last

    return lines


def wrap_text_for_ass(text: str, max_width: float, font_size: float, advances: Advances = None) -> list[str]:
    """Wrap cue text to fit max_width in ASS canvas coordinates, returning list of lines."""
    raw_lines = text.replace("\r\n", "\n").replace(r"\N", "\n").split("\n")
    result_lines: list[str] = []
    for l in raw_lines:
        wrapped = wrap_single_line(l, max_width, font_size, advances)
        if wrapped:
            result_lines.extend(wrapped)
        else:
            result_lines.append("")
    return result_lines


# Layout constants shared with the web preview (web/src/components/SubtitleConfigCard.tsx).
PREVIEW_LINE_HEIGHT = 1.3  # CSS line-height of each subtitle line, in em
MASK_PAD_Y_RATIO = 0.45  # vertical mask padding = mask_padding_x * 0.45
ROUNDED_RADIUS_RATIO = 0.28  # "rounded" mask corner radius, in em

FONT_ALIASES: dict[str, str] = {
    "phetsarath ot": "Phetsarath",
    "phetsarath": "Phetsarath",
    "kantumruy": "Kantumruy Pro",
    "kantumruy pro": "Kantumruy Pro",
}


def _cfg_num(cfg: dict, key: str, default: float) -> float:
    """Config number; 0 is a valid value, only missing/invalid values fall back to the default."""
    v = cfg.get(key)
    if v is None or v == "":
        return float(default)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float(default)
    return f if math.isfinite(f) else float(default)


def _cfg_flag(cfg: dict, key: str, default: bool) -> bool:
    v = cfg.get(key, default)
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "0", "no", "off", "")
    return bool(v) if v is not None else default


def _fmt(x: float) -> str:
    """Compact number for ASS fields: 2 decimals, no trailing zeros."""
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _rounded_rect(w: float, h: float, r: float) -> str:
    """ASS vector drawing of a w x h rectangle with corner radius r, origin top-left."""
    r = max(0.0, min(r, w / 2, h / 2))
    if r < 0.5:
        return f"m 0 0 l {_fmt(w)} 0 l {_fmt(w)} {_fmt(h)} l 0 {_fmt(h)}"
    k = r * 0.5523
    f = _fmt
    return (
        f"m {f(r)} 0 l {f(w - r)} 0 b {f(w - r + k)} 0 {f(w)} {f(r - k)} {f(w)} {f(r)} "
        f"l {f(w)} {f(h - r)} b {f(w)} {f(h - r + k)} {f(w - r + k)} {f(h)} {f(w - r)} {f(h)} "
        f"l {f(r)} {f(h)} b {f(r - k)} {f(h)} 0 {f(h - r + k)} 0 {f(h - r)} "
        f"l 0 {f(r)} b 0 {f(r - k)} {f(r - k)} 0 {f(r)} 0"
    )


def to_ass(
    cues: list[Cue],
    font: str,
    config: dict | None = None,
    video_width: int | None = None,
    video_height: int | None = None,
    fonts_dir: Path | None = None,
) -> str:
    """ASS script that renders the subtitle exactly where the web preview draws it.

    PlayRes equals the video resolution, so every config value is in video pixels.

    The preview is HTML: `font-size` is the em, each line is a `line-height: 1.3` box,
    lines are stacked with `line_spacing` between them and the stack sits `margin_v` above
    the bottom edge. libass instead sizes text by usWinAscent+usWinDescent and spaces lines
    by the same metrics. To match, the ASS Fontsize is scaled by the font's real metrics and
    every wrapped line is its own event anchored (\\an2\\pos) at the baseline the preview uses.

    Layer 0 is the blurred mask that hides the old hardcoded subtitle; layer 1 is the text.
    """
    cfg = config or {}
    raw_font = str(cfg.get("font") or "").strip()
    if raw_font == "__custom__":
        raw_font = ""
    font_name = FONT_ALIASES.get(raw_font.lower(), raw_font) or FONT_ALIASES.get(font.lower(), font)

    if fonts_dir is None:
        fonts_dir = default_fonts_dir()

    if video_width and video_height and video_width > 0 and video_height > 0:
        playres_x, playres_y = int(video_width), int(video_height)
    else:
        playres_x, playres_y = 1920, 1080

    bold = _cfg_flag(cfg, "bold", True)
    italic = _cfg_flag(cfg, "italic", False)
    em = max(12.0, _cfg_num(cfg, "font_size", 50))
    metrics = font_metrics(font_name, bold, italic, fonts_dir)
    ass_fontsize = em * metrics.libass_scale
    advances = glyph_advances(metrics)

    has_border = _cfg_flag(cfg, "has_border", True)
    has_shadow = _cfg_flag(cfg, "has_shadow", True)
    outline = max(0.0, _cfg_num(cfg, "outline", 3.0)) if has_border else 0.0
    shadow = max(0.0, _cfg_num(cfg, "shadow", 1.5)) if has_shadow else 0.0

    margin_l = max(0, int(round(_cfg_num(cfg, "margin_l", 50))))
    margin_r = max(0, int(round(_cfg_num(cfg, "margin_r", 50))))
    margin_v = max(5.0, _cfg_num(cfg, "margin_v", 50))
    line_spacing = max(0.0, _cfg_num(cfg, "line_spacing", 12))
    pad_x = max(2.0, _cfg_num(cfg, "mask_padding_x", 24))
    pad_y = pad_x * MASK_PAD_Y_RATIO

    mask_enabled = _cfg_flag(cfg, "mask_enabled", True)
    mask_by_text = _cfg_flag(cfg, "mask_by_text", True)
    mask_shape = str(cfg.get("mask_shape") or "pill").lower()
    mask_blur = max(0, int(round(_cfg_num(cfg, "mask_blur", 10))))
    opacity = _cfg_num(cfg, "mask_opacity", 40)
    if opacity > 1.0:
        opacity /= 100.0
    opacity = max(0.0, min(1.0, opacity))
    mask_alpha = int(round((1.0 - opacity) * 255))
    mask_colour = hex_to_ass_color(str(cfg.get("mask_color") or "#000000"), alpha=mask_alpha)

    primary_colour = hex_to_ass_color(str(cfg.get("color") or "#FFFFFF"), alpha=0)
    border_colour = hex_to_ass_color(str(cfg.get("color_border") or "#000000"), alpha=0)
    shadow_colour = hex_to_ass_color(str(cfg.get("color_shadow") or "#000000"), alpha=0x80)

    b, i = (1 if bold else 0), (1 if italic else 0)
    fs = _fmt(ass_fontsize)
    mv = int(round(margin_v))
    style_default = (
        f"Style: Default,{font_name},{fs},{primary_colour},&H000000FF,{border_colour},{shadow_colour},"
        f"{b},{i},0,0,100,100,0,0,1,{outline:.1f},{shadow:.1f},2,{margin_l},{margin_r},{mv},1"
    )
    if mask_by_text:
        style_backdrop = (
            f"Style: Backdrop,{font_name},{fs},&HFF000000,&H000000FF,{mask_colour},{mask_colour},"
            f"{b},{i},0,0,100,100,0,0,3,{_fmt(pad_x)},0,2,{margin_l},{margin_r},{mv},1"
        )
    else:
        style_backdrop = (
            f"Style: BackdropFixed,{font_name},{fs},{mask_colour},&H000000FF,{mask_colour},{mask_colour},"
            f"0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1"
        )

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {playres_x}
PlayResY: {playres_y}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style_default}
{style_backdrop}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # --- geometry, in video pixels measured from the bottom edge ---
    css_line_h = PREVIEW_LINE_HEIGHT * em
    css_content = (metrics.css_ascent_ratio + metrics.css_descent_ratio) * em
    # baseline height inside a CSS line box (half-leading + descent)
    css_baseline = (css_line_h - css_content) / 2 + metrics.css_descent_ratio * em
    lib_descent = metrics.libass_descent * em
    lib_box_h = metrics.libass_scale * em  # libass line box = BorderStyle 3 box before \ybord
    stack_pad = pad_y if (mask_enabled and mask_by_text) else 0.0
    pitch = css_line_h + 2 * stack_pad + line_spacing
    x_center = margin_l + (playres_x - margin_l - margin_r) / 2
    available_width = max(50.0, float(playres_x - margin_l - margin_r))
    ybord = max(0.0, (css_line_h + 2 * pad_y - lib_box_h) / 2)
    blur_tag = f"\\blur{mask_blur}" if mask_blur > 0 else ""

    if mask_shape == "pill":
        radius_for = lambda w, h: h / 2  # noqa: E731
    elif mask_shape == "rounded":
        radius_for = lambda w, h: ROUNDED_RADIUS_RATIO * em  # noqa: E731
    else:
        radius_for = lambda w, h: 0.0  # noqa: E731

    events: list[str] = []
    for c in cues:
        lines = [l for l in wrap_text_for_ass(c.text.strip(), available_width, em, advances) if l.strip()]
        if not lines:
            continue
        escaped = [l.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}") for l in lines]
        start, end = _ass_time(c.start_ms), _ass_time(c.end_ms)
        n = len(escaped)

        anchors: list[float] = []  # \an2 anchor y (bottom of libass line box), top line first
        for idx in range(n):
            k = n - 1 - idx  # 0 = bottom line
            baseline_from_bottom = margin_v + stack_pad + css_baseline + k * pitch
            anchors.append(playres_y - (baseline_from_bottom - lib_descent))

        if mask_enabled and not mask_by_text:
            block_h = n * css_line_h + (n - 1) * line_spacing
            y2 = min(float(playres_y), playres_y - margin_v + pad_y)
            y1 = max(0.0, playres_y - margin_v - block_h - pad_y)
            if mask_shape == "bar":
                x1, x2 = 0.0, float(playres_x)
            else:
                x1 = max(0.0, margin_l - pad_x)
                x2 = min(float(playres_x), max(x1 + 10, playres_x - margin_r + pad_x))
            w, h = x2 - x1, max(1.0, y2 - y1)
            r = 0.0 if mask_shape == "bar" else radius_for(w, h)
            events.append(
                f"Dialogue: 0,{start},{end},BackdropFixed,,0,0,0,,"
                f"{{\\an7\\pos({_fmt(x1)},{_fmt(y1)}){blur_tag}\\p1}}{_rounded_rect(w, h, r)}{{\\p0}}"
            )

        for text, y in zip(escaped, anchors):
            pos = f"\\an2\\pos({_fmt(x_center)},{_fmt(y)})"
            if mask_enabled and mask_by_text:
                events.append(
                    f"Dialogue: 0,{start},{end},Backdrop,,0,0,0,,"
                    f"{{{pos}{blur_tag}\\xbord{_fmt(pad_x)}\\ybord{_fmt(ybord)}}}{text}"
                )
            events.append(f"Dialogue: 1,{start},{end},Default,,0,0,0,,{{{pos}}}{text}")
    return header + "\n".join(events) + "\n"


def parse_srt(content: str) -> list[Cue]:
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", content.replace("\r\n", "\n").strip()):
        lines = block.split("\n")
        for i, line in enumerate(lines):
            match = _CUE_RE.search(line)
            if match:
                g = list(map(int, match.groups()))
                start = ((g[0] * 60 + g[1]) * 60 + g[2]) * 1000 + g[3]
                end = ((g[4] * 60 + g[5]) * 60 + g[6]) * 1000 + g[7]
                text = "\n".join(lines[i + 1 :]).strip()
                if text:
                    cues.append(Cue(len(cues) + 1, start, end, text))
                break
    return cues


def is_non_speech(text: str) -> bool:
    return not text.strip() or bool(_NON_SPEECH_RE.match(text))


def tighten_timing(cues: list[Cue], speech: list[tuple[int, int]], max_cue_ms: int) -> list[Cue]:
    """Fit each cue to the voice activity inside it, cap its length, and stop overlaps.

    ASR models sometimes stretch a cue across a long pause (one line on screen for 17 s while
    the speech lasts 1.5 s). The VAD regions are measured on the original audio, so trimming a
    cue to the regions it overlaps puts it back where the words are actually spoken.
    """
    fitted: list[Cue] = []
    for cue in cues:
        start, end = cue.start_ms, cue.end_ms
        inside = [(s, e) for s, e in speech if s < end and e > start]
        if inside:
            # Only trim real slack: VAD edges are tighter than reading time, so small margins stay.
            speech_start, speech_end = min(s for s, _ in inside), max(e for _, e in inside)
            if speech_start - start > TRIM_SLACK_MS:
                start = speech_start
            if end - speech_end > TRIM_SLACK_MS:
                end = speech_end
            if end - start > max_cue_ms:
                end = start + max_cue_ms
        elif end - start > max_cue_ms:
            # Keep the tail: a stretched cue's words are usually at the end, right before the next line.
            start = end - max_cue_ms
        fitted.append(replace(cue, start_ms=start, end_ms=end))

    result: list[Cue] = []
    for i, cue in enumerate(fitted):
        next_start = fitted[i + 1].start_ms if i + 1 < len(fitted) else None
        end = max(cue.end_ms, cue.start_ms + MIN_CUE_MS)
        if next_start is not None:
            end = min(end, next_start - 40)
        if end > cue.start_ms:
            result.append(replace(cue, end_ms=end))
    return result
