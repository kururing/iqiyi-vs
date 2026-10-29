"""Album sync recovers from interrupted pages without saving a partial list."""
import gzip
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subtitle_app as app


class AlbumListTest(unittest.TestCase):
    def setUp(self):
        for name in ("EPISODES", "ALBUM_LISTS"):
            stub = patch.object(app, name, {})
            stub.start()
            self.addCleanup(stub.stop)
        self.save = patch.object(app, "save_episode").start()
        self.addCleanup(patch.stopall)
        patch.object(app.time, "sleep").start()

    def response(self, page, total=21, album_id="123", size=20):
        start = (page - 1) * size + 1
        data = {"code": "A00000", "data": {"albumId": album_id, "total": total,
                # This API can say False even when total requires another page.
                "hasMore": False, "epsodelist": [
                    {"tvId": str(1000 + n), "order": n, "vid": f"video{n}", "name": f"Series ep{n}"}
                    for n in range(start, min(start + size, total + 1))]}}
        return self.compressed(json.dumps(data).encode())

    def compressed(self, raw):
        response = io.BytesIO(gzip.compress(raw))
        response.headers = {"Content-Encoding": "gzip"}
        return response

    def test_retries_failed_page_and_reads_all_gzip_pages(self):
        calls = []
        responses = [self.compressed(b'{"title":"' + b'x' * 146983 + b'\xe7'), self.response(1, size=10),
                     urllib.error.URLError(TimeoutError("timed out")), self.response(3, size=5),
                     self.response(4, size=5), self.response(5, size=5)]

        def upstream(request, **options):
            query = parse_qs(urlsplit(request.full_url).query)
            calls.append((int(query["page"][0]), int(query["size"][0])))
            self.assertEqual(request.get_header("Accept-encoding"), "gzip")
            self.assertTrue(options["no_session_redirect"])
            self.save.assert_not_called()
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

        with patch.object(app, "iqiyi_open", side_effect=upstream):
            app.sync_album_list("123", "Series")
        self.assertEqual(calls, [(1, 20), (1, 10), (2, 10), (3, 5), (4, 5), (5, 5)])
        self.assertEqual(app.ALBUM_LISTS["123"]["stage"], "ready")
        self.assertEqual(app.ALBUM_LISTS["123"]["total"], 21)
        self.assertEqual(len(app.EPISODES), 21)
        self.assertEqual(set(app.EPISODES), {str(1000 + n) for n in range(1, 22)})
        self.assertEqual(app.EPISODES["1021"]["vid"], "video21")
        self.assertEqual(self.save.call_count, 21)

    def test_exhausted_retries_leave_saved_episodes_untouched(self):
        for error in (json.JSONDecodeError("cut", "", 0),
                      UnicodeDecodeError("utf-8", b'\xe7', 0, 1, "unexpected end of data"),
                      urllib.error.URLError(TimeoutError("timed out")), EOFError("gzip cut")):
            with self.subTest(error=type(error).__name__):
                previous = {"tvid": "1001", "title": "Saved episode"}
                app.EPISODES.clear()
                app.EPISODES["1001"] = previous.copy()
                with patch.object(app, "iqiyi_open", side_effect=[self.response(1), error, error, error]) as network:
                    app.sync_album_list("123", "Series")
                self.assertEqual(network.call_count, 4)
                self.assertEqual(app.ALBUM_LISTS["123"]["stage"], "error")
                self.assertNotIn("line 1", app.ALBUM_LISTS["123"]["message"])
                self.assertNotIn("codec", app.ALBUM_LISTS["123"]["message"])
                self.assertEqual(app.EPISODES, {"1001": previous})
                self.save.assert_not_called()

    def test_wrong_album_and_repeated_page_are_rejected(self):
        for responses in ([self.response(1, album_id="456")], [self.response(1), self.response(1)]):
            with self.subTest(pages=len(responses)), patch.object(app, "iqiyi_open", side_effect=responses):
                app.sync_album_list("123", "Series")
                self.assertEqual(app.ALBUM_LISTS["123"]["stage"], "error")
                self.assertFalse(app.EPISODES)
                self.save.assert_not_called()


class IqiyiLibraryTest(unittest.TestCase):
    def test_only_iqiyi_is_loaded_and_album_actions_preserve_other_saved_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            library = Path(temporary) / 'library'
            manifests = {
                '123': {'title': 'iQIYI ep1', 'albumId': '77', 'discoveredAt': 1},
                '456': {'provider': 'unsupported', 'albumId': '77', 'discoveredAt': 1},
                'legacy-entry': {'provider': 'unsupported', 'discoveredAt': 1},
            }
            for key, value in manifests.items():
                folder = library / key
                folder.mkdir(parents=True)
                (folder / 'episode.json').write_text(json.dumps(value), encoding='utf-8')
            with patch.multiple(app, LIBRARY=library, EPISODES={}, DOWNLOAD_PROGRESS={}, ALBUM_LISTS={}, EPISODE_LOCKS={}), \
                    patch.object(app, 'load_library_admissions'), patch.object(app, 'set_library_status'):
                app.load_library()
                self.assertEqual(set(app.EPISODES), {'123'})
                self.assertEqual(app.EPISODES['123']['provider'], 'iqiyi')
                self.assertEqual(app.album_episode_ids('77'), ['123'])
                with self.assertRaises(ValueError):
                    app.episode_dir('legacy-entry')
                server = app.SubtitleHTTPServer(('127.0.0.1', 0), app.Handler)
                server.api_token = 'iqiyi-library-test'
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

                def post(path, data):
                    request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path,
                        data=json.dumps(data).encode(), headers={'Content-Type': 'application/json', 'X-Iqiyi-Token': server.api_token})
                    try:
                        return opener.open(request, timeout=3)
                    except urllib.error.HTTPError as error:
                        return error

                try:
                    with post('/api/register', {'tvid': '123', 'provider': 'unsupported'}) as response:
                        self.assertEqual(response.status, 400)
                    app.ALBUM_LISTS['77'] = {'stage': 'loading'}
                    with post('/api/delete-album', {'albumId': '77'}) as response:
                        self.assertEqual(response.status, 409, 'Keep the album while its episode list is syncing')
                    app.ALBUM_LISTS.clear()
                    with post('/api/delete-album', {'albumId': '77'}) as response:
                        self.assertEqual(response.status, 200)
                    self.assertFalse((library / '123').exists())
                    for key in ('456', 'legacy-entry'):
                        self.assertEqual(json.loads((library / key / 'episode.json').read_text()), manifests[key])
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(3)


if __name__ == "__main__":
    unittest.main()
