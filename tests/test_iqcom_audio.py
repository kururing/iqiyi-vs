"""Run: python -m unittest discover -s tests -p test_iqcom_audio.py"""
from contextlib import contextmanager
import gzip
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import iqcom_audio as audio
import subtitle_app as app
from iqiyi_common import player_token


class AudioTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.version = 1
        self.init = b'\0\0\0\x18ftypisom\0\0\0\0moovmp4a'
        self.parts = [gzip.compress(self.init), b'12345678', b'abcdefgh']
        self.data = {"dd": "https://data.video.iqiyi.com/videos"}
        self.track = {"lid": 161, "ff": "amp4", "cf": "aac", "fs": [
            {"l": f"/v0/test/{i}.amp4?signature=retained", "b": len(raw)} for i, raw in enumerate(self.parts)]}
        self.opens = []

        @contextmanager
        def upstream(url, *, byte_range=None):
            self.opens.append((url, byte_range))
            response = io.BytesIO()
            response.status = 200
            response.headers = {}
            if url.startswith(self.data["dd"]):
                self.assertIn("signature=retained", url)
                index = int(url.split('/')[-1].split('.')[0])
                raw = json.dumps({"l": f"https://v-cc03b183.71edge.com:8402/{index}"}).encode()
            else:
                raw = self.parts[int(url.rsplit('/', 1)[1])]
                if byte_range:
                    low, high = byte_range
                    response.status = 206
                    response.headers["Content-Range"] = f"bytes {low}-{high}/{len(raw)}"
                    raw = raw[low:high + 1]
            response.write(raw)
            response.seek(0)
            yield response

        stub = patch.object(audio, "audio_open", upstream)
        stub.start()
        self.addCleanup(stub.stop)
        self.manager = audio.IqcomAudio(Path(self.temp.name) / 'settings.json',
            lambda _: (self.data, self.track, {"duration": 100, "shiftSeconds": 2, "episode": 1}), lambda: self.version)
        self.addCleanup(self.manager.pool.shutdown)

    def ready(self):
        self.manager.configure({"enabled": True})
        self.manager.status('12345678')
        for _ in range(100):
            state = self.manager.status('12345678')
            if not state['loading']:
                self.assertTrue(state['available'], state['error'])
                return state
            time.sleep(0.01)
        self.fail('Audio worker did not finish')

    def test_virtual_mp4_ranges_cross_init_and_segment_boundaries(self):
        state = self.ready()
        source = self.manager.source('12345678', state['stream'])
        expected = self.init + b'12345678abcdefgh'
        self.assertEqual(source.size, len(expected))
        for start, end in [(0, len(expected)-1), (len(self.init)-2, len(self.init)+10), (len(expected)-4, len(expected)-1)]:
            self.assertEqual(b''.join(source.read(start, end)), expected[start:end+1])
        self.assertNotIn('signature', json.dumps(state))

    def test_settings_survive_restart_disabled_never_loads_and_login_revokes_source(self):
        self.assertFalse(self.manager.status('12345678')['enabled'])
        self.assertEqual(self.opens, [])
        state = self.ready()
        self.assertEqual(json.loads(self.manager.path.read_text()), {"enabled": True})
        self.assertEqual(self.manager.validate({"enabled": True, "delaySeconds": 12}), {"enabled": True})
        self.version += 1
        with self.assertRaises(ValueError):
            self.manager.source('12345678', state['stream'])
        self.manager.configure({"enabled": False})
        with self.assertRaises(ValueError):
            self.manager.source('12345678', state['stream'])
        for bad in ({"enabled": 1}, {"enabled": None}, {}, []):
            with self.assertRaises(ValueError):
                self.manager.configure(bad)

    def test_ready_audio_survives_cache_expiry(self):
        state = self.ready()
        with patch.object(audio.time, 'monotonic', return_value=10**9):
            refreshed = self.manager.status('12345678')
            self.assertTrue(refreshed['available'])
            self.assertEqual(refreshed['stream'], state['stream'])
            self.assertIsNotNone(self.manager.source('12345678', state['stream']))

    def test_range_and_upstream_validation(self):
        cdn = 'https://v-cc03b183.71edge.com:8402/segment'
        self.assertEqual(audio.audio_url(cdn), cdn)
        self.assertEqual(audio.byte_range('bytes=-4', 10), (6, 9))
        self.assertEqual(audio.byte_range('bytes=4-', 10), (4, 9))
        self.assertEqual(audio.byte_range('bytes=0-100', 10), (0, 9))
        for bad in ('bytes=0-1,3-4', 'bytes=10-', 'bytes=-0', 'bytes=5-2', 'bytes=-'):
            with self.assertRaises(ValueError): audio.byte_range(bad, 10)
        for url in ('https://127.0.0.1/x', 'http://localhost/x', 'https://iqiyi.com.attacker.test/x',
                    'https://u:p@data.video.iqiyi.com/x', 'https://data.video.iqiyi.com:9000/x',
                    'https://data.video.iqiyi.com:8402/x', 'https://v-cc03b183.71edge.com:9000/x'):
            with self.assertRaises(ValueError): audio.audio_url(url)

    def test_http_range_seek_head_auth_and_player_settings(self):
        state = self.ready()
        server = app.SubtitleHTTPServer(('127.0.0.1', 0), app.Handler)
        server.api_token = 'audio-test-admin'
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        stub = patch.object(app, 'IQCOM_AUDIO', self.manager)
        stub.start()
        self.addCleanup(stub.stop)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base = f'http://127.0.0.1:{server.server_port}'
        route = f'/audio.mp4?tvid=12345678&stream={state["stream"]}&token={player_token(server.api_token)}'

        def request(path=route, method='GET', **headers):
            req = urllib.request.Request(base+path, method=method, headers=headers,
                data=b'{"enabled":false}' if method == 'POST' else None)
            try: return opener.open(req, timeout=3)
            except urllib.error.HTTPError as exc: return exc

        with request(Range='bytes=21-30') as r:
            self.assertEqual(r.status, 206)
            self.assertEqual(r.headers['Content-Range'], f'bytes 21-30/{len(self.init)+16}')
            self.assertEqual(r.read(), (self.init+b'12345678abcdefgh')[21:31])
        with request(method='HEAD') as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.read(), b'')
            self.assertEqual(int(r.headers['Content-Length']), len(self.init)+16)
        with request(Range='bytes=9999-') as r: self.assertEqual(r.status, 416)
        with request('/audio.mp4?tvid=12345678') as r: self.assertEqual(r.status, 403)
        with request('/api/audio-settings', 'POST', Origin='https://localwebapp.iqiyi.com',
                     **{'X-Iqiyi-Token': player_token(server.api_token)}) as r:
            self.assertEqual(r.status, 200)
        self.assertFalse(self.manager.settings['enabled'])

    def test_resolver_uses_exact_vietnamese_edition_and_episode(self):
        original = {"qipuId": '11111111', "name": '宁安如梦', "total": 38, "chnId": 2, "publishTime": '20231107', "audioInfoList": [{"id": 1}]}
        dub = {**original, "qipuId": '22222222', "name": '宁安如梦 越南语版', "audioInfoList": [{"id": 161}]}
        row = {"tvId": '33333333', "albumId": '22222222', "order": 1, "contentType": 1, "playLocSuffix": 'sample-episode'}
        data = {"tvid": '33333333', "aid": '22222222', "program": {"audio": [{**self.track, "duration": 100}]}}
        page = {"props": {"initialProps": {"pageProps": {"prePlayerData": {"dash": {"data": data}}}}}}
        def metadata(url):
            if 'video/video' in url: return {"data": {"tvId": '12345678', "albumId": '11111111', "order": 1, "durationSec": 102}}
            if 'search2' in url: return {"data": {"epg": [{"name": dub['name'], "qipuId": '22222222', "type": 1}]}}
            return {"data": dub if '/22222222?' in url else original}
        with patch.object(app, 'public_iqiyi_json', side_effect=metadata), patch.object(app, 'international_movie_title'), \
                patch.dict(app.INTERNATIONAL_ALBUM_IDS, {'11111111': (float('inf'), '11111111')}), \
                patch.object(app, 'iqcom_album_metadata', return_value=({"defaultTvId": '33333333'}, {"1": [row]}, page)):
            _, _, info = app.resolve_official_audio('12345678')
            self.assertEqual(info['internationalTvid'], '33333333')
            self.assertEqual(info['shiftSeconds'], 2)
            dub['name'] = '宁安如梦2 越南语版'
            with self.assertRaises(ValueError): app.resolve_official_audio('12345678')


if __name__ == '__main__':
    unittest.main()
