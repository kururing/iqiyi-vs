"""Disconnect removes installed hooks and prevents watcher maintenance from restoring them."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import launcher
import subtitle_app as app


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ManagerRestoreTest(unittest.TestCase):
    def setUp(self):
        restart = patch.object(app, 'restart_running_iqiyi', return_value=False)
        self.restart = restart.start()
        self.addCleanup(restart.stop)

    def test_restore_removes_hooks_from_all_versions_and_stops_watcher(self):
        installer = load_script('apply-vi.py')
        watcher = load_script('watch-players.py')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native = root / 'native'
            cache = root / 'Roaming' / 'IQIYI Video' / 'localwebapp'
            cache.mkdir(parents=True)
            original = b'<html><head></head><body>original</body></html>'
            vendor = '<script src="vendor.js"></script>'
            hooks = ('<script src="./lwa-vi.js?v=old"></script>'
                     '<script src="sub-hook.js#old"></script>'
                     '<script data-iqiyi-vi-ui="1">legacy()</script>'
                     '<script>/* iqiyi-vi */ legacy()</script>')
            skins, webapps = [], [cache]
            for version in ('1.0', '2.0'):
                skin = native / version / 'skin'
                webapp = skin / 'LwaRes' / 'iqiyi_webapp'
                webapp.mkdir(parents=True)
                skins.append(skin)
                webapps.append(webapp)
                (skin / 'menu.xml').write_text('translated', encoding='utf-8')
                backup = root / 'backup-skin' / 'versions' / version
                backup.mkdir(parents=True)
                (backup / 'menu.xml').write_text('original', encoding='utf-8')
            for webapp in webapps:
                (webapp / 'index.html').write_bytes(original + hooks.encode())
                (webapp / 'about.html').write_text(vendor + hooks, encoding='utf-8')
                for name in ('lwa-vi.js', 'sub-hook.js'):
                    (webapp / name).write_text('installed hook')
            legacy = root / 'legacy.vbs'
            legacy.write_text('watcher')
            mode = root / '.local' / 'iqiyi-manager-only'
            mode.parent.mkdir()
            mode.write_text('manager-only')
            process = object()
            with (patch.dict(installer.os.environ, {'APPDATA': str(root / 'Roaming'), 'LOCALAPPDATA': str(root / 'Local')}),
                  patch.multiple(installer, ROOT=root, BACKUP=root / 'backup-skin',
                                 BACKUP_LWA=root / 'backup-lwa', APPDATA_LWA=cache),
                  patch.object(installer, 'find_skin', return_value=skins[-1]),
                  patch.object(installer, 'iqiyi_install_roots', return_value=[native]),
                  patch.object(installer, 'restore_wrapper_app'), patch.object(installer, 'restore_lwa_sign'),
                  patch.object(installer, 'startup_vbs', return_value=legacy),
                  patch.object(installer, 'install_autostart') as install,
                  patch.object(installer, 'integration_user_sid', return_value='fixture-user'),
                  patch.object(installer.app_integration, 'uninstall') as uninstall,
                  patch.object(launcher, 'script_processes', return_value=[process]),
                  patch.object(launcher, 'stop_processes') as stop,
                  patch.object(sys, 'argv', ['apply-vi.py', '--restore'])):
                self.assertEqual(installer.main(), 0)
                stop.assert_called_once_with([process])
                install.assert_not_called()
                uninstall.assert_called_once_with(root, 'fixture-user')
                self.assertTrue((root / 'watch-iqiyi-vi.disabled').exists())
                self.assertFalse(mode.exists())
                self.assertFalse(legacy.exists())
                for skin in skins:
                    self.assertEqual((skin / 'menu.xml').read_text(), 'original')
                with patch.object(watcher, 'ROOT', root), patch.object(watcher, 'find_lwa_dirs', return_value=webapps):
                    watcher.patch_lwa()
                for webapp in webapps:
                    self.assertEqual((webapp / 'index.html').read_bytes(), original)
                    self.assertEqual((webapp / 'about.html').read_text(), vendor)
                    self.assertFalse((webapp / 'lwa-vi.js').exists())
                    self.assertFalse((webapp / 'sub-hook.js').exists())
                self.assertEqual(installer.main(), 0, 'Repeated removal is safe')
                with patch.object(sys, 'argv', ['apply-vi.py']), patch.object(installer, '_main', return_value=0):
                    self.assertEqual(installer.main(), 0)
                self.assertFalse((root / 'watch-iqiyi-vi.disabled').exists())

    def test_restore_wrapper_removes_script_and_backup(self):
        installer = load_script('apply-vi.py')
        with tempfile.TemporaryDirectory() as temporary:
            wrapper = Path(temporary)
            main = wrapper / 'main.js'
            backup = wrapper / 'main.js.iqiyi-vi.bak'
            hook = wrapper / 'iqiyi-vi-subtitle.js'
            backup.write_bytes(b'original entry point')
            main.write_bytes(b'patched entry point')
            hook.write_bytes(b'hook')
            self.assertTrue(installer.restore_wrapper_app(wrapper))
            self.assertEqual(main.read_bytes(), b'original entry point')
            self.assertFalse(backup.exists())
            self.assertFalse(hook.exists())
            self.assertFalse(installer.restore_wrapper_app(wrapper))
            hook.write_bytes(b'orphan hook')
            self.assertTrue(installer.restore_wrapper_app(wrapper))
            self.assertFalse(hook.exists())
            main.write_text('// IQIYI-VI EARLY SUBTITLE HOOK')
            hook.write_bytes(b'needed until restored')
            with self.assertRaises(RuntimeError):
                installer.restore_wrapper_app(wrapper)
            self.assertTrue(hook.exists())

    def test_manager_restore_requests_full_removal_with_and_without_elevation(self):
        with patch.object(app.app_integration, 'installer_args', return_value=['apply-vi.py', '--restore']), \
                patch.object(app.subprocess, 'run') as run, patch.object(app, 'run_elevated') as elevated:
            app._localization_command('restore')
            self.assertNotIn('--keep-manager', run.call_args.args[0])
            app._localization_command('restore', elevated=True)
            self.assertNotIn('--keep-manager', elevated.call_args.args[1])
        for code, status in ((0, 'done'), (2, 'done'), (1, 'error')):
            results = [subprocess.CompletedProcess([], code, '', '')]
            if code == 2:
                results.append(subprocess.CompletedProcess([], 0, '', ''))
            with patch.object(app, '_localization_command', side_effect=results), \
                    patch.object(app, 'ensure_watcher') as watcher, patch.object(app, 'APP_LOCALIZATION_STATE', {}):
                app._run_app_localization('restore')
                watcher.assert_not_called()
                self.assertEqual(app.APP_LOCALIZATION_STATE['status'], status)
                if status == 'done':
                    self.restart.assert_called_once_with('', integrated=False)
                else:
                    self.restart.assert_not_called()
                self.restart.reset_mock()


if __name__ == '__main__':
    unittest.main()
