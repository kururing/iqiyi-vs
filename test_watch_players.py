"""Regression check that one closing native popup does not skip sibling targets."""
import io
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent


class WatchPlayersTests(unittest.TestCase):
    def test_native_watcher_continues_after_one_popup_times_out(self):
        module = runpy.run_path(str(ROOT / "watch-players.py"))
        load = module["inject_runtime"]
        targets = [
            {"type":"page", "url":"https://localwebapp.iqiyi.com/index.html", "webSocketDebuggerUrl":"ws://127.0.0.1:9223/devtools/page/1"},
            {"type":"iframe", "url":"https://www.iqiyi.com/player", "webSocketDebuggerUrl":"ws://127.0.0.1:9223/devtools/page/2"},
            {"type":"page", "url":"https://other.example/", "webSocketDebuggerUrl":"ws://127.0.0.1:9223/devtools/page/3"},
        ]
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(targets).encode()
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
