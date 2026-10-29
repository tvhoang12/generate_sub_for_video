# SubStudio — phụ đề video tự động

Biên tập viên tải video lên, chọn ngôn ngữ, và nhận về mỗi ngôn ngữ một video đã gắn phụ đề, kèm file `.srt`.

```
Video ─► Tách âm thanh ─► Nhận dạng giọng nói ─► Soát lỗi bản gốc ─► Dịch ─► Gắn phụ đề ─► Tải về (.zip)
          (ffmpeg)          (FunASR, offline)       (Claude/OpenAI)   (Claude/OpenAI)  (ffmpeg)
```

- **Ngữ cảnh phim và bảng thuật ngữ** được lưu theo từng bộ phim và dùng cho mọi tập, nhờ đó tên nhân vật và cách xưng hô được dịch thống nhất.
- **Ghi chú cho từng tập**: biên tập viên thêm ghi chú lúc tải video lên.
- **AI đề xuất thuật ngữ mới** (tên riêng, địa danh) khi xử lý từng tập. Thuật ngữ đề xuất chỉ được dùng khi dịch sau khi biên tập viên duyệt.
- **Tự động hoàn toàn**: câu không nghe rõ sẽ bị bỏ khỏi video và liệt kê trong mục "Ghi chú từ AI". Bản dịch phải qua bước tự kiểm tra (đúng số dòng, đúng chữ của ngôn ngữ đích, không lẫn nhãn nội bộ). Nếu kiểm tra không đạt, hệ thống tự dịch lại tối đa 3 lần.

## Cài đặt (Windows)

Cần có: Python 3.12, Node 20+ và ffmpeg nằm trong PATH.

```powershell
# 1. Backend
py -3.12 -m venv backend\.venv
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

# 2. whisper.cpp và mô hình (~575 MB, chỉ tải một lần)
backend\.venv\Scripts\python.exe scripts\setup_tools.py

# 3. Cấu hình
copy .env.example .env   # rồi điền ANTHROPIC_API_KEY hoặc OPENAI_API_KEY

# 4. Chạy (tự build giao diện ở lần đầu)
.\start.ps1
```

Mở `http://localhost:8000`. Máy khác trong mạng nội bộ truy cập qua `http://<IP-máy-này>:8000`.

## Cấu hình chính (`.env`)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `TRANSLATOR_PROVIDER` | `gemini` | `gemini`, `claude`, `openai`, hoặc `mock` (bản dịch giả, chỉ để thử) |
| `GEMINI_API_KEY` | *(trống)* | API key cho Google Gemini |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Model Gemini (Gemini Flash Lite dịch theo ngữ cảnh, kiểm tra lỗi đồng âm tiếng Trung) |
| `OPENAI_API_KEY` | *(trống)* | API key cho OpenAI |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model OpenAI (`gpt-4o-mini`: nhanh, rẻ; `gpt-4o`: văn phong dịch cao cấp nhất) |
| `FUNASR_THREADS` | số nhân CPU | Số luồng dùng cho nhận dạng giọng nói |
| `MAX_CUE_SECONDS` | `7` | Thời gian tối đa một dòng phụ đề hiện trên màn hình |
| `VIDEO_CRF` | `20` | Chất lượng video xuất ra (số nhỏ hơn: đẹp hơn, file nặng hơn) |

## Hiệu năng đo được

Trên máy 8 nhân CPU, card GT 1030, với một tập phim 2 phút 36 giây:
- Nhận dạng giọng nói mất khoảng 40 giây.
- Gắn phụ đề mất khoảng 50 giây cho mỗi ngôn ngữ.
- Thời gian dịch phụ thuộc API.

Hệ thống xử lý lần lượt từng video. Video tải lên sau sẽ chờ trong hàng đợi.

## Phát triển

```powershell
cd backend; .venv\Scripts\python.exe -m pytest -q       # có một test chạy trọn luồng thật trên 20 giây video mẫu
cd web; npm run dev                                       # giao diện ở :5173, chuyển tiếp /api sang :8000
```

- Backend: `backend/app`.
  - `pipeline/`: ffmpeg, funasr, xử lý mốc thời gian, hàng đợi.
  - `translation/`: prompt, các bộ dịch, bước kiểm tra kết quả.
- Giao diện: `web/src`. Hệ thống thiết kế (ui-ux-pro-max) nằm ở `design-system/substudio/MASTER.md`.
- Dữ liệu: `data/`, gồm SQLite và mỗi job một thư mục `jobs/<id>/{input,work,out}`.

## Giới hạn hiện tại

- Chưa có đăng nhập. Chỉ nên chạy trong mạng nội bộ.
- Chưa đọc được phụ đề in cứng trên hình (OCR) và chưa tách giọng nói khỏi nhạc nền.
- Style phụ đề đang cố định: chữ trắng viền đen, đặt giữa phía dưới màn hình.
