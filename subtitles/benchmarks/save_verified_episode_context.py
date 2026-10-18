"""Save source-cited episode context without depending on a later episode summary."""
import copy
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import subtitle_app as app


def main():
    characters = [
        {'name': '连蔓儿', 'translation': 'Liên Mạn Nhi',
         'role': 'Nữ; con gái của người cha nói ở tập 3 câu 198.',
         'address': 'Mạn Nhi → Thẩm Nặc: ta/huynh khi đã xác định lượt nói; Thẩm Nặc → Mạn Nhi: ta và tên Mạn Nhi hoặc lược người nghe, không gọi huynh. Mạn Nhi → cha mẹ: con/cha, mẹ.',
         'evidence': 'Tập 2: 37 蔓丫头 你说你也是; 38 这姑娘家家的; 330 沈兄要住在这里; 333 沈兄. Tập 3: 198 我就蔓儿这么一个女儿.'},
        {'name': '沈诺', 'translation': 'Thẩm Nặc',
         'role': 'Nam; được gọi là 沈兄, 沈公子. Lời nhận con trong cảnh đầu tập 2 là diễn kịch, không chứng minh quan hệ vợ chồng.',
         'address': 'Thẩm Nặc → Mạn Nhi: ta/Mạn Nhi hoặc lược đại từ; không tự xưng em, không gọi người nữ là huynh. Mạn Nhi → Thẩm Nặc: ta/huynh khi xác định được lượt nói.',
         'evidence': 'Tập 2: 330 沈兄要住在这里; 333 沈兄; 337 别叨扰沈公子休息; 563 她并未与人私通; 564 也尚无子嗣.'},
        {'name': '连老爷子', 'translation': 'Liên lão gia tử',
         'role': 'Cha của các con trai trong nhà; ông nội của Mạn Nhi. Cần phân biệt 老大 theo góc nhìn người nói.',
         'address': 'Lão gia tử → con trai: cha/ta, con hoặc thằng cả/thằng hai. Con cháu → lão gia tử: cha hoặc gia gia theo thế hệ; không dùng chung đại bá cho 老大.',
         'evidence': 'Tập 3: 201 望爹做主; 202 三儿啊; 203 我必会让老大; 204 给你们一个交代; 210 爹答应了.'},
        {'name': '娘（蔓儿之母）', 'translation': 'Mẹ Mạn Nhi',
         'role': 'Mẹ Mạn Nhi; không đồng nhất mọi người gọi 娘 trong phim với một nhân vật.',
         'address': 'Mẹ → Mạn Nhi: mẹ/nương và con. Mạn Nhi → mẹ: con và mẹ/nương. Nhiều cue liên tiếp có thể cùng lượt; không tự luân phiên người nói.',
         'evidence': 'Tập 3: 298 走 跟娘回屋; 299 娘; 300 你回去睡吧; 306 娘陪会儿你.'},
    ]
    glossary = [{'source': '钱庄', 'translation': 'tiền trang'},
                {'source': '当铺', 'translation': 'tiệm cầm đồ'},
                {'source': '里正', 'translation': 'lý trưởng'},
                {'source': '恒哥儿', 'translation': 'Hằng ca'},
                {'source': '小儿郎（lời ru）', 'translation': 'cậu bé'},
                {'source': '爷奶', 'translation': 'ông bà nội'}]
    for ep, tid in [(2, '1249473580435700'), (3, '8192218992254200')]:
        folder = app.episode_dir(tid)
        source = app.parse_source((folder/'source.srt').read_text(encoding='utf-8-sig'), 'srt')
        memory = {'setting': 'mixed',
            'summary': ('Tập 2: cảnh đầu giả nhận con để chống hôn sự; các lời nhận quan hệ không phải dữ kiện thật. '
                        'Cảnh 493–511 là đối thoại mẹ/con gái về tranh công tử và việc tìm chồng; câu 500 người mẹ tự xưng 娘. '
                        'Cảnh cuối Mạn Nhi nhớ điện thoại và phim truyền hình, giữ độc thoại hiện đại.' if ep == 2 else
                        'Tập 3: sau vụ ép tuẫn táng, cha Mạn Nhi cầu ông nội phân xử. Lời ru nói về trẻ con. '
                        'Cuối tập gia đình bàn tiền trang và ruộng; Thẩm Nặc yêu cầu Mạn Nhi dọn phòng chứa củi, sau đó Mạn Nhi khen kế sách của Thẩm Nặc.'),
            'characters': copy.deepcopy(characters), 'glossary': copy.deepcopy(glossary),
            'uncertainties': ['Phụ đề không có nhãn người nói; không suy ra luân phiên theo từng cue.',
                'Câu 304–305 tập 3 và cảnh 493–495 tập 2 cần hình/giọng để xác nhận chính xác ranh giới đổi lượt.',
                'Tên cây 野腐婢 và cách gọi dược liệu 醋五味子 ở tập 2 cần đối chiếu chuyên biệt.']}
        profile = {'memory': app.agent.normalize_memory(memory), 'profileVersion': app.agent.PROFILE_VERSION,
                   'episodes': {tid: app.source_fingerprint(source)}, 'updatedAt': time.time()}
        snapshot = folder/'context-profile.json'
        if snapshot.exists():
            app.atomic_write(folder/'history'/('before-context-audit-'+str(time.time_ns()))/'context-profile.json', snapshot.read_bytes())
        app.atomic_write(snapshot, json.dumps(profile, ensure_ascii=False, indent=2))
        assert app.agent.load_episode_profile(folder, app.source_fingerprint(source)) == profile
    print('Saved verified per-episode context for episodes 2 and 3.')


if __name__ == '__main__':
    main()
