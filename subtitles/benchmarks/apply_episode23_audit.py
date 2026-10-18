"""Source-fingerprinted editorial corrections from the episode 2–3 audit."""
import json
from pathlib import Path
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import subtitle_app as app

EDITS = {
    '1249473580435700': ('5b8aeaec1cd245b8f34c046328b529821ccd4b8e06aaf629ddb8dd28ed17e56f', {
        11: ('Chúng ta...', '我们 là đại từ số nhiều, không phải lời gọi con.'),
        19: ('Ta từng nghe cô nhắc đến', 'Không có căn cứ gọi Mạn Nhi là ngài.'),
        20: ('người nhà họ Liên', 'Bỏ kính xưng các ngài không có trong quan hệ của cảnh.'),
        186: ('nhà họ gia nghiệp đồ sộ,', '家大业大 nói về gia sản và thế lực.'),
        251: ('Chân rung, rung lên.', '抖腿 là động tác rung chân trong cảnh tập ra vẻ hung dữ.'),
        253: ('Rung chân, thế này.', 'Giữ động tác 抖腿, không diễn giải thành sợ run.'),
        494: ('Đang xem gì vậy?', 'Chưa có nhãn người nói để chắc ranh giới đổi lượt; lược cách gọi mẹ/con.'),
        495: ('Hoa Nhi mang về cho ta đấy.', 'Giữ 我 là người nói, không tự gán mẹ/con khi chưa rõ lượt.'),
        680: ('Tam xoa khổ ba tiền,', 'Thống nhất tên 三叉苦 với câu 727.'),
        712: ('Cha ta không cho ta học y,', '我爹 là cha của người đang nói.'),
        713: ('ta đành phải gạt ông ấy', 'Người kể tự xưng, tiếp câu 712.'),
        715: ('Gần đây ta đang nghiên cứu một số', 'Không tự gán vai anh trong lời tự kể.'),
        766: ('Đừng vội động đao thương,', '刀枪 là đao thương trong cảnh cổ trang.'),
        906: ('Nhớ quá, nhớ quá,', '想 ở đây là nhớ/mong có lại chiếc điện thoại, nối với 907.'),
    }),
    '8192218992254200': ('8d9f003d29a181b2c5ed75186cab62b81781ab08ad718616d51389f49147ca2e', {
        8: ('Còn chưa nghĩ thử', '怎么想都没想: chưa suy nghĩ đã bảo không được, nối câu 9.'),
        14: ('hương thân có danh vọng ở địa phương,', '乡绅 là hương thân; hào sủng là sai từ.'),
        99: ('Gậy của ta!', '我棍 không phải lời chửi mẹ kiếp.'),
        112: ('Cần gì phải lắm lời?', '饶舌 là lắm lời, không phải lém lỉnh.'),
        129: ('Không sao chứ?', 'Không tự thêm tên người nghe khi nguồn chỉ hỏi 没事吧.'),
        150: ('Đa tạ lão gia,', 'Lời cảm ơn người phát cháo trong cảnh 149–151.'),
        191: ('Cha làm gì vậy?', 'Mạn Nhi hỏi cha đang quỳ; câu 192 gọi 爹.'),
        203: ('Ta nhất định sẽ bắt thằng cả', 'Người cha gọi con cả 老大, không gọi đại bá.'),
        214: ('Đứa trẻ không sao là tốt rồi.', '孩子 là người được nhắc đến, không tự đổi thành người nghe.'),
        228: ('Mấy ngày tới đừng động võ nữa.', 'Lời dặn sau khi chữa thương nói thời gian sắp tới.'),
        229: ('Cứ để Hằng ca luyện tay một chút đi.', '恒哥儿 là cách gọi thân mật, không phải tước vị.'),
        246: ('Mong là được như ý muốn.', 'Không gán huynh cho người vừa mong nhà họ Tôn bỏ qua.'),
        263: ('lần đầu làm chuyện trái phép thế này,', '越轨 nói hành vi vượt phép, không phải tình ái vượt rào.'),
        265: ('Hằng ca,', '恒哥儿 không phải Hằng gia tử.'),
        272: ('Tiền này ở đâu ra thế?', 'Lược đại từ khi không cần thiết, giữ câu hỏi nguồn.'),
        279: ('mà vẫn còn tâm trí moi tiền à?', '坑钱 là moi/lừa tiền, không có khái niệm tiền bẩn.'),
        305: ('Ngủ trước đi,', 'Không có nhãn người nói xác nhận điểm đổi lượt trước 306; lược đại từ giữ nghĩa.'),
        371: ('Trốn một hồi, lộ ra một cậu bé.', '小儿郎 trong lời ru là cậu bé, không phải tiểu lang quân.'),
        372: ('Bé ơi, bé ơi, đừng khóc,', '儿郎 trong lời ru trẻ con, không phải chồng.'),
        396: ('Cha và nhị ca ra đồng rồi.', 'Sửa ký tự 哥 còn sót trong tiếng Việt.'),
        413: ('cứu Hoa Nhi tỷ đi mà!', '你花儿姐姐 là tỷ của người nghe, giữ danh xưng tỷ.'),
        423: ('con và Hoa Nhi tỷ', 'Người lớn nói với Mạn Nhi về 花儿姐姐.'),
        431: ('đừng lấy đạo lý ra ép cháu.', '道德绑架 là dùng đạo lý gây sức ép; đáp người lớn trong họ.'),
        535: ('Nhìn lá bạch quả kia đẹp chưa.', 'Không kéo các thím từ nhóm trước sang lượt nói riêng.'),
        536: ('Nhìn... nhìn trời này,', 'Giữ tiếng lặp 你你 và không thêm các thím.'),
        537: ('rồi nhìn mặt đất này.', 'Tiếp lời đánh lạc hướng, không phải nói với các thím.'),
        538: ('Đang làm gì thế?', 'Lượt đáp riêng, không mang đại từ nhóm trước.'),
        583: ('định dụ mọi người chạy đến đó như thế à?', '跑去 là chạy đến nơi khác, không phải đến đây.'),
        632: ('trước bao nhiêu người chứng kiến,', '众目睽睽 là trước mắt đám đông, không chỉ ban ngày.'),
        642: ('Lý trưởng nói rất phải.', 'Thống nhất chức danh 里正.'),
        649: ('Lý trưởng cứ yên tâm,', 'Thống nhất chức danh 里正.'),
        661: ('tối hôm đó, sau khi lấy ra', 'Thẩm Nặc nhắc tiền Mạn Nhi để quên; không phải tiền Thẩm huynh lấy.'),
        662: ('rồi để trên bàn ấy à?', '搁在桌上的 tiếp lời nhắc số tiền để quên.'),
        680: ('Sao lại cuống lên thế?', 'Không thêm tên người nghe ngoài nguồn.'),
        719: ('trong đó có một miếng', 'Giữ cấu trúc qua các cue; không lặp ý câu 720–721.'),
        720: ('ngọc bội đắt tiền của nhà họ,', 'Giữ 值钱的玉佩 và sở hữu 他们家 từ câu trước.'),
        753: ('Đồ đàn bà phá gia này!', '娘们儿 chỉ người phụ nữ, không phải phá gia chi tử.'),
        786: ('rồi giúp thằng cả', 'Người cha nhắc con cả, không tự gọi là đại ca.'),
        869: ('cũng đâu phải cháu ruột của ông bà nội nó đâu!', '爷奶 là ông bà nội; giữ nguyên lời mỉa mai của nhân vật.'),
        870: ('Lão Nhị, bảo vợ con im miệng đi.', 'Cha gọi con thứ 老二, không xưng anh.'),
        874: ('Gia gia,', '爷 là gọi ông nội trong cảnh này.'),
        877: ('chẳng phải là chưởng quỹ tiền trang sao?', '钱庄 là tiền trang, khác tiệm cầm đồ 当铺.'),
        879: ('Tiền trong tiền trang đó tuyệt đối không thể vay đâu,', 'Phân biệt 钱庄 với 当铺.'),
        883: ('tuyệt đối không được hỏi vay tiền trang,', 'Phân biệt 钱庄 với 当铺.'),
        898: ('thằng cả,', 'Mẹ nói về con cả với chồng, không gọi đại bá.'),
        905: ('Gia gia sắp đi tìm lão Kim thúc', '爷爷 là ông nội, không phải Gia đứng riêng.'),
        910: ('Thế nhưng tiền trong sổ sách của tiền trang đó,', 'Phân biệt 钱庄 với 当铺.'),
        918: ('Ta chỉ nhờ', 'Thẩm Nặc nói với Mạn Nhi, không gọi người nữ là anh.'),
        919: ('dọn giúp ta gian chứa củi,', 'Tiếp lời nhờ dọn phòng; thống nhất tự xưng.'),
        921: ('Đang nghĩ gì thế?', 'Thẩm Nặc hỏi Mạn Nhi; bỏ anh sai chiều.'),
        931: ('Ta đồng ý với huynh.', 'Mạn Nhi đáp Thẩm Nặc; nguồn không có là được chứ gì.'),
        932: ('Vậy, việc vay tiền trang', 'Phân biệt 钱庄 với 当铺.'),
        934: ('Việc tiền trên sổ sách của tiền trang', 'Phân biệt 钱庄 với 当铺.'),
        945: ('Đúng là đầu óc huynh nhanh nhạy hơn.', 'Mạn Nhi khen Thẩm Nặc, không gọi người nam là cô.'),
    }),
}


def main():
    report = {'scope': 'Đối chiếu toàn bộ nguồn chữ tập 2–3; không có nhãn người nói hoặc video.',
              'episodes': [], 'unresolved': [
                  {'episode': 2, 'id': 417, 'source': '野腐婢',
                   'note': 'Tên cây: bản dịch hoa phù đàm chưa có căn cứ chắc chắn; cần kiểm tra nguồn/âm thanh.'},
                  {'episode': 2, 'id': 688, 'source': '醋五味子',
                   'note': 'Tên vị thuốc đã chế biến: cần xác minh cách gọi chuẩn; chưa tự sửa tên dược liệu.'}]}
    prepared = []
    for tid, (fingerprint, edits) in EDITS.items():
        folder = app.episode_dir(tid)
        req = urllib.request.Request('http://127.0.0.1:18766/api/translation-state?tvid='+tid,
                                     headers={'X-Iqiyi-Token': app.api_token(app.ROOT)})
        assert not json.load(urllib.request.urlopen(req, timeout=5)).get('translating'), 'Episode busy'
        source = app.parse_source((folder/'source.srt').read_text(encoding='utf-8-sig'), 'srt')
        assert app.source_fingerprint(source) == fingerprint, 'Source changed'
        state = app.load_translation_state(folder, source)
        assert len(state['translations']) == len(source)
        changes = [{'id': i, 'source': source[i-1][2], 'before': state['translations'][str(i)],
                    'after': text, 'reason': reason} for i, (text, reason) in edits.items()
                   if text != state['translations'][str(i)]]
        prepared.append((folder, source, state, changes))
        report['episodes'].append({'tvid': tid, 'sourceHash': fingerprint, 'cues': len(source), 'corrections': changes})
    if '--apply' in sys.argv:
        for record, (folder, source, state, changes) in zip(report['episodes'], prepared):
            backup = folder/'history'/('before-episode23-audit-'+str(time.time_ns()))
            for name in ('source.srt', 'translations.json', 'translated.srt'):
                app.atomic_write(backup/name, (folder/name).read_bytes())
            record['backup'] = str(backup)
            state['translations'].update({str(row['id']): row['after'] for row in changes})
            state.update(agentPending=False, agentReviewed=True, lastError='')
            app.save_translation_state(folder, state)
            output = [(start, end, state['translations'][str(i)]) for i, (start, end, _) in enumerate(source, 1)]
            app.atomic_write(folder/'translated.srt', app.to_srt(output))
            actual = app.parse_source((folder/'translated.srt').read_text(encoding='utf-8'), 'srt')
            assert actual == output
        app.atomic_write(ROOT/'subtitles/benchmarks/episode23-audit.json', json.dumps(report, ensure_ascii=False, indent=2))
    else:
        app.atomic_write(ROOT/'subtitles/benchmarks/episode23-audit-proposed.json', json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps([{'tvid': e['tvid'], 'cues': e['cues'], 'changes': len(e['corrections'])}
                      for e in report['episodes']], ensure_ascii=False))


if __name__ == '__main__':
    main()
