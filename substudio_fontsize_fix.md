# Prompt xử lý lỗi lệch kích thước chữ (Font Size Scaling) tiếng Khmer (`Kantumruy Pro`) trong SubStudio

Thực hiện tuần tự các bước sửa đổi mã nguồn dưới đây trong dự án `/home/vtechdev/substudio`. Chỉ thực thi thay đổi code, không thêm bình luận giải thích dài dòng.

---

## Bước 1: Chuẩn hóa file Font `Kantumruy Pro` (Static TTF) và cấu hình ngôn ngữ

1. Kiểm tra thư mục chứa font của Backend (tạo mới `/home/vtechdev/substudio/backend/assets/fonts` nếu chưa tồn tại).
2. Đảm bảo sử dụng các file **Static TTF** (`KantumruyPro-Regular.ttf`, `KantumruyPro-Bold.ttf`, `KantumruyPro-Medium.ttf`, `KantumruyPro-SemiBold.ttf`) từ bộ [Kantumruy Pro](https://github.com/anagata-design/kantumruy-pro). Xóa hoặc không sử dụng file Variable Font (`KantumruyPro[wght].ttf` / `KantumruyPro-VariableFont_wght.ttf`) trong thư mục font của FFmpeg.
3. Mở file `/home/vtechdev/substudio/backend/app/pipeline/languages.py` và `/home/vtechdev/substudio/web/src/components/SubtitleConfigCard.tsx`:
   - Đặt tên font mặc định cho ngôn ngữ Khmer (`km`) thống nhất ở cả Frontend và Backend là `"Kantumruy Pro"` (viết đúng dấu cách chuẩn theo bảng `name` của OpenType).

---

## Bước 2: Sửa công thức `previewScale` trên Frontend (`SubtitleConfigCard.tsx`)

Mở file `/home/vtechdev/substudio/web/src/components/SubtitleConfigCard.tsx` (tại khoảng dòng `L551 - L559`) và thay thế đoạn tính `previewScale` bằng `Math.min` giữa tỷ lệ chiều rộng và chiều cao thực của video:

```typescript
const previewScale =
  containerSize.width > 0 &&
  containerSize.height > 0 &&
  refVideoWidth > 0 &&
  refVideoHeight > 0
    ? Math.min(
        containerSize.width / refVideoWidth,
        containerSize.height / refVideoHeight
      )
    : containerSize.height > 0 && refVideoHeight > 0
    ? containerSize.height / refVideoHeight
    : containerSize.width > 0 && refVideoWidth > 0
    ? containerSize.width / refVideoWidth
    : 0.333;

const renderedFontSize = Math.max(9, Math.round(cfg.font_size * previewScale));
```

---

## Bước 3: Sửa hàm đo độ rộng ký tự Khmer `char_width` (`subtitles.py`)

Mở file `/home/vtechdev/substudio/backend/app/pipeline/subtitles.py` (tại khoảng dòng `L83 - L103`):

1. Khai báo tập hợp mã Unicode của các nguyên âm trên/dưới và dấu tiếng Khmer có độ rộng ngang bằng `0`:
```python
KHMER_ZERO_WIDTH_CODES = (
    set(range(0x17B7, 0x17BE))
    | {0x17C6}
    | set(range(0x17C9, 0x17D4))
    | {0x17DD}
)
```
2. Cập nhật hàm `char_width` và vòng lặp tính độ rộng chuỗi trong `wrap_text_for_ass` để bỏ qua độ rộng của phụ âm chân đứng ngay sau dấu `COENG` (`\u17D2`):
```python
def char_width(ch: str, font_size: float, prev_ch: str = "") -> float:
    if unicodedata.combining(ch) > 0:
        return 0.0
    code = ord(ch)
    if 0x1780 <= code <= 0x17FF:
        if prev_ch == "\u17D2" or code in KHMER_ZERO_WIDTH_CODES:
            return 0.0
        return font_size * 0.58
    w = unicodedata.east_asian_width(ch)
    if w in ("F", "W"):
        return font_size * 0.95
    if 0x0E80 <= code <= 0x0EFF:
        return font_size * 0.56
    if 0x0E00 <= code <= 0x0E7F:
        return font_size * 0.56
    if 0x1000 <= code <= 0x109F:
        return font_size * 0.58
    if ch in "ijlI1.,:;!'\"| ":
        return font_size * 0.28
    if ch in "mwMW@%#&":
        return font_size * 0.78
    return font_size * 0.52
```
3. Tại mọi vị trí gọi `char_width` trong `subtitles.py`, truyền thêm ký tự liền trước `prev_ch` (nếu duyệt theo cụm hoặc chuỗi).

---

## Bước 4: Tách `logical_fontsize` và `ass_fontsize` theo hệ số `OS/2` trong `subtitles.py`

Trong file `/home/vtechdev/substudio/backend/app/pipeline/subtitles.py` (tại khoảng dòng `L223 - L330`), thực hiện:

1. Thêm hàm tính hệ số bù kích thước chữ cho `libass` (`(usWinAscent + usWinDescent) / unitsPerEm` theo đặc tả [libass Issue #644](https://github.com/libass/libass/issues/644)):
```python
from pathlib import Path

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
```

2. Tại phần xử lý kích thước chữ (`L230`), tách biệt `logical_fontsize` (dùng cho thuật toán ngắt dòng và hộp Mask) với `ass_fontsize` (dùng để ghi vào dòng `Style:` của ASS):
```python
logical_fontsize = max(12, int(cfg.get("font_size") or 50))
metric_scale, extra_descent_ratio = get_ass_font_metrics(font_name, fonts_dir)

# Kích thước ghi vào [V4+ Styles] của ASS để libass render đúng bằng kích thước EM trên Canvas
ass_fontsize = max(12, round(logical_fontsize * metric_scale))

# Bù trừ khoảng đệm đáy của usWinDescent để vị trí dòng chữ khớp với Canvas
raw_margin_v = int(cfg.get("margin_v") or 40)
ass_margin_v = max(0, round(raw_margin_v - logical_fontsize * extra_descent_ratio))
```

3. Cập nhật việc sử dụng biến trong `subtitles.py`:
   - **Dòng `Style: Default,...`**: Sử dụng `ass_fontsize` và `ass_margin_v`.
   - **Hàm `wrap_text_for_ass(...)`**: Giữ nguyên truyền `logical_fontsize`.
   - **Tính toán kích thước hộp làm mờ (`Mask`)**: Giữ nguyên công thức với `logical_fontsize` và `raw_margin_v`:
     ```python
     line_height = int(logical_fontsize * 1.3)
     h = line_height * num_lines + extra_spacing + round(logical_fontsize * 0.4)
     y2 = playres_y - raw_margin_v + round(logical_fontsize * 0.1)
     y1 = y2 - h
     ```
   - **Thẻ ngắt dòng `line_break_tag` (`L313 - L317`)**: Thay `{\r}` bằng khôi phục rõ ràng `{\fs{ass_fontsize}\alpha&H00&}`:
     ```python
     line_break_tag = (
         f"\\N{{\\fs{line_spacing}\\alpha&HFF&}}\\h\\N{{\\fs{ass_fontsize}\\alpha&H00&}}"
         if line_spacing > 0
         else r"\N"
     )
     ```

---

## Bước 5: Truyền `fontsdir` vào lệnh FFmpeg trong `media.py`

Mở file `/home/vtechdev/substudio/backend/app/pipeline/media.py` (tại khoảng dòng `L355 - L378`):

1. Escape đường dẫn thư mục chứa font (`fonts_dir`) theo chuẩn filtergraph của FFmpeg (thay `\` bằng `/`, escape `:` thành `\:` và `'` thành `\'`) ([FFmpeg Filters Documentation](https://ayosec.github.io/ffmpeg-filters-docs/8.0/Filters/Video/subtitles.html)).
2. Sửa chuỗi bộ lọc `-vf` từ:
   ```python
   f"ass='{ass_path_escaped}':shaping=complex"
   ```
   thành:
   ```python
   f"ass='{ass_path_escaped}':fontsdir='{fonts_dir_escaped}':shaping=complex"
   ```

---

## Bước 6: Kiểm tra và xác nhận kết quả

1. Chạy script kiểm tra hệ số metric của font `Kantumruy Pro` trong môi trường backend:
   ```bash
   python3 -c "from app.pipeline.subtitles import get_ass_font_metrics; from pathlib import Path; print(get_ass_font_metrics('Kantumruy Pro', Path('backend/assets/fonts')))"
   ```
2. Tạo một file `.ass` thử nghiệm với câu tiếng Khmer (font `Kantumruy Pro`, `font_size = 50` trên video `1920x1080`), kiểm tra dòng `Style: Default,Kantumruy Pro,<ass_fontsize>,...` trong file `.ass` đã được nhân hệ số bù (~`108`).
3. Xuất thử 1 frame hình bằng FFmpeg để xác nhận `libass` load đúng `Kantumruy Pro` từ `fontsdir` và không xuất hiện cảnh báo `fontconfig` fallback:
   ```bash
   ffmpeg -y -ss 00:00:02 -i test_input.mp4 -vf "ass='test.ass':fontsdir='backend/assets/fonts':shaping=complex" -frames:v 1 preview_check.png
   ```
