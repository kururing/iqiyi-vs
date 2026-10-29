"""Title-only UI fields must use an exact, unambiguous catalog record."""
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subtitle_app as app


class TitleNameTest(unittest.TestCase):
    def test_exact_search_keeps_official_title_for_the_live_suggestion(self):
        cached = {"12345601": (time.monotonic() + 3600,
                  {"title": "Dữ Tấn Trường An", "sourceTitle": "与晋长安"})}
        with patch.object(app, "INTERNATIONAL_TITLE_CACHE", cached), \
                patch.object(app, "public_iqiyi_json") as upstream:
            result = app.international_search_query("du tan truong an")
        self.assertEqual(result["query"], "与晋长安")
        self.assertEqual(result["title"], "Dữ Tấn Trường An")
        upstream.assert_not_called()

    def resolve(self, *, extra=None, original=None, localized=None):
        row = {"type": 1, "qipuId": "12345678", "name": "测试仅标题剧", "chnId": 2, "publishTime": "20250101"}

        def upstream(url):
            parsed = urlsplit(url)
            params = parse_qs(parsed.query)
            self.assertEqual(params["modeCode"], [app.IQCOM_CATALOG_REGION])
            if parsed.path == "/api/search2":
                return {"code": 0, "data": {"epg": [row] + (extra or [])}}
            data = dict(row)
            if params["langCode"] == ["vi_vn"]:
                data.update(name="Phim từ tên gốc", matchedLang=15, **(localized or {}))
            else:
                data.update(original or {})
            return {"code": 0, "data": data}

        with patch.object(app, "public_iqiyi_json", side_effect=upstream), patch.object(app, "cache_international_cast"):
            return app.international_movie_title_by_name("测试仅标题剧")

    def test_exact_unique_album(self):
        self.assertEqual(self.resolve(), {"title": "Phim từ tên gốc", "sourceTitle": "测试仅标题剧", "globalAlbumId": "12345678"})

    def test_ambiguous_name_is_not_guessed(self):
        self.assertEqual(self.resolve(extra=[{"type": 1, "qipuId": "23456789", "name": "测试仅标题剧"}])["title"], "")

    def test_full_metadata_must_match(self):
        for mutation in ({"qipuId": "99999999"}, {"name": "另一部剧"}, {"chnId": 4}, {"publishTime": "20240101"}):
            with self.subTest(mutation=mutation):
                self.assertEqual(self.resolve(original=mutation)["title"], "")
        self.assertEqual(self.resolve(localized={"matchedLang": 1})["title"], "")

    def test_invalid_name(self):
        for value in ("", "English title", "剧" * 201, "<剧>"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                app.international_movie_title_by_name(value)


if __name__ == "__main__":
    unittest.main()
