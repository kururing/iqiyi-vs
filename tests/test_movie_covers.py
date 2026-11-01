"""Movie artwork shares the asynchronous title lookup and its persistent cache."""
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subtitle_app as app


class MovieCoversTest(unittest.TestCase):
    def test_discoveries_group_episodes_with_the_same_cached_album_cover(self):
        episodes = {str(n): {"tvid": str(n), "albumId": "12345601", "albumTitle": "Series"}
                    for n in (1, 2)}
        cached = {"12345601": (time.monotonic() + 3600, {"title": "Phim mới",
                  "coverUrl": "http://pic3.iqiyipic.com/poster.jpg"})}
        with patch.object(app, "EPISODES", episodes), \
                patch.object(app, "LIBRARY_ADMISSIONS", {}), \
                patch.object(app, "INTERNATIONAL_TITLE_CACHE", cached), \
                patch.object(app.TITLE_LOOKUP_POOL, "submit") as lookup:
            movies = app.pending_movies()
            self.assertEqual(len(movies), 1)
            self.assertEqual(movies[0]["episodes"], 2)
            self.assertEqual(movies[0]["title"], "Phim mới")
            self.assertEqual(movies[0]["albumCoverUrl"], app.series_cover_url(episodes["1"]))
            self.assertEqual(movies[0]["albumCoverUrl"], "https://pic3.iqiyipic.com/poster.jpg")
            lookup.assert_not_called()

    def test_cover_urls_only_allow_iqiyi_cdn_and_upgrade_https(self):
        for value in (None, {}, "javascript:alert(1)", "https://evil.test/a.jpg",
                      "https://pic.iqiyipic.com.evil.test/a.jpg",
                      "https://user:pass@pic.iqiyipic.com/a.jpg",
                      "https://pic.iqiyipic.com:9000/a.jpg", "https://[bad/a.jpg"):
            with self.subTest(value=value):
                self.assertEqual(app.movie_cover_url(value), "")
        for scheme in ("http:", "https:", ""):
            self.assertEqual(app.movie_cover_url(scheme + "//pic3.iqiyipic.com/a.jpg"),
                             "https://pic3.iqiyipic.com/a.jpg")

    def test_video_uses_album_artwork_instead_of_episode_thumbnail(self):
        calls = []

        def upstream(url):
            calls.append(url)
            if "/video/" in url:
                return {"code": "A00000", "data": {"albumId": "12345601", "name": "Series",
                        "imageUrl": "https://pic3.iqiyipic.com/episode.jpg"}}
            return {"code": "A00000", "data": {"name": "Series",
                    "imageUrl": "http://pic3.iqiyipic.com/poster.jpg"}}

        with patch.object(app, "INTERNATIONAL_TITLE_CACHE", {}), \
                patch.object(app, "public_iqiyi_json", side_effect=upstream):
            first = app.international_movie_title("12345678")
            second = app.international_movie_title("12345678")
        self.assertEqual(first["coverUrl"], "https://pic3.iqiyipic.com/poster.jpg")
        self.assertEqual(second, first)
        self.assertEqual(len(calls), 2, "Repeated polls must reuse the metadata cache")

    def test_old_cache_keeps_title_while_one_background_refresh_loads_cover(self):
        cached = {"12345601": (time.monotonic() + 3600, {"title": "Phim đã lưu"})}
        item = {"albumId": "12345601"}
        with patch.object(app, "INTERNATIONAL_TITLE_CACHE", cached), \
                patch.object(app, "INTERNATIONAL_TITLE_PENDING", set()), \
                patch.object(app.TITLE_LOOKUP_POOL, "submit") as submit:
            self.assertEqual(app.vietnamese_series_title(item), "Phim đã lưu")
            self.assertEqual(app.series_cover_url(item), "")
            submit.assert_called_once_with(app._load_international_series_title, "12345601")
            cached["12345601"][1]["coverUrl"] = "http://pic3.iqiyipic.com/poster.jpg"
            self.assertEqual(app.series_cover_url(item), "https://pic3.iqiyipic.com/poster.jpg")
            self.assertEqual(submit.call_count, 1)

    def test_expired_metadata_remains_visible_during_one_background_refresh(self):
        cached = {"12345601": (time.monotonic() - 1, {"title": "Tên Việt đã xác minh",
                  "sourceTitle": "测试剧", "coverUrl": "https://pic3.iqiyipic.com/poster.jpg"})}
        with patch.object(app, "INTERNATIONAL_TITLE_CACHE", cached), \
                patch.object(app, "INTERNATIONAL_TITLE_PENDING", set()), \
                patch.object(app.TITLE_LOOKUP_POOL, "submit") as submit:
            for _ in range(4):
                self.assertEqual(app.vietnamese_series_title({"albumId": "12345601"}), "Tên Việt đã xác minh")
                self.assertEqual(app.series_cover_url({"albumId": "12345601"}), "https://pic3.iqiyipic.com/poster.jpg")
            submit.assert_called_once_with(app._load_international_series_title, "12345601")

    def test_failed_refresh_keeps_known_artwork_without_delaying_retry(self):
        cached = {"12345601": (0, {"title": "Tên Việt đã xác minh", "sourceTitle": "测试剧",
                                  "coverUrl": "https://pic3.iqiyipic.com/poster.jpg"})}
        with patch.object(app, "INTERNATIONAL_TITLE_CACHE", cached), \
                patch.object(app, "public_iqiyi_json", side_effect=OSError("temporary timeout")), \
                patch.object(app.time, "monotonic", return_value=100):
            result = app.international_movie_title("12345601")
        self.assertEqual(result["title"], "Tên Việt đã xác minh")
        self.assertEqual(result["coverUrl"], "https://pic3.iqiyipic.com/poster.jpg")
        self.assertEqual(cached["12345601"][0], 110, "Retaining known metadata must not suppress the next retry")

    def test_new_source_identity_does_not_inherit_an_unrelated_cached_title(self):
        cached = {"12345601": (0, {"title": "Tên cũ", "sourceTitle": "旧剧",
                                  "coverUrl": "https://pic3.iqiyipic.com/old.jpg"})}

        def upstream(url):
            if "/album/album/" in url:
                return {"code": "A00000", "data": {"name": "新剧", "imageUrl": "https://pic3.iqiyipic.com/new.jpg"}}
            return {"code": 0, "data": {"epg": []}}

        with patch.object(app, "INTERNATIONAL_TITLE_CACHE", cached), \
                patch.object(app, "public_iqiyi_json", side_effect=upstream):
            result = app.international_movie_title("12345601")
        self.assertEqual(result["sourceTitle"], "新剧")
        self.assertEqual(result["title"], "")
        self.assertEqual(result["coverUrl"], "https://pic3.iqiyipic.com/new.jpg")


if __name__ == "__main__":
    unittest.main()
