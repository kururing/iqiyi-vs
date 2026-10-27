# iQIYI / Youku Việt hóa

Việt hóa giao diện iQIYI và Youku; quản lý phụ đề gốc tải từ player, phụ đề Việt chính thức trên iq.com và dịch file SRT sang tiếng Việt bằng hai model AI tùy chọn.

- Quản lý phim, tập và phụ đề gốc tại [trang quản lý](http://127.0.0.1:18766/).
- Phim mới thêm/chấp nhận nằm trên cùng; thứ tự được giữ khi mở lại app. Ô **Tìm phim trong thư viện** lọc ngay theo tên Việt (có hoặc không dấu) và tên gốc trong nền tảng đang chọn.
- Xem phụ đề gốc đã lưu hoặc chọn track Việt chính thức của iq.com trong player khi tập có cung cấp.
- Trong player iQIYI, chọn **Tiếng Việt AI** khi tập đã dịch và kiểm định xong. Track lấy đúng bản dịch đã liên kết với tập; không xuất bản dịch dở hoặc bản có nguồn đã thay đổi. Hook iQIYI tự nâng cấp trong cửa sổ đang phát, cập nhật cả menu và URL table của SDK; không cần đóng video. Nếu menu phụ đề đang mở, đóng rồi mở lại menu. Trên web, tải lại trang để nạp script của tiện ích mới. Các lần dịch hoàn tất sau đó được cập nhật tự động.
- Việt hóa giao diện có sẵn; không cần khóa API.
- Cấu hình AI qua nút **Cài đặt dịch**, rồi bấm **Dịch** tại tập trong thư viện; cần API key của provider đã chọn.

## Quy trình dịch SRT bằng AI

**Lưu nhiều provider:** vào **Cài đặt dịch → Quản lý provider → Thêm provider**, đặt tên gợi nhớ, chọn mẫu, nhập URL và API key. Bấm **Quét model** rồi **Lưu provider** để giữ cả danh sách model; có thể thêm model ID thủ công. Có thể lưu nhiều tài khoản cùng một hãng. Sửa provider không ảnh hưởng các tài khoản khác. Đổi mẫu, URL, key hoặc Workspace sẽ xóa danh sách model đang sửa để tránh dùng catalog của kết nối cũ; các model đã chọn vẫn được giữ khi chỉ quét lại cùng kết nối. Backend gọi `/models`, không lưu key hoặc trả key về giao diện. Quét chỉ lấy danh mục, không gửi phụ đề hay chạy dịch.

Preset **Google Gemini** dùng `https://generativelanguage.googleapis.com/v1beta/openai` với API key của Google AI Studio; hỗ trợ cả quét model và dịch qua giao thức tương thích OpenAI. Xem [tài liệu Gemini](https://ai.google.dev/gemini-api/docs/openai/#list-models).

Riêng bước tạo hồ sơ/ngữ cảnh với preset Gemini, backend gửi `reasoning_effort: "low"` cho `gemini-3.8-flash` và `gemini-3.5-flash-lite`: giảm thời gian chờ của 3.8 Flash so với mặc định `medium`, tăng mức suy luận của 3.5 Flash Lite so với mặc định `minimal`. 3.8 Flash không hỗ trợ `minimal`. Bước dịch và các model/provider khác giữ mức suy luận mặc định. Xem [mức suy luận Gemini](https://ai.google.dev/gemini-api/docs/thinking/).

Trong **Cài đặt dịch**, hai mục **Model hồ sơ / ngữ cảnh** và **Model dịch thuật** chỉ cần chọn **Provider đã lưu → Model**, rồi bấm **Lưu lựa chọn**. Hai bước có thể dùng chung hoặc khác provider/key. Danh sách model đã quét vẫn có sau khi tải lại trang, không cần quét lại. Mẫu provider có OpenAI, Anthropic/Claude, Gemini, Qwen/DashScope và endpoint tùy chỉnh tương thích OpenAI. Với Qwen, chọn URL theo khu vực/workspace của key; Anthropic có ô Workspace ID nếu key yêu cầu. Cấu hình hai model của bản cũ được tự đọc thành các provider đã lưu, gộp khi cùng kết nối và giữ các model đã chọn. Đóng hộp thoại không lưu lựa chọn model đang sửa; nút **Lưu provider** lưu riêng từng provider ngay khi bấm.

**Dịch tập đã tải:** lưu cấu hình model một lần trong **Cài đặt dịch**, chọn tập trong thư viện và bấm **Dịch**. Backend tự đọc `source.srt` của tập; không cần xuất rồi tải lại file. Nếu thiếu cấu hình, app mở hộp thoại **Cài đặt dịch**; lưu xong bấm **Dịch** tại tập. Tập hiển thị tiến độ, **Xem bản dịch**, **Tải SRT Việt** và **Dịch lại** khi hoàn tất. Kết quả được liên kết với tập qua `translation-job.json` và vẫn mở lại được sau khi khởi động app. Khi phụ đề gốc thay đổi, liên kết cũ không còn được coi là bản dịch của phụ đề hiện tại; cần bấm Dịch lại. Các kết quả cũ vẫn giữ trong `.local/translations/`.

**Lưu tiến độ và Dịch tiếp:** mỗi batch hợp lệ được ghi ngay vào `batch-*.json`; QC xong batch nào được lưu vào `qc-*.json`. Khi API lỗi, hủy hoặc app bị đóng, bấm **Dịch tiếp** tại tập hoặc trong hộp thoại tiến độ để dùng lại cùng phiên, JSON Memory và các batch đã lưu. Chỉ phần còn thiếu hoặc checkpoint hỏng cần gọi API lại; giữ nguyên ID/timestamp và kiểm định toàn bộ trước khi xuất SRT. Đóng/mở lại app vẫn dịch tiếp được; cấu hình hai model và API key được lưu trong trình duyệt bằng nút **Lưu cài đặt**. Đóng cài đặt giữ lựa chọn model đã lưu. Xóa dữ liệu trang hoặc đổi trình duyệt cần nhập lại. Muốn bỏ tiến độ cũ, chọn **Dịch từ đầu** trong menu của tập. Backend từ chối dịch tiếp nếu phụ đề nguồn đã thay đổi.

HTTP 429 có thông báo riêng về giới hạn/hạn mức. Các batch dùng chung thời gian chờ, đọc `Retry-After` (số giây hoặc ngày HTTP) và thời gian thử lại Gemini trả về; sau 429 các yêu cầu được giãn ra. Tự thử lại tối đa 3 lượt; nếu provider yêu cầu đợi hơn 60 giây hoặc vẫn lỗi, app dừng và giữ checkpoint để người dùng Dịch tiếp khi hạn mức cho phép. Các phiên tạo trước tính năng checkpoint chỉ có Memory và số đếm; nội dung batch chưa được lưu của các phiên cũ không thể phục hồi.

1. **Đọc và phân cụm:** Python kiểm tra SRT, giữ ID/timestamp, chia mặc định 35 câu/batch và 3 câu gối đầu (chỉ làm ngữ cảnh, không dịch lại).
2. **Ngữ cảnh:** context model đọc SRT của 120 câu đầu (hoặc toàn bộ file ngắn hơn), tạo `memory.json` gồm `genre`, `characters` (tên Trung, tên Việt, vai trò), `pronoun_matrix`, `glossary` và `translation_style`.
3. **Dịch:** translation model nhận từng batch cùng Memory, mặc định chạy 4 batch đồng thời. Model trả JSON array gồm `id`, `time`, `text`; chỉ được dịch `text`. JSON sai cấu trúc, thiếu/thừa/trùng ID, đổi thứ tự hoặc timestamp sẽ được yêu cầu làm lại, tối đa 3 lần. Khi dịch tiếp phiên cũ, backend đọc hồ sơ cũ và chuyển sang cấu trúc mới cho model, giữ nguyên file hồ sơ và các batch đã lưu. Muốn tạo hồ sơ mới bằng prompt mới, chọn **Dịch lại**.
4. **QC:** ngắt dòng tại khoảng trắng, ưu tiên dấu câu/liên từ; mặc định 40 ký tự/dòng, tối đa 2 dòng. Câu không vừa được gửi lại model để rút gọn theo nghĩa. Nếu vẫn không đạt, phiên dịch báo lỗi và không cho xuất SRT.
5. **Xuất:** ghép đúng thứ tự, kiểm tra SRT một lần nữa; tải `translated.srt`, `memory.json`, `qc.json` và xem trước 30 câu đầu.

Prompt ngữ cảnh yêu cầu căn cứ trong đoạn SRT, thống nhất tên Hán–Việt, phân biệt tên riêng/chức danh và chọn một cặp xưng hô mặc định cho từng chiều quan hệ. Prompt dịch chỉ áp dụng ma trận khi xác định được người nói/người nghe; khi thiếu căn cứ, ưu tiên lược đại từ tự nhiên hoặc giữ danh xưng có trong câu gốc. Khi rút gọn, phải giữ phủ định, điều kiện, số liệu, ý nghĩa và sắc thái; không chuyển nội dung sang câu khác. Các quy tắc này hướng dẫn model; QC tự động vẫn chỉ kiểm tra cấu trúc và độ dài. Sau khi đổi prompt, khởi động lại dịch vụ; **Dịch tiếp** giữ hồ sơ/batch cũ, **Dịch từ đầu** tạo hồ sơ mới.

Thông số cố định tại backend: `PIPELINE_DEFAULTS` trong `translation_pipeline.py` dùng batch 35 câu, overlap 3 câu, mẫu ngữ cảnh 120 câu, 4 batch đồng thời và 40 ký tự/dòng, tối đa 2 dòng. `MODEL_MAX_TOKENS` trong `translation_ai.py` đặt 8192 token đầu ra cho mỗi model. Giao diện không gửi các thông số này; backend bỏ qua giá trị ghi đè từ request. SRT phải có ID tăng dần (không bắt buộc liên tục); timestamp giữ nguyên, kể cả khoảng chồng lấn giữa các câu. Giới hạn file là 2 triệu ký tự/10.000 câu. Câu quá dài và JSON lỗi có thể phát sinh thêm lượt API. QC kiểm tra cấu trúc và độ dài; chất lượng nghĩa/xưng hô vẫn cần người xem duyệt.

Backend gồm `translation_srt.py` (parser/format/export), `translation_ai.py` (provider/API/JSON), `translation_pipeline.py` (ngữ cảnh, dịch, QC, phiên chạy). `translation_ui.html` chỉ thu thập cấu hình/file, gọi backend và hiển thị/tải kết quả. Không có logic dịch hoặc kiểm định SRT ở JavaScript.

Mỗi lần chỉ chạy một file, các batch bên trong chạy song song. Tiến độ tiếp tục khi tải lại trang; sau khi đóng dịch vụ có thể mở lại rồi bấm **Dịch tiếp**. Nút **Hủy phiên dịch** ngừng các batch chưa gửi, ngắt kết nối API đang chờ và giữ các batch đã lưu để Dịch tiếp. File gốc, Memory, checkpoint và kết quả nằm tại `.local/translations/<id>/`; không ghi đè phụ đề gốc. Bản dịch hoàn tất được cung cấp cho player iQIYI qua track Tiếng Việt AI. API key được lưu trong localStorage của trình duyệt cùng cấu hình; backend không ghi key vào hồ sơ dịch hay báo cáo. Nội dung phụ đề được gửi tới provider đã cấu hình. HTTP chỉ được hỗ trợ cho endpoint localhost; endpoint từ xa phải dùng HTTPS.

Định dạng API tham khảo: [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [Anthropic Messages](https://platform.claude.com/docs/en/api/overview), [Qwen tương thích OpenAI](https://www.alibabacloud.com/help/en/model-studio/compatibility-of-openai-with-dashscope).

## Bản desktop webapp cho Windows

Trong thư viện, tên Việt được lấy từ metadata iq.com đã đối chiếu đúng phim; tên gốc hiển thị bên dưới. Luồng phụ đề iq.com phục vụ trực tiếp player: `/api/official-subtitle-state` lấy trạng thái, backend gọi iq.com và căn thời gian theo cuối video, rồi `/subtitle.xml?source=iqcom&tvid=...` trả XML cho track **Tiếng Việt iq.com**. Đăng nhập iq.com trong trình duyệt đã cài tiện ích rồi bấm **Kiểm tra iq.com** để đồng bộ phiên khi tập yêu cầu quyền xem. Phụ đề iq.com được giữ trong cache của dịch vụ, không có chức năng tải iq.com thành file trong webapp. Tải lại thư viện không khởi chạy yêu cầu phụ đề cho toàn bộ các tập.

Giải nén toàn bộ gói `IQIYI-VI-Windows-x64.zip` vào thư mục có quyền ghi, rồi mở **IQIYI-VI.exe**. Bản này kèm Python và các thư viện cần thiết; không cần cài Python hay chạy terminal. Cần Windows 10/11 x64 và Edge hoặc Chrome.

Phụ đề, cài đặt, token và bản sao lưu được lưu cạnh file `.exe`. Gói tải về không chứa thư viện phim hay phiên đăng nhập của người tạo bản build. Không đặt app trong `Program Files` hoặc chạy trực tiếp từ trong file ZIP.

Đóng cửa sổ vẫn giữ dịch vụ phụ đề chạy để phục vụ player. Các lệnh tùy chọn:

```powershell
.\IQIYI-VI.exe iqiyi    # Mở iQIYI cùng webapp
.\IQIYI-VI.exe youku    # Mở Youku cùng webapp
.\IQIYI-VI.exe restore  # Khôi phục giao diện gốc
.\IQIYI-VI.exe stop     # Dừng dịch vụ
```

Chỉ chạy một bản quản lý tại một thời điểm vì player dùng cổng `18766`. Khi chuyển từ bản mã nguồn sang bản portable, dừng dịch vụ cũ trước. Dữ liệu không được tự động di chuyển. Muốn giữ thư viện và cài đặt, sao lưu rồi chép `subtitles/library/`, `.local/`, `backup-skin/`, `backup-lwa/`, `backup-ppstream.ini` và `.iqiyi-install-location` từ bản cũ sang bản mới khi cả hai dịch vụ đã dừng. Giữ bản sao lưu giao diện để thao tác khôi phục tiếp tục hoạt động.

Để tự build trên Windows bằng CPython x64 đã có pip:

```powershell
python build-desktop.py
```

Kết quả nằm trong `dist/IQIYI-VI-Windows-x64/` và file ZIP cạnh thư mục này. Script từ chối ghi đè thư mục đã có để bảo vệ dữ liệu; dùng `--output` để chọn tên khác. Chạy `IQIYI-VI.exe --check` để kiểm tra gói mà không mở player hoặc thư viện.

## Cài đặt từ mã nguồn

Yêu cầu Windows 10/11, Python 3.10 trở lên, iQIYI desktop hoặc Youku.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe launcher.py iqiyi
```

Mở iQIYI qua launcher để bộ Việt hóa được gắn trước khi trang bắt đầu chạy. Ô tìm kiếm hỗ trợ tên phim Việt có dấu hoặc không dấu. Bộ Việt hóa đối chiếu tên đã biết và danh mục iq.com; chỉ đổi sang tên gốc khi khớp duy nhất một phim. Nhập một phần tên hoặc tên gõ sai nhẹ rồi bấm Tìm/Enter để xem tối đa 5 gợi ý.

Thay `iqiyi` bằng:

- `youku`: mở Youku.
- `open-manager`: chỉ mở app quản lý phụ đề.
- `restore`: khôi phục giao diện iQIYI gốc.

Trong app quản lý, vào **Thông báo** và chọn **Chấp nhận** để thêm phim mới vào thư viện. Chọn tập để tải hoặc xem phụ đề gốc đã lưu.

## Tiện ích Chrome / Edge

1. Mở `chrome://extensions` hoặc `edge://extensions`.
2. Bật **Chế độ dành cho nhà phát triển**.
3. Chọn **Tải tiện ích đã giải nén** và trỏ tới thư mục `ext/`.
4. Tải lại trang iQIYI để dùng bộ Việt hóa giao diện và phụ đề Việt chính thức nếu có.

Để lấy phụ đề Việt chính thức từ iq.com, đăng nhập iq.com trên trình duyệt đã cài tiện ích, rồi bấm **Kiểm tra iq.com** trong app quản lý. Tài khoản cần có quyền xem tập đó; không phải tập nào cũng có track Việt.

Khi chuyển sang máy khác, dùng phiên đăng nhập iq.com của máy đó và tải tiện ích từ thư mục `ext/` cạnh app đang chạy. Mở app quản lý trước để tạo cấu hình kết nối, rồi tải lại tiện ích và bấm **Kiểm tra iq.com** trong cùng hồ sơ trình duyệt. Tên phim công khai không cần đăng nhập; phụ đề chính thức phụ thuộc quyền xem tập và khu vực.

Chrome/Edge mới: dùng tiện ích từ bản 1.2.37 trở lên. Các yêu cầu tên phim và phụ đề được gửi qua service worker của tiện ích bằng quyền host có sẵn. Sau khi cập nhật, mở lại app quản lý, bấm **Tải lại** tiện ích trong trang quản lý tiện ích của Chrome/Edge, rồi tải lại trang iQIYI. Khi đổi trình duyệt, mở trang quản lý phụ đề trong trình duyệt mới và bấm **Kiểm tra iq.com** để chọn đúng phiên đăng nhập của trình duyệt đó.

## Lưu ý

- Phụ đề chưa tải giữ nguyên trạng thái gốc. Dịch AI chỉ chạy khi bạn nhập file và bấm **Bắt đầu dịch**.
- Sau khi cập nhật, tải lại tiện ích và trang web; mở lại ứng dụng bằng launcher.
- Nút **Proxy** trong app quản lý áp dụng cho player iQIYI. Đổi proxy sẽ mở lại iQIYI và có thể ngắt video đang xem; giữ app quản lý chạy khi dùng proxy.
- Giữ `backup-skin/` và `backup-lwa/` để có thể khôi phục giao diện gốc.
- Không chia sẻ `.iqiyi-vi-token`, `ext/proxy-token.json` hoặc `.local/` vì có thể chứa token và phiên đăng nhập. Phụ đề được lưu tại `subtitles/library/`.

Dự án dành cho mục đích cá nhân, không liên kết với iQIYI / Youku và không phân phối phụ đề hay tài nguyên thương mại. Sử dụng theo điều khoản của từng nền tảng.
