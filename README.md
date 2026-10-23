# iQIYI / Youku Việt hóa

Việt hóa giao diện và hỗ trợ phụ đề tiếng Việt cho iQIYI / Youku trên Windows.

- Giao diện dùng bản dịch có sẵn, ưu tiên hiện tiếng Việt ngay khi mở trang.
- Lấy phụ đề Việt từ iq.com hoặc dịch phụ đề bằng AI khi bạn chọn.
- Quản lý phim, tập và phụ đề tại [trang quản lý](http://127.0.0.1:18766/).

## Yêu cầu

- Windows 10/11, Python 3.10 trở lên.
- Đã cài iQIYI desktop hoặc Youku.
- API key nếu muốn dịch phụ đề bằng AI.

## Cài đặt

Mở terminal trong thư mục dự án và chạy:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Chỉ tạo `.env` ở lần cài đầu. Điền API key vào file này nếu dùng dịch AI:
`GEMINI_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `OPENROUTER_API_KEY`
hoặc `AI_API_KEY`. Chọn nhà cung cấp và model trong app quản lý.

## Sử dụng

Mở iQIYI và app quản lý phụ đề:

```powershell
.\.venv\Scripts\python.exe launcher.py iqiyi
```

Thay `iqiyi` bằng:

- `youku`: mở Youku.
- `open-manager`: chỉ mở app quản lý phụ đề.
- `restore`: khôi phục giao diện iQIYI gốc.

Trong app quản lý, vào **Thông báo** và chọn **Chấp nhận** để thêm phim mới
vào thư viện. Chọn tập hoặc phim cần dịch, rồi chọn phụ đề Việt trong player.

## Tiện ích Chrome / Edge

1. Mở `chrome://extensions` hoặc `edge://extensions`.
2. Bật **Chế độ dành cho nhà phát triển**.
3. Chọn **Tải tiện ích đã giải nén** và trỏ tới thư mục `ext/`.
4. Tải lại trang iQIYI để dùng giao diện và phụ đề Việt.

Để lấy phụ đề từ iq.com, đăng nhập iq.com trên trình duyệt đã cài tiện ích,
rồi bấm **Kiểm tra iq.com** trong app quản lý. Tài khoản cần có quyền xem tập đó;
không phải tập nào cũng có phụ đề Việt.

## Lưu ý

- Nội dung chưa có bản dịch giữ nguyên tên gốc. Tên phim/diễn viên có thể tạm ẩn trong lúc chờ bản Việt.
- Sau khi cập nhật, tải lại tiện ích và trang web; mở lại ứng dụng bằng launcher. Chờ dịch xong trước khi khởi động lại app quản lý.
- Nút **Proxy** trong app quản lý áp dụng cho player iQIYI. Đổi proxy sẽ mở lại iQIYI và có thể ngắt video đang xem; giữ app quản lý chạy khi dùng proxy.
- Giữ `backup-skin/` và `backup-lwa/` để có thể khôi phục giao diện gốc.
- Không chia sẻ `.env`, `.iqiyi-vi-token`, `ext/proxy-token.json` hoặc `.local/` vì có thể chứa khóa API và phiên đăng nhập. Phụ đề được lưu tại `subtitles/library/`.

Dự án dành cho mục đích cá nhân, không liên kết với iQIYI / Youku và không phân phối
phụ đề hay tài nguyên thương mại. Sử dụng theo điều khoản của từng nền tảng.
