"""Check explicit proxy selection without sending network requests."""
import urllib.request
import base64
import http.client
from http.server import BaseHTTPRequestHandler
import json
import io
import socket
import threading
from unittest.mock import patch

import subtitle_app as app
from iqiyi_common import subtitle_manager_alive


def check():
    original = app.IQIYI_PROXY_URL
    try:
        for proxy in ("", "http://127.0.0.1:8888"):
            app.IQIYI_PROXY_URL = proxy
            for redirects in (False, True):
                with patch.object(urllib.request, "build_opener") as build:
                    app.iqiyi_open("https://pcw-api.iqiyi.com/", no_session_redirect=redirects)
                    handlers = build.call_args.args
                    assert handlers[0].proxies == ({"http": proxy, "https": proxy} if proxy else {})
                    assert any(isinstance(h, app.NoSessionRedirect) for h in handlers) == redirects
                    build.return_value.open.assert_called_once()
    finally:
        app.IQIYI_PROXY_URL = original


def check_browser_proxy():
    server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    server.api_token = "test-admin"
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    extension = "chrome-extension://" + "a" * 32
    try:
        with patch.object(app, "IQIYI_PROXY_URL", "http://user:p%40ss@127.0.0.1:8888"):
            for origin, token, status in (
                (extension, app.browser_proxy_token(server.api_token), 200),
                (extension, app.player_token(server.api_token), 403),
                (extension, server.api_token, 403),
                ("https://www.iqiyi.com", app.browser_proxy_token(server.api_token), 403),
                ("https://evil.example", app.browser_proxy_token(server.api_token), 403),
                (extension, "", 403),
            ):
                connection.request("GET", "/api/browser-proxy", headers={
                    "Origin": origin, "X-Iqiyi-Token": token})
                response = connection.getresponse()
                payload = json.loads(response.read())
                assert response.status == status, (origin, status, payload)
                if status == 200:
                    assert payload == {"proxy": {"host": "127.0.0.1", "port": 8888,
                                                 "username": "user", "password": "p@ss"}}
                    assert response.getheader("Access-Control-Allow-Origin") == extension
                else:
                    assert "p@ss" not in json.dumps(payload)
            connection.request("OPTIONS", "/api/browser-proxy", headers={"Origin": extension})
            response = connection.getresponse()
            response.read()
            assert response.status == 204
            connection.request("GET", "/api/iqiyi-proxy", headers={"X-Iqiyi-Token": server.api_token})
            response = connection.getresponse()
            assert json.loads(response.read()) == {"configured": True}
        with patch.object(app, "IQIYI_PROXY_URL", ""):
            connection.request("GET", "/api/browser-proxy", headers={
                "Origin": extension, "X-Iqiyi-Token": app.browser_proxy_token(server.api_token)})
            response = connection.getresponse()
            assert response.status == 200 and json.loads(response.read()) == {"proxy": None}
        with patch.object(app, "ALBUM_LISTS", {"123": {"stage": "error", "checked": 100},
                                               "456": {"stage": "ready", "checked": 100}}):
            connection.request("POST", "/api/iqiyi-proxy", json.dumps({"url": ""}), headers={
                "Content-Type": "application/json", "X-Iqiyi-Token": server.api_token})
            response = connection.getresponse()
            assert response.status == 200 and json.loads(response.read()) == {"configured": False}
            assert "checked" not in app.ALBUM_LISTS["123"], "Changing proxy must allow an immediate album retry"
            assert app.ALBUM_LISTS["456"]["checked"] == 100
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        worker.join()


def check_manual_proxy_input():
    server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    server.api_token = "test-admin"
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        with patch.object(app, "IQIYI_PROXY_URL", ""), patch.object(app, "ALBUM_LISTS", {}):
            for raw, port in (("61.130.176.21:6328", 6328), (" 61.130.176.21:6645 ", 6645)):
                connection.request("POST", "/api/iqiyi-proxy", json.dumps({"url": raw}), headers={
                    "Content-Type": "application/json", "X-Iqiyi-Token": server.api_token})
                response = connection.getresponse()
                assert response.status == 200 and json.loads(response.read()) == {"configured": True}
                expected = f"http://61.130.176.21:{port}"
                assert app.IQIYI_PROXY_URL == expected, "Saving a new port must replace the old port"
                connection.request("GET", "/api/browser-proxy", headers={
                    "X-Iqiyi-Token": app.browser_proxy_token(server.api_token)})
                response = connection.getresponse()
                assert response.status == 200
                assert json.loads(response.read())["proxy"] == {
                    "host": "61.130.176.21", "port": port, "username": "", "password": ""}
                with patch.object(urllib.request, "build_opener") as build:
                    app.iqiyi_open("https://cache.video.iqiyi.com/dash")
                    assert build.call_args.args[0].proxies == {"http": expected, "https": expected}
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        worker.join()


def check_live_proxy_flow():
    with app.SubtitleHTTPServer(("127.0.0.1", 0), app.Handler) as server, socket.socket() as refused:
        server.api_token = "test-admin"
        refused.bind(("127.0.0.1", 0))
        dead_proxy = "http://user:secret@127.0.0.1:" + str(refused.getsockname()[1])
        refused.close()
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            # A second manager must not accept requests with a different in-memory proxy.
            try:
                duplicate = app.ThreadingHTTPServer(server.server_address, app.Handler)
            except OSError:
                pass
            else:
                duplicate.server_close()
                raise AssertionError("Two managers can bind the same port")
            with patch.object(urllib.request, "getproxies", return_value={"http": dead_proxy, "https": dead_proxy}), \
                    patch.object(urllib.request, "proxy_bypass", return_value=False), \
                    patch.object(urllib.request, "_opener", None):
                assert subtitle_manager_alive(server.server_port), "Health checks must bypass system proxies"
                url = f"http://127.0.0.1:{server.server_port}/health"
                with patch.object(app, "IQIYI_PROXY_URL", ""):
                    with app.iqiyi_open(url) as response:
                        assert json.load(response)["ok"], "Disabling proxy must bypass system proxies"
                with patch.object(app, "IQIYI_PROXY_URL", dead_proxy):
                    try:
                        app.iqiyi_open(url, timeout=5)
                    except ValueError as exc:
                        assert "Proxy iQIYI" in str(exc) and "secret" not in str(exc)
                    else:
                        raise AssertionError("A configured broken proxy must report failure")
        finally:
            server.shutdown()
            worker.join()


def check_metadata_errors():
    tvid, vid = "7273739096275000", "6ae06758e3fd30b08a51e61ddb7fa31c"
    message = "Proxy iQIYI từ chối kết nối"
    with patch.object(app, "iqiyi_open", side_effect=app.IqiyiProxyError(message)):
        try:
            app.fetch_episode_tracks(tvid, vid, session={})
        except app.IqiyiProxyError as exc:
            assert str(exc) == message, "Metadata downloads must preserve proxy diagnostics"
        else:
            raise AssertionError("Proxy failure was swallowed")
    payload = {"code": "A00000", "data": {"tvid": tvid, "st": 502, "program": {}}}
    with patch.object(app, "iqiyi_open", return_value=io.BytesIO(json.dumps(payload).encode())):
        try:
            app.fetch_episode_tracks(tvid, vid, session={})
        except ValueError as exc:
            assert "502" in str(exc), "An empty metadata response must retain the service status"
        else:
            raise AssertionError("Empty metadata was accepted")
    with patch.object(app, "IQIYI_PROXY_URL", "http://user:secret@127.0.0.1:8888"), \
            patch.object(urllib.request, "build_opener") as build:
        for error in (TimeoutError(), urllib.error.URLError(TimeoutError())):
            build.return_value.open.side_effect = error
            try:
                app.iqiyi_open("https://cache.video.iqiyi.com/")
            except app.IqiyiProxyError as exc:
                assert "proxy iQIYI" in str(exc) and "secret" not in str(exc)
            else:
                raise AssertionError("Proxy timeout was not diagnosed")


def check_https_proxy_tunnel():
    seen = []

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_CONNECT(self):
            seen.append((self.path, self.headers.get("Proxy-Authorization")))
            self.send_response(502)
            self.end_headers()

    with app.ThreadingHTTPServer(("127.0.0.1", 0), Proxy) as proxy:
        worker = threading.Thread(target=proxy.serve_forever, daemon=True)
        worker.start()
        try:
            with patch.object(app, "IQIYI_PROXY_URL", f"http://user:p%40ss@127.0.0.1:{proxy.server_port}"), \
                    patch.object(urllib.request, "proxy_bypass", return_value=False):
                try:
                    app.iqiyi_open("https://cache.video.iqiyi.com/dash", timeout=3)
                except urllib.error.URLError as exc:
                    assert "Tunnel connection failed: 502" in str(exc.reason)
                else:
                    raise AssertionError("The test proxy must refuse the tunnel")
            assert seen == [("cache.video.iqiyi.com:443", "Basic " + base64.b64encode(b"user:p@ss").decode())]
        finally:
            proxy.shutdown()
            worker.join()


if __name__ == "__main__":
    check()
    check_browser_proxy()
    check_manual_proxy_input()
    check_live_proxy_flow()
    check_metadata_errors()
    check_https_proxy_tunnel()
    print("PASS: manual IP/port replacement, HTTPS CONNECT/auth, proxy routing, metadata errors, exclusive manager and browser sync")
