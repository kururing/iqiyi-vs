"""Code-only checks: python -m unittest test_ui_translation"""
import io
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock
import ui_translation as ui
from iqcom_requests import RequestCache

ROOT = Path(__file__).resolve().parent

class UiTranslationTests(unittest.TestCase):
    def test_validated_batched_translation_and_cache(self):
        payload = json.dumps(["Nhãn", "Mô tả"]).encode()
        response = MagicMock()
        response.__enter__.return_value.read.return_value = payload
        with patch.object(ui, "UI_TRANSLATIONS", RequestCache()):
            with patch.object(ui.urllib.request, "urlopen", return_value=response) as request:
                self.assertEqual(ui.translate_ui(["标签", "描述"]), ["Nhãn", "Mô tả"])
                self.assertEqual(ui.translate_ui(["标签", "描述"]), ["Nhãn", "Mô tả"])
                self.assertEqual(request.call_count, 1)
                url = request.call_args.args[0].full_url
                self.assertTrue(url.startswith("https://clients5.google.com/translate_a/t?"))
                self.assertNotIn("Cookie", request.call_args.args[0].headers)
                self.assertEqual(request.call_args.kwargs["timeout"], 8)
        for value in ([], "标签", [None], ["x" * 501], ["x"] * 9):
            with self.assertRaises(ValueError):
                ui.translate_ui(value)

    def test_malformed_response_and_failure_cooldown(self):
        for result in ([""], [], [42]):
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(result).encode()
            with patch.object(ui, "UI_TRANSLATIONS", RequestCache()):
                with patch.object(ui.urllib.request, "urlopen", return_value=response) as request:
                    for _ in range(2):
                        with self.assertRaises(ValueError):
                            ui.translate_ui(["标签"])
                    self.assertEqual(request.call_count, 1)

    def test_player_api_requires_token_and_routes_batch(self):
        import subtitle_app as app
        handler = app.Handler.__new__(app.Handler)
        handler.command = "POST"
        handler.path = "/api/ui-translate"
        handler.server = SimpleNamespace(api_token="test-secret", server_port=18766)
        handler.headers = {"Host":"127.0.0.1:18766", "Origin":"https://www.iqiyi.com"}
        replies = []
        handler.send_json = lambda code, body: replies.append((code, body))
        self.assertFalse(handler.authorized())
        handler.headers["X-Iqiyi-Token"] = app.player_token("test-secret")
        self.assertTrue(handler.authorized())
        body = json.dumps({"texts":["标签"]}).encode()
        handler.headers["Content-Length"] = str(len(body))
        handler.rfile = io.BytesIO(body)
        with patch.object(app, "translate_ui", return_value=["Nhãn"]) as translate:
            handler.do_POST()
            translate.assert_called_once_with(["标签"])
        self.assertEqual(replies[-1], (200, {"translations":["Nhãn"]}))

    def test_native_watcher_continues_after_one_popup_times_out(self):
        module = runpy.run_path(str(ROOT / "watch-players.py"))
        load = module["inject_runtime"]
        targets = [
            {"type":"page", "url":"https://localwebapp.iqiyi.com/index.html", "webSocketDebuggerUrl":"ws://127.0.0.1:9223/devtools/page/1"},
            {"type":"iframe", "url":"https://www.iqiyi.com/player", "webSocketDebuggerUrl":"ws://127.0.0.1:9223/devtools/page/2"},
            {"type":"page", "url":"https://other.example/", "webSocketDebuggerUrl":"ws://127.0.0.1:9223/devtools/page/3"},
        ]
        response = MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps(targets).encode())
        opener = MagicMock()
        opener.open.return_value = response
        cdp = SimpleNamespace(inject=MagicMock())
        state = load.__globals__
        with patch.dict(state, {"runtime_current":MagicMock(side_effect=[TimeoutError("closing popup"),False]),
                                "subtitle_hook":lambda _: b"/* subtitle hook */", "CDP":cdp}):
            with patch.object(state["urllib"].request, "build_opener", return_value=opener):
                with self.assertRaisesRegex(RuntimeError, "1 app target"):
                    load()
        self.assertEqual(cdp.inject.call_count, 1)
        self.assertEqual(cdp.inject.call_args.args[0], targets[1])

if __name__ == "__main__":
    unittest.main()
