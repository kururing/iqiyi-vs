"""Background Edge tabs must not appear as blank entries in Alt+Tab."""
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iqcom_session import IqcomSession
from iqiyi_common import HEADLESS_BROWSER_ARGS
import windows_runtime as runtime


class BackgroundBrowserTest(unittest.TestCase):
    def test_metadata_browser_disables_edge_tab_registration(self):
        with tempfile.TemporaryDirectory() as temporary:
            session = IqcomSession.__new__(IqcomSession)
            session.closed, session.context = False, None
            session.profile = Path(temporary)
            session.playwright = MagicMock()
            api = SimpleNamespace(sync_playwright=MagicMock())
            with patch.dict(sys.modules, {'playwright': SimpleNamespace(sync_api=api), 'playwright.sync_api': api}):
                session._browser()
            options = session.playwright.chromium.launch_persistent_context.call_args.kwargs
            self.assertTrue(options['headless'])
            self.assertTrue(set(HEADLESS_BROWSER_ARGS).issubset(options['args']))

    def test_cleanup_only_stops_our_exact_headless_profile(self):
        with tempfile.TemporaryDirectory(prefix='iq browser ') as temporary:
            profile = Path(temporary) / 'private profile'

            def browser(pid, path, *flags):
                return runtime.Process(pid, 'msedge.exe', 'msedge.exe', subprocess.list2cmdline(
                    ['msedge.exe', '--remote-debugging-pipe', '--user-data-dir='+str(path), *flags]))

            rows = [browser(1, profile, '--headless=new'), browser(2, profile),
                    browser(3, str(profile)+'-other', '--headless'),
                    browser(4, profile, '--headless', '--type=renderer'),
                    browser(5, 'relative-profile', '--headless'),
                    runtime.Process(6, 'msedge.exe', '', subprocess.list2cmdline(
                        ['msedge.exe', '--headless', '--user-data-dir='+str(profile)]))]
            with patch.object(runtime, 'list_processes', return_value=rows), \
                    patch.object(runtime, 'terminate_process', return_value=True) as stop:
                runtime.stop_background_browsers(profile)
                stop.assert_called_once_with(1)


if __name__ == '__main__':
    unittest.main()
