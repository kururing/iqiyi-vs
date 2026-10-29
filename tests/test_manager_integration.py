"""Run: python -m unittest discover -s tests -p test_manager_integration.py"""
import json
from pathlib import Path
import sys
import tempfile
import subprocess
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop
import app_integration
import launcher
import subtitle_app as app
from iqiyi_common import player_token


class ManagerIntegrationTest(unittest.TestCase):
    def test_installed_users_can_explicitly_update_native_localization(self):
        with patch.object(app_integration, 'installed', return_value=True), \
                patch.object(app, 'APP_LOCALIZATION_STATE', {'status': 'idle'}), \
                patch.object(app.threading, 'Thread') as worker:
            state = app.start_app_localization('repair')
            self.assertEqual(state['status'], 'running')
            self.assertTrue(state['installed'])
            worker.assert_called_once_with(target=app._run_app_localization, args=('repair',),
                                          name='iqiyi-localization', daemon=True)
        with patch.object(app, '_localization_command', return_value=subprocess.CompletedProcess([], 0, '', '')) as command, \
                patch.object(app, 'ensure_watcher') as watcher, patch.object(app, 'APP_LOCALIZATION_STATE', {}):
            app._run_app_localization('repair')
            command.assert_called_once_with('repair')
            watcher.assert_called_once()
            self.assertIn('cập nhật', app.APP_LOCALIZATION_STATE['message'])

    def test_parent_starts_watcher_only_after_elevated_installation_finishes(self):
        events = []

        def elevated(*args):
            events.append('elevation finished')
            return subprocess.CompletedProcess([], 0, '', '')

        with patch.object(launcher, 'installer_args', return_value=['apply-vi.py', '--user-sid', 'source-user', '--defer-watcher']), \
                patch.object(launcher.subprocess, 'run', return_value=subprocess.CompletedProcess([], 2, '', '')), \
                patch.object(launcher, 'run_elevated', side_effect=elevated), \
                patch.object(launcher, 'ensure_watcher', side_effect=lambda: events.append('normal watcher started')):
            self.assertEqual(launcher.run_apply(), 0)
            self.assertEqual(events, ['elevation finished', 'normal watcher started'])

    def test_settings_install_uses_same_parent_handoff(self):
        responses = [subprocess.CompletedProcess([], 2, '', ''), subprocess.CompletedProcess([], 0, '', '')]
        with patch.object(app, '_localization_command', side_effect=responses) as install, \
                patch.object(app, 'ensure_watcher') as watcher, \
                patch.object(app, 'APP_LOCALIZATION_STATE', {}):
            app._run_app_localization('apply')
            self.assertEqual(install.call_args_list, [unittest.mock.call('apply'), unittest.mock.call('apply', elevated=True)])
            watcher.assert_called_once()
            self.assertEqual(app.APP_LOCALIZATION_STATE['status'], 'done')

    def test_apply_is_idempotent_after_one_time_install(self):
        with patch.object(app_integration, 'installed', return_value=True), \
                patch.object(app, 'APP_LOCALIZATION_STATE', {'status':'idle'}), \
                patch.object(app.threading, 'Thread') as worker:
            self.assertTrue(app.start_app_localization('apply')['installed'])
            self.assertTrue(app.app_localization_status()['installed'])
            worker.assert_not_called()

    def test_native_settings_can_open_window_without_exposing_admin_routes(self):
        server = app.SubtitleHTTPServer(('127.0.0.1', 0), app.Handler)
        server.api_token = 'manager-integration-test'
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base = f'http://127.0.0.1:{server.server_port}'

        def post(path='/api/open-manager', origin='https://localwebapp.iqiyi.com', token=None):
            headers = {'Content-Type': 'application/json'}
            if origin:
                headers['Origin'] = origin
            if token:
                headers['X-Iqiyi-Token'] = token
            try:
                return opener.open(urllib.request.Request(base+path, data=b'{}', headers=headers), timeout=3)
            except urllib.error.HTTPError as error:
                return error

        try:
            token = player_token(server.api_token)
            with patch.object(desktop, 'open_window') as open_window:
                with post() as response:
                    self.assertEqual(response.status, 403)
                for origin in ['https://www.iqiyi.com', 'https://attacker.test', 'chrome-extension://'+'a'*32]:
                    with post(origin=origin, token=token) as response:
                        self.assertEqual(response.status, 403)
                open_window.assert_not_called()
                with post(token=token) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(json.load(response), {'ok': True})
                open_window.assert_called_once()
                with post(origin=None, token=token) as response:
                    self.assertEqual(response.status, 200, 'Native WebView requests can omit Origin')
                self.assertEqual(open_window.call_count, 2)
                with post('/api/translation/cancel', token=token) as response:
                    self.assertEqual(response.status, 403, 'The player token gains no manager permissions')
            with patch.object(desktop, 'open_window', side_effect=OSError('window unavailable')):
                with post(token=token) as response:
                    self.assertEqual(response.status, 503)
                    self.assertEqual(json.load(response)['error'], 'window unavailable')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)

    def test_launch_keeps_manager_in_background_until_requested(self):
        self.assertEqual(launcher.launch_iqiyi.__defaults__, (False,))
        with tempfile.TemporaryDirectory() as temporary, patch.object(desktop, 'ROOT', Path(temporary)), \
                patch.object(desktop, 'ensure_manager') as ensure, patch.object(desktop, 'open_window') as window, \
                patch.object(launcher, 'launch_iqiyi', return_value=0) as launch, \
                patch.object(sys, 'argv', ['desktop.py', 'iqiyi']):
            self.assertEqual(desktop.main(), 0)
            ensure.assert_called_once()
            launch.assert_called_once_with(open_ui=False)
            window.assert_not_called()

    def test_installed_launcher_does_not_reinstall(self):
        with tempfile.TemporaryDirectory() as temporary:
            client = Path(temporary) / 'QyClient.exe'
            client.touch()
            with patch.object(launcher, 'integration_installed', return_value=True), \
                    patch.object(launcher, 'iqiyi_player_proxy', return_value=''), \
                    patch.object(launcher, 'script_processes', return_value=iter([object()])), \
                    patch.object(launcher, 'run_apply') as apply, \
                    patch.object(launcher.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=str(client))), \
                    patch.object(launcher, 'start_iqiyi_client') as start, \
                    patch.object(launcher, 'open_manager_when_ready', return_value=0):
                self.assertEqual(launcher.launch_iqiyi(), 0)
                apply.assert_not_called()
                start.assert_called_once_with(client, '')


if __name__ == '__main__':
    unittest.main()
