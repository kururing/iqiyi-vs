"""Installer lifecycle never terminates active work or another checkout."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop
import launcher


class DesktopLifecycle(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.own = SimpleNamespace(command_line='python.exe "subtitle_app.py"')
        for target, value in (
            ("desktop.ROOT", self.root), ("desktop.health", {"busy": False}),
            ("launcher.script_processes", [self.own]), ("launcher.stop_processes", None),
            ("launcher.run_apply", 0), ("desktop.ensure_manager", False),
            ("launcher.integration_installed", False), ("launcher.ensure_watcher", None),
            ("desktop.open_window", None),
        ):
            item = patch(target, return_value=value) if target != "desktop.ROOT" else patch(target, value)
            setattr(self, target.split(".")[-1], item.start())
            self.addCleanup(item.stop)

    def run_action(self, action):
        with patch.object(sys, "argv", ["desktop.py", action]):
            return desktop.main()

    def test_busy_blocks_stop_and_uninstall(self):
        self.health.return_value = {"busy": True}
        for action in ("stop", "uninstall"):
            with self.assertRaises(RuntimeError):
                self.run_action(action)
        self.stop_processes.assert_not_called()
        self.run_apply.assert_not_called()

    def test_unknown_live_manager_is_protected(self):
        self.health.return_value = None
        with self.assertRaises(RuntimeError):
            self.run_action("stop")
        self.stop_processes.assert_not_called()

    def test_other_checkout_is_untouched(self):
        self.health.side_effect = RuntimeError("another root")
        self.script_processes.return_value = []
        self.assertEqual(self.run_action("uninstall"), 0)
        self.stop_processes.assert_called_once_with([])

    def test_uninstall_restores_integration_before_removing_app(self):
        (self.root / ".local").mkdir()
        (self.root / ".local/iqiyi-integration.json").write_text("{}")
        self.assertEqual(self.run_action("uninstall"), 0)
        self.run_apply.assert_called_once_with(restore=True)
        self.stop_processes.assert_called_once_with([self.own])

    def test_failed_restore_keeps_app_running(self):
        (self.root / ".local").mkdir()
        (self.root / ".local/iqiyi-integration.json").write_text("{}")
        self.run_apply.return_value = 1
        with self.assertRaises(RuntimeError):
            self.run_action("uninstall")
        self.stop_processes.assert_not_called()

    def test_background_does_not_open_window(self):
        self.assertEqual(self.run_action("background"), 0)
        self.ensure_manager.assert_called_once()
        self.open_window.assert_not_called()


if __name__ == "__main__":
    unittest.main()
