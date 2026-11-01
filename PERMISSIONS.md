# Quyền và luồng phụ đề/âm thanh

Rà soát ngày 01/11/2026. App quản lý chạy bằng tài khoản Windows thường. Chỉ bước
cài/sửa/gỡ tích hợp có thể cần UAC khi Windows bảo vệ thư mục iQIYI hoặc registry.

| Thành phần | Quyền/cấu hình cần thiết | Phạm vi và tình trạng |
| --- | --- | --- |
| Giao diện và Cài đặt quản lý | Đọc/ghi thư mục app, `.local/`, thư viện phụ đề; token quản trị localhost | Không cần chạy toàn bộ app bằng Administrator. Các API cài đặt không nhận token player. |
| Việt hóa cửa sổ chính và player native | WebView2, chèn script lúc tạo trang, autoplay cho âm thanh phụ | Chính sách chỉ áp dụng `QyClient.exe` và `QyPlayer.exe`; debugger chỉ nghe loopback. Cài/gỡ lưu và khôi phục giá trị cũ. |
| Tiện ích Chrome/Edge | `scripting`, quyền website, `storage` | Có sẵn trong manifest; cần cho phép tiện ích hoạt động trên website iQIYI/iq.com. |
| Proxy | `proxy`, `webRequest`, `webRequestAuthProvider`, `alarms`, quyền host | Có sẵn; proxy tùy chỉnh có thể truy cập nhiều host. Không mở thêm firewall/inbound cho dịch vụ chỉ nghe localhost. |
| Phiên iq.com | `cookies`, quyền host iq.com, hoặc đăng nhập hồ sơ riêng của app | Cookie chỉ đi giữa tiện ích và dịch vụ localhost. Quyền tài khoản/VIP/khu vực do iq.com xác nhận theo từng tập. |
| Phụ đề chính thức | Metadata đúng phim/tập, phiên iq.com khi cần, truy cập CDN phụ đề | Trang tra metadata được kích hoạt ở trạng thái tắt tiếng; chặn tải video/âm thanh trong trang này. |
| Lồng tiếng/thuyết minh | Metadata track AAC Việt được iq.com cấp, HTTPS CDN, HTTP Range, autoplay | Không cần quyền microphone, ghi âm hay camera. Không phát các track mã hóa chưa được hỗ trợ. |
| Âm thanh trên web | Iframe extension có `allow="autoplay"`, worker có quyền host CDN và localhost | Có sẵn; khi trình duyệt từ chối autoplay, hiển thị hướng dẫn và chờ người dùng nhấn/phím. |

Quyền microphone của WebView2 dùng để **thu âm**. Quyền autoplay dùng cho việc gọi
`play()` tự động; hai quyền này độc lập. Xem [Microsoft WebView2 permissions](https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/winrt/microsoft_web_webview2_core/corewebview2permissionkind)
và [Chrome autoplay](https://developer.chrome.com/blog/autoplay/). Quyền host của tiện ích
cho phép worker gọi API/CDN; xem [Chrome cross-origin requests](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests).

## Những sửa đổi về độ ổn định

- Đoạn âm thanh của dịch vụ Windows tải dở được tiếp tục từ byte đầu tiên còn thiếu, tối đa ba lượt;
  URL CDN hết hạn được xin lại. Không nối trùng dữ liệu, chấp nhận sai Range hay đổi
  ranh giới segment trong lúc refresh.
- `preload=auto`; một lần thăm dò trạng thái timeout không hủy âm thanh đã đệm.
  Mất quyền 401/403 vẫn dừng ngay; mất kết nối trạng thái quá 15 giây thì trả tiếng gốc.
- Không đặt lại vị trí khi bộ phát đang seek. Bỏ qua một nhịp PTS lệch tạm thời;
  vẫn căn ngay khi chuyển vị trí rõ ràng hoặc khi độ lệch kéo dài ba nhịp thăm dò.
- Lỗi mạng của phần tử audio được tự kết nối lại tối đa ba lần; lỗi giải mã không
  bị thử vô hạn. Khi autoplay bị chặn, chờ tương tác thay vì gọi `play()` mỗi 200 ms.

`window.__iqiyiAudioEngine.status()` cho biết `readyState`, `seeking`, `drift`,
`seeks`, `reconnects`, `errorCode`, `autoplayBlocked` cùng trạng thái hiện có;
không trả cookie, token hay URL CDN ký số.

Mẫu track của tập phát gần nhất đã trả HTTP 206 và được Edge giải mã thành công
trong một trình phát kiểm tra tắt đầu ra âm thanh. Mẫu đo không có lỗi decoder hoặc
clipping. Kiểm tra này không chứng minh rằng toàn bộ tập hay đầu ra loa Windows đã
hết rè; cần đối chiếu khi player native đang phát sau cập nhật.

Quyền WebView mới được ghi khi cài/sửa tích hợp, có hiệu lực khi tạo lại WebView.
Không thay đổi lựa chọn tích hợp đã tắt hoặc tự cấp thêm quyền tài khoản iq.com.
