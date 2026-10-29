"""Regional titles remain resolvable when iq.com's search index omits them."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subtitle_app as app


class TitleCatalogFallbackTest(unittest.TestCase):
    def setUp(self):
        for name in ("INTERNATIONAL_TITLE_CACHE", "INTERNATIONAL_ALBUM_IDS", "INTERNATIONAL_ACTOR_CACHE"):
            stub = patch.object(app, name, {})
            stub.start()
            self.addCleanup(stub.stop)
        stub = patch.object(app, "_save_international_metadata_cache")
        stub.start()
        self.addCleanup(stub.stop)

    def resolve(self, domestic_id, global_id, source, localized, mutation=None, rows=None):
        def upstream(url):
            parsed = urlsplit(url)
            if parsed.hostname == "pcw-api.iqiyi.com":
                return {"code": "A00000", "data": {"albumId": domestic_id, "name": source,
                        "year": "2025", "channelId": 2}}
            self.assertEqual(parse_qs(parsed.query)["modeCode"], ["vn"])
            if parsed.path == "/api/search2":
                return {"code": 0, "data": {"epg": rows or []}}
            identifier = parsed.path.rsplit("/", 1)[-1]
            lang = parse_qs(parsed.query)["langCode"][0]
            if identifier != global_id:
                return {"code": 0, "data": {}}
            data = {"qipuId": global_id, "name": source,
                    "publishTime": "20250626", "chnId": 2}
            if lang == "vi_vn":
                data.update(name=localized, matchedLang=15)
            else:
                data.update(mutation or {})
            return {"code": 0, "data": data}

        with patch.object(app, "public_iqiyi_json", side_effect=upstream):
            return app.international_movie_title(domestic_id)

    def test_vietnam_catalog_resolves_a_different_international_id(self):
        rows = [{"type": 1, "qipuId": "12345678", "name": "测试区域剧", "publishTime": "20250626", "chnId": 2}]
        result = self.resolve("88888888", "12345678", "测试区域剧", "Phim thử vùng Việt Nam", rows=rows)
        self.assertEqual(result["title"], "Phim thử vùng Việt Nam")
        self.assertEqual(result["sourceTitle"], "测试区域剧")
        self.assertEqual(result["globalAlbumId"], "12345678")
        self.assertEqual(app.INTERNATIONAL_ALBUM_IDS["88888888"][1], "12345678")

    def test_unindexed_album_uses_its_direct_id(self):
        result = self.resolve("6582272134154501", "6582272134154501", "黑岛监狱", "Nhà Tù Hắc Đảo")
        self.assertEqual(result["title"], "Nhà Tù Hắc Đảo")

    def test_direct_lookup_still_verifies_identity(self):
        for mutation in ({"qipuId": "99999999"}, {"name": "另一部剧"},
                         {"publishTime": "20240101"}, {"chnId": 4}):
            app.INTERNATIONAL_TITLE_CACHE.clear()
            with self.subTest(mutation=mutation):
                result = self.resolve("6582272134154501", "6582272134154501", "黑岛监狱",
                                      "Nhà Tù Hắc Đảo", mutation=mutation)
                self.assertEqual(result["title"], "")

    def test_ambiguous_editions_and_untranslated_titles_stay_untranslated(self):
        rows = [{"type": 1, "qipuId": identifier, "name": "测试剧", "publishTime": "20250101", "chnId": 2}
                for identifier in ("11111111", "22222222")]
        result = self.resolve("88888888", "88888888", "测试剧", "Phim thử", rows=rows)
        self.assertEqual(result["title"], "")
        result = self.resolve("77777777", "77777777", "未收录", "未收录")
        self.assertEqual(result["title"], "")


if __name__ == "__main__":
    unittest.main()
