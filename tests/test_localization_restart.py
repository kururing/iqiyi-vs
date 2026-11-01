"""Run: python -m unittest discover -s tests -p test_localization_restart.py"""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launcher


class LocalizationRestartTest(unittest.TestCase):
    def test_closed_player_stays_closed(self):
        with patch.object(launcher, 'list_processes', return_value=[]), \
                patch.object(launcher, 'start_iqiyi_client') as start:
            self.assertFalse(launcher.restart_running_iqiyi(integrated=False))
            start.assert_not_called()

    def test_restore_restarts_only_this_install_without_waiting_for_removed_watcher(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = Path(temporary) / 'QyClient.exe'
            client.touch()
            def process(pid, name, path):
                return SimpleNamespace(pid=pid, name=name, path=str(path))
            processes = [process(1, 'QyClient.exe', client),
                         process(2, 'QyPlayer.exe', client.parent / 'QyPlayer.exe'),
                         process(3, 'pythonw.exe', client.parent / 'runtime/pythonw.exe'),
                         process(4, 'QyPlayer.exe', client.parent / 'other/QyPlayer.exe')]
            # A distinct install must be outside the selected install's directory.
            processes[-1].path = str(client.parent.parent / 'other/QyPlayer.exe')
            webview_env = {'WEBVIEW2_WAIT_FOR_SCRIPT_DEBUGGER': '1',
                           'WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS': '--remote-debugging-port=9223',
                           'WEBVIEW2_BROWSER_EXECUTABLE_FOLDER': 'custom-runtime'}
            with patch.object(launcher, 'list_processes', return_value=processes), \
                    patch.object(launcher, 'terminate_process', return_value=True) as stop, \
                    patch.object(launcher.time, 'sleep'), \
                    patch.object(launcher, 'webview_runtime') as runtime, \
                    patch.dict(os.environ, webview_env), \
                    patch.object(launcher.subprocess, 'Popen') as start:
                self.assertTrue(launcher.restart_running_iqiyi(integrated=False))
                self.assertEqual([call.args[0] for call in stop.call_args_list], [1, 2])
                runtime.assert_not_called()
                start.assert_called_once()
                self.assertEqual(start.call_args.args[0], [str(client)])
                self.assertTrue(set(webview_env).isdisjoint(start.call_args.kwargs['env']))
                self.assertEqual(os.environ['WEBVIEW2_WAIT_FOR_SCRIPT_DEBUGGER'], '1')

    def test_connect_keeps_early_injection_and_proxy(self):
        with patch.object(launcher, 'webview_runtime', return_value=''), \
                patch.object(launcher.subprocess, 'Popen') as start:
            launcher.start_iqiyi_client(Path('C:/IQIYI/QyClient.exe'), 'http://127.0.0.1:18767', processes=[])
            env = start.call_args.kwargs['env']
            self.assertEqual(env['WEBVIEW2_WAIT_FOR_SCRIPT_DEBUGGER'], '1')
            self.assertIn('--remote-debugging-port=9223', env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'])
            self.assertIn('--autoplay-policy=no-user-gesture-required', env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'])
            self.assertIn('--proxy-server=http://127.0.0.1:18767', env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'])

    def test_failed_stop_does_not_launch_a_second_client(self):
        client = Path('C:/IQIYI/QyClient.exe')
        process = SimpleNamespace(pid=1, name='QyClient.exe', path=str(client))
        with patch.object(launcher, 'terminate_process', return_value=False), \
                patch.object(launcher, 'list_processes', return_value=[process]), \
                patch.object(launcher.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(RuntimeError, 'Không đóng được'):
                launcher.start_iqiyi_client(client, '', [process], integrated=False)
            start.assert_not_called()


if __name__ == '__main__':
    unittest.main()
