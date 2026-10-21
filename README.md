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
- Python 3.10+ (đã kiểm thử với 3.12).
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
| `ui-engine.js`, `sub-hook.js` | Engine giao diện chung và hook phụ đề; `sub-hook.js` chứa cả nhánh iQIYI lẫn Youku (kèm CSS riêng của Youku), tự chọn theo trang |
| `ext/` | Tiện ích Chrome (manifest v3) dịch giao diện web |

Trạng thái tài khoản trong app phụ đề hiển thị riêng **App** và **Web**. Để kiểm
tra phiên web, bật tiện ích `ext/` rồi mở trang iQIYI; không cần phát phim.
Khi cập nhật tiện ích, tải lại tiện ích và trang iQIYI để nạp hook mới.

Phim mới được nhận diện nằm trong **Thông báo** của trang quản lý. Chọn
**Chấp nhận** để thêm phim vào thư viện hoặc **Bỏ qua** để không báo lại phim đó.
Lựa chọn được lưu qua các lần mở app; phim đã có trong thư viện được giữ nguyên.
Thông tin nhận diện vẫn được lưu tạm để phục vụ player trong lúc chờ chấp nhận.

Nếu trước đó đã chọn **Tiếng Việt iq.com**, player tự nạp lại track này khi
phụ đề tải xong, kể cả khi lần tải đầu thất bại hoặc vừa chuyển tập.
Đổi sang ngôn ngữ khác hoặc tắt phụ đề trong lúc chờ sẽ hủy việc tự khôi phục.

Thông tin bộ phim và danh sách tập iq.com được dùng chung trong RAM tối đa
5 phút; nếu chưa thấy tập cần xem, app tra lại ngay. Metadata phát và URL phụ
đề vẫn được lấy mới theo từng tập. Trình đọc nền dùng ngay metadata có sẵn
trong trang khi có track Việt hợp lệ, không cần chờ thêm DASH.

Để dùng phiên VIP **iq.com** của trình duyệt hiện tại, bật tiện ích `ext/` rồi
bấm **Kiểm tra iq.com** trong app phụ đề. Tiện ích đọc cookie iq.com của chính
trình duyệt đó, kể cả cookie HttpOnly, và đồng bộ thẳng với server cục bộ.
Nút kiểm tra chọn trình duyệt/profile cung cấp phiên iq.com; lựa chọn này được
giữ qua lần khởi động sau. Chỉ nguồn đã chọn được tự đồng bộ đăng nhập/đăng xuất,
tránh browser hoặc profile khác ghi đè phiên VIP. Bấm kiểm tra ở trình duyệt khác
để chuyển nguồn. Tiện ích cần thêm quyền lưu định danh profile (`storage`).
Nút kiểm tra không mở tab/cửa sổ hoặc chuyển trang. Nếu chưa đăng nhập, đăng
nhập iq.com trong trình duyệt đang dùng rồi kiểm tra lại.

Phiên được chép vào hồ sơ riêng `.local/iqcom-browser/` để lấy phụ đề ở chế độ
nền và giữ cho lần chạy sau. Thay đổi đăng nhập/đăng xuất trong trình duyệt
được tiện ích đồng bộ lại. Hồ sơ này tách biệt với tài khoản `iqiyi.com`;
không chia sẻ hoặc commit thư mục hồ sơ. Cookie không được trả về trang quản lý.
Sau khi cập nhật, tải lại tiện ích (có thêm quyền cookie) và trang quản lý phụ đề.

Cần cài dependencies bằng `python -m pip install -r requirements.txt`. App ưu
tiên Edge hoặc Chrome đã cài trên Windows; nếu không có, chạy
`python -m playwright install chromium`. Khi iq.com yêu cầu xác minh hoặc đăng
nhập lại, thực hiện trên trình duyệt đang dùng rồi kiểm tra lại. Lưu phiên không kéo dài quyền VIP và
không bảo đảm mọi tập đều có phụ đề Việt. App phụ đề luôn lấy tên phim,
metadata và tải phụ đề trực tiếp, bỏ qua proxy trong app và proxy hệ thống.
Trình đọc iq.com nền cũng kết nối trực tiếp; đổi proxy player không ảnh hưởng
đến cache phụ đề hoặc phiên iq.com.

Nút **Proxy** trong app phụ đề cũng áp dụng cho trang và video iQIYI trên web
qua tiện ích `ext/` (Chrome/Edge 120+). Sau khi cập nhật, mở lại app phụ đề,
tải lại tiện ích và chấp nhận quyền proxy mới. Lưu proxy, chờ khoảng 30 giây
rồi tải lại trang iQIYI. Tiện ích hỗ trợ proxy HTTP có tài khoản/mật khẩu;
chỉ các tên miền iQIYI và CDN của iQIYI đi qua proxy. Tắt proxy trong app sẽ
gỡ cấu hình proxy của tiện ích ở lần đồng bộ tiếp theo. Nếu app tạm ngừng,
tiện ích giữ cấu hình và thông tin xác thực gần nhất khi worker nền khởi động lại
trong cùng phiên trình duyệt; sau khi khởi động lại toàn bộ trình duyệt, cần app
phụ đề đang chạy để đồng bộ lại thông tin xác thực. Tắt tiện ích để trả lại proxy trình duyệt.
Proxy trong app phụ đề được đặt lại khi khởi động app.

Khi lưu, đổi hoặc tắt proxy, app phụ đề tự mở lại iQIYI đang chạy để áp dụng
kết nối mới; video đang xem có thể bị gián đoạn. Không cần chạy launcher thủ công.
Nếu iQIYI đang đóng, dùng `python launcher.py iqiyi` để mở với cấu hình hiện tại.
Thay đổi proxy giữ nguyên app phụ đề và các tác vụ dịch đang chạy. Proxy desktop đi qua relay nội bộ
do app phụ đề quản lý để hỗ trợ tài khoản/mật khẩu; giữ app phụ đề chạy trong
khi xem. Tắt proxy sẽ ép WebView2 kết nối trực tiếp, kể cả khi Windows có proxy.

## Dữ liệu và cấu hình cục bộ

Những đường dẫn sau **không** được commit:

| Đường dẫn | Nội dung |
| --- | --- |
| `.env` | Khoá API |
| `.ai-settings.json` | Nhà cung cấp và model đã chọn trong UI |
| `.iqiyi-vi-token` | Token xác thực API cục bộ |
| `ext/proxy-token.json` | Token riêng cho tiện ích đồng bộ proxy, tự tạo khi mở app phụ đề |
| `subtitles/library/` | Phụ đề gốc + bản dịch, tạo khi chạy |
| `backup-skin/`, `backup-lwa/` | Bản sao tài nguyên gốc client ghi khi patch |
| `.local/` | Bản dịch/override dùng khi phát triển |

`backup-skin/` và `backup-lwa/` là thứ `launcher.py restore` dựa vào — đừng xoá nếu
còn muốn khôi phục giao diện gốc.

Từ điển Youku là tùy chọn: watcher tìm `youku-vi.json` ở thư mục dự án trước,
rồi đến `.local/youku-vi.json`. Khi chưa có từ điển, watcher vẫn nạp engine giao
diện và hook phụ đề.

Khi chưa có từ điển JSON riêng, installer iQIYI dùng từ điển đã đóng gói trong
`lwa-vi.js` để dịch skin native. Nếu cả hai nguồn đều thiếu hoặc không hợp lệ,
installer báo lỗi trước khi thay đổi client.

## Prompt và hồ sơ phim

Hồ sơ AI thiếu trường, tên Việt rỗng hoặc còn chữ Hán được yêu cầu viết lại;
nếu vẫn không hợp lệ, app giữ hồ sơ cũ. Các nhân vật và thuật ngữ bị model bỏ sót
được giữ khi cập nhật. Bản dịch phải có ID cụ thể, không ghép theo vị trí trả về.
Nếu file hồ sơ đã lưu bị hỏng, app báo lỗi và giữ nguyên file để sửa, tránh ghi
đè các thông tin còn đúng hoặc tên đã khóa trong đó.

`AI_CONTEXT_CHARS` và `AI_PROFILE_CONTEXT_CHARS` giới hạn số ký tự JSON của phần
lời thoại, không phải tổng token của request; system, metadata, hồ sơ và bản nháp
lân cận nằm ngoài giới hạn này. Lô dịch quá dài được tự chia nhỏ; cue đơn lẻ quá
dài cần tăng budget. Bước hồ sơ gửi độ phủ nếu chỉ lấy mẫu lời thoại.

Để khóa tên nhân vật, thêm `"confirmedNames": {"夏侯": "Hạ Hầu"}` ở cấp gốc
của file hồ sơ phim tương ứng trong `subtitles/library/.agent/`. Đây là dữ liệu
người dùng quản lý, tách khỏi output của model; hiện chưa có trình sửa tên trên UI.
Tên tạm do model chọn chỉ được sửa ở bước lập hồ sơ, kèm bằng chứng mới và ghi chú
tên cũ → tên mới; bước dịch giữ nguyên cách viết đã chốt.

Khi prompt đổi, hồ sơ tập được phân tích lại khi cần dịch; thông tin phim từ phiên
bản cũ được hỗ trợ vẫn được giữ. Bản dịch đã lưu không tự bị xóa hoặc dịch lại.
Khởi động lại app quản lý phụ đề để nạp prompt/mã mới.

## Giấy phép

Chỉ dùng cho mục đích cá nhân. Tác giả không liên kết với iQIYI hay Youku;
việc dùng công cụ phải tuân thủ điều khoản dịch vụ của các nền tảng đó.
