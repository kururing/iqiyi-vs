"""Check that upgrades preserve iQIYI's native WebView bridge."""
import tempfile
import unittest
import runpy
from pathlib import Path
from unittest.mock import Mock, patch

from iqiyi_common import api_token, subtitle_hook, patch_subtitle_tag

ROOT = Path(__file__).resolve().parent
inject_lwa_dir = runpy.run_path(str(ROOT / 'apply-vi.py'))['inject_lwa_dir']
installer = runpy.run_path(str(ROOT / 'apply-vi.py'))
patch_wrapper_app = installer['patch_wrapper_app']
restore_wrapper_app = installer['restore_wrapper_app']
patch_lwa = runpy.run_path(str(ROOT / 'watch-players.py'))['patch_lwa']
sync_wrapper_hook = runpy.run_path(str(ROOT / 'watch-players.py'))['sync_wrapper_hook']


class InstallTest(unittest.TestCase):
    def test_hook_updates_bust_cache_without_duplicate_tags(self):
        old = '<html><head><script src="./sub-hook.js"></script></head></html>'
        first = patch_subtitle_tag(old, b'first')
        self.assertIn('sub-hook.js?v=', first)
        self.assertEqual(patch_subtitle_tag(first, b'first'), first)
        second = patch_subtitle_tag(first, b'second')
        self.assertNotEqual(first, second)
        self.assertEqual(second.count('sub-hook.js'), 1)
        self.assertNotIn('sub-hook.js', patch_subtitle_tag(second, None))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.hook = b'window.__iqiyiViToken = "offline-test";\n' + (ROOT / 'sub-hook.js').read_bytes()
        for globals_ in (inject_lwa_dir.__globals__, installer['main'].__globals__, patch_lwa.__globals__, sync_wrapper_hook.__globals__):
            changes = patch.dict(globals_, {'ROOT': self.root, 'BACKUP_LWA': self.root / 'backup-lwa',
                'BACKUP': self.root / 'backup-skin', 'subtitle_hook': lambda root: self.hook})
            changes.start()
            self.addCleanup(changes.stop)

    def test_install_and_watch_preserve_host_bridge(self):
        with tempfile.TemporaryDirectory() as directory:
            webapp = Path(directory)
            host = webapp / "localwebapp.js"
            original = b"window.localWebApp = {getHandler(){return {}}};"
            host.write_bytes(original)
            for name in ("index.html", "player.html", "settings.html"):
                (webapp / name).write_text('<html><head></head><body></body></html>', encoding="utf-8")
            inject_lwa_dir(webapp, 'window.__iqiyiViVersion = 100;')
            with patch.dict(patch_lwa.__globals__, {"find_lwa_dirs": lambda: [webapp]}):
                patch_lwa()
            # The host bridge is owned by the client and must never be rewritten.
            self.assertEqual(host.read_bytes(), original)
            # Every LWA page needs the dictionary before React renders Chinese strings,
            # so the tag goes into <head> of each page (including the player shell).
            for name in ("index.html", "player.html", "settings.html"):
                page = (webapp / name).read_text(encoding="utf-8")
                self.assertIn('lwa-vi.js', page)
                self.assertLess(page.index('lwa-vi.js'), page.index('</head>'))
            settings = (webapp / "settings.html").read_text(encoding="utf-8")
            self.assertIn('sub-hook.js', settings)
            self.assertLess(settings.index('sub-hook.js'), settings.index('lwa-vi.js'))

    def test_wrapper_hook_is_early_synced_idempotent_and_restorable(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory)
            main = app / "main.js"
            original = (
                "const fs = require('fs');\n"
                "const path = require('path');\n"
                "const app = {on: () => {}};\n"
                "const userscript = fs.readFileSync(path.join(__dirname, 'theater.user.js'), 'utf8');\n"
                "app.on('web-contents-created', (_event, contents) => {\n"
                "  contents.on('dom-ready', () => contents.executeJavaScript(userscript, true));\n"
                "});\n"
            )
            main.write_text(original, encoding="utf-8")
            with patch.dict(patch_wrapper_app.__globals__, {"ROOT": ROOT}):
                self.assertTrue(patch_wrapper_app(app))
                patched = main.read_text(encoding="utf-8")
                self.assertIn("Page.addScriptToEvaluateOnNewDocument", patched)
                self.assertIn("userscript + '\\n' + subtitleHook", patched)
                self.assertTrue((app / "main.js.iqiyi-vi.bak").is_file())
                self.assertEqual((app / "iqiyi-vi-subtitle.js").read_bytes(), self.hook)
                self.assertTrue(patch_wrapper_app(app))
                self.assertEqual(main.read_text(encoding="utf-8").count("IQIYI-VI EARLY SUBTITLE HOOK"), 1)

            with patch.dict(sync_wrapper_hook.__globals__, {
                "ROOT": ROOT,
                "WRAPPER_APP": app,
                "WRAPPER_SUB_HOOK": app / "iqiyi-vi-subtitle.js",
                "SUB_HOOK_JS": ROOT / "sub-hook.js",
            }):
                (app / "iqiyi-vi-subtitle.js").write_text("outdated", encoding="utf-8")
                sync_wrapper_hook()
                self.assertEqual((app / "iqiyi-vi-subtitle.js").read_bytes(), self.hook)

            with patch.dict(restore_wrapper_app.__globals__, {"ROOT": ROOT}):
                self.assertTrue(restore_wrapper_app(app))
                self.assertEqual(main.read_text(encoding="utf-8"), original)
                self.assertFalse((app / "iqiyi-vi-subtitle.js").exists())

    def test_restore_disables_watcher_before_removing_hooks(self):
        webapp = self.root / 'appdata' / '17.test'
        webapp.mkdir(parents=True)
        original = '<html><head></head><body>Original</body></html>'
        (webapp / 'index.html').write_text(original, encoding='utf-8')
        inject_lwa_dir(webapp, 'window.__audit = 1;')
        startup = self.root / 'startup.vbs'
        startup.write_text('watcher', encoding='ascii')
        registry = Mock()
        registry.OpenKey.return_value.__enter__.return_value = object()
        with patch.dict(installer['main'].__globals__, {'find_skin': lambda: None,
                'find_lwa_dirs': lambda: [webapp], 'restore_wrapper_app': lambda: False,
                'restore_lwa_sign': lambda: None, 'startup_vbs': lambda: startup,
                'winreg': registry}):
            with patch('sys.argv', ['apply-vi.py', '--restore']):
                self.assertEqual(installer['main'](), 0)
        self.assertTrue((self.root / 'watch-iqiyi-vi.disabled').exists())
        with patch.dict(patch_lwa.__globals__, {'find_lwa_dirs': lambda: [webapp]}):
            patch_lwa()
        self.assertEqual((webapp / 'index.html').read_text(encoding='utf-8'), original)
        self.assertFalse((webapp / 'lwa-vi.js').exists())
        self.assertFalse((webapp / 'sub-hook.js').exists())
        self.assertFalse(startup.exists())

    def test_skin_backups_are_restored_only_to_the_matching_version(self):
        originals = {}
        for version in ('17.99', '17.100'):
            skin = self.root / version / 'skin'
            skin.mkdir(parents=True)
            originals[version] = f'<ui version="{version}" text="首页" />'
            (skin / 'menu.xml').write_text(originals[version], encoding='utf-8')
            installer['apply_skin'](skin, {'首页': 'Trang chủ'})
        current = self.root / '17.100' / 'skin'
        installer['restore_tree'](installer['skin_backup_dir'](current), current)
        self.assertEqual((current / 'menu.xml').read_text(encoding='utf-8'), originals['17.100'])
        self.assertNotEqual(installer['skin_backup_dir'](current), installer['skin_backup_dir'](self.root / '17.99' / 'skin'))
        with patch.dict(installer['find_skin'].__globals__, {'SKIN_CANDIDATES': [self.root]}):
            self.assertEqual(installer['find_skin'](), current)

    def test_installation_token_is_stable_and_included_in_hook_payload(self):
        (self.root / 'sub-hook.js').write_bytes(b'// test hook')
        token = api_token(self.root)
        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(api_token(self.root), token)
        payload = subtitle_hook(self.root)
        self.assertIn(token.encode('ascii'), payload)
        self.assertTrue(payload.endswith(b'// test hook'))


if __name__ == '__main__':
    unittest.main()
