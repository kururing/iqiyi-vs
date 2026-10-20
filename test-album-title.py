"""Run: python test-album-title.py (no network or library changes)."""
import io
import json
from unittest.mock import patch

import subtitle_app as app


def check():
    album_id = "3493131454654001"
    wrong_title = "无衣嘉鱼的混乱初遇"
    episodes = {
        "8493031186391200": {"albumId": album_id, "albumTitle": wrong_title},
        "1575955081636100": {"albumId": album_id, "albumTitle": wrong_title},
    }
    payload = {"code": "A00000", "data": {"albumId": album_id, "total": 2,
        "hasMore": False, "epsodelist": [
            {"tvId": int(tvid), "name": f"雀骨第{order}集", "subtitle": wrong_title,
             "order": order} for order, tvid in enumerate(episodes, 1)]}}
    with patch.object(app, "EPISODES", episodes), patch.object(app, "ALBUM_LISTS", {}), \
            patch.object(app, "atomic_write"), patch.object(app, "iqiyi_open",
                side_effect=lambda *args, **kwargs: io.BytesIO(json.dumps(payload).encode())):
        app.sync_album_list(album_id, wrong_title)
        assert app.ALBUM_LISTS[album_id]["stage"] == "ready"
        assert {item["albumTitle"] for item in episodes.values()} == {"雀骨"}
        # Later web/native registrations must not replace the verified album name.
        tvid = next(iter(episodes))
        app.save_episode(tvid, {**episodes[tvid], "albumTitle": wrong_title})
        assert episodes[tvid]["albumTitle"] == "雀骨"
        # Do not guess a common title from conflicting or unnumbered names.
        for names in (("雀骨第1集", "别的电影第2集"), ("第一集的描述", "第二集的描述")):
            for row, name in zip(payload["data"]["epsodelist"], names):
                row["name"] = name
            app.sync_album_list(album_id, "已知的片名")
            assert app.ALBUM_LISTS[album_id]["title"] == ""
        app.save_episode("yk-test", {"provider": "youku", "albumId": album_id,
                                    "albumTitle": "Youku title"})
        assert episodes["yk-test"]["albumTitle"] == "Youku title"


if __name__ == "__main__":
    check()
    print("PASS: album title repaired, later registrations guarded, ambiguous names preserved")
