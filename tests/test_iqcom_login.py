"""Private login selection never reads or selects an existing browser session."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subtitle_app as app
from iqcom_session import IqcomSession
from iqiyi_common import HEADLESS_BROWSER_ARGS, player_token


class IqcomLoginTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.session = IqcomSession(Path(self.temp.name) / "profile")
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.session.close)
        self.session.source = "existing-browser-source-123"

    def pending(self):
        with patch.object(self.session.pool, "submit"):
            self.session.start_login()
        self.session.login_browser = MagicMock()
        self.session.login_context = MagicMock()
        self.session.login_page = MagicMock()
        self.session.login_page.is_closed.return_value = False
        return self.session.login_stop

    def test_one_visible_empty_context_is_opened_without_importing_cookies(self):
        with patch.object(self.session.pool, "submit") as submit:
            first = self.session.start_login()
            self.session.start_login()
            submit.assert_called_once()
        self.assertTrue(first["loginPending"])
        self.session.playwright = MagicMock()
        with patch("iqcom_session.threading.Thread"):
            self.session._open_login(self.session.login_stop)
        chromium = self.session.playwright.chromium
        options = chromium.launch.call_args.kwargs
        self.assertFalse(options["headless"])
        self.assertTrue(set(HEADLESS_BROWSER_ARGS).isdisjoint(options["args"]))
        chromium.launch_persistent_context.assert_not_called()
        context = chromium.launch.return_value.new_context.return_value
        context.add_cookies.assert_not_called()
        context.new_page.return_value.goto.assert_called_once_with(
            "https://www.iq.com/?lang=vi_vn", wait_until="domcontentloaded", timeout=30000)
        self.assertEqual(self.session.source, "existing-browser-source-123")

    def test_existing_browser_sync_and_guest_cookies_cannot_complete_login(self):
        stop = self.pending()
        self.session.update([{"name": "P00001", "value": "existing-fixture", "domain": ".iq.com"}],
                            "other-browser-source-123", select=True)
        self.assertEqual(self.session.source, "existing-browser-source-123")
        self.assertIsNone(self.session.browser_cookies)
        self.session.login_context.cookies.return_value = [
            {"name": "I00001", "value": "guest-fixture", "expires": -1},
            {"name": "I00019", "value": "0", "expires": -1}]
        self.assertFalse(self.session._poll_login(stop))
        self.assertTrue(self.session.status()["loginPending"])
        self.session.login_browser.close.assert_not_called()

    def test_new_login_is_selected_then_window_closes_without_exposing_cookies(self):
        stop = self.pending()
        context, browser = self.session.login_context, self.session.login_browser
        context.cookies.return_value = [
            {"name": "I00001", "value": "new-auth-fixture", "domain": ".iq.com", "path": "/",
             "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax"},
            {"name": "I00019", "value": "1", "domain": ".iq.com", "path": "/", "expires": -1}]
        new_source = self.session.login_source
        with patch.object(self.session.pool, "submit") as store:
            self.assertTrue(self.session._poll_login(stop))
            store.assert_called_once_with(self.session._store_browser_cookies_job)
        state = self.session.status()
        self.assertTrue(state["connected"])
        self.assertFalse(state["loginPending"])
        self.assertEqual(self.session.source, new_source)
        self.assertEqual((self.session.profile / "browser-source").read_text(), new_source)
        self.assertNotIn("new-auth-fixture", json.dumps(state))
        browser.close.assert_called_once()
        context.cookies.assert_called_once_with("https://www.iq.com/")

    def test_closing_or_failing_login_keeps_previous_session_and_allows_retry(self):
        stop = self.pending()
        self.session.login_page.is_closed.return_value = True
        self.assertTrue(self.session._poll_login(stop))
        self.assertFalse(self.session.status()["loginPending"])
        self.assertEqual(self.session.source, "existing-browser-source-123")
        with patch.object(self.session.pool, "submit"):
            self.session.start_login()
        self.session.playwright = MagicMock()
        self.session.playwright.chromium.launch.side_effect = RuntimeError("fixture launch failure")
        self.session._open_login(self.session.login_stop)
        self.assertFalse(self.session.status()["loginPending"])
        self.assertIn("Không mở được", self.session.status()["message"])

    def test_only_the_manager_can_start_the_login_window(self):
        server = app.SubtitleHTTPServer(("127.0.0.1", 0), app.Handler)
        server.api_token = "login-fixture-token"
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def post(token):
            request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/api/iqcom-login",
                data=b"{}", headers={"Content-Type": "application/json", "X-Iqiyi-Token": token})
            try:
                return opener.open(request, timeout=3)
            except urllib.error.HTTPError as error:
                return error

        try:
            with patch.object(app.IQCOM_SESSION, "start_login", return_value={"loginPending": True}) as start:
                with post(player_token(server.api_token)) as response:
                    self.assertEqual(response.status, 403)
                start.assert_not_called()
                with post(server.api_token) as response:
                    self.assertEqual(response.status, 202)
                    self.assertTrue(json.load(response)["loginPending"])
                start.assert_called_once()
        finally:
            server.shutdown()
            server.server_close()
            worker.join(3)

    def test_private_metadata_page_starts_muted_and_still_blocks_media(self):
        page = MagicMock()
        data = {"tvid": "12345678", "program": {"stl": [{"lid": 23, "xml": "track.xml"}]}}
        page.locator.return_value.count.return_value = 1
        page.locator.return_value.text_content.return_value = json.dumps({
            "props": {"initialProps": {"pageProps": {"prePlayerData": {"dash": {"data": data}}}}}})
        browser = MagicMock()
        browser.new_page.return_value = page
        with patch.object(self.session, '_browser', return_value=browser), \
                patch.object(self.session, '_store_browser_cookies', return_value=True), patch.object(self.session, '_poll'):
            self.assertEqual(self.session._dash('https://www.iq.com/play/test', '12345678'), data)
        self.assertIn('media.muted = true', page.add_init_script.call_args.args[0])
        route_handler = page.route.call_args.args[1]
        for suffix, blocked in (('1.amp4?signature=test', True), ('1.aac', True), ('dash?tvid=12345678', False), ('track.xml', False)):
            route = MagicMock()
            route.request.resource_type = 'fetch'
            route.request.url = 'https://data.video.iqiyi.com/' + suffix
            route_handler(route)
            self.assertEqual(route.abort.called, blocked)
        page.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
