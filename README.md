# iQIYI / Youku Việt hóa

Công cụ Việt hóa giao diện và phụ đề cho ứng dụng desktop iQIYI và Youku trên
Windows, gồm hai phần độc lập:

- **Việt hóa giao diện** — patch tài nguyên hiển thị của client đã cài
  (`apply-vi.py`) và tiêm bản dịch vào WebView2, không đụng tới file đã ký.
- **Phụ đề AI** — app quản lý cục bộ tại `http://127.0.0.1:18766/`, tải phụ đề
  gốc theo quyền tài khoản, dịch bằng endpoint chat-completions tương thích
  OpenAI, rồi đưa bản dịch vào player.

> Dự án không phân phối phụ đề, bản dịch thương mại hay bản sao tài nguyên của
> iQIYI/Youku. Mọi dữ liệu đó được tạo tại máy người dùng khi chạy.

## Yêu cầu

- Windows 10/11 (dùng WebView2 và registry của client iQIYI).
- Python 3.10+ (đã kiểm thử với 3.12) và Node.js 18+ cho các test JS.
- Đã cài ứng dụng iQIYI desktop (và/hoặc Youku) nếu muốn Việt hóa giao diện.
- Một API key cho endpoint tương thích OpenAI.

## Cài đặt

```cmd
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env      # rồi điền khoá API vào .env
```

Khoá API được đọc theo host của endpoint đã cấu hình
(`GEMINI_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`),
hoặc `AI_API_KEY` cho endpoint bất kỳ.

## Chạy

```cmd
.\.venv\Scripts\python.exe launcher.py iqiyi    # mở iQIYI kèm app phụ đề
.\.venv\Scripts\python.exe launcher.py youku    # mở Youku kèm Việt hóa
.\.venv\Scripts\python.exe launcher.py manager  # chỉ mở app quản lý phụ đề
.\.venv\Scripts\python.exe launcher.py restore  # khôi phục giao diện gốc
```

App quản lý chạy nền và phục vụ giao diện tại `http://127.0.0.1:18766/`.
Hai nút **Việt hóa iQIYI** / **Khôi phục tiếng Trung** gọi `apply-vi.py`;
launcher xin quyền Administrator qua hộp thoại UAC khi cần ghi vào thư mục cài
đặt. Mọi lệnh chạy trực tiếp bằng Python, không cần PowerShell hay batch.

## Kiểm thử

```cmd
.\.venv\Scripts\python.exe -m unittest test_install_subtitles test_iqiyi_runtime test_subtitle_watchers test_quality_metrics test_tian_geng_ji_benchmark -v
node test-iqiyi-runtime.js
node test-youku-subtitle.js
```

Ba lệnh trên là toàn bộ bộ kiểm thử; chúng chạy offline và không cần dữ liệu
phim thật.

## Cấu trúc

| Đường dẫn | Vai trò |
| --- | --- |
| `launcher.py` | Khởi chạy iQIYI, Youku, app phụ đề và khôi phục giao diện |
| `windows_runtime.py` | UAC và quản lý tiến trình qua Windows API |
| `subtitle_app.py` | Server quản lý phụ đề, API, UI và luồng dịch |
| `subtitle_agent.py` | Prompt, schema và bộ chuẩn hoá kết quả của model |
| `apply-vi.py` | Patch / khôi phục tài nguyên giao diện đã cài |
| `iqiyi_common.py` | Tiện ích dùng chung (token API, tiêm script) |
| `watch-players.py` | Watcher chung cho iQIYI và Youku; tự chọn nhánh theo tham số khởi chạy |
| `cdp.py` | Giao tiếp WebSocket với Chrome DevTools Protocol |
| `ui-engine.js`, `youku-ui.js`, `youku-subtitle.js`, `sub-hook.js` | Hook giao diện và phụ đề trong trang |
| `quality_metrics.py`, `audit_*.py`, `verify-vietnamese.py` | Đo chất lượng bản dịch |
| `ext/` | Tiện ích Chrome (manifest v3) dịch giao diện web |

## Dữ liệu và cấu hình cục bộ

Những đường dẫn sau **không** được commit:

| Đường dẫn | Nội dung |
| --- | --- |
| `.env` | Khoá API |
| `.ai-settings.json` | Nhà cung cấp và model đã chọn trong UI |
| `.iqiyi-vi-token` | Token xác thực API cục bộ |
| `subtitles/library/` | Phụ đề gốc + bản dịch, tạo khi chạy |
| `backup-skin/`, `backup-lwa/` | Bản sao tài nguyên gốc client ghi khi patch |
| `.local/` | Bản dịch/override dùng khi phát triển |

`backup-skin/` và `backup-lwa/` là thứ `launcher.py restore` dựa vào — đừng xoá nếu
còn muốn khôi phục giao diện gốc.

## Giấy phép

Chỉ dùng cho mục đích cá nhân. Tác giả không liên kết với iQIYI hay Youku;
việc dùng công cụ phải tuân thủ điều khoản dịch vụ của các nền tảng đó.
