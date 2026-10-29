"""Run: python -m unittest discover -s tests -p test_manager_window.py"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop
import launcher


class ManagerWindowTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = patch.object(desktop, "ROOT", Path(self.temporary.name))
        root.start()
        self.addCleanup(root.stop)

    def test_existing_window_is_focused_without_launching_or_reloading(self):
        with patch.object(desktop, "focus_app_window", return_value=True) as focus, \
                patch.object(desktop, "_launch_window", return_value=None) as launch:
            for _ in range(3):
                desktop.open_window()
            self.assertEqual(focus.call_count, 3)
            focus.assert_called_with(desktop.MANAGER_TITLES, desktop.ROOT / "manager_window.py")
            launch.assert_not_called()

    def test_window_can_reopen_immediately_after_user_closes_it(self):
        with patch.object(desktop, "focus_app_window", side_effect=[False, True, False, True]), \
                patch.object(desktop, "_launch_window", return_value=None) as launch, \
                patch.object(desktop.time, "sleep"):
            desktop.open_window()
            desktop.open_window()
            self.assertEqual(launch.call_count, 2)

    def test_concurrent_clicks_only_start_one_slow_browser(self):
        with patch.object(desktop, "focus_app_window", return_value=False), \
                patch.object(desktop, "_launch_window", return_value=None) as launch, \
                patch.object(desktop.time, "sleep"):
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda _: desktop.open_window(), range(8)))
            launch.assert_called_once()

    def test_failed_launch_can_be_retried_and_stale_pending_launch_expires(self):
        with patch.object(desktop, "focus_app_window", return_value=False), \
                patch.object(desktop, "_launch_window", side_effect=[OSError("browser failed"), None, None]) as launch, \
                patch.object(desktop.time, "sleep"), \
                patch.object(desktop.time, "time", return_value=100) as now:
            with self.assertRaises(OSError):
                desktop.open_window()
            desktop.open_window()
            desktop.open_window()
            self.assertEqual(launch.call_count, 2)
            now.return_value = 116
            desktop.open_window()
            self.assertEqual(launch.call_count, 3)

    def test_launcher_uses_the_same_window_opener(self):
        with patch.object(desktop, "health", return_value={"ok": True}), \
                patch.object(desktop, "open_window") as window:
            self.assertEqual(launcher.open_manager_when_ready("iQIYI"), 0)
            window.assert_called_once()
            window.reset_mock()
            self.assertEqual(launcher.open_manager_when_ready("iQIYI", open_ui=False), 0)
            window.assert_not_called()


if __name__ == "__main__":
    unittest.main()
