"""Run with: python -m unittest test_international_actors"""
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import subtitle_app as app


class InternationalActorsTest(unittest.TestCase):
    def test_verified_localization_and_fallbacks(self):
        def response(url):
            query = parse_qs(urlsplit(url).query)
            self.assertEqual(urlsplit(url).hostname, "pcw-api.iq.com")
            self.assertEqual(query["key"], ["许凯"])
            name = "许凯" if query["langCode"] == ["zh_cn"] else "Hứa Khải"
            return {"code": "0", "data": {"starsInfo": {"qipuId": 234379605, "name": name}}}

        with patch.object(app, "INTERNATIONAL_ACTOR_CACHE", {}):
            with patch.object(app, "public_iqiyi_json", side_effect=response) as request:
                expected = {"name": "Hứa Khải", "sourceName": "许凯", "id": "234379605"}
                self.assertEqual(app.international_actor_name(" 许凯 "), expected)
                self.assertEqual(app.international_actor_name("许凯"), expected)
                self.assertEqual(request.call_count, 2)
            for localized in ({"qipuId": 999, "name": "Wrong Person"},
                              {"qipuId": 234379605, "name": "许凯"},
                              {"qipuId": 234379605, "name": ""}):
                app.INTERNATIONAL_ACTOR_CACHE.clear()
                rows = [{"code": "0", "data": {"starsInfo": {"qipuId": 234379605, "name": "许凯"}}},
                        {"code": "0", "data": {"starsInfo": localized}}]
                with patch.object(app, "public_iqiyi_json", side_effect=rows):
                    self.assertEqual(app.international_actor_name("许凯")["name"], "")
            app.INTERNATIONAL_ACTOR_CACHE.clear()
            with patch.object(app, "public_iqiyi_json", return_value={"code": "0", "data": {
                "starsInfo": {"qipuId": 234379605, "name": "其他人"}}}) as request:
                self.assertEqual(app.international_actor_name("许凯")["name"], "")
                self.assertEqual(request.call_count, 1)
            app.INTERNATIONAL_ACTOR_CACHE.clear()
            with patch.object(app, "public_iqiyi_json", side_effect=OSError("offline")):
                self.assertEqual(app.international_actor_name("许凯")["name"], "")
            for name in ("", "a" * 81, "<许凯>", "许凯\nInjected: header"):
                with self.assertRaises(ValueError):
                    app.international_actor_name(name)
        self.assertIn("/api/international-actor", app.PLAYER_API_ROUTES["GET"])


if __name__ == "__main__":
    unittest.main()
