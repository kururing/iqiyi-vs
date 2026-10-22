# Rà soát code Việt hóa web và app — 1.2.28

Phạm vi: mã nguồn trong repository; theo yêu cầu chỉ kiểm tra code, không xác nhận
trực tiếp mọi trang hoặc trạng thái popup trên dịch vụ iQIYI.

| Luồng dùng chung | Lỗi đã sửa | Kiểm tra |
| --- | --- | --- |
| Trang chủ, tìm kiếm, danh mục, chi tiết và player | Nhầm tiêu đề nhóm trong thẻ phim thành tên phim, bỏ qua nội dung cần dịch | `test_ui_coverage.js` |
| Popup, tooltip và trường gợi ý | Không theo dõi thuộc tính thay đổi; chặn luôn placeholder của input/textarea | `test_ui_coverage.js` |
| Shadow DOM và iframe | Bỏ qua Document/DocumentFragment; không quét iframe cùng miền hoặc quan sát shadow root | `test_ui_coverage.js` |
| Web và iframe trên miền con | Bootstrap chỉ chạy ở trang chính; đường dịch phụ thuộc kết nối của trang | `test_ui_worker.js`, `test_no_legacy_dict.py` |
| App | Thêm đường dịch qua dịch vụ cục bộ có token và dự phòng cho backend cũ | `test_ui_translation.py`, `test_ui_transports.js` |
| Nhiều cửa sổ app | Một cửa sổ timeout làm bỏ qua các cửa sổ còn lại; bỏ qua target iframe/webview | `test_ui_translation.py` |
| Mô tả dài | Bị bỏ qua khi quá 500 ký tự; giờ chia nhỏ và thay cả đoạn sau khi hoàn tất | `test_ui_transports.js` |
| XML/HTML tĩnh của app | Thiếu thuộc tính hiển thị; giữ script/style/nội dung nhập và escape bản dịch | `test_no_legacy_dict.py` |

Nhãn Việt soạn sẵn được ưu tiên. Không phục hồi từ điển cũ. Tên phim và diễn viên
iQIYI vẫn lấy từ API iq.com; khi chưa có bản địa hóa xác nhận được thì giữ tên gốc.
Không đưa giá trị người dùng đang nhập hoặc phụ đề qua bộ dịch giao diện.

Giới hạn: chữ nằm trong bitmap/video, nhãn ảnh chưa có quy tắc thay thế, shadow root
đóng và cửa sổ native tạo chuỗi trực tiếp từ DLL không thể được bảo đảm bằng việc
quét DOM hoặc XML/HTML của repository. Không tuyên bố mọi chữ Trung đã biến mất
trên toàn bộ dịch vụ.

Để dùng code mới: tải lại extension và trang; khởi động lại app quản lý/watcher
khi không có tác vụ dịch phụ đề đang chạy. Không thay bootstrap native có chữ ký.
