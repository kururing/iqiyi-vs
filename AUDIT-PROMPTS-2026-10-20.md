# Audit toàn bộ prompt — 20/10/2026

Rà soát working tree của `D:\App\iqiyi-vi`, gồm thay đổi chưa commit. Audit ban đầu có **8 phát hiện: 1 P1, 5 P2, 2 P3**. **Đã áp dụng sửa cả 8 phát hiện**; phần mô tả đánh số bên dưới lưu lại trạng thái trước khi sửa.

| Phát hiện | Cách xử lý đã áp dụng |
| --- | --- |
| 1 | Kiểm tra trường/kiểu/schema tại mọi lần thử; gộp theo name/source, giữ mục bị bỏ sót; chỉ ghi cache sau khi ứng viên được kiểm tra và gộp thành công |
| 2 | Không còn xóa chữ Hán để sửa dữ liệu; tên/thuật ngữ Việt rỗng bị từ chối; hết lượt thử thì giữ hồ sơ cũ; file hồ sơ cũ bị hỏng được báo lỗi và giữ nguyên |
| 3 | Chỉ nhận kết quả có ID rõ ràng; mảng thiếu ID không được suy ra theo vị trí |
| 4 | Đo chính xác JSON được chọn; giảm block hồ sơ, chia lô dịch theo kích thước thực; giữ nguyên source và ID |
| 5 | Tách nhãn Việt với `_original`, ghi trạng thái tên phim confirmed/unconfirmed, không fallback tên tập Việt sang chữ Hán |
| 6 | Ví dụ ghi đúng người gọi/người nghe và bằng chứng cùng chiều, bỏ quan hệ em họ chưa được chứng minh |
| 7 | Tách quy tắc lập hồ sơ và dịch; bước dịch chỉ có id/translation, không bị yêu cầu ghi uncertainty/glossary |
| 8 | Thêm confirmedNames do người dùng quản lý ngoài output model, áp dụng khóa ở backend; tên tạm chỉ sửa trong hồ sơ khi có evidence mới và ghi chú tên cũ → mới |

Đã tăng phiên bản prompt, hỗ trợ giữ memory từ v13 khi phân tích lại, thêm độ phủ và định danh tập vào payload hồ sơ, cùng thời lượng cue vào payload dịch. Không tự sửa thư viện hiện có hoặc dịch lại phụ đề đã lưu.

Kiểm chứng sau sửa: **8 nhóm hồi quy** trong `audit-prompts-check.py` và **6 script Python có sẵn** (`test-album-title.py`, `test-iqiyi-network.py`, `test-p1.py`, `test-p2.py`, `test-session.py`, `test-signed-lwa.py`) đạt. Các ca mới chạy hoàn toàn offline, mock provider, có kiểm tra toàn luồng chia lô/song song/lưu/dịch tiếp. Chưa benchmark model thật. `README.md` và `.env.example` đã mô tả budget và cơ chế khóa tên.

P1: ưu tiên sửa vì có thể ghi mất dữ liệu liên tục đã lưu. P2: ảnh hưởng tính đúng hoặc độ tin cậy trong điều kiện nêu rõ. P3: yêu cầu mâu thuẫn hoặc chưa thể thực hiện đầy đủ, cần làm rõ hợp đồng prompt.

## Phạm vi và bản đồ prompt

Đã tìm khai báo và nơi sử dụng prompt trong mã Python, JavaScript, JSON, tài liệu và script phát triển của dự án. Không thấy luồng gọi model nào khác ngoài hai luồng dưới đây. Không coi prompt của thành phần trình duyệt bên thứ ba trong `.tmp/` là prompt ứng dụng; không audit lại dữ liệu backup, khóa API hay nội dung toàn bộ thư viện phụ đề cá nhân.

| Thành phần | Nơi khai báo / lắp ghép | Vai trò |
| --- | --- | --- |
| `ADDRESS_RULES` | [subtitle_agent.py:25](D:/App/iqiyi-vi/subtitle_agent.py:25) | Xác định người nói/nghe, chiều xưng hô, quan hệ và sắc thái |
| `CHARACTER_NAME_RULES` | [subtitle_agent.py:57](D:/App/iqiyi-vi/subtitle_agent.py:57) | Tên người, biệt danh, âm Hán–Việt và tính nhất quán |
| `WORK_NAME_RULES` | [subtitle_agent.py:70](D:/App/iqiyi-vi/subtitle_agent.py:70) | Tên tác phẩm chính thức và cách đọc tạm |
| `PROFILE_SYSTEM` | [subtitle_agent.py:98](D:/App/iqiyi-vi/subtitle_agent.py:98) | Hồ sơ phim và ngữ cảnh tập; nối cả ba khối quy tắc trên |
| `profile_prompt()` | [subtitle_agent.py:356](D:/App/iqiyi-vi/subtitle_agent.py:356) | Metadata phim, bộ nhớ cũ, lời thoại đã chọn và phản hồi yêu cầu sửa |
| `memory_context()` | [subtitle_agent.py:383](D:/App/iqiyi-vi/subtitle_agent.py:383) | Đưa hồ sơ phim/ngữ cảnh tập sang luồng dịch |
| `TRANSLATION_SYSTEM` | [subtitle_app.py:691](D:/App/iqiyi-vi/subtitle_app.py:691) | Dịch từng cue; nối cả ba khối quy tắc chung |
| `translation_prompt()` | [subtitle_app.py:1580](D:/App/iqiyi-vi/subtitle_app.py:1580) | Metadata, bộ nhớ, cửa sổ source, bản nháp lân cận và ID cần dịch |
| `_chat_payload()` | [subtitle_app.py:848](D:/App/iqiyi-vi/subtitle_app.py:848) | Bổ sung quy tắc JSON/schema và wrapper `results` theo chế độ API |

Đã đối chiếu cả schema, bộ chuẩn hóa, vòng thử lại, cache hồ sơ và nơi ghi kết quả. `titles-vi.json` là dữ liệu hỗ trợ chọn tên; `international_reference()` không được gọi từ luồng sinh bản dịch hiện tại.

## 1. [P1] Hồ sơ thiếu dữ liệu được nhận rồi ghi đè bộ nhớ phim

**Vị trí:** [subtitle_agent.py:224](D:/App/iqiyi-vi/subtitle_agent.py:224), [subtitle_agent.py:274](D:/App/iqiyi-vi/subtitle_agent.py:274), [subtitle_app.py:1727](D:/App/iqiyi-vi/subtitle_app.py:1727), [subtitle_app.py:1742](D:/App/iqiyi-vi/subtitle_app.py:1742).

Prompt yêu cầu giữ nhân vật và thông tin cũ có căn cứ. Nhưng `repair=False` vẫn cho phép thiếu hầu hết trường bắt buộc: `memory={"summary":"Tập mới."}` trở thành hồ sơ hợp lệ với `characters=[]`, `glossary=[]`. `episode_context={}` cũng được chấp nhận. Caller thay toàn bộ memory cũ, ghi xuống đĩa và đánh dấu tập đã phân tích thành công.

**Tái hiện:** hồ sơ cũ chứa nhân vật Hạ Hầu và glossary; mock model trả `{"memory":{"summary":"Tập mới."},"episode_context":{}}`. Sau `ensure_agent_profile()`, file hồ sơ mất nhân vật/glossary và có fingerprint tập mới. Một phản hồi đủ khóa theo schema nhưng trả các mảng rỗng cũng vượt kiểm tra hiện tại; vì thế structured output không bảo đảm giữ dữ liệu liên tục.

**Hướng sửa:** kiểm tra đầy đủ trường khi `repair=False`; trước khi thay memory, đối chiếu các nhân vật/thuật ngữ đã lưu. Giữ mục cũ khi phản hồi chỉ bỏ sót; trường hợp sửa/xóa do bằng chứng mới cần có cơ chế phân biệt rõ. Không coi phản hồi thiếu dữ liệu là hồ sơ thành công để cache.

## 2. [P2] Lần thử sau xóa chữ Hán thay vì sửa tên, rồi lưu thành hồ sơ hợp lệ

**Vị trí:** [subtitle_agent.py:197](D:/App/iqiyi-vi/subtitle_agent.py:197), [subtitle_agent.py:250](D:/App/iqiyi-vi/subtitle_agent.py:250), [subtitle_app.py:1726](D:/App/iqiyi-vi/subtitle_app.py:1726).

Lần đầu yêu cầu model viết lại trường tiếng Việt có chữ Hán. Từ lần thứ hai, `repair=True` dùng `_strip_han()`: `translation="夏侯"` trở thành chuỗi rỗng; mục nhân vật vẫn tồn tại vì còn `name`, `role` hoặc `evidence`. Không thêm uncertainty và không yêu cầu model dịch lại tên này.

**Tác động:** hồ sơ có tên/quan hệ bị thiếu hoặc mất một phần ý vẫn được lưu, trong khi prompt dịch yêu cầu chép chính xác tên và thuật ngữ của hồ sơ. Đây là mất nội dung trong bước chuẩn hóa, không phải Việt hóa tên.

**Hướng sửa:** tiếp tục từ chối các trường nội dung thiết yếu chưa dịch; giữ tên cũ hợp lệ nếu có. Nếu phải fallback, đánh dấu mục chưa xác định và không thay dữ liệu tốt bằng chuỗi đã bị cắt mất nghĩa.

## 3. [P2] Phản hồi không có ID vẫn được ghép theo vị trí và nhận làm bản dịch

**Vị trí:** [subtitle_app.py:737](D:/App/iqiyi-vi/subtitle_app.py:737), [subtitle_app.py:1655](D:/App/iqiyi-vi/subtitle_app.py:1655).

Prompt yêu cầu giữ ID, cấm đổi số và dịch đúng source cạnh từng ID. Tuy nhiên, nếu số phần tử khớp, validator tự gán ID cho mảng chuỗi hoặc object thiếu ID. Với các ID không liên tiếp sau khi dịch tiếp/thử lại, không còn dữ liệu để xác nhận model trả đúng thứ tự.

**Tái hiện:** yêu cầu `[101,102]`, nhận `["Câu của id 102","Câu của id 101"]`; kết quả được chấp nhận thành `101 → câu 102`, `102 → câu 101`.

**Hướng sửa:** yêu cầu mỗi kết quả có ID xác thực được. Phản hồi thiếu ID phải được sửa/thử lại; không suy ra ID chỉ từ số lượng phần tử. Các chế độ fallback vẫn phải giữ hợp đồng này.

## 4. [P2] Bộ chọn context có thể vượt giới hạn đã cấu hình

**Vị trí:** [subtitle_agent.py:314](D:/App/iqiyi-vi/subtitle_agent.py:314), [subtitle_app.py:1546](D:/App/iqiyi-vi/subtitle_app.py:1546), [subtitle_app.py:1767](D:/App/iqiyi-vi/subtitle_app.py:1767).

`_fit_episode()` chọn ít nhất một block 40 cue dựa vào kích thước trung bình, không đo lại tổng kích thước block được chọn. `context_window()` luôn giữ toàn bộ cue thuộc lô yêu cầu ngay cả khi riêng lô đó đã vượt limit. Caller không chia nhỏ lô theo kích thước thực tế.

**Tái hiện:** 80 cue, mỗi cue 500 ký tự, đặt budget 1.000 ký tự; profile selector trả 40 cue với JSON dài **20.872 ký tự**. Cửa sổ dịch cũng trả nguyên 40 cue khi được yêu cầu, dù vượt budget tương tự. Mức 1.000 là cấu hình hợp lệ cho profile; giới hạn dịch tối thiểu lớn hơn nhưng vẫn có cùng nhánh vượt limit khi lô đủ dài.

**Tác động:** giảm context budget không bảo đảm request nhỏ đi đúng mức; với endpoint giới hạn context, request có thể bị từ chối và lặp lại cùng kích thước. System, metadata và memory cũng nằm ngoài các budget source này, nên chúng không phải giới hạn tổng request.

**Hướng sửa:** đo tổng kích thước thật của các đoạn được chọn; cho phép block nhỏ hơn 40. Nếu source bắt buộc của lô đã quá lớn, chia lô trước khi gửi và giữ nguyên ID; không cắt mất nội dung cue. Tách rõ budget lời thoại và budget tổng request.

## 5. [P2] Metadata chứa tiếng Trung dù system khẳng định đã là tiếng Việt

**Vị trí:** [subtitle_agent.py:76](D:/App/iqiyi-vi/subtitle_agent.py:76), [subtitle_app.py:1569](D:/App/iqiyi-vi/subtitle_app.py:1569), [subtitle_app.py:1584](D:/App/iqiyi-vi/subtitle_app.py:1584).

`WORK_NAME_RULES` nói `metadata.series_title` và `metadata.episode_title` đã là tiếng Việt. Nhưng khi không tìm được tên Việt, builder đưa tên phim gốc vào `series_title`. Với tập/đặc biệt không nhận diện được số tập, `episode_title_vi()` trả rỗng khi thấy chữ Hán, rồi builder lại dùng chính `item.title` tiếng Trung làm fallback.

**Tái hiện:** phim chưa có trong bảng tên và tập tên `特别篇` tạo metadata có chữ Hán ở cả hai trường.

**Tác động:** model nhận khai báo ngôn ngữ trái với dữ liệu. Điều này đặc biệt liên quan các quy tắc giữ nguyên tên đã xác nhận và không dịch lại metadata. Việc model thực tế có đưa sai tên vào cue hay không cần kiểm thử AI riêng.

**Hướng sửa:** tách tên gốc và tên Việt thành các trường riêng, gắn rõ trạng thái tên đã xác nhận. Với tiêu đề tập không có tiếng Việt, bỏ trường hoặc dùng nhãn trung tính; sửa lời khẳng định trong system cho đúng payload.

## 6. [P2] Ví dụ hồ sơ chưa khớp chiều xưng hô với bằng chứng

**Vị trí:** [subtitle_agent.py:130](D:/App/iqiyi-vi/subtitle_agent.py:130).

Ví dụ cho nhân vật Mạn Nhi ghi `Mạn Nhi → Thanh Lan: gọi là tỷ, tự xưng muội`, nhưng evidence lại là `#12, #15: bị gọi là tỷ`. Trong chiều xưng hô được minh họa, người được gọi là tỷ là Thanh Lan, nhưng evidence đang mô tả Mạn Nhi bị gọi là tỷ; nó không chứng minh chiều gọi đã ghi. Hai người vẫn có thể được người khác gọi là tỷ trong những lượt khác nhau, nên cần nêu rõ ai gọi ai. Ví dụ cũng đưa quan hệ “em họ” và tự xưng “muội” mà bằng chứng được minh họa không xác nhận đủ các điều đó.

**Tác động:** ví dụ không minh họa đúng trọng tâm của `ADDRESS_RULES`: phải giữ đúng chiều và không suy quan hệ/giới tính từ một lời gọi. Đây là vấn đề của nội dung hướng dẫn; chưa đo mức ảnh hưởng đến model thật.

**Hướng sửa:** dùng evidence cùng chiều, ví dụ “#12: Mạn Nhi gọi Thanh Lan là tỷ; #15: Mạn Nhi tự xưng muội”. Chỉ ghi “em họ” nếu ví dụ cũng cấp bằng chứng tương ứng, hoặc bỏ quan hệ cụ thể.

## 7. [P3] Quy tắc chung yêu cầu ghi trường không có trong output dịch

**Vị trí:** [subtitle_agent.py:62](D:/App/iqiyi-vi/subtitle_agent.py:62), [subtitle_agent.py:64](D:/App/iqiyi-vi/subtitle_agent.py:64), [subtitle_agent.py:73](D:/App/iqiyi-vi/subtitle_agent.py:73), [subtitle_app.py:740](D:/App/iqiyi-vi/subtitle_app.py:740), [subtitle_app.py:746](D:/App/iqiyi-vi/subtitle_app.py:746).

Các khối chung được nối nguyên vào cả hai system. Chúng yêu cầu “ghi vào uncertainties” và lưu tên vào `characters.translation`/`glossary.translation`. Nhưng output dịch chỉ cho `id` và `translation`; schema còn cấm trường khác. Luồng dịch cũng không có thao tác ghi ngược cập nhật này vào hồ sơ.

**Tác động:** khi tên hoặc tên phim chưa chốt xuất hiện trong lô dịch, model không thể vừa ghi uncertainty/cập nhật hồ sơ vừa tuân thủ schema. Với strict schema, phần ghi chú bị bỏ; với chế độ prompt có nguy cơ phản hồi thừa trường hoặc lời giải thích. Chưa có bằng chứng rằng mọi model đều chọn cùng cách xử lý.

**Hướng sửa:** tách hướng dẫn cho bước lập hồ sơ và bước dịch. Chỉ bước hồ sơ ghi uncertainty/glossary; bước dịch áp dụng dữ liệu đã có và có quy tắc fallback diễn đạt rõ ràng cho tên chưa chốt.

## 8. [P3] Chưa thống nhất khi nào giữ hay sửa cách Việt hóa cũ

**Vị trí:** [subtitle_agent.py:117](D:/App/iqiyi-vi/subtitle_agent.py:117), [subtitle_agent.py:65](D:/App/iqiyi-vi/subtitle_agent.py:65), [subtitle_app.py:715](D:/App/iqiyi-vi/subtitle_app.py:715).

Phần định nghĩa `characters.translation` yêu cầu giữ tên cũ, chỉ đổi nếu source chứng minh nhầm danh tính hoặc có chỉ dẫn sửa cụ thể. Khối quy tắc nối phía sau lại yêu cầu sửa tên cũ khi sai rõ ràng với đúng chữ nguồn — có thể chỉ là sai âm Hán–Việt, không nhầm danh tính. System dịch đồng thời yêu cầu “chép chính xác” hồ sơ và kiểm tra lại tên theo quy tắc chung.

Schema hiện không đánh dấu tên do người dùng xác nhận hay tên do model tự đề xuất, nên thứ tự ưu tiên “người dùng xác nhận → đã kiểm chứng → quy tắc chung” không được hỗ trợ rõ bằng dữ liệu.

**Hướng sửa:** thống nhất một quy tắc giữ/sửa tên cho cả hai giai đoạn; phân biệt tên đã được người dùng khóa với tên tạm do model chọn. Thay đổi tên đã xác nhận cần được ghi nhận cụ thể; tên tạm sai âm được sửa có lý do trong bước hồ sơ.

## Những điểm đã làm tốt và các cải thiện tiếp theo

- Có ranh giới dữ liệu/chỉ dẫn rõ trong cả hai system; JSON đóng gói source, metadata và memory. Không phát hiện đường gọi tool hay thực thi mã theo lời thoại. Điều này không thay thế kiểm thử prompt injection với model thật.
- Có ưu tiên giữ nghĩa, chủ thể, phủ định và số liệu trước phong cách; quy tắc đa người nói trong một cue và quan hệ có chiều được mô tả cụ thể.
- Có schema đầu ra, wrapper `results` nhất quán tại adapter, phát hiện output bị cắt và lọc các ID trùng với nội dung khác nhau.
- Prompt có phiên bản và cache context riêng từng tập. Bản dịch đã lưu chỉ gắn `sourceHash`, **không tự dịch lại khi prompt đổi**; mã đã chú thích đây là chính sách hiện tại. Nên lưu thêm phiên bản sinh để người dùng nhận biết bản dịch cũ, thay vì tự xóa kết quả.
- System profile dài **11.743 ký tự**, system dịch dài **13.010 ký tự** trước user payload. Các quy tắc tên/xưng hô có nhiều phần lặp. Có thể rút gọn sau khi xử lý mâu thuẫn, rồi so sánh trên cùng bộ câu kiểm chuẩn; không thể kết luận “ngắn hơn dịch tốt hơn” chỉ từ số ký tự.
- Với dữ liệu giả lập 1.000 cue, budget profile mặc định 8.000 ký tự chọn **200 cue**. Payload có thông báo đây là mẫu, nhưng system vẫn mô tả nhiệm vụ đọc toàn bộ tập. Nên thống nhất mô tả và đánh dấu độ phủ; trường hợp cần nhận diện quan hệ đầy đủ nên cân nhắc xử lý theo đoạn thay vì chỉ lấy mẫu cách đều.
- Chưa có giới hạn độ dài/nhịp đọc dựa vào thời lượng cue. Luồng dịch chỉ gửi thời điểm bắt đầu, không gửi thời điểm kết thúc. Nếu mục tiêu là chất lượng phụ đề theo thời gian, cần truyền duration và kiểm tra độ dài ở hậu xử lý; đây là cải tiến sản phẩm, không phải lỗi JSON.
- Evidence lưu theo chuỗi tự do như `#12` có thể thiếu định danh tập khi tích lũy xuyên tập. Nên chuẩn hóa tối thiểu “tập + cue + chiều quan hệ” để bằng chứng không bị hiểu là cue cùng số của tập đang dịch.

## Kiểm chứng và giới hạn

Chạy:

```powershell
.\.venv\Scripts\python.exe audit-prompts-check.py
```

[audit-prompts-check.py](D:/App/iqiyi-vi/audit-prompts-check.py) hiện gồm **8 nhóm kiểm tra hồi quy** cho hành vi sau sửa, thay thế các assertions tái hiện lỗi của lượt audit ban đầu. Script mock phản hồi model, chặn `urllib.request.urlopen`, dùng thư mục tạm cho hồ sơ và không đọc khóa API.

Phát hiện 8 được đối chiếu trực tiếp giữa các điều khoản prompt. Các nhận xét về ảnh hưởng lên văn phong, xưng hô và hành vi model là đánh giá rủi ro từ hợp đồng đầu vào/đầu ra; không phải kết quả benchmark model. Không gọi AI thật, không sửa thư viện phụ đề, không chạy apply/restore hoặc thay đổi client đã cài.

Thứ tự xử lý đề xuất: bảo toàn memory (1–2) → xác thực ID và giới hạn context (3–4) → metadata và ví dụ xưng hô (5–6) → tách quy tắc theo giai đoạn và thống nhất tên (7–8). Khi đổi system/schema, cập nhật phiên bản phù hợp và quyết định riêng việc xử lý hồ sơ cũ đã bị mất dữ liệu; cache mới không tự khôi phục thông tin đã bị ghi đè.
