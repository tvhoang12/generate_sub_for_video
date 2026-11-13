---
name: ffmpeg-subtitle-styler
description: Design, customize, and burn subtitles into videos using FFmpeg and libass (subtitles and ass filters). Use when the user asks to add, style, position, or edit subtitles in FFmpeg, including customizing font family, font size, text color, outline/border, background box, shadow, margins, or left/center/right and top/middle/bottom alignment.
---

# ffmpeg-subtitle-styler

Design, customize, and render styled subtitles (.srt, .vtt, .ass, .ssa) in FFmpeg using libass force_style parameters and ASS override tags with accurate color byte ordering, alignment grids, border/background modes, and filtergraph escaping.

## When to Use

- The user wants to burn (hardsub) or style subtitles in FFmpeg using `-vf subtitles` or `-vf ass`.
- The user specifies visual subtitle parameters: position (top, middle, bottom, or exact coordinates), horizontal alignment (left, center, right), font family, font size, text color, border/outline width and color, background box, or drop shadow.
- The user wants to convert `#RRGGBB` hex colors or opacity percentages into FFmpeg/ASS `&HAABBGGRR` format.
- The user needs to generate or modify `.ass` style headers (`[V4+ Styles]`) or inline ASS override tags before passing subtitles to FFmpeg.

## Steps

### 1. Convert Colors to ASS Hex Format (&HAABBGGRR)

FFmpeg's subtitles filter uses libass, which expects colors in reverse byte order (Alpha, Blue, Green, Red) prefixed with `&H`:

1. Parse the standard RGB hex color `#RRGGBB` into its Red (`RR`), Green (`GG`), and Blue (`BB`) hex pairs.
2. Convert opacity/transparency to an inverted Alpha hex byte (`AA`):
   - `00` = 100% opaque (0% transparent)
   - `4D` = 70% opaque (30% transparent)
   - `80` = 50% opaque (50% transparent)
   - `FF` = 0% opaque (100% transparent / invisible)
3. Assemble as `&HAABBGGRR`.

Common color reference table:

| Color | HTML Hex | ASS Opaque (`&H00BBGGRR`) | ASS 50% Semi-Transparent (`&H80BBGGRR`) |
| :--- | :--- | :--- | :--- |
| White | `#FFFFFF` | `&H00FFFFFF` | `&H80FFFFFF` |
| Black | `#000000` | `&H00000000` | `&H80000000` |
| Yellow | `#FFFF00` | `&H0000FFFF` | `&H8000FFFF` |
| Red | `#FF0000` | `&H000000FF` | `&H800000FF` |
| Green | `#00FF00` | `&H0000FF00` | `&H8000FF00` |
| Blue | `#0000FF` | `&H00FF0000` | `&H80FF0000` |
| Cyan | `#00FFFF` | `&H00FFFF00` | `&H80FFFF00` |

### 2. Map Alignment and Position (Left/Center/Right and Vertical Offset)

Set Alignment using the standard numpad grid (1 to 9) and refine exact screen spacing with `MarginL`, `MarginR`, and `MarginV`:

```text
+-----------------------+-----------------------+-----------------------+
| 7: Top-Left           | 8: Top-Center         | 9: Top-Right          |
| (Can trai tren)       | (Can giua tren)       | (Can phai tren)       |
+-----------------------+-----------------------+-----------------------+
| 4: Middle-Left        | 5: Middle-Center      | 6: Middle-Right       |
| (Can trai giua)       | (Can chinh giua)      | (Can phai giua)       |
+-----------------------+-----------------------+-----------------------+
| 1: Bottom-Left        | 2: Bottom-Center      | 3: Bottom-Right       |
| (Can trai duoi)       | (Can giua duoi - std) | (Can phai duoi)       |
+-----------------------+-----------------------+-----------------------+
```

- **Left Alignment (Căn lề trái)**: Set `Alignment=1` (bottom-left), `Alignment=4` (middle-left), or `Alignment=7` (top-left), and control distance from the left edge with `MarginL=<value>`.
- **Center Alignment (Căn giữa)**: Set `Alignment=2` (bottom-center, default), `Alignment=5` (screen center), or `Alignment=8` (top-center).
- **Right Alignment (Căn lề phải)**: Set `Alignment=3` (bottom-right), `Alignment=6` (middle-right), or `Alignment=9` (top-right), and control distance from the right edge with `MarginR=<value>`.
- **Vertical Position (`MarginV`)**:
  - When Alignment is 1, 2, or 3: `MarginV` sets distance from the bottom edge.
  - When Alignment is 7, 8, or 9: `MarginV` sets distance from the top edge.
  - When Alignment is 4, 5, or 6: Subtitle is vertically centered (`MarginV` is ignored).
- **Exact Pixel Coordinates (Per-Line Override)**: When the user requests exact (X, Y) coordinates, inject `{\an5\pos(X,Y)}` into the subtitle dialogue text or convert the subtitle file to `.ass` with explicit `PlayResX` and `PlayResY` matching the video resolution.

### 3. Configure Typography, Outline, Shadow, and Background Box

Choose the appropriate `BorderStyle` based on whether the user wants a character outline or a rectangular background box:

#### Mode A: Character Outline and Drop Shadow (BorderStyle=1, Default)

- `Fontname=<Name>`: Font family name (e.g., Arial, Roboto, Montserrat). If loading from a local folder, pass `:fontsdir='/path/to/fonts'` to the subtitles filter.
- `Fontsize=<Number>`: Font size in virtual ASS units (for `.srt` default 384x288 canvas, 16-24 is standard; if original_size=1920x1080 is not scaled, remember force_style operates on PlayResY=288 for SRT files).
- `Bold=1` / `Bold=0`: Enable (1 or -1) or disable (0) bold weight.
- `Italic=1` / `Italic=0`: Enable (1) or disable (0) italic style.
- `PrimaryColour=&HAABBGGRR`: Main text color.
- `OutlineColour=&HAABBGGRR`: Border/stroke color around each character.
- `BackColour=&HAABBGGRR`: Drop shadow color.
- `BorderStyle=1`: Character stroke + shadow mode.
- `Outline=<0-4>`: Width of the character border (0 disables border).
- `Shadow=<0-4>`: Distance of the drop shadow (0 disables shadow).
- `Spacing=<Number>`: Extra horizontal spacing between characters.

#### Mode B: Rectangular Background Box (BorderStyle=3 or BorderStyle=4)

When the user requests a solid or semi-transparent background box behind the subtitle text:

- Set `BorderStyle=3` (opaque/semi-transparent box per line) or `BorderStyle=4` (single merged box across multi-line subtitles in supported libass versions).
- Set `OutlineColour=&HAABBGGRR` to the desired background box color and opacity (e.g., `&H80000000` for a 50% black background box). In libass, `OutlineColour` controls the box fill when `BorderStyle=3`.
- Set `Outline=<Number>` to control the box padding around the text (e.g., `Outline=4` adds 4 units of padding around the text inside the box).
- Set `Shadow=0` (and `BackColour=&HFF000000`) to prevent a secondary offset box shadow from rendering behind the background box, unless a shadowed box is explicitly desired.

### 4. Construct and Validate the FFmpeg Command

Assemble the FFmpeg filter string with proper quoting and escaping:

```bash
ffmpeg -i input.mp4 -vf "subtitles='subtitles.srt':charenc=UTF-8:force_style='Fontname=Roboto,Fontsize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,BorderStyle=1,Outline=2,Shadow=1,Alignment=2,MarginL=20,MarginR=20,MarginV=25'" -c:v libx264 -crf 18 -preset fast -c:a copy output.mp4
```

#### Common Preset Examples

- **Bottom-Left Aligned with Yellow Text and Black Stroke:**
  ```bash
  ffmpeg -i input.mp4 -vf "subtitles='sub.srt':force_style='Fontname=Arial,Fontsize=20,Bold=1,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Shadow=0,Alignment=1,MarginL=30,MarginV=25'" -c:a copy output.mp4
  ```

- **Bottom-Right Aligned with Semi-Transparent Black Background Box:**
  ```bash
  ffmpeg -i input.mp4 -vf "subtitles='sub.srt':force_style='Fontname=Arial,Fontsize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H66000000,BackColour=&HFF000000,BorderStyle=3,Outline=5,Shadow=0,Alignment=3,MarginR=30,MarginV=25'" -c:a copy output.mp4
  ```

- **Custom Font File Directory + Top-Center Subtitle:**
  ```bash
  ffmpeg -i input.mp4 -vf "subtitles='sub.srt':fontsdir='./fonts':force_style='Fontname=Montserrat,Fontsize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=2,Alignment=8,MarginV=20'" -c:a copy output.mp4
  ```

### 5. Verify Subtitle Rendering (When Running in a Terminal/VM)

When executing FFmpeg to burn subtitles, extract a single test frame at a timestamp where dialogue occurs to verify alignment, font rendering, and colors before encoding the full video:

```bash
ffmpeg -y -ss 00:00:05 -i input.mp4 -vf "subtitles='sub.srt':force_style='...'" -frames:v 1 preview_frame.png
```

## Gotchas

- **RGB vs BGR Color Inversion**: Writing `&H00FF0000` thinking it is Red will render Blue subtitles. Always swap RR and BB (`#RRGGBB` -> `&H00BBGGRR`).
- **Inverted Alpha Channel**: In ASS hex `&HAABBGGRR`, `00` is fully opaque and `FF` is invisible. Setting `&HFF...` makes the text or border disappear completely.
- **Background Box Color Uses OutlineColour**: With `BorderStyle=3`, libass uses `OutlineColour` for the background box fill and `Outline` for box padding. Leaving `Shadow > 0` with `BorderStyle=3` creates an unwanted duplicate offset box behind the background box; always set `Shadow=0` unless a double-box effect is requested.
- **SRT Virtual Canvas Scaling (PlayResY=288)**: When passing `.srt` or `.vtt` to `-vf subtitles`, FFmpeg converts it internally to ASS with a default virtual resolution of 384x288. Therefore, `Fontsize=20` and `MarginV=20` are scaled relative to 288p (equivalent to ~75px on a 1080p video). Do not set `Fontsize=60` on an `.srt` file via `force_style` or the text will fill the entire screen.
- **Path Escaping in FFmpeg Filtergraphs**: Colon (`:`), backslash (`\`), and single quote (`'`) characters inside file paths must be escaped inside `-vf subtitles=...` (e.g., on Windows `subtitles='C\:\\path\\to\\sub.srt'`). Prefer relative paths without special characters when possible.
- **Audio Stream Handling**: Adding `-vf subtitles=...` re-encodes the video stream, but audio does not need re-encoding. Pass `-c:a copy` to preserve original audio quality and speed up rendering.

