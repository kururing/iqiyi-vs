"""Offline proxy regressions: authenticated tunnels and truthful settings results."""
import base64
import json
from pathlib import Path
import socket
import socketserver
import sys
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import proxy_support as proxy
import subtitle_app as app
import launcher


class Upstream(socketserver.StreamRequestHandler):
    def handle(self):
        request = self.rfile.readline()
        headers = {}
        while line := self.rfile.readline():
            if line == b"\r\n":
                break
            key, value = line.decode().split(":", 1)
            headers[key.lower()] = value.strip()
        self.server.requests.append((request, headers))
        code = self.server.code
        self.wfile.write(f"HTTP/1.1 {code} Result\r\n\r\n".encode())
        self.wfile.flush()
        if 200 <= code < 300:
            self.wfile.write(b"tunnel-data")
            self.wfile.flush()


class Cdn(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(b"cdn-video-data")


class ProxyTest(unittest.TestCase):
    def setUp(self):
        self.upstream = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Upstream)
        self.upstream.requests = []
        self.upstream.code = 200
        thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(self.upstream.server_close)
        self.addCleanup(self.upstream.shutdown)
        self.url = f"http://user:p%40ss%3Aword@127.0.0.1:{self.upstream.server_address[1]}"

    def test_authenticated_relay_keeps_tunnel_data(self):
        relay = proxy.DesktopProxyRelay(lambda: self.url)
        self.addCleanup(relay.close)
        endpoint = urlsplit(relay.url())
        with socket.create_connection((endpoint.hostname, endpoint.port), timeout=3) as client:
            client.sendall(b"CONNECT www.iqiyi.com:443 HTTP/1.1\r\nHost: www.iqiyi.com:443\r\n\r\n")
            with client.makefile("rb", buffering=0) as response:
                self.assertIn(b"200", response.readline())
                while response.readline() != b"\r\n":
                    pass
                self.assertEqual(response.read(11), b"tunnel-data")
        request, headers = self.upstream.requests[0]
        self.assertEqual(request, b"CONNECT www.iqiyi.com:443 HTTP/1.1\r\n")
        expected = "Basic " + base64.b64encode(b"user:p@ss:word").decode()
        self.assertEqual(headers["proxy-authorization"], expected)

    def test_probe_reports_proxy_auth_and_access_errors_without_credentials(self):
        for code in (407, 403, 502):
            with self.subTest(code=code):
                self.upstream.code = code
                with self.assertRaisesRegex(OSError, f"HTTP {code}") as caught:
                    proxy.check_iqiyi_proxy(self.url)
                self.assertNotIn("user", str(caught.exception))
                self.assertNotIn("p@ss", str(caught.exception))

    def test_external_video_cdn_bypasses_proxy_like_the_browser(self):
        origin = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Cdn)
        thread = threading.Thread(target=origin.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(origin.server_close)
        self.addCleanup(origin.shutdown)
        relay = proxy.DesktopProxyRelay(lambda: self.url)
        self.addCleanup(relay.close)
        endpoint = urlsplit(relay.url())
        connect = socket.create_connection

        def route(address, **kwargs):
            if address == ("v-test.71edge.com", 443):
                return connect(origin.server_address, **kwargs)
            return connect(address, **kwargs)

        with patch.object(proxy.socket, "create_connection", side_effect=route), \
                connect((endpoint.hostname, endpoint.port), timeout=3) as client:
            client.sendall(b"CONNECT v-test.71edge.com:443 HTTP/1.1\r\nHost: v-test.71edge.com:443\r\n\r\n")
            with client.makefile("rb") as response:
                self.assertIn(b"200", response.readline())
                while response.readline() != b"\r\n":
                    pass
                self.assertEqual(response.read(), b"cdn-video-data")
        self.assertEqual(self.upstream.requests, [], "The CDN must not reach the upstream proxy")
        self.assertTrue(proxy.is_iqiyi_host("CACHE.VIDEO.IQIYI.COM."))
        self.assertFalse(proxy.is_iqiyi_host("iqiyi.com.attacker.test"))

    def test_probe_requires_tls_after_connect(self):
        with self.assertRaisesRegex(OSError, "HTTPS"):
            proxy.check_iqiyi_proxy(self.url)

    def test_native_launcher_bypasses_media_cdns_before_connect(self):
        with patch.object(launcher, "webview_runtime", return_value=""), \
                patch.object(launcher.subprocess, "Popen") as launch:
            launcher.start_iqiyi_client(Path("C:/IQIYI/QyClient.exe"), "http://127.0.0.1:18767", processes=[])
        environment = launch.call_args.kwargs["env"]
        self.assertEqual(environment["HTTPS_PROXY"], "http://127.0.0.1:18767")
        self.assertIn(".71edge.com", environment["NO_PROXY"].split(","))
        self.assertIn(".ppsimg.com", environment["NO_PROXY"].split(","))
        self.assertIn("--proxy-server=http://127.0.0.1:18767", environment["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"])

    def test_settings_reject_failed_probe_and_registry_before_changing_state(self):
        server = app.SubtitleHTTPServer(("127.0.0.1", 0), app.Handler)
        server.api_token = "proxy-test"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 3)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def save(url):
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/iqiyi-proxy",
                data=json.dumps({"url": url}).encode(),
                headers={"X-Iqiyi-Token": server.api_token, "Content-Type": "application/json"})
            try:
                response = opener.open(request, timeout=3)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                return response.status, json.load(response)

        with patch.object(app, "IQIYI_PROXY_URL", "http://old.test:8080"), \
                patch.object(app, "check_iqiyi_proxy", side_effect=OSError("Proxy từ chối xác thực (HTTP 407).")) as check, \
                patch.object(app.app_integration, "read_state", return_value={"entries": [{}]}), \
                patch.object(app.app_integration, "set_proxy") as registry, \
                patch.object(app.DESKTOP_PROXY, "url", return_value="http://127.0.0.1:12345"), \
                patch.object(app, "apply_running_iqiyi_proxy", return_value={"status": "closed"}) as restart:
            status, data = save(self.url)
            self.assertEqual(status, 400)
            self.assertIn("407", data["error"])
            self.assertEqual(app.current_player_proxy(), "http://old.test:8080")
            registry.assert_not_called()
            restart.assert_not_called()

            check.side_effect = None
            registry.side_effect = RuntimeError("integration changed")
            status, data = save(self.url)
            self.assertEqual(status, 409)
            self.assertIn("error", data)
            self.assertEqual(app.current_player_proxy(), "http://old.test:8080")
            restart.assert_not_called()

            registry.side_effect = None
            self.assertEqual(save(self.url)[0], 200)
            self.assertEqual(app.current_player_proxy(), self.url)
            restart.assert_called_once_with("http://127.0.0.1:12345")
            check.reset_mock()
            self.assertEqual(save("")[0], 200)
            check.assert_not_called()
            self.assertEqual(app.current_player_proxy(), "")
            restart.assert_called_with("")


if __name__ == "__main__":
    unittest.main()
