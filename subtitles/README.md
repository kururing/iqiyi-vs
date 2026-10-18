# App phụ đề iQIYI và Youku

Chạy `start-iqiyi-vi.bat` hoặc `start-youku-vi.bat` để khởi động app quản lý tại `http://127.0.0.1:18766/`. Hai nút **Việt hóa iQIYI** và **Khôi phục tiếng Trung** gọi `apply-vi.py`; `restore-zh.bat` là phương án khôi phục độc lập.

App quản lý tải phụ đề gốc theo quyền tài khoản, lưu thư viện cục bộ, dịch bằng cấu hình model hiện có và đưa bản dịch vào player. Dữ liệu thư viện được tạo tại `subtitles/library/` khi chạy; thư mục này không chứa dữ liệu mẫu trong codebase. Cấu hình riêng của người dùng nằm trong `.env`, `.ai-settings.json` và `.iqiyi-vi-token`.

Các track phụ đề quốc tế và các đầu ra đối chiếu không được đóng gói trong codebase. Công cụ trong `subtitles/benchmarks/` chỉ chạy quy trình dữ liệu tương ứng khi người dùng tự cung cấp lại các track và snapshot cần thiết; `--self-test` của bộ so sánh dùng dữ liệu tổng hợp.

Kiểm tra offline:

```powershell
& .\.venv\Scripts\python.exe -m unittest test_install_subtitles test_iqiyi_runtime test_subtitle_watchers test_tian_geng_ji_benchmark -v
node test-iqiyi-runtime.js
```
