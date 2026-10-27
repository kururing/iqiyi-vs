"""Regression check for automatic UI localization through the player API."""
import io
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from urllib.parse import parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subtitle_app as app
from iqcom_requests import RequestCache
from iqiyi_common import player_token


class UiLocalizationTest(unittest.TestCase):
    def test_player_route_translates_and_caches_valid_results(self):
        server = app.SubtitleHTTPServer(("127.0.0.1", 0), app.Handler)
        server.api_token = "ui-localization-test"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def post(texts):
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/localize-remaining",
                data=json.dumps({"texts": texts}).encode(),
                headers={"Content-Type": "application/json", "Origin": "https://www.iqiyi.com",
                         "X-Iqiyi-Token": player_token(server.api_token)})
            try:
                response = opener.open(request, timeout=5)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                return response.status, json.load(response)

        def upstream(rows):
            response = io.BytesIO(json.dumps(rows).encode())
            response.headers = {}
            return response

        # Mock only the upstream service: the HTTP handler and translator run for real.
        with (patch.object(app, "UI_FAST_CACHE", RequestCache(), create=True),
              patch.object(app, "pooled_open", side_effect=lambda *a, **kw: upstream(["Phát", "Tạm dừng"])) as network):
            expected = (200, {"translations": ["Phát", "Tạm dừng"]})
            self.assertEqual(post(["播放", "暂停"]), expected)
            self.assertEqual(post(["播放", "暂停"]), expected)
            self.assertEqual(network.call_count, 1)
            request = network.call_args.args[0]
            self.assertEqual(parse_qs(request.data.decode()), {"q": ["播放", "暂停"]})
            self.assertEqual(post([])[0], 400)
            self.assertEqual(network.call_count, 1)

        for rows in (["Phát"], ["播放", "Tạm dừng"], ["", "Tạm dừng"]):
            with (self.subTest(rows=rows),
                  patch.object(app, "UI_FAST_CACHE", RequestCache(), create=True),
                  patch.object(app, "pooled_open", side_effect=lambda *a, **kw: upstream(rows))):
                status, body = post(["播放", "暂停"])
                self.assertEqual(status, 400)
                self.assertNotIn("translations", body)


if __name__ == "__main__":
    unittest.main()
