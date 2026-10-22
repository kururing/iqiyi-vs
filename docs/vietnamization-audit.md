# Rà soát và Việt hóa giao diện

Ngày rà soát: 22/10/2026
Phạm vi: mã nguồn được quản lý trong repository, bộ ứng viên tài nguyên desktop đã lưu và bản override cũ `.local/lwa-vi.js` có trong workspace.

## Kết quả

- Đã gỡ dịch máy tự động khỏi giao diện iQIYI desktop/web. Khi thiếu bản UI tiếng Việt soạn sẵn, chuỗi giao diện giữ nguyên nguồn; không xếp hàng, gửi, thử lại hay lưu kết quả.
- Dịch phụ đề vẫn được giữ: app còn nút dịch tập/phim, API, cấu hình provider/model và hồ sơ AI; phụ đề tiếng Việt đã lưu tiếp tục đọc, phát và tải xuống. Bản dịch model chỉ chạy khi người dùng chủ động yêu cầu.
- API dịch UI cục bộ, worker extension và cache dịch UI đã gỡ. Dịch phụ đề Youku trực tiếp vẫn hoạt động bằng hook hiện có và cache riêng cho caption; không bị xem là dịch giao diện.
- Sau khi nhận đính chính, đã khôi phục hook Youku phiên bản 3, app/model dịch phụ đề và cấu hình của chúng; extension trên đĩa hiện ở bản 1.2.34. Cần bấm **Reload/Tải lại** trong Extensions rồi tải lại trang để trình duyệt nạp bản mới. Phiên bản hook 4 trước đó có lệnh xóa cache caption khi được nạp. Không xác minh được hook đó đã chạy trên tab Youku nào; nếu cache cũ đã bị xóa, caption sẽ được dịch lại khi phát.
- Bản dịch cố định, mẫu câu theo ngữ cảnh, thay nhãn ảnh bằng SVG và tra cứu tiêu đề/diễn viên đã xác minh từ iq.com vẫn hoạt động.
- Thông báo trạng thái/lỗi API có chữ Hán được thay bằng thông báo tiếng Việt ổn định, không gửi tiếp tới dịch vụ dịch.
- Bộ quét ban đầu bỏ sót thuộc tính native `tip` và nội dung được dựng trong player. Các lượt kiểm tra WebView theo ảnh ngày 22/10/2026 bổ sung nhãn native, mẫu câu runtime, menu và metadata có nguồn xác minh; engine hiện tại 160 có 1.558 khóa duy nhất trong `FIXED_COPY`. Tên riêng chưa xác minh vẫn được giữ nguyên.

## Cấu trúc và cơ chế bản địa hóa

Không tìm thấy `AGENTS.md` trong repository hoặc các thư mục cha đã kiểm tra. Đã đọc `README.md` và báo cáo quét tĩnh được lưu tại [archive/static-ui-audit-2026-10-22.md](archive/static-ui-audit-2026-10-22.md). Báo cáo hiện hành này là nguồn tổng hợp duy nhất về Việt hóa.

| Phần | Tệp/nguồn | Cách hoạt động |
| --- | --- | --- |
| UI web và WebView desktop | `ui-engine.js`, bản đồng bộ `ext/content.js` và `lwa-vi.js` | Bảng dịch thủ công `FIXED_COPY` 1.558 khóa duy nhất ở engine 160, mẫu câu hoàn chỉnh, theo dõi DOM động; nhãn ảnh đã nhận diện được dựng lại bằng SVG. Node DOM mới/đổi được xử lý trong callback MutationObserver; lượt quét dự phòng chạy mỗi 15 giây. Thiếu bản dịch thì giữ nguyên nguồn, không gọi máy dịch. |
| Tài nguyên native | `apply-vi.py`, tài nguyên cài đặt do người dùng có | Dùng `FIXED_COPY` để thay text/tooltip/`tip`/attribute; không có dịch vụ dịch. |
| Player iQIYI/Youku | `sub-hook.js`, `ext/sub-hook.js` | Dùng các track iQIYI đã lưu; Youku vẫn dịch caption đang phát và ghi nhận caption vào thư viện. |
| Tiêu đề và diễn viên iQIYI | API cục bộ `/api/international-title`, `/api/international-actor` và iq.com | Chỉ thay khi có tên Việt đã đối chiếu với tên gốc/mã người; nếu thiếu thì giữ tên nguồn. |
| App quản lý | `subtitle_app.py`, `subtitle_agent.py` | Giao diện và API quản lý phụ đề; dịch phụ đề theo yêu cầu bằng provider/model đã cấu hình. Không còn API hoặc module dịch UI. |

## Các luồng dịch máy giao diện đã gỡ

| Vị trí | Trước | Sau |
| --- | --- | --- |
| `ui-engine.js`, `lwa-vi.js`, `ext/content.js` — nhãn, popup, tooltip, placeholder, metadata trang | Hàng đợi Google, batch, retry/cooldown và cache RAM; fallback qua worker hoặc API cục bộ | Gỡ mọi đường dịch UI; giữ nguyên chuỗi chưa có trong `FIXED_COPY`. Yêu cầu tra cứu tên đã xác minh từ iq.com vẫn hoạt động riêng. |
| `ext/iqcom-bootstrap.js`, `ext/proxy.js`, `ext/ui-translate.js` | Bootstrap chuyển yêu cầu sang service worker; worker gọi Google | Bỏ bridge và import worker; xóa `ext/ui-translate.js`. Bootstrap chỉ còn lấy token cần cho API phiên và metadata. |
| `subtitle_app.py`, `ui_translation.py` | `POST /api/ui-translate` từng gọi `translate_ui`; module Python có cache/cooldown | Xóa route, import và dịch vụ; không còn endpoint `/api/ui-translate` hoặc module `ui_translation.py`. Gọi đường dẫn cũ nhận 404 như API không tồn tại. |
| `sub-hook.js`, `ext/sub-hook.js` — caption trực tiếp Youku | Dịch caption đang phát qua Google và cache kết quả trong `localStorage` | Giữ nguyên vì đây là dịch phụ đề, không phải dịch UI. Hook phiên bản 3 vẫn đọc cache và hiện caption tiếng Việt. |
| `subtitle_app.py` — dịch phụ đề bằng model AI | Nút dịch tập/toàn phim, API `/api/translate`, `/api/translate-all`, cấu hình provider/model, gọi model, prompt và hồ sơ AI | Giữ nguyên; đây là chức năng phụ đề theo yêu cầu người dùng. API `/api/settings`, `/api/ai/models`, `/api/agent-profile` và `/api/stop-translation` vẫn hoạt động. |
| Cấu hình `.env.example`, `.ai-settings.json`/`.env` | Mẫu provider, model và khóa API | Đã khôi phục `.env.example` và bộ đọc cấu hình. Tệp `.ai-settings.json` cục bộ không có trong workspace sau thay đổi trước; nếu trước đó chứa provider/model tùy chỉnh, cần chọn lại trong **Cài đặt**. Không ghi giá trị khóa vào báo cáo. |
| `.local/lwa-vi.js` — bản override cũ có sẵn trong workspace | Còn nguyên hàng đợi và đường Google/local API | Đã gỡ riêng phần tự dịch, giữ nguyên bảng dịch tùy chỉnh của tệp. Không đọc hoặc sửa hồ sơ trình duyệt, cookie hay thư viện phụ đề trong `.local`. |

Các bản sao UI đã đồng bộ từ `ui-engine.js`; phiên bản engine tăng từ 133 lên 134, hook Youku từ 3 lên 4 và manifest extension từ 1.2.28 lên 1.2.29. Không có thư viện dịch bên thứ ba trong `requirements.txt`; Playwright vẫn phục vụ đọc phụ đề và metadata.

Toàn bộ request và endpoint dịch tự động giao diện đã bị gỡ; đường dẫn cũ không còn route và không thể gọi dịch vụ. Hàm trạng thái giả, dọn cache dịch UI cũ và thao tác xóa global từ điển cũ cũng đã bỏ. Luồng dịch phụ đề độc lập còn nguyên: thao tác dịch do người dùng bấm gọi provider/model, cập nhật tiến độ và lưu kết quả theo cue; dịch caption Youku tiếp tục dùng cache của hook.

`FIXED_COPY` là bảng bản dịch thủ công đang được dùng trực tiếp bởi engine và bộ vá native, nên được giữ lại để bảo toàn giao diện tiếng Việt. Các asset từ điển legacy (`vi.json`, `web-vi.json`, `vi-overrides.json`, `titles-vi.json`, `vi-dict.js`) không được tải, đóng gói hay đọc; test `test_no_legacy_dict.py` kiểm tra ranh giới này. `VERIFIED_TITLE_COPY` chỉ chứa ánh xạ tên đã xác minh và không phải fallback dịch tự động.

## Nội dung Trung đã đối chiếu với bản Việt

Các cặp dưới đây đã có trong `FIXED_COPY` trước lượt sửa này. Chúng được giữ nguyên và tiếp tục dùng trong các màn hình tương ứng; không phải bản dịch máy mới.

| Màn hình/thành phần | Tiếng Trung | Tiếng Việt hiện có |
| --- | --- | --- |
| Menu player | `循环播放` | Phát lặp |
| Điều khiển player | `隔空手势` | Điều khiển bằng cử chỉ |
| Cài đặt hình ảnh | `画面缩放` | Thu phóng hình ảnh |
| Kích thước video | `原始尺寸` | Kích thước gốc |
| Trợ giúp player | `常用快捷键` | Phím tắt thường dùng |
| Tắt máy theo lịch | `定时关机` | Hẹn giờ tắt máy |
| Chẩn đoán player | `播放问题诊断` | Chẩn đoán lỗi phát |
| Cài đặt player | `更多设置` | Cài đặt khác |
| Lựa chọn chất lượng | `（仅针对1080P及以下清晰度生效）` | (Chỉ áp dụng cho chất lượng 1080P trở xuống) |
| Popup đồng ý điều khoản | `感谢您选择爱奇艺PC客户端！…同意并继续…` (đoạn HTML/XML đầy đủ nằm trong khóa của `FIXED_COPY`) | Toàn bộ đoạn đã Việt hóa; thẻ `<c>`, `<a>`, URL và dấu xuống dòng được giữ. |
| Điều hướng/tên tab | `关闭`, `下一集`, `播放设置` | Đóng, Tập tiếp, Cài đặt phát |

Không tạo bản dịch theo từng chữ cho tiêu đề phim. Các mẫu số tập, lịch phát, giá và bảng xếp hạng chỉ thay khi khớp cả mẫu câu đã soạn sẵn.

## Tiếng Trung còn lại và cách xử lý

| Vị trí/loại | Ví dụ | Lý do giữ nguyên và ảnh hưởng | Hướng xử lý |
| --- | --- | --- | --- |
| Ứng viên tài nguyên cũ 14.9.5, `geeplayer\skin\player\miniplayer\other\lyric\musicmode.xml` | `孙燕姿` | Tên riêng ca sĩ; ảnh hưởng một nhãn/tên hiển thị trong bộ tài nguyên cũ. Không dịch nghĩa hoặc đoán phiên âm. | Chỉ thay khi có tên Việt được xác nhận. Tên này không còn là ứng viên thiếu của bộ 14.10. |
| Tiêu đề phim/tập, tên diễn viên do API trả về | Giá trị thay đổi theo phim và tài khoản | Là nội dung riêng, không phải nhãn UI. iq.com có thể không có tên Việt cho mọi bản ghi. | Dùng metadata Việt đã xác minh; nếu thiếu, giữ tên gốc. Không gửi sang dịch vụ dịch. |
| Mô tả, bình luận, nội dung marketing và caption nguồn | Văn bản thay đổi theo API/video | Repository không chứa toàn bộ nội dung runtime; tự dịch có thể làm sai nghĩa phim. Caption gốc được lưu riêng để đối chiếu. | Dùng nguồn Việt hoặc track đã có trong thư viện; nếu chưa có thì giữ nguyên nguồn. |
| Tên nguồn trong hồ sơ thuật ngữ/phụ đề | Ví dụ `夏侯`, `我不是不想去。` | Đây là trường nguồn dùng để giải thích đối chiếu, prompt hoặc ví dụ kiểm thử; dịch nó sẽ làm mất bằng chứng gốc. | Giữ nguyên trường nguồn và hiển thị bản Việt ở trường dịch tương ứng. |
| Mẫu phân tích tập/player | `第…集`, `越南语` trong regex | Hằng số nhận dạng ngôn ngữ, tập phim và tiêu đề; không phải text UI được đưa lên màn hình. | Giữ cho parser hoạt động. |
| Bitmap, video và tài nguyên ngoài repository | Chữ nằm sẵn trong ảnh/video | Engine thay được một số badge/icon đã nhận diện bằng SVG, nhưng không có đầy đủ ảnh nguồn hoặc quyền truy cập mọi popup/tài nguyên client để quét từng pixel. | Cần tài nguyên thay thế hoặc ảnh chụp cụ thể cho các mục chưa có selector/mapping. |

Các trạng thái/lỗi API của app quản lý đi qua `safeStatusText()`: nếu nội dung có chữ Hán, UI dùng thông báo dự phòng tiếng Việt thay vì đưa chuỗi đó qua dịch máy. Tên phim, diễn viên, mô tả, track nguồn và các trường bằng chứng không dùng helper này vì đó là dữ liệu nội dung cần giữ nguyên khi chưa có nguồn Việt đáng tin.

## Kiểm chứng và giới hạn

- Đối chiếu script tại lượt rà đầu: `FIXED_COPY` có 1.314 khóa, không mục nào có giá trị tiếng Trung; 0/2 ứng viên của bộ 14.10 thiếu khóa; 1/937 ứng viên bộ 14.9 còn thiếu là `孙燕姿`. Ở thời điểm đó, bảng copy có 1.504 mục; bản engine của lượt rà sau đó có 1.533 mục.
- Regression check xác nhận bản dịch soạn sẵn vẫn chạy, chuỗi UI chưa có khóa giữ nguyên, placeholder không đổi và không phát sinh fetch/timer fallback.
- Kiểm tra mã xác nhận không còn endpoint Google Translate cho UI, worker UI hay đường gọi `/api/ui-translate` đang hoạt động. Google endpoint chỉ còn trong hook dịch caption Youku. Hai hook Youku/iQIYI và các bản engine được kiểm tra cú pháp JavaScript.
- `python -m unittest discover -v`: 19 test passed. Năm bài Node `test_ui_coverage.js`, `test_iqcom_metadata.js`, `test_international_actors.js`, `test_fixed_ui.js` và `test_api_status_fallback.js` đều passed. `node --check` passed cho 14 tệp JS; kiểm tra cú pháp Python passed cho 16 tệp mã dự án.
- Regression test xác nhận mã provider/model, prompt, hàm dịch phụ đề, tiến độ/hủy dịch và API hồ sơ AI vẫn có mặt; endpoint UI cũ đã bị xóa, trong khi các API phụ đề hoạt động.
- Sau khi khôi phục luồng phụ đề, app quản lý đã khởi động lại khi `/health` báo `busy=false`. `/health` trả HTTP 200, phiên bản 24, `busy=false`; `GET /` trả 200 và HTML có nút dịch tập/toàn phim, cài đặt provider/model và hồ sơ AI. `GET /api/settings` trả 200 (1 provider, model đã chọn, khóa API được cấu hình); `GET /api/episodes` trả 200 (1.021 tập). Runtime cũ từng trả 410 cho route UI; mã hiện tại đã xóa route, được xác minh tĩnh và bằng hồi quy. Không gọi `/api/translate` trong kiểm tra runtime để tránh tạo lệnh dịch hoặc phát sinh chi phí.
- Quét source xác nhận không còn vận chuyển dịch máy cho UI; mã Gemini/provider và prompt chỉ thuộc luồng dịch phụ đề. `.env.example` và bộ đọc cấu hình đã khôi phục. `.ai-settings.json` cục bộ không có trong workspace nên lựa chọn provider/model tùy chỉnh trước đó có thể cần thiết lập lại. `git diff --check` passed; Git chỉ cảnh báo quy tắc chuyển LF sang CRLF trên một số tệp.
- `python -m compileall -q .` không dùng làm kết quả kiểm tra vì lệnh quét cả `.venv` và vấp cú pháp type-alias của NumPy trong virtualenv không tương thích Python 3.11.9. Kiểm tra cú pháp có phạm vi 16 tệp mã dự án đã passed.
- Đã đọc bộ nhớ cục bộ hiện có chỉ ở mức liệt kê tên file; không rà nội dung thư viện phim/phụ đề riêng tư hoặc profile trình duyệt.
- QyClient và Edge đang chạy lúc rà soát. Không thao tác hoặc khởi động lại các cửa sổ đó; chưa kiểm tra trực quan từng màn hình client/extension, popup, tài khoản, mọi phản hồi API hay ảnh/video. App quản lý phụ đề đã được nạp mã mới và API kiểm tra trực tiếp như trên; điều này không thay cho kiểm tra pixel/runtime trên mọi màn hình hoặc phiên người dùng.
- Repository không có `package.json`, cấu hình lint/typecheck hoặc lệnh build frontend riêng; vì vậy không có lệnh lint/typecheck/build dự án để chạy. Các kiểm tra cú pháp và test ở trên không thay cho kiểm tra trên mọi phiên bản app/extension.

Lượt rà ban đầu chưa kết nối vào WebView player đang mở. Bổ sung dưới đây ghi kết quả kiểm tra trực tiếp sau khi watcher nạp engine mới; việc này chỉ xác nhận màn hình player hiện tại, không đại diện cho mọi màn hình hoặc mọi trạng thái tài khoản.

## Bổ sung theo ảnh player native

### Phạm vi và kết quả runtime

- Đối chiếu ảnh với QyClient `14.10.0.10319`, trang `player.html` đang chạy trong WebView2. Trước sửa, WebView chạy engine 134; sau sửa, watcher đã nạp engine 139 mà không đóng player.
- Đọc DOM hiển thị, thuộc tính trợ năng và các chuỗi do React dựng. Không bấm nút phát, đổi tập hoặc thay trạng thái tài khoản để tránh làm gián đoạn phiên xem.
- Tiêu đề/diễn viên trên trang hiện tại đã thành `Mị Ảnh Thần Bộ · Tập 2` và `La Vân Hi`. Placeholder danmaku hiện là `Gửi bình luận chạy thôi…`; nút bật/tắt và nút cài đặt có `aria-label`/`title` tiếng Việt.
- Các nhãn giao diện còn sót trên màn hình này đã được dịch. Quét lại DOM còn 19 phần tử chứa CJK; các phần này là nội dung quảng cáo, tên tác phẩm hoặc lời giới thiệu video, không phải nhãn điều khiển.

### Các chuỗi đã bổ sung hoặc sửa

| Tệp/thành phần | Tiếng Trung | Tiếng Việt / cách xử lý |
| --- | --- | --- |
| `ui-engine.js` và bản đồng bộ `lwa-vi.js`, `ext/content.js` — toast player | `已切换主字幕为 {track}` | `Đã chuyển phụ đề chính sang {track}`; giữ nguyên tên track được chèn vào. |
| Player — tiêu đề nội dung | `魅影神捕 第2集` | `Mị Ảnh Thần Bộ · Tập 2`; tên lấy từ bản ghi iq.com ID `6343226711532601`, có `sourceTitle` trùng khớp và tên Việt `Mị Ảnh Thần Bộ` ([trang iQ.com tiếng Việt](https://www.iq.com/short/mi-anh-than-bo-tap-1-1ewmjgipdkk?lang=vi_vn)). |
| Player — diễn viên | `罗云熙` | `La Vân Hi`; API iq.com trả tên Việt cùng `sourceName`/ID khớp. Đã bổ sung nhận diện entity `TVG演员筛选标签` của player hiện tại để dùng nguồn này. |
| Player — phản hồi số tập | `会员更新至30集` | `VIP đã cập nhật tới tập 30`. |
| Player — số mục | `查看全部(30)` | `Xem tất cả (30)`. |
| Player — điều hướng/nhãn | `返回主窗口`; `速看`; `详情`; `加追`; `开会员立享`; `长剧`; `短剧`; `精彩短视频`; `讨论`; `二创` | `Trở về cửa sổ chính`; `Xem nhanh`; `Chi tiết`; `Theo dõi`; `Đăng ký VIP, hưởng ưu đãi ngay`; `Phim dài tập`; `Phim ngắn`; `Video ngắn nổi bật`; `Thảo luận`; `Sáng tạo lại`. |
| Player — nhãn quảng cáo | `广告 {content}` | `Quảng cáo {content}`; tên sản phẩm/tác phẩm được giữ nguyên. |
| Player — placeholder gửi danmaku | `弹幕走一波...` | `Gửi bình luận chạy thôi...`. Giá trị DOM cũ `Chúng ta hãy vượt qua rào chắn...` cũng được ghi đè bằng placeholder đúng theo entity của input. |
| Player — trợ năng | Entity `弹幕切换按钮,弹幕开关`; `弹幕设置按钮` | Gắn `aria-label` và `title`: `Bật/tắt bình luận chạy`; `Cài đặt bình luận chạy`. Nội dung hình vẽ của icon không có text node trong DOM. |
| `LoginRes/login_xml/logindlg.xml` | `请输入密码`; `请输入手机号`; `请输入手机号/邮箱`; `请输入验证码` | `Nhập mật khẩu`; `Nhập số điện thoại`; `Nhập số điện thoại/email`; `Nhập mã xác minh`. |
| `LoginRes/login_xml/sms_code.xml`, `varify_lay.xml` | `请输入手机号`; `请输入验证码` | `Nhập số điện thoại`; `Nhập mã xác minh`. |
| `TabSearchContainer.xml` | `搜视频...` | `Tìm video...`. |
| `geeplayer/skin/frame/feedbackdlg.xml` | `为了更好处理您的反馈与建议，请填写QQ号/微信号`; `请填写意见建议` | `Để hỗ trợ phản hồi của bạn tốt hơn, vui lòng nhập ID QQ hoặc WeChat.`; `Vui lòng nhập ý kiến góp ý.` |
| `geeplayer/skin/player/miniplayer/other/playconfig/subaudio.xml`, `subsubtitle.xml`, `speed/speed.xml` | `请输入` | `Vui lòng nhập`. |
| `player/panel/danmaku/screen_setting.xml` | `最多5个字符，回车可添加` | `Tối đa 5 ký tự, nhấn Enter để thêm`. |
| `player/panel/danmaku/sender.xml` | `弹幕来一波…` | `Gửi bình luận chạy thôi…`; bộ vá native nay nhận thuộc tính `tip`. |
| Trang lỗi `net/VodOtherErr_White.html`, `net/VodOtherErr.html` | `页面加载失败，请重新` | `Trang không tải được, vui lòng`; link `Tải lại trang` được giữ. |
| Tiêu đề/meta của trang LWA đã ký | `爱奇艺-在线视频网站-海量正版高清视频在线观看`; `爱奇艺-客户端下载`; `爱奇艺-sleep`; `爱奇艺客户端下载页面。`; `爱奇艺,客户端下载,下载` | Có bản dịch thủ công chính xác trong engine: `iQIYI – Xem video trực tuyến, kho nội dung bản quyền chất lượng cao`; `Tải ứng dụng iQIYI`; `iQIYI – Đang tạm nghỉ`; `Trang tải ứng dụng iQIYI.`; `iQIYI, tải ứng dụng, tải xuống`. HTML đã ký vẫn giữ nguyên trên đĩa; engine áp bản dịch ở runtime. |

`FIXED_COPY` tăng từ 1.314 lên 1.341 mục và không có giá trị dịch còn chữ Hán. Bộ vá `apply-vi.py` trước đó bỏ sót `tip`; sau khi bổ sung, lượt áp dụng trên skin `14.10.0.10319` cập nhật 17 giá trị trong 11 file native và 2 text node của hai trang lỗi. Quét lại các thuộc tính hiển thị `text`, `tooltip`, `tip`, `hint`, `placeholder`, `title`, `alt` và `aria-label` trong skin hiện cài đặt không còn giá trị CJK nào thiếu khóa.

### Các mẫu CJK trên player đã được xử lý

| Nhóm còn lại | Ví dụ đã thấy | Ảnh hưởng và hướng xử lý |
| --- | --- | --- |
| Quảng cáo động | `微信上可以借钱了！打开微信-服务，看看你的微粒贷额度是多少？`; tên sản phẩm `微粒贷`; thẻ `Quảng cáo 小城良方`; `肖战返乡行医，人间烟火即是良药` | Văn bản/quảng cáo do nguồn bên thứ ba cấp; phần nhãn `广告` đã được đổi thành `Quảng cáo`. Giữ tên sản phẩm và nội dung quảng cáo cho tới khi nhà quảng cáo cung cấp bản Việt. |
| Tiêu đề video đề xuất | `小城良方`; `重案六组：消失的警号` | Đã truy vấn tìm kiếm iq.com và từng ID khớp chính xác; các bản ghi trả `title` rỗng nên chưa có tên Việt được xác minh. Giữ nguyên, không tự phiên âm. |
| Mô tả/teaser video | `青阳公子黎斯大战鬼捕蒙锐！ #魅影神捕`; `黎斯发现蒙锐竟是当年替自己死的小男孩兄长 #魅影神捕`; `盛唐之下诡案续篇`; `长安重聚，入局破诡`; `中式恐怖 诡案丛生`; `迷雾盛唐 诡案千重`; `纯过日子，嘎嘎回血！`; `奇案未破 诡局再起`; `四案连阵撕开皇室秘辛`; `法医魂穿 借尸开局`; `以身为棋 胜天半子`; `死对头变生死搭档`; `百姓刑侦破身边重案` | Nội dung biên tập từ API/recommendation, không phải UI và không có trường tiếng Việt tương ứng trong dữ liệu đang kiểm tra. Giữ nguyên cho tới khi có metadata hoặc bản dịch do chủ nguồn xác nhận. |
| Glyph danmaku trong ảnh | Chữ nhìn giống `弹` trên nút player | Nút tương ứng trong DOM là icon không có text node, `aria-label`, `title`, `alt` hoặc pseudo-element chữ Hán. Đã thêm nhãn trợ năng tiếng Việt; glyph nhìn thấy trong ảnh cần truy nguyên và thay asset/font của player để đổi phần hình. |

### Kiểm chứng và giới hạn bổ sung

- Runtime QyClient hiện chạy engine 139; DOM xác nhận tiêu đề `Mị Ảnh Thần Bộ · Tập 2`, diễn viên `La Vân Hi`, placeholder `Gửi bình luận chạy thôi…`, và nhãn `aria-label`/`title` của hai nút danmaku.
- Scan thuộc tính CJK trên skin native đang cài: 0 mục chưa ánh xạ. Scan DOM player sau bản vá: các nhãn UI đã dịch; 19 leaf element còn CJK là quảng cáo/tên/mô tả nội dung được liệt kê ở trên.
- Test sau lượt bổ sung: `python -m unittest discover -v` (19 passed); 5 script Node (`test_fixed_ui.js`, `test_international_actors.js`, `test_iqcom_metadata.js`, `test_ui_coverage.js`, `test_api_status_fallback.js`) passed; `node --check` các engine/hook/extension JavaScript, `python -m compileall` các file Python liên quan và `git diff --check` passed.
- `apply-vi.py` đã cập nhật resource trên đĩa và watcher đã hot-load engine mới. Không đóng QyClient; các cửa sổ native chỉ đọc XML lúc khởi tạo có thể cần mở lại để nhận mọi cập nhật XML. Không kiểm tra trực quan mọi popup, trang tài khoản/đăng nhập, thiết bị khác, mọi phản hồi API hoặc ảnh quảng cáo/video.

## Rà soát bổ sung từng trang và menu native

Ngày kiểm tra bổ sung: 22/10/2026. Engine chạy trong QyClient `14.10.0.10319` được đồng bộ từ phiên bản 145 lên 150; bảng copy tăng từ 1.438 lên 1.504 mục. Lượt này rà text node trực tiếp (kể cả text nằm trong phần tử có con), menu đang ẩn, thuộc tính trợ năng và các nhãn trong panel player. Không thay đổi dữ liệu tài khoản; mã định danh được che khỏi kết quả ghi nhận.

### Phạm vi runtime đã mở

| Trang/menu | Kiểm tra | Kết quả |
| --- | --- | --- |
| Trang chủ và thanh điều hướng — `/index.html` | Menu bên, bộ lọc, tab tìm kiếm, menu tiện ích, thông báo, lịch sử và menu tài khoản | Các nhãn giao diện quan sát được đã Việt hóa. Danh sách menu tiện ích có `Chế độ tối giản`, `Tải lên`, `Phát tệp máy`, `Cài đặt`, `Cập nhật trực tuyến`, `Hỗ trợ trực tuyến`, `Phản hồi và sửa lỗi`, `Chẩn đoán lỗi phát`, `Trợ giúp`, `Thoát ứng dụng`. |
| Tìm kiếm | Mở panel tìm kiếm và đọc nhãn phần đề xuất/tab; không nhập hoặc sửa truy vấn | `搜索推荐` thành `Đề xuất tìm kiếm`; tab và huy hiệu được ánh xạ như bảng bên dưới. Tên phim, diễn viên, người đăng và video ngắn trong kết quả vẫn là dữ liệu nội dung; không ghi lại lịch sử tìm kiếm cá nhân. |
| Thông báo/lịch sử/tài khoản | Đọc các panel đã dựng trong DOM; giá trị định danh tài khoản được che khi kiểm tra | `通知`, `点赞`, `在追` và `钱包` đã hiển thị bằng tiếng Việt; tiền tố `用户` được dịch còn mã định danh được giữ nguyên. |
| Player — `/player.html` | Mở menu tốc độ, chất lượng, cài đặt, chọn phụ đề; rà nhãn menu lồng và toast | Lượt quét engine 150 trước đây còn bỏ sót `分集视频标题`, nhãn `长按倍速`, chữ trên lớp quảng cáo và tiền tố toast bị tách node. Đã bổ sung bản dịch và xác minh bằng engine 154; chi tiết ở phần cuối báo cáo. |
| Hết thời gian xem thử/VIP | Đã đọc DOM của màn hình lúc nó xuất hiện; không chọn gói hoặc bấm mua | Bổ sung bản dịch thủ công cho nội dung gói, bảng quyền lợi, phiếu giảm giá và mẫu giá. Màn hình tự chuyển sang trạng thái phát khác khi engine được nạp, nên lượt này không xác nhận lại trực quan paywall sau bản vá; các chuỗi được kiểm tra bằng regression test. |
| Trang đăng nhập, lỗi mạng và popup native XML | Đối chiếu bộ tài nguyên native đã quét trong lượt trước | Các chuỗi có khóa tiếp tục được áp dụng qua `apply-vi.py`; chưa mở từng popup native trong cửa sổ ứng dụng sau thay đổi. |

### Các bản dịch mới và chỉnh sửa trong lượt này

| Vị trí | Tiếng Trung | Bản tiếng Việt |
| --- | --- | --- |
| `ui-engine.js` — menu thông báo/tài khoản | `通知`; `点赞`; `在追`; `钱包`; `用户@{id}` | `Thông báo`; `Lượt thích`; `Đang theo dõi`; `Ví tiền`; `Người dùng@{id}` |
| `ui-engine.js` — xác minh/tiện ích | `关闭验证`; `刷新验证`; `请输入您听到的内容`; `上传` | `Đóng xác minh`; `Làm mới xác minh`; `Nhập nội dung bạn nghe được`; `Tải lên` |
| `ui-engine.js` — tìm kiếm | `搜索推荐`; `热搜`; `热点`; `爆`; `热`; `预` | `Đề xuất tìm kiếm`; `Tìm kiếm nổi bật`; `Chủ đề nóng`; `Bùng nổ`; `Đang hot`; `Sắp chiếu` |
| `ui-engine.js` — thẻ chuyên mục phim | `迷雾剧场`; `大家剧场`; `恋恋剧场`; `小逗剧场` | `Rạp Sương Mù`; `Rạp Phim Đại Chúng`; `Rạp Phim Tình Cảm`; `Rạp Hài` |
| `ui-engine.js` — chất lượng/âm thanh player | `画质`; `黄金/白金/星钻VIP尊享`; `超高清4K`; `准高清`; `智能`; `自动调节画质`; `音效`; `（VIP音效限黄金/白金/星钻VIP）` | `Chất lượng hình ảnh`; `Dành riêng cho VIP Vàng, Bạch Kim và Kim Cương`; `Siêu nét 4K`; `Gần HD`; `Thông minh`; `Tự động điều chỉnh chất lượng hình ảnh`; `Hiệu ứng âm thanh`; `(Hiệu ứng âm thanh VIP chỉ dành cho VIP Vàng, Bạch Kim và Kim Cương)` |
| `ui-engine.js` — player/nhãn danh sách | `分`; `本剧全集免费看`; `番外`; `花絮{n}`; `查看全部内容`; `风云榜总榜`; `查看完整风云榜` | `điểm`; `Xem miễn phí toàn bộ phim này`; `Ngoại truyện`; `Hậu trường {n}`; `Xem toàn bộ nội dung`; `Bảng xếp hạng tổng hợp`; `Xem đầy đủ bảng xếp hạng` |
| `ui-engine.js` — màn hình hết thời gian xem thử/VIP | `试看已结束，继续观看请开通VIP会员`; `未开通会员，不能观看海量VIP内容`; `更多开通选择` | `Đã hết thời gian xem thử. Đăng ký VIP để xem tiếp.`; `Bạn chưa đăng ký VIP nên chưa xem được kho nội dung VIP.`; `Xem thêm gói hội viên` |
| `ui-engine.js` — gói và quyền lợi VIP | `黄金VIP`; `白金VIP`; `星钻VIP`; `广告特权+五端可用`; `高清投屏+七端通(含电视)`; `加更礼免费看+七端通`; `连续包年/月/季`; `双月卡`; `赠送以下权益`; `会员特权对比`; `个人标准`; `家庭标准`; `家庭高端`; `会员抢先看`; `适用终端`; `同时播放`; `同时登录`; `会员积分` | `VIP Vàng/Bạch Kim/Kim Cương`; quyền lợi dùng trên 5/7 thiết bị được giữ đúng số lượng; `Gia hạn tự động hằng năm/tháng/quý`; `Gói 2 tháng`; `Quyền lợi được tặng kèm`; `So sánh quyền lợi VIP`; `Gói cá nhân/gia đình/gia đình cao cấp`; `Xem trước nội dung VIP`; `Thiết bị hỗ trợ`; `Phát đồng thời`; `Đăng nhập đồng thời`; `Điểm VIP`. |
| `ui-engine.js` — gói theo kỳ/khuyến mãi VIP | `年卡`; `季卡`; `月卡`; `大促红包`; `惊喜半价特惠`; `双11大促`; `限时加赠{n}天`; `已优惠¥{n}`; `次月续费{n}元`; `次季续费{n}元`; `共{n}项`; `黄金VIP会员15天` | `Gói năm/quý/tháng`; `Voucher khuyến mãi`; `Ưu đãi bất ngờ giảm nửa giá`; `Đại ưu đãi 11/11`; `Tặng thêm {n} ngày trong thời gian có hạn`; `Đã tiết kiệm ¥{n}`; `Từ tháng sau/quý sau gia hạn ¥{n}`; `Tổng cộng {n} quyền lợi`; `15 ngày VIP Vàng`. |
| `ui-engine.js` — giá/phần cuối màn VIP | `本页展示的划线价为建议零售价`; `共减`; `代金券`; `暂无可用`; `《会员协议》`; `黄金会员首月低至{n}元`; `新朋友，开通享精彩内容` | `Giá gạch ngang trên trang là giá bán lẻ đề xuất.`; `Tổng tiết kiệm`; `Phiếu giảm giá`; `Chưa có phiếu khả dụng`; `“Thỏa thuận hội viên”`; `VIP Vàng tháng đầu chỉ từ ¥{n}`; `Đăng ký VIP để khám phá nhiều nội dung hấp dẫn`. |
| `ui-engine.js` — giá và ưu đãi | `已优惠¥{n}`; `限时加赠{n}天`; `次月续费{n}元`; `次季续费{n}元`; `黄金会员首月低至{n}元`; `共{n}项` | `Đã tiết kiệm ¥{n}`; `Tặng thêm {n} ngày trong thời gian có hạn`; `Từ tháng sau/quý sau gia hạn ¥{n}`; `VIP Vàng tháng đầu chỉ từ ¥{n}`; `Tổng cộng {n} quyền lợi`. Số tiền, ký hiệu tiền tệ, số ngày và số quyền lợi được giữ theo nguồn. |

Nhận diện tiêu đề nội dung trong `isMovieTitleNode()` được mở rộng cho các lớp card native `tilesItem_title__`, `videoListItem_title__` và `title_title__`. Engine chỉ thay tên phim khi có bản ghi iq.com xác nhận khớp nguồn, hoặc có mục trong danh sách tên Việt đã xác minh; không dịch câu mô tả phim.

Tiêu đề trong ảnh người dùng, `魅影神捕 第2集`, có bản dịch đã xác minh `Mị Ảnh Thần Bộ · Tập 2`. Bổ sung nhận diện lớp `title_title__` giúp nhãn này được xử lý ngay cả khi client không gắn entity hint; regression test bao phủ trường hợp đó. Trang player trực tiếp đổi sang tác phẩm khác trước khi xác nhận lại bằng ảnh sau cập nhật.

### Tiếng Trung còn lại sau lượt rà

| Vị trí/nhóm | Mẫu còn lại | Phân loại, mức ảnh hưởng và hướng xử lý |
| --- | --- | --- |
| Tiêu đề nội dung đang phát | `田耕纪` (trang hiện phát hiển thị thêm số tập) | Tên tác phẩm đã xác minh là **Điền Canh Kỷ** trên trang iQIYI tiếng Việt; engine trước đây chưa có khóa tên này. Thêm tên cố định dựa trên nguồn chính thức. [Trang iQIYI tiếng Việt](https://www.iq.com/short/2d2h85aocrk?lang=vi_vn). |
| Thẻ phim trang chủ | Trong một snapshot có 59 thẻ; 38 hiển thị tiếng Việt từ copy đã xác minh hoặc metadata, 21 còn CJK | Danh mục thay đổi theo API/tài khoản. Không thay tên thiếu bản ghi hoặc có `title` rỗng; tiếp tục tra khi nguồn Việt/ID khớp xuất hiện. Con số này là snapshot của một lượt mở, không đại diện toàn bộ danh mục. |
| Tên phim, diễn viên và mô tả gợi ý | Tiêu đề phim, tên người, teaser, caption và nội dung video ngắn | Nội dung API thay đổi theo phiên, có thể là tên riêng hoặc lời biên tập. Hệ thống chỉ dùng tên Việt metadata đã xác minh; phần còn lại cần nguồn tiếng Việt hoặc bản dịch từ chủ nội dung. |
| Quảng cáo động | Tên tác phẩm, tên riêng và nội dung API thay đổi theo quảng cáo | Nhãn điều khiển quảng cáo và câu giới thiệu đã quan sát được đã có khóa thủ công. Tên `小城良方` và nội dung quảng cáo khác không có tên Việt được xác minh thì giữ nguyên; quảng cáo tiếp theo có thể dùng chuỗi mới. |
| Văn bản nằm sẵn trong video/ảnh hoặc glyph | Chữ trong khung hình; icon font có hình giống chữ `弹` | Không phải text node giao diện. Phụ đề track đang phát trong ảnh kiểm tra là tiếng Việt; glyph icon cần asset/font thay thế từ client để đổi hình, còn nhãn truy cập đã được Việt hóa. |
| Dữ liệu cá nhân ở lịch sử/tài khoản | Tên phim đã xem, từ khóa tìm kiếm hoặc mã tài khoản | Không đưa giá trị riêng vào báo cáo. Đây là dữ liệu người dùng hoặc định danh; menu và tiền tố nhãn được dịch, nội dung/ID được giữ nguyên. |

### Kiểm chứng lượt bổ sung và giới hạn

- Lượt bổ sung trước khi rà submenu cài đặt, `apply-vi.py` đồng bộ engine 154 với 1.533 chuỗi trong `FIXED_COPY` sang `lwa-vi.js` và `ext/content.js`; WebView `/index.html` và `/player.html` cùng báo engine 154. Kết quả mới nhất ở phần “Rà soát submenu cài đặt player” bên dưới.
- Trên hai WebView, `__iqiyiViAutoStatus().enabled` là `false`, hàng đợi/pending/cached đều bằng 0. Không phát sinh yêu cầu dịch giao diện; endpoint `/api/translate` chỉ được dùng khi người dùng chủ động dịch phụ đề.
- Lần quét trước kết luận quá sớm vì chưa mở menu cài đặt và chưa kích hoạt toast. Lượt mới đã mở các menu tốc độ, chất lượng, cài đặt và phụ đề; sau bản vá, canary DOM chạy trong WebView xác nhận các nhãn player vừa bổ sung không còn CJK. CJK còn trong bản player hiện tại là tên phim/tác phẩm, dữ liệu gợi ý và nội dung API được liệt kê ở phần cuối báo cáo.
- `.venv\\Scripts\\python.exe -m unittest discover -v`: 19 test passed. Năm script Node `test_fixed_ui.js`, `test_international_actors.js`, `test_iqcom_metadata.js`, `test_ui_coverage.js`, `test_api_status_fallback.js` đều passed. `node --check` trên 7 engine/hook/extension JS, `python -m compileall -q .` và `git diff --check` passed.
- Repository không có cấu hình frontend lint, typecheck hoặc build riêng; các kiểm tra cú pháp/test không chứng minh mọi màn hình client. QyClient, mọi phiên bản extension, tài khoản khác, phản hồi API khác, mọi popup native, quảng cáo và ảnh/video chưa được mở/quét đầy đủ. Trang paywall được kiểm tra DOM trước khi cập nhật và regression test sau cập nhật; chưa buộc app quay lại paywall để tránh thay đổi trạng thái xem/gói.

## Kiểm tra menu và thông báo player sau phản hồi

Ngày rà soát: 22/10/2026. Mở menu tốc độ, chất lượng, cài đặt và chọn phụ đề trong WebView `/player.html`; kiểm tra nội dung trước khi vá bằng text node, class, thuộc tính trợ năng và vị trí DOM. Chọn lại đúng track `Tiếng Việt iq.com` đang được chọn để tạo lại toast mà không đổi track.

### Các mục phát hiện và sửa

| Vị trí | Tiếng Trung | Bản tiếng Việt |
| --- | --- | --- |
| Menu cài đặt player | `分集视频标题` | `Hiển thị tiêu đề tập phim` |
| Menu tốc độ | `长按倍速` | `Nhấn giữ để tăng tốc` |
| Toast đổi phụ đề, node đầu tiên | `已切换主字幕为` | `Đã chuyển phụ đề chính sang `; tên track được giữ nguyên. Toast thực tế gồm hai `span`, nên khóa dịch cả câu trước đây không khớp node đầu. |
| Lớp quảng cáo player | `点击一下，快速跳过广告`; `▶ 跳过广告观看正片`; `了解详情`; `打开广告落地页` | `Nhấn một lần để bỏ qua quảng cáo`; `▶ Bỏ qua quảng cáo để xem phim`; `Xem chi tiết`; `Mở trang quảng cáo` (nhãn trợ năng). |
| Đếm ngược quảng cáo | `{n}s后可继续看正片`; `{n}秒后可继续看正片` | `Sau {n} giây có thể xem tiếp phim`; giữ nguyên số giây từ API. |
| Nội dung quảng cáo đang hiển thị | `天才医生跌落神坛，小城行医暖人心` | `Bác sĩ thiên tài sa cơ, hành nghề ở thị trấn nhỏ, sưởi ấm lòng người`. Tên tác phẩm/nhãn `小城良方` được giữ nguyên vì chưa có bản Việt được xác minh. |

Các bản dịch giao diện nằm trong `ui-engine.js`; `apply-vi.py` đã đồng bộ bản engine 154. `test_fixed_ui.js` kiểm tra trực tiếp các chuỗi mới và dựng toast bằng hai node riêng để bảo vệ trường hợp tách node. Trạng thái player sau đồng bộ báo `__iqiyiViAutoStatus().enabled=false`, hàng đợi/pending/cache bằng 0. Canary DOM trên WebView 154 trả đủ bản dịch trên và không còn CJK trong các nhãn đó. Bộ đếm resource của hai trang trong snapshot không có URL dịch Google cho UI hoặc `/api/ui-translate`.

### Tiếng Trung vẫn còn và giới hạn ở lượt rà player trước

| Vị trí | Nội dung còn lại | Lý do/ảnh hưởng | Hướng xử lý |
| --- | --- | --- | --- |
| Tiêu đề đang phát và thẻ gợi ý | Các tiêu đề, tên diễn viên và mô tả do API trả về | Tên phim `田耕纪` và diễn viên của phim đã có nguồn iQIYI Việt để đối chiếu; phần nội dung khác thay đổi theo phiên và cần xác minh riêng. | Dùng các khóa đã xác minh; nội dung API mới chưa có nguồn thì giữ nguyên và rà theo từng màn hình. |
| Quảng cáo và gợi ý khác | `小城良方` và các tiêu đề/mô tả thay đổi theo phiên | Có thể là tên phim, thương hiệu, tên người hoặc lời biên tập. Chỉ chuỗi quảng cáo đang quan sát và dịch rõ nghĩa đã được thêm thủ công; không đoán tên riêng. | Bổ sung theo từng chuỗi khi có bản dịch Việt xác minh; nội dung quảng cáo mới cần được mở và rà lại. |
| Glyph/icon danmaku | Hình chữ giống `弹` trên nút | Đây là glyph/icon, không phải text node hay tooltip. | Cần asset/font thay thế trong client; nhãn trợ năng tiếng Việt đã có. |
| Popup native khác và trạng thái tài khoản | Các trang/popup chưa mở trong lượt này | Kết quả WebView không chứng minh toàn bộ client; một số popup chỉ dựng theo trạng thái tài khoản hoặc khởi động. | Mở và chụp từng trạng thái trong client để tiếp tục rà; không tuyên bố đã kiểm tra toàn bộ runtime. |

Không sửa tài khoản hoặc thiết lập player trong lượt rà; ngoại lệ duy nhất là chọn lại track phụ đề tiếng Việt đang được chọn để tái tạo toast. Ở lượt rà player trước, `apply-vi.py` báo 0 file skin XML thay đổi; engine WebView đã hot-load mà không cần khởi động lại trang.

## Rà soát bổ sung menu phụ trên trang chủ

Sau khi rà menu player, quét lại WebView `/index.html` ở engine 154 và mở các danh sách lý do ẩn trên thẻ đề xuất. Lượt này phát hiện thêm các chuỗi giao diện chưa có khóa:

| Vị trí | Tiếng Trung | Bản tiếng Việt |
| --- | --- | --- |
| Menu phụ “không quan tâm” trên thẻ đề xuất | `选择不考虑观看的原因：`; `已看过`; `重复推荐`; `就是不想看` | `Chọn lý do bạn không muốn xem:`; `Đã xem`; `Được đề xuất nhiều lần`; `Tôi không muốn xem`. |
| Huy hiệu đề xuất tìm kiếm | `爆`; `热`; `预` | `Bùng nổ`; `Đang hot`; `Sắp chiếu`. Trước đây thuật toán nhận diện tiêu đề phim bỏ qua các huy hiệu này vì chúng nằm trong cùng nhóm DOM với tiêu đề. Engine nay loại riêng class `search-board-item_tag` khỏi nhận diện tiêu đề để khóa UI được áp dụng. |
| Tag thể loại/tình tiết trên thẻ nội dung | `甜宠`; `暗恋成真`; `打脸虐渣`; `现代言情`; `闪婚`; `虐恋`; `破镜重圆`; `先婚后爱`; `东方玄幻`; `恋爱`; `恋爱脑`; `百姓趣闻`; `农村`; `御兽`; `废柴` | `Ngọt sủng`; `Thầm yêu thành đôi`; `Vả mặt kẻ xấu`; `Ngôn tình hiện đại`; `Cưới chớp nhoáng`; `Tình yêu ngược`; `Gương vỡ lại lành`; `Cưới trước, yêu sau`; `Huyền huyễn phương Đông`; `Tình yêu`; `Lụy tình`; `Chuyện đời thường thú vị`; `Nông thôn`; `Ngự thú`; `Phế vật`. |

Sau bản 154, menu “không quan tâm” và các huy hiệu tìm kiếm đã được quét lại: 0 text node CJK trong hai nhóm này. Snapshot trang chủ còn 108 leaf node chứa CJK, gồm tiêu đề/mô tả phim, teaser, tên người, tag dạng bảng xếp hạng, truy vấn/lịch sử tìm kiếm và nội dung gợi ý do API trả về; đây không phải 108 chuỗi giao diện riêng biệt. Có 42 thuộc tính `title` chứa CJK, tất cả trên mô tả thẻ `filmFeed_desc`/`feedZaizhui_desc`; không thấy CJK trong `aria-label`, `alt` hoặc `placeholder` ở snapshot đó. Không ghi lại giá trị truy vấn cá nhân vào báo cáo. Tên riêng và nội dung chưa có nguồn Việt khớp vẫn được giữ nguyên.

## Rà soát tiếp trang iQIYI trong ảnh người dùng

Ảnh ngày 22/10/2026 là trang xem `田耕纪`, tập 22. Trang iQIYI tiếng Việt xác nhận tên **Điền Canh Kỷ**, diễn viên **Tăng Thuấn Hy** và **Điền Hi Vi**. Bổ sung alias tên phim/diễn viên đã xác minh, tiêu đề tập nhìn thấy, và các nhãn/chú thích đọc được trong ảnh. Không dùng dịch máy.

| Vị trí trên trang | Tiếng Trung trong ảnh | Bản tiếng Việt/điều chỉnh |
| --- | --- | --- |
| Tiêu đề player | `田耕纪 第22集 沈诺蔓儿制定救人计划` | `Điền Canh Kỷ · Tập 22 · Thẩm Nặc và Liên Mạn Nhi lập kế hoạch cứu người`. Tên phim đối chiếu nguồn chính thức; phần tiêu đề tập được dịch thủ công từ câu đang hiển thị. |
| Thông tin diễn viên | `曾舜晞`; `田曦薇` | `Tăng Thuấn Hy`; `Điền Hi Vi`, theo trang iQIYI tiếng Việt. Ánh xạ cục bộ giúp vẫn dịch được khi API metadata không trả kết quả. |
| Player/quảng cáo | `客户端4K播放`; `7秒后可跳过广告`; `黄金关闭此广告`; `关闭此广告` | `Phát 4K trên ứng dụng`; `Có thể bỏ qua quảng cáo sau 7 giây`; `VIP Vàng có thể tắt quảng cáo`; `Tắt quảng cáo này`. Bộ đếm giây dùng mẫu dịch thủ công. |
| Thẻ video ngắn | `新婚当晚被关柴房！她被养兄长骗嫁为妾` | `Đêm tân hôn bị nhốt trong nhà củi! Nàng bị anh nuôi lừa gả làm thiếp`. |
| Thẻ video ngắn | `《田耕纪》腹黑大姐连花儿，嫁人了也不安...` | `Chị cả Liên Hoa mưu mô trong “Điền Canh Kỷ”, lấy chồng rồi vẫn chưa yên...`. Giữ dấu rút gọn vì văn bản nguồn trên thẻ đã bị cắt. |
| Thẻ/nhãn nội dung | `播单`; `种田电子榨菜大全` | `Danh sách phát`; `Tuyển tập video giải trí đề tài làm ruộng`. Khóa cho cụm sau áp dụng nếu đó là text node. Nếu chữ được ghép sẵn vào ảnh poster, cần ảnh nguồn thay thế để loại bỏ chữ khỏi ảnh. |

Engine được nâng lên **156**, `FIXED_COPY` có **1.554** mục; `apply-vi.py` đã đồng bộ sang `ext/content.js` và `lwa-vi.js`. `test_fixed_ui.js`, `test_international_actors.js` và kiểm tra cú pháp JS đạt; test bao phủ tiêu đề tập, hai tên diễn viên không cần gọi API metadata, mẫu đếm ngược và các câu trong thẻ video. Nguồn tên phim/diễn viên: [trang iQIYI tiếng Việt](https://www.iq.com/short/2d2h85aocrk?lang=vi_vn).

Lượt này chỉ xử lý chuỗi nhìn thấy trong ảnh. Chưa quét DOM runtime của trang đó để xác định cụm `种田电子榨菜大全` là text hay chữ raster, chưa mở mọi đề xuất/video ngắn và chưa rà các biến thể quảng cáo khác. Các nội dung động chưa liệt kê có thể vẫn xuất hiện bằng tiếng Trung; cần kiểm tra theo phiên/màn hình và bổ sung bản dịch thủ công đã xác minh.

## Rà soát submenu cài đặt player

Ngày rà soát: 22/10/2026. Theo phản hồi rằng các mục có dấu `>` vẫn còn tiếng Trung, mở trực tiếp submenu **Thu phóng hình ảnh**, **Phím tắt thường dùng** và **Phụ đề** trong player `/player.html`, đọc text node thực tế và kiểm tra các khóa mới trên WebView đang chạy.

| Màn hình/menu | Tiếng Trung còn sót | Bản tiếng Việt đã thêm |
| --- | --- | --- |
| Cài đặt > Thu phóng hình ảnh | `铺满（保持比例）` | `Lấp đầy (giữ nguyên tỷ lệ)` |
| Cài đặt > Thu phóng hình ảnh | `铺满（拉伸画面）` | `Lấp đầy (kéo giãn khung hình)` |
| Cài đặt > Phím tắt thường dùng | `老板键` | `Phím ẩn nhanh` |
| Cài đặt > Phím tắt thường dùng | `全屏/退出全屏`; `Alt + 回车` | `Toàn màn hình/Thoát toàn màn hình`; `Alt + Enter` |
| Cài đặt > Phím tắt thường dùng | `播放/暂停`; `空格` | `Phát/Tạm dừng`; `Phím cách` |
| Cài đặt > Phím tắt thường dùng | `快进（长按开启倍速）`; `快退` | `Tua nhanh (nhấn giữ để tăng tốc)`; `Tua lùi` |
| Cài đặt > Phím tắt thường dùng | `增加音量`; `降低音量`; `全部快捷键` | `Tăng âm lượng`; `Giảm âm lượng`; `Tất cả phím tắt` |
| Toast/lớp player | `关闭广告，放大暂停画面` | `Đóng quảng cáo để phóng to khung hình khi tạm dừng` |
| Popup native: xóa danh sách, tắt player, tiêu đề trailer | `确定`; `取消` trong thuộc tính `tooptip` | `Xác nhận`; `Hủy`. Native skin viết sai tên thuộc tính thành `tooptip`; `apply-vi.py` nay nhận diện cả cách viết này. |

Trong submenu **Phụ đề**, các mục quan sát được đã là tiếng Việt: `Phụ đề`, `Tiếng Trung giản thể`, `Tiếng Việt AI`, `Tiếng Việt iq.com`, `Đóng`, các cỡ chữ và nền phụ đề. Engine được nâng lên **155**, có **1.546** mục trong `FIXED_COPY`; canary tạo text node tạm cho toàn bộ 13 chuỗi mới và xác nhận chúng được đổi sang tiếng Việt. Hai WebView `/index.html` và `/player.html` báo engine 155, `enabled=false`, hàng đợi dịch tự động bằng 0. Không phát sinh yêu cầu dịch máy trong lượt xác minh này.

### Mục cài đặt còn cần xác minh

| Mục | Kết quả quan sát | Ảnh hưởng và hướng xử lý |
| --- | --- | --- |
| `Tất cả phím tắt` (liên kết sâu từ submenu phím tắt) | Thấy mục điều hướng nhưng chưa xác nhận được màn hình đích; tọa độ/nội dung đích nằm ngoài vùng DOM có thể thao tác trong phiên hiện tại. | Chưa kết luận danh sách sâu đã Việt hóa; cần mở lại trong client và ghi nhận nội dung nếu trang đích còn CJK. |
| `Hẹn giờ tắt máy`, `Chẩn đoán lỗi phát`, `Cài đặt khác` | Khi thử mở từ overlay, panel biến mất hoặc DOM native không còn lộ ra WebView để đọc. | Chưa xác minh popup/trang đích. Cần rà trực tiếp trong client sau khi khôi phục được overlay; không tính là đã kiểm tra xong. |
| Native tooltip vừa vá | Resource trên đĩa ở `ClearFile.xml`, `shutdown.xml` và `titletrailer.xml` đều còn đúng hai giá trị `tooptip`: `Xác nhận`, `Hủy`; không còn CJK trong thuộc tính này. | `apply-vi.py` cập nhật 6 giá trị trên 3 tệp. Client hiện tại đọc resource native khi khởi động, vì vậy cần khởi động lại QyClient để tooltip đã nạp trong bộ nhớ nhận bản sửa; lượt này không đóng player đang phát. |

Các khóa mới nằm trong `ui-engine.js`; `test_fixed_ui.js` có assertion riêng cho submenu và toast. Đã chạy lại `node test_fixed_ui.js`, `python -m unittest discover -v` (19 test passed), `python -m py_compile apply-vi.py test_static_ui_copy.py` và `git diff --check` (đều thành công). Kiểm tra WebView/canary chỉ xác minh những menu và trạng thái nêu trên; không đại diện cho mọi popup native, mọi trang đích hay mọi phản hồi API.

## Rà soát player theo ảnh quảng cáo Trục Ngọc

Ngày rà soát: 22/10/2026. Ảnh mới cho thấy player iQIYI đang phát tập 2 của `逐玉`, cùng lớp quảng cáo, banner VIP và thẻ gợi ý. Bổ sung các nhãn giao diện dưới đây vào engine 157. Tên tiếng Việt **Trục Ngọc** được đối chiếu với [trang iQIYI tiếng Việt](https://www.iq.com/album/truc-ngoc-2026-19vub7xxrwd?lang=vi_vn).

| Vị trí | Tiếng Trung/chuỗi trong ảnh | Bản tiếng Việt hoặc xử lý |
| --- | --- | --- |
| Tiêu đề player | `逐玉 · Tập 2` | `Trục Ngọc · Tập 2`; tên phim có nguồn iQIYI tiếng Việt. |
| Lớp quảng cáo | `跳过广告` | `Bỏ qua quảng cáo`. |
| Lớp quảng cáo | `关闭此广告` | `Tắt quảng cáo này` (khóa có sẵn, đã kiểm tra lại trên engine mới). |
| Giá gói VIP | `首月12元起` | `Tháng đầu từ ¥12`; mẫu giữ nguyên số tiền động. |
| Banner tập miễn phí | `免费集将看完` | `Sắp hết số tập được xem miễn phí`. |
| Nút banner VIP | `开会员看全集` | `Đăng ký VIP để xem trọn bộ`. |
| Tên bên thông tin phim | `Truc Ngoc` | `Trục Ngọc`; bổ sung dấu tiếng Việt cho biến thể Latin không dấu. |
| Tên phim trong watermark video và thẻ gợi ý | `小城良方` | Giữ nguyên tên nguồn. Chưa xác minh được tên phát hành tiếng Việt; không dịch đoán tên riêng. Đây là nội dung phim/thẻ gợi ý, không phải nhãn giao diện. |

Đã cập nhật `ui-engine.js` và đồng bộ nội dung sang `lwa-vi.js` cùng `ext/content.js`; tăng engine lên 157 và phiên bản extension trong `ext/manifest.json` lên 1.2.30. Kiểm tra WebView đang chạy qua CDP cho thấy cả hai target `localwebapp.iqiyi.com` đều đã nạp engine 157 và `__iqiyiViAutoStatus().enabled=false`; canary DOM dịch đúng sáu chuỗi giao diện gồm tên `逐玉`, nút quảng cáo, giá VIP và banner. Canary chỉ tạo text node tạm rồi xóa. Một target đang có nội dung CJK là thẻ/video gợi ý `小城良方`; tên này được giữ nguyên như nội dung phim chưa có bản Việt được xác minh. Không thấy các nhãn quảng cáo trong DOM ở trạng thái chụp runtime tại thời điểm kiểm tra, vì vậy chúng được xác minh bằng canary DOM và test khóa dịch, chưa xác nhận trực tiếp trạng thái quảng cáo đang phát.

Kiểm tra sau cập nhật: `node test_fixed_ui.js`, `node --check ui-engine.js`, `python -m unittest discover -v` (19 test passed) và `git diff --check` đều đạt. Bản extension trên đĩa đã được cập nhật; trình duyệt có thể cần bấm **Tải lại/Reload** tại trang quản lý Extensions để nạp phiên bản 1.2.30, sau đó tải lại trang iQIYI nếu tab đang giữ content script cũ.

## Gỡ stub dịch giao diện và mã từ điển legacy

Lượt cập nhật 22/10/2026 nâng engine lên 158 và extension lên 1.2.32. Các thay đổi liên quan:

| Tệp | Phần đã gỡ | Hiện trạng |
| --- | --- | --- |
| `ui-engine.js`, `lwa-vi.js`, `ext/content.js` | `window.__iqiyiViAutoStatus`, vòng lặp xóa cache `__iqiyiViAutoV*`, lệnh xóa `window.__iqiyiViDict` và `window.__iqiyiViTitles` | Không còn stub hay xử lý runtime cho auto-translation; ba bản engine được đồng bộ. |
| `.local/lwa-vi.js` (tệp ignored, giữ nguyên ngoài gói phát hành) | Cùng ba phần dư nói trên trong override cũ | Gỡ stub/cache/global legacy; giữ bảng copy thủ công riêng của override. |
| `subtitle_app.py` | Hằng lỗi và route `POST /api/ui-translate` trả HTTP 410 | Đã xóa route. API lạ nhận 404; API dịch phụ đề vẫn còn. |
| `ext/manifest.json` | Phiên bản extension cũ | Nâng lên 1.2.32 để trình duyệt nhận bản cần tải lại. |
| `test_no_machine_translation.py`, `test_fixed_ui.js`, `test_ui_coverage.js` | Kỳ vọng stub báo `enabled=false` | Kiểm tra stub không còn, không có transport UI, không fallback mạng và bản dịch phụ đề vẫn hoạt động. |

Trong lượt dọn code chết, đã xóa các helper không có caller `mostlyCjk`, `wordChar`, `replaceWithSpacing` khỏi `ui-engine.js`; `clearActiveViTrack` khỏi `sub-hook.js`; method `_login()` khỏi `iqcom_session.py`; biến không dùng `IS_PLAYER` và `providerUrls`; cùng loader `international_reference()` và import `csv` chỉ phục vụ loader đó trong `subtitle_agent.py`. `FindProxyForURL` và `do_CONNECT` được giữ vì chúng là entry point do trình duyệt/thư viện gọi.

Không có nội dung giao diện Trung mới cần dịch trong thay đổi này. `FIXED_COPY` (1.558 khóa duy nhất) và `VERIFIED_TITLE_COPY` được giữ vì là nguồn copy/metadata đã xác minh đang dùng; chúng không phát sinh yêu cầu dịch. Gỡ bốn mục lặp: `逐玉 → Trục Ngọc` khỏi `FIXED_COPY` vì đã có trong `VERIFIED_TITLE_COPY`, cùng ba khóa `爆`, `热`, `预` bị khai báo hai lần. `tr()` dùng trực tiếp bảng tên đã xác minh; khóa `热` dùng một bản dịch thống nhất `Đang hot`. Các tệp từ điển legacy `vi.json`, `web-vi.json`, `vi-overrides.json`, `titles-vi.json`, `vi-dict.js` không được runtime hoặc installer nạp.

Kiểm tra lượt này: 20 test Python passed (`test_no_machine_translation`, `test_no_legacy_dict`, `test_static_ui_copy`, `test_iqcom_requests`, `test_international_actors`, `test_watch_players`); `node test_fixed_ui.js`, `node test_ui_coverage.js`, `node test_international_actors.js`, cú pháp Python/JavaScript và `git diff --check` đều passed. Đây là xác minh mã và test; phiên trình duyệt chưa được tải lại sau khi tăng version, nên cần **Reload** extension và tải lại tab iQIYI để áp dụng bản 1.2.32.

## Sửa nhấp nháy ở bộ đếm quảng cáo động

Ngày 22/10/2026, kiểm tra hiện tượng số giây đổi khiến nhãn hiện tiếng Trung thoáng qua trước khi thành tiếng Việt. Quy tắc thủ công đã có cho `N秒后可跳过广告` và `Ns/N秒后可继续看正片`; nguyên nhân nằm ở lịch cập nhật: MutationObserver trước đây chỉ xếp một lượt quét vào `requestAnimationFrame`, vì vậy DOM mới có thể được vẽ trước khi lượt dịch chạy.

Engine 159 xử lý ngay text node/nhánh DOM/thuộc tính vừa đổi trong callback MutationObserver (callback chạy trước khi trình duyệt vẽ), rồi vẫn giữ lượt quét toàn trang hiện có. Điều này áp dụng chung cho các luồng UI động, gồm hai mẫu đếm ngược quảng cáo, thông báo đổi phụ đề và nội dung vừa được thêm vào DOM. Hook dịch phụ đề vẫn tách riêng.

Kiểm tra tự động cập nhật các số 7→0 cho `N秒后可跳过广告`, cập nhật 5→0 cho mẫu tiếp tục phim, và cập nhật thông báo player; từng giá trị được xác nhận đã dịch ngay trong callback quan sát. Chưa kiểm tra lại phiên trình duyệt đang mở; để áp dụng extension mới, tải lại extension bản **1.2.34** và refresh tab iQIYI. Không tuyên bố đã kiểm chứng trực tiếp mọi kiểu player/API runtime.

## Tối ưu thời gian tải trang quản lý

Ngày 22/10/2026, rà trang `http://127.0.0.1:18766/` và luồng cập nhật thư viện. Workspace có 1.026 thư mục tập; trước thay đổi, mỗi lượt `/api/episodes` đọc và phân tích lại mọi phụ đề đã tải, dù file không đổi. Trình duyệt hỏi lại API mỗi 2,5 giây và dựng cả lưới tập đang bị thu gọn.

`subtitle_app.py` nay lưu tạm số câu dịch/trạng thái theo thời gian sửa và kích thước các file liên quan; khi file thay đổi, giá trị được tính lại. API chỉ gửi các trường cần thiết cho giao diện, nén HTML/JSON gzip cho trình duyệt hỗ trợ, và loại bỏ chi tiết danh sách track khỏi dữ liệu trang. Phía trình duyệt dựng lưới tập khi mở album, giảm lượt hỏi thư viện xuống 5 giây, tạm dừng hỏi khi tab ẩn và cập nhật ngay khi tab hiện lại.

Engine UI web/WebView dịch trực tiếp các nút DOM vừa đổi; không quét lại toàn bộ trang sau mỗi đợt DOM mutation. Quét dự phòng chỉ tìm shadow root được gắn trễ mỗi 60 giây khi tab đang hiện. `fitCompact` chỉ đọc kích thước phần tử khi bản dịch của text node vừa đổi.

Mã đã được kiểm tra cú pháp; chưa đo thời gian tải trong trình duyệt hoặc kiểm tra toàn bộ trạng thái player runtime. Extension trên đĩa là bản **1.2.35**; cần reload extension và refresh trang iQIYI để nạp engine mới.

## Tối ưu tốc độ iQIYI web và ứng dụng desktop

Ngày 22/10/2026, cập nhật engine chung cho extension trình duyệt và WebView LWA của ứng dụng desktop. Engine tăng từ 160 lên **161**; extension tăng từ **1.2.34** lên **1.2.35**. `ui-engine.js` được đồng bộ nguyên bản sang `lwa-vi.js` và `ext/content.js`.

Các thay đổi giảm chi phí lúc mở trang và khi giao diện cập nhật:

- Bỏ đọc toàn bộ `textContent` của mỗi phần tử trong vòng duyệt DOM. Nhánh chip cũ vốn không thể chạy vì đồng thời yêu cầu phần tử có con là element và chỉ có một text node trực tiếp; đã xóa nhánh chết này.
- Chuỗi không có chữ Hán bỏ qua các mẫu dịch động và việc dò tên phim/diễn viên/API metadata. Các khóa dịch tĩnh tiếng Việt vẫn được tra trước để giữ alias đã xác minh như `Truc Ngoc`.
- Các nhãn đặc biệt chỉ quét phạm vi node mới chứa điều khiển, thanh bên, huy hiệu hoặc nhãn kênh cần xử lý; không chạy lại toàn bộ danh sách selector toàn trang sau mọi node được thêm.
- Bỏ lượt quét và dựng lại giao diện đầy đủ mỗi 15 giây. MutationObserver tiếp tục xử lý text, thuộc tính và node mới ngay; lượt dự phòng chỉ tìm shadow root gắn trễ mỗi 60 giây khi tab đang hiện.
- `iqcom-bootstrap.js` chỉ yêu cầu engine nạp lại khi nhận được token mới. Lỗi, phản hồi rỗng hoặc hết thời gian chờ không kích hoạt một lượt quét toàn trang thừa; token trả về muộn vẫn được nhận và chỉ nạp lại một lần.

Phạm vi mã được rà: engine chung, script content của extension, bootstrap lấy token metadata, manifest và đường chèn `lwa-vi.js` vào các trang LWA trong `apply-vi.py`. `node --check` đạt cho ba engine và bootstrap; `test_fixed_ui.js`, `test_ui_coverage.js`, `test_international_actors.js` đều đạt; kiểm thử bootstrap xác nhận token mới chỉ kích hoạt một lượt nạp lại và lỗi không kích hoạt nạp lại; toàn bộ 20 bài unittest Python đạt; `git diff --check` đạt. Dự án không có lệnh build JavaScript riêng. Đây là tối ưu dựa trên luồng mã; chưa đo thời gian tải bằng profiler trên trang iQIYI trực tiếp. Chưa có runtime WebView/browser được nối ở phiên này. Để áp dụng bản extension, reload extension **1.2.35** và tải lại tab iQIYI; để áp dụng engine desktop, đóng hẳn rồi mở lại ứng dụng sau khi chạy quy trình cập nhật/patch của dự án.

Trong lịch sử kiểm chứng phía trên, `test_api_status_fallback.js` là harness dùng một lần; đã xóa sau khi chạy. Các test hồi quy còn lại được giữ vì đang kiểm tra chức năng trong dự án.
