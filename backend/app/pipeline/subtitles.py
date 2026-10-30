"""Subtitle cues: SRT read/write and timing clean-up."""

import re
from dataclasses import dataclass, replace

MIN_CUE_MS = 800
TRIM_SLACK_MS = 1000

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


def to_ass(cues: list[Cue], font: str, config: dict | None = None) -> str:
    """ASS script for burning. Same 384x288 canvas libass uses for SRT, so sizes match the old look.

    Burning ASS through ffmpeg's `ass` filter is what allows complex text shaping; the `subtitles`
    filter on Debian's ffmpeg shapes simply and breaks Khmer clusters (stacked consonants, split vowels).
    Layer 0 (Backdrop) creates a softly blurred, semi-transparent dark pill behind the subtitle to mask
    original hardcoded subtitles (e.g. Chinese characters) without needing intrusive solid bars.
    Layer 1 (Default) renders customizable text with a black outline and subtle drop shadow.
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
    fontsize = int(cfg.get("font_size") or 25)
    color_hex = str(cfg.get("color") or "#FFFFFF")
    color_border_hex = str(cfg.get("color_border") or "#000000")
    primary_colour = hex_to_ass_color(color_hex, alpha=0)
    border_colour = hex_to_ass_color(color_border_hex, alpha=0)
    bold = 1 if cfg.get("bold", True) else 0
    italic = 1 if cfg.get("italic", False) else 0
    margin_l = int(cfg.get("margin_l") or 10)
    margin_r = int(cfg.get("margin_r") or 10)
    margin_v = int(cfg.get("margin_v") or 12)
    outline = float(cfg.get("outline") or 1.6)
    shadow = float(cfg.get("shadow") or 0.5)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 384
PlayResY: 288
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{fontsize},{primary_colour},&H000000FF,{border_colour},&H80000000,{bold},{italic},0,0,100,100,0,0,1,{outline},{shadow},2,{margin_l},{margin_r},{margin_v},1
Style: Backdrop,{font_name},{fontsize},&HFF000000,&H000000FF,&H80000000,&H80FFFFFF,{bold},{italic},0,0,100,100,0,0,1,6,0,2,{margin_l},{margin_r},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for c in cues:
        text = c.text.strip().replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")
        start = _ass_time(c.start_ms)
        end = _ass_time(c.end_ms)
        # Layer 0: softly blurred dark backdrop to obscure old hardcoded subtitles
        lines.append(f"Dialogue: 0,{start},{end},Backdrop,,0,0,0,,{{\\blur10}}{text}")
        # Layer 1: sharp styled text with black border and subtle shadow
        lines.append(f"Dialogue: 1,{start},{end},Default,,0,0,0,,{text}")
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
            # Cap maximum cue duration without cutting off the start of speech
            end = start + max_cue_ms
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
