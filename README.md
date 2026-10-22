# SubStudio — phụ đề video tự động

Biên tập viên tải video lên, chọn ngôn ngữ, và nhận về mỗi ngôn ngữ một video đã gắn phụ đề, kèm file `.srt`.

```
Video ─► Tách âm thanh ─► Nhận dạng giọng nói ─► Soát lỗi bản gốc ─► Dịch ─► Gắn phụ đề ─► Tải về (.zip)
          (ffmpeg)          (whisper.cpp, offline)   (Claude/OpenAI)   (Claude/OpenAI)  (ffmpeg)
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

## Triển khai bằng Docker (server nội bộ)

Hiện tool đang chạy trên `192.168.1.101` ở thư mục `~/substudio`, địa chỉ **http://192.168.1.101:8000**.

```bash
# Trên server, trong thư mục chứa Dockerfile, docker-compose.yml và .env:
docker compose up -d --build     # lần đầu ~6 phút: biên dịch whisper.cpp và tải mô hình
docker compose logs -f           # xem log
docker compose restart           # sau khi sửa .env
```

- **Nơi lưu dữ liệu:** thư mục `./data` trên server, gồm SQLite và video của các job. Đây là thư mục cần sao lưu.
- **Build trên chính server:** `WHISPER_NATIVE=ON` biên dịch whisper theo đúng CPU của máy chạy lệnh build. Server hiện tại là máy ảo VMware, chỉ thấy AVX/FMA chứ không thấy AVX2, nên **không dùng lại image build trên máy khác**. Nếu bắt buộc phải build ở nơi khác, đặt `WHISPER_NATIVE=OFF` và chỉnh `WHISPER_CPU_FLAGS`.
- **Chỉ chạy 1 worker uvicorn**, vì hàng đợi job nằm trong tiến trình.

## Cấu hình chính (`.env`)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `TRANSLATOR_PROVIDER` | `claude` | `claude`, `openai`, hoặc `mock` (bản dịch giả, chỉ để thử) |
| `CLAUDE_MODEL` / `CLAUDE_EFFORT` | `claude-opus-5-5` / `medium` | Model Claude và mức độ suy nghĩ |
| `OPENAI_MODEL` | `gpt-5` | Model OpenAI |
| `WHISPER_THREADS` | số nhân CPU | Số luồng dùng cho nhận dạng giọng nói |
| `MAX_CUE_SECONDS` | `7` | Thời gian tối đa một dòng phụ đề hiện trên màn hình |
| `VIDEO_CRF` | `20` | Chất lượng video xuất ra (số nhỏ hơn: đẹp hơn, file nặng hơn) |

## Hiệu năng đo được

Trên máy 8 nhân CPU, card GT 1030, với một tập phim 2 phút 36 giây:
- Nhận dạng giọng nói mất khoảng 40 giây.
- Gắn phụ đề mất khoảng 50 giây cho mỗi ngôn ngữ.
- Thời gian dịch phụ thuộc API.

Trên server 192.168.1.101 (4 nhân Xeon E5-2620 v4, không có AVX2), với một đoạn 45 giây ra 3 ngôn ngữ, tổng cộng khoảng 4.5 phút:
- Nhận dạng giọng nói: ~2 phút.
- Soát lỗi và dịch bằng Claude: ~1 phút.
- Gắn phụ đề cho 3 video: ~1.5 phút.

Hệ thống xử lý lần lượt từng video. Video tải lên sau sẽ chờ trong hàng đợi.

## Phát triển

```powershell
cd backend; .venv\Scripts\python.exe -m pytest -q       # có một test chạy trọn luồng thật trên 20 giây video mẫu
cd web; npm run dev                                       # giao diện ở :5173, chuyển tiếp /api sang :8000
```

- Backend: `backend/app`.
  - `pipeline/`: ffmpeg, whisper, xử lý mốc thời gian, hàng đợi.
  - `translation/`: prompt, các bộ dịch, bước kiểm tra kết quả.
- Giao diện: `web/src`. Hệ thống thiết kế (ui-ux-pro-max) nằm ở `design-system/substudio/MASTER.md`.
- Dữ liệu: `data/`, gồm SQLite và mỗi job một thư mục `jobs/<id>/{input,work,out}`.

## Giới hạn hiện tại

- Chưa có đăng nhập. Chỉ nên chạy trong mạng nội bộ.
- Chưa đọc được phụ đề in cứng trên hình (OCR) và chưa tách giọng nói khỏi nhạc nền.
- Style phụ đề đang cố định: chữ trắng viền đen, đặt giữa phía dưới màn hình.
