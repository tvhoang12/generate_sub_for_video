"""Subtitle cues: SRT read/write and timing clean-up."""

import math
import re
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

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


def char_width(ch: str, font_size: float, prev_ch: str = "") -> float:
    if is_zero_width_mark(ch, prev_ch):
        return 0.0
    code = ord(ch)
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


def measure_text_width(text: str, font_size: float) -> float:
    """Measure total advance width of text using char_width."""
    total_w = 0.0
    prev_c = ""
    for c in text:
        total_w += char_width(c, font_size, prev_c)
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


def split_balanced_clusters(text: str, max_width: float, font_size: float) -> list[str]:
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
            cw += char_width(c, font_size, prev_c)
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


def wrap_single_line(line: str, max_width: float, font_size: float) -> list[str]:
    """Wrap a single line of text to fit within max_width with overflow tolerance and orphan prevention."""
    line = line.strip()
    if not line:
        return []
    total_w = measure_text_width(line, font_size)
    if total_w <= max_width * OVERFLOW_TOLERANCE:
        return [line]

    if " " not in line:
        return split_balanced_clusters(line, max_width, font_size)

    words = [w for w in line.split(" ") if w]
    expanded_words: list[str] = []
    for w in words:
        w_w = measure_text_width(w, font_size)
        if w_w > max_width * OVERFLOW_TOLERANCE:
            expanded_words.extend(split_balanced_clusters(w, max_width, font_size))
        else:
            expanded_words.append(w)

    space_w = char_width(" ", font_size)
    lines: list[str] = []
    cur_line: list[str] = []
    cur_w = 0.0

    for word in expanded_words:
        word_w = measure_text_width(word, font_size)
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
            if measure_text_width(candidate_last, font_size) <= max_width * OVERFLOW_TOLERANCE:
                lines[-2] = " ".join(prev_line_words[:-1])
                lines[-1] = candidate_last

    return lines


def wrap_text_for_ass(text: str, max_width: float, font_size: float) -> list[str]:
    """Wrap cue text to fit max_width in ASS canvas coordinates, returning list of lines."""
    raw_lines = text.replace("\r\n", "\n").replace(r"\N", "\n").split("\n")
    result_lines: list[str] = []
    for l in raw_lines:
        wrapped = wrap_single_line(l, max_width, font_size)
        if wrapped:
            result_lines.extend(wrapped)
        else:
            result_lines.append("")
    return result_lines


FONT_METRIC_FALLBACK = {
    "Kantumruy Pro": (2.15, 0.22),
    "Noto Sans Khmer": (2.20, 0.25),
    "Khmer OS": (2.35, 0.28),
}


def get_ass_font_metrics(font_name: str, fonts_dir: Path | None = None) -> tuple[float, float]:
    """
    Trả về (scale_factor, extra_descent_ratio):
    - scale_factor = (usWinAscent + usWinDescent) / unitsPerEm
    - extra_descent_ratio = max(0, (usWinDescent - abs(sTypoDescender)) / unitsPerEm)
    """
    if fonts_dir and fonts_dir.exists():
        try:
            from fontTools.ttLib import TTFont
            for ttf_path in fonts_dir.glob("*.[to]tf"):
                font = TTFont(str(ttf_path))
                family_names = [
                    rec.toUnicode()
                    for rec in font["name"].names
                    if rec.nameID in (1, 4, 16)
                ]
                if any(font_name.lower() == n.lower() for n in family_names) and "Regular" in "".join(family_names):
                    upem = float(font["head"].unitsPerEm)
                    os2 = font["OS/2"]
                    win_ascent = float(os2.usWinAscent)
                    win_descent = float(os2.usWinDescent)
                    typo_descent = abs(float(getattr(os2, "sTypoDescender", font["hhea"].descent)))
                    if win_ascent + win_descent > 0 and upem > 0:
                        scale = (win_ascent + win_descent) / upem
                        extra_desc = max(0.0, (win_descent - typo_descent) / upem)
                        return (scale, extra_desc)
        except Exception:
            pass
    return FONT_METRIC_FALLBACK.get(font_name, (1.22, 0.05))


def to_ass(
    cues: list[Cue],
    font: str,
    config: dict | None = None,
    video_width: int | None = None,
    video_height: int | None = None,
    fonts_dir: Path | None = None,
) -> str:
    """ASS script for burning styled subtitles matching exact video dimensions.

    Uses the actual video resolution (PlayResX = video_width, PlayResY = video_height)
    so subtitle font size, margins, outline, and shadow units correspond 1:1 to video pixels
    and perfectly match the frontend live preview without scaling distortion.

    Burning ASS through ffmpeg's `ass` filter allows complex text shaping (critical for
    Khmer clusters, Lao tones, Myanmar subjoined consonants).
    Layer 0 (Backdrop) creates a softly blurred, semi-transparent mask behind the subtitle.
    Layer 1 (Default) renders customizable text with sharp stroke and shadow.
    """
    cfg = config or {}
    font_aliases: dict[str, str] = {
        "phetsarath ot": "Phetsarath",
        "phetsarath": "Phetsarath",
        "kantumruy": "Kantumruy Pro",
        "kantumruy pro": "Kantumruy Pro",
    }
    raw_font = str(cfg.get("font") or "").strip()
    font_name = font_aliases.get(raw_font.lower(), raw_font) or font

    if fonts_dir is None:
        candidate = Path(__file__).resolve().parents[2] / "assets" / "fonts"
        if not candidate.exists():
            candidate = Path(__file__).resolve().parents[2] / "app" / "fonts"
        if candidate.exists():
            fonts_dir = candidate

    # Exact video dimensions: do not scale down to virtual canvas
    if video_width and video_height and video_width > 0 and video_height > 0:
        playres_x = int(video_width)
        playres_y = int(video_height)
    else:
        playres_x = 1920
        playres_y = 1080

    logical_fontsize = max(12, int(cfg.get("font_size") or 50))
    metric_scale, extra_descent_ratio = get_ass_font_metrics(font_name, fonts_dir)
    ass_fontsize = max(12, round(logical_fontsize * metric_scale))

    color_hex = str(cfg.get("color") or "#FFFFFF")
    color_border_hex = str(cfg.get("color_border") or "#000000")
    color_shadow_hex = str(cfg.get("color_shadow") or "#000000")

    has_border = cfg.get("has_border", True)
    if isinstance(has_border, str):
        has_border = has_border.lower() not in ("false", "0", "no")

    has_shadow = cfg.get("has_shadow", True)
    if isinstance(has_shadow, str):
        has_shadow = has_shadow.lower() not in ("false", "0", "no")

    bold = 1 if cfg.get("bold", True) else 0
    italic = 1 if cfg.get("italic", False) else 0

    margin_l = max(0, int(cfg.get("margin_l") if cfg.get("margin_l") is not None else 50))
    margin_r = max(0, int(cfg.get("margin_r") if cfg.get("margin_r") is not None else 50))
    raw_margin_v = int(cfg.get("margin_v") or 40)
    ass_margin_v = max(0, round(raw_margin_v - logical_fontsize * extra_descent_ratio))
    line_height = int(logical_fontsize * 1.3)
    outline = float(cfg.get("outline") or 3.0) if has_border else 0.0
    shadow = float(cfg.get("shadow") or 1.5) if has_shadow else 0.0

    line_spacing = max(0, int(cfg.get("line_spacing") or 0))
    mask_padding_x = max(2, int(cfg.get("mask_padding_x") if cfg.get("mask_padding_x") is not None else 24))

    mask_enabled = cfg.get("mask_enabled", True)
    if isinstance(mask_enabled, str):
        mask_enabled = mask_enabled.lower() not in ("false", "0", "no")

    mask_by_text = cfg.get("mask_by_text", True)
    if isinstance(mask_by_text, str):
        mask_by_text = mask_by_text.lower() not in ("false", "0", "no")

    mask_color_hex = str(cfg.get("mask_color") or "#000000")
    raw_opacity = float(cfg.get("mask_opacity") if cfg.get("mask_opacity") is not None else 40)
    if raw_opacity > 1.0:
        raw_opacity = raw_opacity / 100.0
    mask_opacity = max(0.0, min(1.0, raw_opacity))
    mask_alpha = int((1.0 - mask_opacity) * 255)
    mask_ass_colour = hex_to_ass_color(mask_color_hex, alpha=mask_alpha)

    mask_blur = int(cfg.get("mask_blur") if cfg.get("mask_blur") is not None else 10)
    mask_shape = str(cfg.get("mask_shape") or "pill").lower()

    backdrop_border_style = 3
    backdrop_outline = mask_padding_x
    if mask_shape == "bar":
        backdrop_margin_l = 0
        backdrop_margin_r = 0
        backdrop_back_colour = mask_ass_colour
    else:
        backdrop_margin_l = margin_l
        backdrop_margin_r = margin_r
        backdrop_back_colour = mask_ass_colour

    primary_colour = hex_to_ass_color(color_hex, alpha=0)
    border_colour = hex_to_ass_color(color_border_hex, alpha=0)
    shadow_colour = hex_to_ass_color(color_shadow_hex, alpha=0x80)

    if mask_by_text:
        backdrop_style_line = f"Style: Backdrop,{font_name},{ass_fontsize},&HFF000000,&H000000FF,{mask_ass_colour},{backdrop_back_colour},{bold},{italic},0,0,100,100,0,0,{backdrop_border_style},{backdrop_outline},0,2,{backdrop_margin_l},{backdrop_margin_r},{ass_margin_v},1"
    else:
        backdrop_style_line = f"Style: BackdropFixed,{font_name},{ass_fontsize},{mask_ass_colour},&H000000FF,{mask_ass_colour},{mask_ass_colour},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {playres_x}
PlayResY: {playres_y}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{ass_fontsize},{primary_colour},&H000000FF,{border_colour},{shadow_colour},{bold},{italic},0,0,100,100,0,0,1,{outline},{shadow},2,{margin_l},{margin_r},{ass_margin_v},1
{backdrop_style_line}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    blur_tag = f"{{\\blur{mask_blur}}}" if mask_blur > 0 else ""
    available_width = max(50.0, float(playres_x - margin_l - margin_r))
    mask_alpha_hex = f"&H{mask_alpha:02X}&"
    backdrop_line_break_tag = (
        f"\\N{{\\fs{line_spacing}\\alpha&HFF&}}\\h\\N{{\\fs{ass_fontsize}\\1a&HFF&\\3a{mask_alpha_hex}\\4a{mask_alpha_hex}}}"
        if line_spacing > 0
        else r"\N"
    )
    default_line_break_tag = (
        f"\\N{{\\fs{line_spacing}\\alpha&HFF&}}\\h\\N{{\\fs{ass_fontsize}\\alpha&H00&}}"
        if line_spacing > 0
        else r"\N"
    )
    for c in cues:
        raw_lines = wrap_text_for_ass(c.text.strip(), available_width, logical_fontsize)
        escaped_lines = [
            l.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")
            for l in raw_lines
        ]
        backdrop_text = backdrop_line_break_tag.join(escaped_lines)
        default_text = default_line_break_tag.join(escaped_lines)
        start = _ass_time(c.start_ms)
        end = _ass_time(c.end_ms)
        # Layer 0: blurred dark backdrop to obscure old hardcoded subtitles
        if mask_enabled:
            if mask_by_text:
                lines.append(f"Dialogue: 0,{start},{end},Backdrop,,0,0,0,,{blur_tag}{backdrop_text}")
            else:
                x1 = 0 if mask_shape == "bar" else max(0, margin_l - mask_padding_x)
                x2 = playres_x if mask_shape == "bar" else min(playres_x, max(x1 + 10, playres_x - margin_r + mask_padding_x))
                w = x2 - x1
                num_lines = max(1, len(raw_lines))
                extra_spacing = (num_lines - 1) * line_spacing
                h = line_height * num_lines + extra_spacing + round(logical_fontsize * 0.4)
                y2 = playres_y - ass_margin_v + round(logical_fontsize * 0.2)
                y1 = max(0, y2 - h)
                lines.append(f"Dialogue: 0,{start},{end},BackdropFixed,,0,0,0,,{{\\pos({x1},{y1}){blur_tag}\\p1}}m 0 0 l {w} 0 l {w} {h} l 0 {h}{{\\p0}}")
        # Layer 1: sharp styled text with black border and subtle shadow
        lines.append(f"Dialogue: 1,{start},{end},Default,,0,0,0,,{default_text}")
    return header + "\n".join(lines) + "\n"


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
