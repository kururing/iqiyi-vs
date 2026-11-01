"""Required extension capabilities and the manager/player authority boundary."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from iqiyi_common import player_token
from subtitle_app import Handler

ROOT = Path(__file__).resolve().parents[1]


class PermissionTest(unittest.TestCase):
    def test_extension_declares_its_network_session_and_injection_capabilities(self):
        manifest = json.loads((ROOT / 'ext/manifest.json').read_text(encoding='utf-8'))
        required = {'declarativeNetRequestWithHostAccess', 'proxy', 'alarms', 'webRequest',
                    'webRequestAuthProvider', 'cookies', 'scripting', 'storage'}
        self.assertTrue(required.issubset(manifest['permissions']))
        self.assertIn('<all_urls>', manifest['host_permissions'], 'The configurable proxy handles arbitrary upstream hosts')
        exposed = {name for row in manifest.get('web_accessible_resources', []) for name in row['resources']}
        self.assertTrue({'audio-player.html', 'audio-player.js'}.issubset(exposed))
        self.assertNotIn('proxy-token.json', exposed, 'Manager/browser credentials stay inside the extension')
        for resource in exposed:
            self.assertTrue((ROOT / 'ext' / resource).is_file())

    def handler(self, path, method, token, origin):
        handler = Handler.__new__(Handler)
        handler.server = SimpleNamespace(server_port=18766, api_token='permission-fixture')
        handler.path, handler.command = path, method
        handler.headers = {'Host': '127.0.0.1:18766', 'Origin': origin, 'X-Iqiyi-Token': token}
        handler.send_json = Mock()
        return handler

    def test_settings_require_manager_authority_while_player_media_is_allowed(self):
        admin = 'permission-fixture'
        for path in ('/api/iqiyi-proxy', '/api/iqcom-login', '/api/app-localization', '/api/translation/start'):
            with self.subTest(path=path):
                manager = self.handler(path, 'POST', admin, 'http://127.0.0.1:18766')
                self.assertTrue(manager.authorized())
                page = self.handler(path, 'POST', player_token(admin), 'https://localwebapp.iqiyi.com')
                self.assertFalse(page.authorized())
                self.assertEqual(page.send_json.call_args.args[0], 403)
        for path in ('/api/audio-state', '/api/official-subtitle-state', '/audio.mp4'):
            with self.subTest(path=path):
                page = self.handler(path, 'GET', player_token(admin), 'https://localwebapp.iqiyi.com')
                self.assertTrue(page.authorized())
                page.headers['Origin'] = 'https://unrelated.test'
                self.assertFalse(page.authorized())


if __name__ == '__main__':
    unittest.main()
