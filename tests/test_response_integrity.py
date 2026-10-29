"""Reject interrupted HTTP bodies before exposing metadata or saving subtitles."""
import gzip
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch
import urllib.request
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subtitle_app as app
import translation_ai as ai
from iqcom_requests import pooled_open, read_response


def response(raw, **headers):
    stream = io.BytesIO(raw)
    stream.headers = headers
    return stream


class ResponseIntegrityTest(unittest.TestCase):
    def test_real_http_rejects_short_body_and_recovers_pool_connection(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                raw = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw) + (10 if self.path == "/short" else 0)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(raw)
                self.close_connection = True

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(base + "/short", timeout=2) as upstream:
            with self.assertRaises(OSError):
                read_response(upstream, 100)
        with self.assertRaises(OSError), pooled_open(base + "/short", timeout=2) as upstream:
            read_response(upstream, 100)
        with pooled_open(base + "/ok", timeout=2) as upstream:
            self.assertEqual(json.loads(read_response(upstream, 100)), {"ok": True})

    def test_gzip_truncation_corruption_and_size_limit(self):
        raw = "你好".encode() * 100
        compressed = gzip.compress(raw)
        for body in (compressed[:-5], compressed[:-8] + b'\0' * 8, b'not gzip'):
            with self.subTest(body=body[:8]), self.assertRaises(OSError):
                read_response(response(body, **{"Content-Encoding": "gzip"}), 1000)
        with self.assertRaises(ValueError):
            read_response(response(compressed, **{"Content-Encoding": "gzip"}), 100)
        self.assertEqual(read_response(response(compressed, **{"Content-Encoding": "gzip"}), len(raw)), raw)

    def test_short_reads_do_not_split_utf8_and_exact_limit_is_allowed(self):
        raw = "你好".encode()
        upstream = response(raw, **{"Content-Length": str(len(raw))})
        read = upstream.read
        upstream.read = lambda size: read(min(size, 2))
        self.assertEqual(read_response(upstream, len(raw)).decode(), "你好")
        with self.assertRaises(ValueError):
            read_response(response(raw), len(raw) - 1)

    def test_metadata_search_and_page_fail_with_readable_errors(self):
        for raw in (b'{"data":"\xe7', b'{"data":'):
            for fetch, url in ((app._fetch_public_iqiyi_json, "https://pcw-api.iqiyi.com/test"),
                               (app.public_iqcom_page, "test-episode"),
                               (app.search_iqiyi_albums, "test")):
                body = (b'<script id="__NEXT_DATA__" type="application/json">' + raw + b'</script>'
                        if fetch is app.public_iqcom_page else raw)
                with self.subTest(fetch=fetch.__name__, raw=raw), patch.object(app, "pooled_open", return_value=response(body)):
                    with self.assertRaises((OSError, ValueError)) as error:
                        fetch(url)
                    self.assertNotIn("codec", str(error.exception))
                    self.assertNotIn("line 1", str(error.exception))

    def test_invalid_official_subtitle_uses_short_retry_cache(self):
        for error in (UnicodeDecodeError("utf-8", b'\xe7', 0, 1, "cut"), ET.ParseError("cut"), OSError("timeout")):
            with self.subTest(error=type(error).__name__), patch.object(app, "OFFICIAL_SUBTITLE_CACHE", {}), \
                    patch.object(app, "fetch_official_subtitle", side_effect=error):
                app._load_official_subtitle("12345678", app.IQCOM_SESSION.version)
                state = app.OFFICIAL_SUBTITLE_CACHE["12345678"]
                self.assertFalse(state["available"])
                self.assertFalse(state["loading"])
                self.assertLessEqual(state["expires"] - time.monotonic(), 10)
                self.assertNotIn("codec", state["error"])

    def test_short_subtitle_is_never_saved_even_with_valid_xml_prefix(self):
        raw = b'<xml><dia><st>1</st><et>2</et><sub>test</sub></dia></xml>'
        item = {"tracks": [{"lid": "1", "format": "xml", "url": "https://meta.video.iqiyi.com/test.xml"}]}
        with patch.object(app, "EPISODES", {"123": item}), patch.object(app, "current_player_session", return_value={"version": 1}), \
                patch.object(app, "iqiyi_open", return_value=response(raw, **{"Content-Length": str(len(raw) + 50)})), \
                patch.object(app, "capture_source") as capture, patch.object(app, "set_download_progress") as progress:
            app.download_episode_source("123")
            capture.assert_not_called()
            self.assertEqual(progress.call_args.args[:2], ("123", "error"))

    def test_provider_invalid_utf8_is_reported_without_raw_decoder_error(self):
        config = ai.model_config({"provider": "custom", "model": "test", "base_url": "http://127.0.0.1/v1"})
        with patch.object(ai, "read_api_response", return_value=b'{"data":"\xe7'):
            with self.assertRaises(ValueError) as error:
                ai.request_json(config, "test", {}, threading.Event())
        self.assertIn("UTF-8", str(error.exception))
        self.assertNotIn("codec", str(error.exception))

    def test_disconnected_browser_does_not_trigger_second_response(self):
        handler = app.Handler.__new__(app.Handler)
        handler.headers = {}
        handler.authorized = lambda: True
        handler.get_response = lambda: handler.send_body(200, "text/plain", b'test')
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock(side_effect=ConnectionAbortedError("browser closed"))
        handler.send_json = Mock()
        handler.do_GET()
        self.assertTrue(handler.close_connection)
        handler.send_response.assert_called_once_with(200)
        handler.send_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
