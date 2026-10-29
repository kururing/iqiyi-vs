"""SDK preloads use empty XML while the separate state API reports availability."""
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subtitle_app as app
from iqiyi_common import player_token


class SubtitleAvailabilityTest(unittest.TestCase):
    def setUp(self):
        self.server = app.SubtitleHTTPServer(("127.0.0.1", 0), app.Handler)
        self.server.api_token = "subtitle-availability-test"
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.cache = {}
        self.state = {"available": False, "loading": True, "error": "Waiting"}
        for stub in (patch.object(app, "OFFICIAL_SUBTITLE_CACHE", self.cache),
                     patch.object(app, "EPISODE_LOCKS", {}),
                     patch.object(app, "ai_subtitle_job", return_value=None),
                     patch.object(app, "official_subtitle_status", side_effect=lambda _: dict(self.state))):
            stub.start()
            self.addCleanup(stub.stop)

    def get(self, route, authenticated=True, origin="https://www.iqiyi.com"):
        headers = {"Origin": origin} if origin else {}
        if authenticated:
            headers["X-Iqiyi-Token"] = player_token(self.server.api_token)
        request = urllib.request.Request(f"http://127.0.0.1:{self.server.server_port}" + route, headers=headers)
        try:
            upstream = self.opener.open(request, timeout=3)
        except urllib.error.HTTPError as error:
            upstream = error
        with upstream:
            return upstream.status, dict(upstream.headers), upstream.read()

    def test_preloaded_tracks_are_empty_without_claiming_availability(self):
        for source in ("iqcom", "ai"):
            code, headers, body = self.get(f"/subtitle.xml?tvid=12345678&source={source}")
            self.assertEqual(code, 200)
            self.assertEqual(len(ET.fromstring(body)), 0)
            self.assertEqual(headers["Cache-Control"], "no-store")
        code, _, body = self.get("/api/official-subtitle-state?tvid=12345678")
        state = json.loads(body)
        self.assertEqual(code, 200)
        self.assertFalse(state["officialAvailable"])
        self.assertFalse(state["aiAvailable"])
        self.assertTrue(state["officialLoading"])
        self.state.update(loading=False, error="No track")
        self.assertEqual(len(ET.fromstring(self.get("/subtitle.xml?tvid=12345678&source=iqcom")[2])), 0)

    def test_ready_track_is_returned_after_the_empty_preload(self):
        route = "/subtitle.xml?tvid=12345678&source=iqcom"
        self.assertEqual(len(ET.fromstring(self.get(route)[2])), 0)
        xml = b'<xml><dia><st>1</st><et>2</et><sub>Ready</sub></dia></xml>'
        self.cache["12345678"] = {"available": True, "xml": xml}
        self.assertEqual(self.get(route)[2], xml)

    def test_invalid_routes_ids_and_credentials_are_still_rejected(self):
        self.assertEqual(self.get("/subtitle.xml?tvid=12345678&source=unknown")[0], 404)
        self.assertEqual(self.get("/subtitle.xml?tvid=invalid&source=iqcom")[0], 400)
        self.assertEqual(self.get("/subtitle.xml?tvid=12345678&source=ai", authenticated=False, origin=None)[0], 403)


if __name__ == "__main__":
    unittest.main()
