# iQIYI / Youku Việt hóa

Việt hóa giao diện và hỗ trợ phụ đề tiếng Việt cho iQIYI / Youku trên Windows.

- Giao diện dùng bản dịch có sẵn, ưu tiên hiện tiếng Việt ngay khi mở trang.
- Lấy phụ đề Việt từ iq.com hoặc dịch phụ đề bằng AI khi bạn chọn.
- Quản lý phim, tập và phụ đề tại [trang quản lý](http://127.0.0.1:18766/).

## Bản desktop webapp cho Windows

Giải nén toàn bộ gói `IQIYI-VI-Windows-x64.zip` vào thư mục có quyền ghi, rồi
mở **IQIYI-VI.exe**. Bản này kèm Python và các thư viện cần thiết; không cần
cài Python hay chạy terminal. Cần Windows 10/11 x64 và Edge hoặc Chrome.
Giao diện mở trong cửa sổ app riêng; nếu không tìm thấy Edge/Chrome, app dùng
trình duyệt mặc định. Extension cần được cài trong cùng hồ sơ trình duyệt mở webapp.

Phụ đề, cài đặt, token và bản sao lưu được lưu cạnh file `.exe`. Gói tải về
không chứa thư viện phim, khóa API hay phiên đăng nhập của người tạo bản build.
Không đặt app trong `Program Files` hoặc chạy trực tiếp từ trong file ZIP.

Đóng cửa sổ vẫn giữ dịch vụ phụ đề chạy để phục vụ player và các lượt dịch.
Các lệnh tùy chọn khi cần mở player hoặc dừng dịch vụ:

```powershell
.\IQIYI-VI.exe iqiyi    # Mở iQIYI cùng webapp
.\IQIYI-VI.exe youku    # Mở Youku cùng webapp
.\IQIYI-VI.exe restore  # Khôi phục giao diện gốc
.\IQIYI-VI.exe stop     # Dừng dịch vụ khi không còn xử lý phụ đề
```

Chỉ chạy một bản quản lý tại một thời điểm vì player dùng cổng `18766`.
Nếu đang dùng bản mã nguồn, chờ các lượt dịch xong và dừng dịch vụ cũ trước
khi chuyển sang bản portable. Dữ liệu cũ không được tự động di chuyển.
Muốn giữ thư viện/cài đặt, sao lưu rồi chép `subtitles/library/`, `.ai-settings.json`,
`.env`, `.local/`, `backup-skin/`, `backup-lwa/`, `backup-ppstream.ini` và
`.iqiyi-install-location` từ bản cũ sang bản mới khi cả hai dịch vụ đã dừng.
Giữ bản sao lưu giao diện để thao tác khôi phục tiếp tục hoạt động.

Để tự build trên Windows bằng CPython x64 đã có pip:

```powershell
python build-desktop.py
```

Kết quả nằm trong `dist/IQIYI-VI-Windows-x64/` và file ZIP cạnh thư mục này.
Script từ chối ghi đè thư mục đã có để bảo vệ dữ liệu; dùng `--output` để chọn
tên khác. Chạy `IQIYI-VI.exe --check` để kiểm tra gói mà không mở player hoặc
thư viện. Build dùng compiler .NET Framework có sẵn trên Windows và chỉ lấy
các file nguồn được liệt kê rõ ràng, không gom dữ liệu cá nhân của workspace.

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

Mở iQIYI qua launcher để bộ Việt hóa được gắn trước khi trang bắt đầu chạy.
Mở trực tiếp QyClient có thể làm giao diện gốc xuất hiện trước khi watchdog kết nối.
Ô tìm kiếm hỗ trợ tên phim Việt có dấu hoặc không dấu. Bộ Việt hóa đối chiếu tên
đã biết và danh mục iq.com; chỉ đổi sang tên gốc khi khớp duy nhất một phim.
Nhập một phần tên hoặc tên gõ sai nhẹ rồi bấm Tìm/Enter để xem tối đa 5 gợi ý.
Chọn phim trong danh sách để tìm bằng tên gốc đã xác minh. Nếu không có gợi ý,
từ khóa được tìm như bạn nhập; kết quả gần đúng không tự chọn thay bạn.

Tên phim/diễn viên đang tra tên Việt sẽ tạm ẩn; nếu danh mục chưa có tên Việt,
tên gốc được hiện lại để thẻ phim luôn có tên.

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

Khi chuyển sang máy khác, dùng phiên đăng nhập iq.com của máy đó và tải tiện ích
từ thư mục `ext/` cạnh app đang chạy. Mở app quản lý trước để tạo cấu hình kết nối,
rồi tải lại tiện ích và bấm **Kiểm tra iq.com** trong cùng hồ sơ trình duyệt.
Tên phim công khai không cần đăng nhập; phụ đề phụ thuộc quyền xem tập và khu vực.
Nếu iq.com trả trạng thái 110 mà không có phụ đề Việt, kiểm tra đăng nhập và quyền
xem tập trên iq.com. Xóa cache không thay thế bước đăng nhập.

Chrome/Edge mới: dùng tiện ích từ bản 1.2.37 trở lên. Các yêu cầu tên phim và
phụ đề được gửi qua service worker của tiện ích bằng quyền host có sẵn.
Sau khi cập nhật, mở lại app quản lý, bấm **Tải lại** tiện ích trong trang
quản lý tiện ích của Chrome/Edge, rồi tải lại trang iQIYI. Khi đổi trình duyệt,
mở trang quản lý phụ đề trong trình duyệt mới và bấm **Kiểm tra iq.com** để chọn
đúng phiên đăng nhập của trình duyệt đó.

## Quy tắc dịch AI

Agent lập hồ sơ và tầng dịch dùng [quy tắc chung Trung–Việt](TRANSLATION-RULES.md):
phân biệt tên, danh xưng và số hiệu; xưng hô theo từng chiều và phạm vi cảnh;
giữ bằng chứng qua các tập. Sau khi cập nhật mã, mở lại app quản lý để nạp
prompt mới. Quy tắc áp dụng cho câu dịch mới/còn thiếu; bản dịch hoàn tất
không tự bị thay thế.

Prompt hồ sơ và prompt dịch dùng chung một bộ quy tắc, tránh lặp chỉ dẫn.
Mặc định chia lô cố định 80 câu (`AI_BATCH_SIZE`), 3 lô song song; app không
tự giảm số câu vì giới hạn context hay đầu ra. Tổng request có trần 24.000 ký tự JSON (`AI_INPUT_CHARS`),
gồm cả system, schema và hồ sơ. Mỗi lô chỉ lấy hồ sơ liên quan, tối đa 6.000
ký tự, cùng tối đa 24 cue trước và 24 cue sau; JSON lời thoại mặc định tối đa
8.000 ký tự. Các số này là giới hạn ký tự, không phải số token của model.
Mỗi lô xong được lưu ngay. Khi đầu ra thiếu, sai JSON
hoặc bị cắt, app chỉ thử lại toàn bộ câu còn thiếu trong lô, tối đa 3 lượt.
App có thể bỏ bớt ngữ cảnh phụ; nếu vẫn không vừa, app báo chỉnh cấu hình
và giữ các câu đã lưu. Có thể chọn **Dịch tiếp** nếu còn câu chưa hợp lệ. Timeout mỗi
yêu cầu AI mặc định 180 giây, đổi bằng `AI_REQUEST_TIMEOUT` nếu cần.

## Lưu ý

- Nội dung chưa có bản dịch giữ nguyên tên gốc. Tên phim/diễn viên có thể tạm ẩn trong lúc chờ bản Việt.
- Sau khi cập nhật, tải lại tiện ích và trang web; mở lại ứng dụng bằng launcher. Chờ dịch xong trước khi khởi động lại app quản lý.
- Nút **Proxy** trong app quản lý áp dụng cho player iQIYI. Đổi proxy sẽ mở lại iQIYI và có thể ngắt video đang xem; giữ app quản lý chạy khi dùng proxy.
- Giữ `backup-skin/` và `backup-lwa/` để có thể khôi phục giao diện gốc.
- Không chia sẻ `.env`, `.iqiyi-vi-token`, `ext/proxy-token.json` hoặc `.local/` vì có thể chứa khóa API và phiên đăng nhập. Phụ đề được lưu tại `subtitles/library/`.

Dự án dành cho mục đích cá nhân, không liên kết với iQIYI / Youku và không phân phối
phụ đề hay tài nguyên thương mại. Sử dụng theo điều khoản của từng nền tảng.
