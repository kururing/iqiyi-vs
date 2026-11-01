"""Recheck native frames whose execution context exists before their remote URL."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cdp


class NativeFrameNavigation(unittest.TestCase):
    def test_navigation_and_load_retry_known_contexts_without_a_default_context_race(self):
        session = cdp.EarlyScriptSession.__new__(cdp.EarlyScriptSession)
        session.source = "if(location.hostname.endsWith('iqiyi.com'))window.localized=true"
        session.sessions = {"native": {"contexts": {2, 3}}}
        session.command = Mock()
        for event in ("Page.frameNavigated", "Page.frameStoppedLoading", "Page.domContentEventFired"):
            with self.subTest(event=event):
                session.command.reset_mock()
                session.handle({"method": event, "sessionId": "native", "params": {}})
                self.assertEqual(session.command.call_count, 2)
                self.assertEqual({call.args[1]["contextId"] for call in session.command.call_args_list}, {2, 3})
                for call in session.command.call_args_list:
                    self.assertEqual(call.args, ("Runtime.evaluate", {
                        "expression": session.source, "contextId": call.args[1]["contextId"]}, "native"))
        session.command.reset_mock()
        session.handle({"method": "Page.frameStoppedLoading", "sessionId": "detached", "params": {}})
        session.command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
