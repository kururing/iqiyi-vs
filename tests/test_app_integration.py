"""Run: python -m unittest discover -s tests -p test_app_integration.py"""
from pathlib import Path
import importlib.util
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app_integration as integration


class AppIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.user_sid = 'S-1-5-21-111-222-333-1001'
        stub = patch.object(integration, 'current_user_sid', return_value=self.user_sid)
        stub.start()
        self.addCleanup(stub.stop)

    def test_watcher_waits_for_iqiyi_before_starting_manager(self):
        spec = importlib.util.spec_from_file_location('watcher_test', Path(__file__).resolve().parents[1] / 'watch-players.py')
        watcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(watcher)
        with tempfile.TemporaryDirectory() as temporary:
            for names, expected in ((['other.exe'], 0), (['QyClient.exe'], 1)):
                with self.subTest(processes=names), patch.object(watcher, 'ROOT', Path(temporary)), \
                        patch.object(watcher, 'create_named_mutex', return_value=1), \
                        patch.object(watcher, 'EARLY_RUNTIME', None), \
                        patch.object(watcher, 'inject_runtime'), patch.object(watcher, 'patch_lwa'), \
                        patch.object(watcher, 'sync_wrapper_hook'), patch.object(watcher, 'start_manager') as manager, \
                        patch.object(watcher, 'list_processes', return_value=[SimpleNamespace(name=name) for name in names]), \
                        patch.object(watcher.time, 'sleep', side_effect=StopIteration):
                    with self.assertRaises(StopIteration):
                        watcher.run_iqiyi()
                    self.assertEqual(manager.call_count, expected)

    def test_install_is_scoped_idempotent_and_restores_original_values(self):
        with tempfile.TemporaryDirectory(prefix='iq-integration-') as temporary:
            root = Path(temporary)
            settings = {(integration.WEBVIEW_KEY, integration.WEBVIEW_APP): ['--disable-features=Test --remote-debugging-port=9999', 1],
                        (integration.WEBVIEW_KEY, '*'): ['--other-app-setting', 1]}
            original = {key: value[:] for key, value in settings.items()}

            def write(key, name, value, user_sid=None):
                if value is None:
                    settings.pop((key, name), None)
                else:
                    settings[key, name] = value

            with patch.object(integration, 'read_value', side_effect=lambda key, name, user_sid=None: settings.get((key, name))), \
                    patch.object(integration, 'write_value', side_effect=write), \
                    patch.object(integration, 'python_executable', return_value=root / 'runtime' / 'pythonw.exe'), \
                    patch.object(integration, 'winreg', SimpleNamespace(REG_SZ=1)):
                self.assertFalse(integration.installed(root))
                integration.install(root)
                self.assertTrue(integration.installed(root))
                policy = settings[integration.WEBVIEW_KEY, integration.WEBVIEW_APP][0]
                self.assertIn('--disable-features=Test', policy)
                self.assertIn('--remote-debugging-port=9223', policy)
                self.assertNotIn('9999', policy)
                self.assertEqual(settings[integration.WEBVIEW_KEY, '*'], original[integration.WEBVIEW_KEY, '*'])
                first = integration.read_state(root)
                integration.install(root)
                self.assertEqual(integration.read_state(root), first, 'Repeated installation preserves the original backup')
                integration.uninstall(root)
                self.assertEqual(settings, original)
                self.assertFalse(integration.installed(root))

    def test_uninstall_preserves_later_user_changes(self):
        with tempfile.TemporaryDirectory(prefix='iq-integration-') as temporary:
            root = Path(temporary)
            settings = {}
            with patch.object(integration, 'read_value', side_effect=lambda key, name, user_sid=None: settings.get((key, name))), \
                    patch.object(integration, 'write_value', side_effect=lambda key, name, value, user_sid=None: settings.__setitem__((key, name), value)), \
                    patch.object(integration, 'python_executable', return_value=root / 'pythonw.exe'), \
                    patch.object(integration, 'winreg', SimpleNamespace(REG_SZ=1)):
                integration.install(root)
                settings[integration.WEBVIEW_KEY, integration.WEBVIEW_APP] = ['--changed-by-user', 1]
                self.assertFalse(integration.installed(root))
                integration.uninstall(root)
                self.assertEqual(settings[integration.WEBVIEW_KEY, integration.WEBVIEW_APP], ['--changed-by-user', 1])

    def test_repair_then_uninstall_preserves_user_added_arguments(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = {(integration.WEBVIEW_KEY, integration.WEBVIEW_APP): ['--original-setting', 1]}
            def write(key, name, value, user_sid=None):
                if value is None:
                    values.pop((key, name), None)
                else:
                    values[key, name] = value
            with patch.object(integration, 'read_value', side_effect=lambda key, name, user_sid=None: values.get((key, name))), \
                    patch.object(integration, 'write_value', side_effect=write), \
                    patch.object(integration, 'python_executable', return_value=root / 'pythonw.exe'), \
                    patch.object(integration, 'winreg', SimpleNamespace(REG_SZ=1)):
                integration.install(root)
                key = integration.WEBVIEW_KEY, integration.WEBVIEW_APP
                values[key][0] += ' --user-added-setting'
                integration.install(root)
                integration.uninstall(root)
                self.assertEqual(values[key], ['--original-setting --user-added-setting', 1])

    def test_proxy_is_registered_for_normal_launch_and_restored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            values = {}
            def write(key, name, value, user_sid=None):
                if value is None:
                    values.pop((key, name), None)
                else:
                    values[key, name] = value
            with patch.object(integration, 'read_value', side_effect=lambda key, name, user_sid=None: values.get((key, name))), \
                    patch.object(integration, 'write_value', side_effect=write), \
                    patch.object(integration, 'python_executable', return_value=root / 'pythonw.exe'), \
                    patch.object(integration, 'winreg', SimpleNamespace(REG_SZ=1)):
                integration.install(root)
                integration.set_proxy(root, 'http://127.0.0.1:18767')
                key = integration.WEBVIEW_KEY, integration.WEBVIEW_APP
                self.assertIn('--proxy-server=http://127.0.0.1:18767', values[key][0])
                self.assertTrue(integration.installed(root))
                integration.uninstall(root)
                self.assertNotIn(key, values)

    def test_elevation_targets_the_original_user_and_restore_uses_same_identity(self):
        admin_sid = 'S-1-5-21-111-222-333-500'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings, writes = {}, []

            def read(key, name, sid):
                return settings.get((sid, key, name))

            def write(key, name, value, sid):
                writes.append(sid)
                if value is None:
                    settings.pop((sid, key, name), None)
                else:
                    settings[sid, key, name] = value

            with patch.object(integration, 'current_user_sid', return_value=admin_sid), \
                    patch.object(integration, 'read_value', side_effect=read), \
                    patch.object(integration, 'write_value', side_effect=write), \
                    patch.object(integration, 'python_executable', return_value=root / 'runtime' / 'pythonw.exe'), \
                    patch.object(integration, 'winreg', SimpleNamespace(REG_SZ=1, HKEY_CURRENT_USER='HKCU', HKEY_USERS='HKU')):
                self.assertEqual(integration.registry_location(integration.RUN_KEY, self.user_sid),
                                 ('HKU', self.user_sid + '\\' + integration.RUN_KEY))
                integration.install(root, self.user_sid)
                self.assertEqual(set(writes), {self.user_sid})
                self.assertFalse(integration.installed(root), 'An admin helper does not own the user installation')
                with patch.object(integration, 'current_user_sid', return_value=self.user_sid):
                    self.assertTrue(integration.installed(root))
                integration.uninstall(root, self.user_sid)
                self.assertFalse(settings)

    def test_installer_protocol_captures_identity_before_elevation(self):
        root = Path('D:/Portable App/iQIYI Việt')
        for restore in (False, True):
            args = integration.installer_args(root, restore)
            self.assertEqual(args[0], str(root / 'apply-vi.py'))
            self.assertEqual(args[args.index('--user-sid')+1], self.user_sid)
            self.assertIn('--defer-watcher', args)
            self.assertEqual('--restore' in args, restore)
        with patch.dict(integration.os.environ, {'APPDATA':str(root / 'Roaming'), 'LOCALAPPDATA':str(root / 'Local')}):
            args = integration.installer_args(root)
            self.assertEqual(args[args.index('--appdata')+1], str(root / 'Roaming'))
            self.assertEqual(args[args.index('--localappdata')+1], str(root / 'Local'))


if __name__ == '__main__':
    unittest.main()
