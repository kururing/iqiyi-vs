"""Offline checks for native player selection and runtime updates."""
import importlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cdp
youku = importlib.import_module('watch-players')
iqiyi = youku


class SubtitleWatchersTest(unittest.TestCase):
    def test_youku_accepts_native_player_and_rejects_other_origins(self):
        for url in ('https://www.youku.com/', 'https://v.youku.com/v_show/id_test.html',
                    'client://iku.youku.com/video?vid=test'):
            with self.subTest(url=url):
                self.assertTrue(youku.is_youku_page(url))
        for url in ('http://www.youku.com/', 'https://youku.com.evil.example/',
                    'client://evil.example/video', 'client://iku.youku.com:80/video',
                    'file:///C:/player.html', 'https://user:pass@youku.com/',
                    'https://youku.com:invalid/'):
            with self.subTest(url=url):
                self.assertFalse(youku.is_youku_page(url))

    def test_reinjection_uses_fresh_sessions_and_reports_js_errors(self):
        operations = []
        class Socket:
            def close(self): pass
        def call(sock, method, params, command_id):
            operations.append((method, params))
            if method == 'Page.addScriptToEvaluateOnNewDocument':
                return {'identifier': str(len(operations))}
            return {}
        target = {'id': 'test', 'webSocketDebuggerUrl': 'ws://127.0.0.1/test'}
        with patch.object(cdp, 'ws_connect', return_value=Socket()), patch.object(cdp, 'call', side_effect=call):
            cdp.inject(target, ['first'])
            cdp.inject(target, ['second'])
            methods = [method for method, params in operations]
            self.assertEqual(methods.count('Runtime.evaluate'), 2)
            self.assertNotIn('Page.removeScriptToEvaluateOnNewDocument', methods)
            with patch.object(cdp, 'call', return_value={'exceptionDetails': {'text': 'broken'}}):
                with self.assertRaisesRegex(RuntimeError, 'broken'):
                    cdp.inject({'id': 'broken', 'webSocketDebuggerUrl': target['webSocketDebuggerUrl']}, [])

    def test_iqiyi_updates_changed_source_and_skips_unchanged_source(self):
        class Transport:
            revision = None
            injections = 0
            def ws_connect(self, url): return self
            def close(self): pass
            def call(self, sock, method, params, command_id):
                expected = json.loads(params['expression'].rsplit(' === ', 1)[1])
                return {'result': {'value': self.revision == expected}}
            def evaluate(self, target, expression):
                return self.call(self, 'Runtime.evaluate', {'expression': expression}, 1)
            def inject(self, target, scripts):
                self.revision = scripts[0].split('window.__iqiyiRuntimeVi = ')[-1].split(';')[0].strip('"')
                self.injections += 1
        target = {'id': 'native', 'type': 'page', 'url': 'https://localwebapp.iqiyi.com/player.html',
                  'webSocketDebuggerUrl': 'ws://127.0.0.1:9223/devtools/page/native'}
        class Opener:
            def open(self, *args, **kwargs): return io.BytesIO(json.dumps([target]).encode())
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / 'lwa-vi.js'
            bundle.write_text('first', encoding='utf-8')
            transport = Transport()
            with patch.object(iqiyi, 'CDP', transport), patch.object(iqiyi, 'LWA_JS', bundle), patch.object(iqiyi, 'subtitle_hook', return_value=b'hook'), patch.object(iqiyi.urllib.request, 'build_opener', return_value=Opener()):
                iqiyi.inject_runtime()
                iqiyi.inject_runtime()
                self.assertEqual(transport.injections, 1)
                bundle.write_text('second', encoding='utf-8')
                iqiyi.inject_runtime()
                self.assertEqual(transport.injections, 2)


if __name__ == '__main__':
    unittest.main()
