"""Offline regressions for API access, source ownership and translation integrity."""
import concurrent.futures
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import iqiyi_common
import subtitle_app as app


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.library = self.root / 'library'
        self.library.mkdir()
        values = {'LIBRARY': self.library, 'PLAYER_LOG': self.root / 'player.log',
                  'AI_SETTINGS_PATH': self.root / 'ai-settings.json',
                  'EPISODES': {}, 'TRANSLATION_PROGRESS': {}, 'EPISODE_LOCKS': {}, 'PLAYER_LOG_SIGNATURE': None,
                  'ALBUM_LISTS': {}, 'DOWNLOAD_PROGRESS': {}, 'PLAYER_SESSION': {}, 'SESSION_VERSION': 0,
                  'APP_LOCALIZATION_STATE': {'status': 'idle', 'action': '', 'message': ''},
                  'APP_LOCALIZATION_LOCK': threading.Lock()}
        changes = patch.multiple(app, **values)
        changes.start()
        self.addCleanup(changes.stop)
        self.agent_profile = patch.object(app, 'ensure_agent_profile', return_value={'memory': {}})
        self.agent_profile.start()
        self.addCleanup(self.agent_profile.stop)
        background = patch.object(app, 'refresh_album_lists')
        background.start()
        self.addCleanup(background.stop)
        self.queue_downloads = app.queue_subtitle_downloads
        downloads = patch.object(app, 'queue_subtitle_downloads')
        downloads.start()
        self.addCleanup(downloads.stop)
        self.refresh_rights = app.refresh_player_entitlements
        rights = patch.object(app, 'refresh_player_entitlements')
        rights.start()
        self.addCleanup(rights.stop)
        self.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.server.api_token = 'offline-test-token-with-at-least-32-characters'
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        worker = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        worker.start()
        self.addCleanup(worker.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, route, data=None, token=True, origin=None, method=None, headers=None):
        request_headers = {'Content-Type': 'application/json'}
        if token:
            request_headers['X-Iqiyi-Token'] = self.server.api_token
        if origin is not None:
            request_headers['Origin'] = origin
        request_headers.update(headers or {})
        request = urllib.request.Request(self.url + route,
            data=json.dumps(data).encode() if data is not None else None, headers=request_headers, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def episode(self, tvid='101', text='Old source', start=1):
        self.assertEqual(self.request('/api/register', {'tvid': tvid, 'title': 'Audit ep1', 'albumId': '9'})[0], 200)
        source = [(start * 1000, (start + 1) * 1000, text)]
        self.assertEqual(self.request('/api/capture', {'tvid': tvid, 'format': 'srt', 'raw': app.to_srt(source)})[0], 200)
        return source

    def test_app_localization_status_requires_token(self):
        self.assertEqual(self.request('/api/app-localization', token=False)[0], 403)
        status, _, body = self.request('/api/app-localization')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['status'], 'idle')

    def test_app_localization_controls_render_in_webapp(self):
        status, _, body = self.request('/', token=False)
        page = body.decode('utf-8')
        self.assertEqual(status, 200)
        self.assertIn('id="localizeIqiyiButton"', page)
        self.assertIn('id="restoreIqiyiButton"', page)
        self.assertIn('refreshAppLocalization()', page)

    def test_localization_commands_suppress_console_windows(self):
        completed = app.subprocess.CompletedProcess([], 0, '', '')
        with patch.object(app.subprocess, 'run', return_value=completed) as run:
            app._localization_command('apply')
        self.assertEqual(run.call_args.kwargs['creationflags'], getattr(app.subprocess, 'CREATE_NO_WINDOW', 0))
        with patch.object(app.subprocess, 'run', return_value=completed) as run, \
                patch.object(app.shutil, 'which', return_value='powershell.exe'):
            app._localization_command('restore', elevated=True)
        self.assertEqual(run.call_args.kwargs['creationflags'], getattr(app.subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertIn('-WindowStyle Hidden', run.call_args.args[0][-1])
        self.assertIn('--restore', run.call_args.args[0][-1])

    def test_localization_status_names_the_running_action(self):
        with patch.object(app.threading, 'Thread') as worker:
            state = app.start_app_localization('restore')
        self.assertEqual(state['status'], 'running')
        self.assertIn('Đang khôi phục', state['message'])
        worker.return_value.start.assert_called_once_with()

    def test_app_localization_action_is_allowlisted_and_dispatched(self):
        with patch.object(app, 'start_app_localization', return_value={
                'status': 'running', 'action': 'restore', 'message': 'working'}) as start:
            status, _, body = self.request('/api/app-localization', {'action': 'restore'})
        self.assertEqual(status, 202)
        self.assertEqual(json.loads(body)['action'], 'restore')
        start.assert_called_once_with('restore')
        status, _, body = self.request('/api/app-localization', {'action': 'shell'})
        self.assertEqual(status, 400)
        self.assertIn('không hợp lệ', json.loads(body)['error'])

    def complete(self, source, tvid='101'):
        folder = app.episode_dir(tvid)
        state = {'sourceHash': app.source_fingerprint(source), 'translations': {'1': 'Old Vietnamese'},
                 'albumTitleVi': '', 'lastError': ''}
        app.save_translation_state(folder, state)
        iqiyi_common.atomic_write(folder / 'translated.srt', app.to_srt([(source[0][0], source[0][1], 'Old Vietnamese')]))

    def test_album_list_loads_all_pages_and_preserves_subtitles(self):
        import io
        source = self.episode()
        self.complete(source)
        app.EPISODES['101']['tracks'] = [{'lid': '1', 'url': 'https://meta.video.iqiyi.com/source.xml'}]
        pages = [io.BytesIO(json.dumps({'code': 'A00000', 'data': {
            'albumId': '9', 'total': 3, 'hasMore': index == 0, 'epsodelist': rows}}).encode())
            for index, rows in enumerate([
                [{'tvId': 101, 'name': 'Audit ep1', 'order': 1}, {'tvId': 102, 'name': 'Audit ep2', 'order': 2}],
                [{'tvId': 103, 'name': 'Audit ep3', 'order': 3}]])]
        with patch.object(app.urllib.request, 'urlopen', side_effect=pages) as fetch:
            app.sync_album_list('9', 'Audit')
        self.assertEqual(fetch.call_count, 2)
        self.assertIn('page=2', fetch.call_args.args[0])
        self.assertEqual(app.ALBUM_LISTS['9']['total'], 3)
        self.assertEqual(set(app.EPISODES), {'101', '102', '103'})
        self.assertEqual(len(app.EPISODES['101']['tracks']), 1)
        self.assertEqual(len(app.translated_cues('101')), 1)
        rows = json.loads(self.request('/api/episodes')[2])['episodes']
        self.assertEqual([row['order'] for row in rows], [1, 2, 3])
        self.assertFalse(rows[-1]['downloaded'])
        self.assertTrue((app.episode_dir('103') / 'episode.json').exists())

    def test_album_list_failure_keeps_existing_library_and_reports_error(self):
        self.episode()
        with patch.object(app.urllib.request, 'urlopen', side_effect=OSError('offline')):
            app.sync_album_list('9', 'Audit')
        self.assertEqual(set(app.EPISODES), {'101'})
        self.assertEqual(app.ALBUM_LISTS['9']['stage'], 'error')
        self.assertIn('offline', app.ALBUM_LISTS['9']['message'])

    def test_newly_discovered_movies_sort_first_without_promoting_updated_movies(self):
        for tvid, album, discovered in [('101', '99', 100), ('102', '1', 200), ('103', '99', 300)]:
            with patch.object(app.time, 'time', return_value=discovered):
                self.assertEqual(self.request('/api/register', {'tvid': tvid, 'albumId': album,
                    'title': f'Show ep{1 if tvid != "103" else 2}'})[0], 200)
        with patch.object(app.time, 'time', return_value=400):
            self.request('/api/register', {'tvid': '101', 'title': 'Updated ep1'})
        self.assertEqual(app.EPISODES['101']['discoveredAt'], 100)
        rows = json.loads(self.request('/api/episodes')[2])['episodes']
        self.assertEqual([row['tvid'] for row in rows], ['102', '101', '103'])
        app.EPISODES.clear()
        app.load_library()
        rows = json.loads(self.request('/api/episodes')[2])['episodes']
        self.assertEqual([row['tvid'] for row in rows], ['102', '101', '103'])
        self.assertEqual(app.EPISODES['101']['discoveredAt'], 100)

    def test_subtitle_download_needs_no_player_and_checks_episode_identity(self):
        app.EPISODES['102'] = {'title': 'Audit ep2', 'albumId': '9', 'vid': 'a' * 32}
        metadata = {'code': 'A00000', 'data': {'tvid': 102, 'dstl': 'https://meta.video.iqiyi.com/',
            'program': {'stl': [{'lid': 1, 'xml': '/ep2.xml'}, {'lid': 2, 'xml': '/other.xml'}]}}}
        pages = [io.BytesIO(json.dumps(metadata).encode()), io.BytesIO(
            b'<xml><dia><st>1000</st><et>2000</et><sub>Episode two</sub></dia></xml>')]
        with patch.object(app.urllib.request, 'urlopen', side_effect=pages) as fetch:
            app.download_episode_source('102')
        self.assertEqual(fetch.call_count, 2)
        query = app.parse_qs(app.urlsplit(fetch.call_args_list[0].args[0].full_url).query)
        self.assertEqual(query['tvid'], ['102'])
        self.assertEqual(query['vid'], ['a' * 32])
        self.assertIn('vf', query)
        self.assertEqual(fetch.call_args.args[0], 'https://meta.video.iqiyi.com/ep2.xml')
        self.assertEqual(app.DOWNLOAD_PROGRESS['102']['stage'], 'ready')
        self.assertEqual(app.parse_source((app.episode_dir('102') / 'source.srt').read_text(), 'srt'),
                         [(1000, 2000, 'Episode two')])
        metadata['data']['tvid'] = 999
        with patch.object(app.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(metadata).encode())):
            with self.assertRaises(ValueError):
                app.fetch_episode_tracks('102', 'a' * 32)
        metadata['data']['tvid'] = 102
        metadata['data']['ctl'] = {'boss_not_pass': True}
        app.EPISODES['102'].pop('tracks')
        with patch.object(app.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(metadata).encode())):
            app.download_episode_source('102')
        self.assertEqual(app.DOWNLOAD_PROGRESS['102']['stage'], 'access')
        metadata['data']['tvid'] = 102
        metadata['data']['program']['stl'][0]['xml'] = 'https://untrusted.example/evil.xml'
        with patch.object(app.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(metadata).encode())):
            with self.assertRaises(ValueError):
                app.fetch_episode_tracks('102', 'a' * 32)

    def test_download_queue_deduplicates_and_never_replaces_saved_work(self):
        self.episode()
        app.EPISODES['102'] = {'vid': 'a' * 32}
        with patch.object(app.DOWNLOAD_POOL, 'submit') as submit:
            self.assertEqual(self.queue_downloads(['101', '102']), 1)
            self.assertEqual(self.queue_downloads(['101', '102'], retry=True), 0)
            submit.assert_called_once_with(app.download_episode_source, '102')
            app.DOWNLOAD_PROGRESS['102'] = {'stage': 'error', 'message': 'offline'}
            self.assertEqual(self.queue_downloads(['101', '102']), 0)
            self.assertEqual(self.queue_downloads(['102'], retry=True), 1)
        with patch.object(app.urllib.request, 'urlopen', side_effect=OSError('offline')):
            app.download_episode_source('102')
        self.assertEqual(app.DOWNLOAD_PROGRESS['102']['stage'], 'error')
        self.assertIn('metadata', app.DOWNLOAD_PROGRESS['102']['message'])

    def test_player_session_authenticates_metadata_without_exposing_or_persisting_secrets(self):
        session = {'authcookie': 'private-player-session', 'uid': '123', 'vipTypes': ['1', '4'],
                   'deviceId': 'player-device', 'dfp': 'player-dfp'}
        self.assertEqual(self.request('/api/session', session, token=False)[0], 403)
        self.assertEqual(self.request('/api/session', session, origin='https://localwebapp.iqiyi.com')[0], 200)
        version = app.current_player_session()['version']
        self.assertEqual(self.request('/api/session', session)[0], 200)
        self.assertEqual(app.current_player_session()['version'], version)
        metadata = {'code': 'A00000', 'data': {'tvid': 102, 'program': {
            'stl': [{'lid': 1, 'xml': 'https://meta.video.iqiyi.com/source.xml'}]}}}
        with patch.object(app.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(json.dumps(metadata).encode())
            app.fetch_episode_tracks('102', 'a' * 32)
            req = opener.return_value.open.call_args.args[0]
            query = app.parse_qs(app.urlsplit(req.full_url).query)
            self.assertEqual(query['pck'], [session['authcookie']])
            self.assertEqual(query['uid'], ['123'])
            self.assertEqual(query['ut'], ['1', '4'])
            self.assertEqual(query['k_uid'], ['player-device'])
            self.assertEqual(query['dfp'], ['player-dfp'])
            self.assertIn('P00001=private-player-session', req.get_header('Cookie'))
            self.assertIsInstance(opener.call_args.args[0], app.NoSessionRedirect)
        payload = json.loads(self.request('/api/episodes')[2])
        self.assertTrue(payload['session']['connected'])
        self.assertNotIn(session['authcookie'], json.dumps(payload))
        self.assertEqual(list(self.library.iterdir()), [])
        with self.assertRaises(ValueError):
            app.NoSessionRedirect().redirect_request(None, None, 302, '', {}, 'https://untrusted.example')
        self.assertEqual(self.request('/api/session', {'authcookie': 'bad\r\ncookie', 'uid': '123'})[0], 400)
        with patch.object(app.time, 'monotonic', return_value=app.PLAYER_SESSION['received'] + 181):
            self.assertFalse(app.current_player_session().get('authcookie'))
        self.assertEqual(self.request('/api/session', {})[0], 200)
        self.assertFalse(app.current_player_session().get('authcookie'))
        self.assertGreater(app.current_player_session()['version'], version)

    def test_refresh_and_new_session_never_queue_downloads_until_manual_request(self):
        self.episode()
        self.request('/api/register', {'tvid': '102', 'albumId': '9', 'title': 'Show ep2'})
        app.EPISODES['102']['vid'] = 'a' * 32
        app.set_download_progress('102', 'access', message='Cần quyền', sessionVersion=0)
        queue_mock = app.queue_subtitle_downloads
        queue_mock.reset_mock()
        for _ in range(3):
            rows = json.loads(self.request('/api/episodes')[2])['episodes']
            self.assertEqual(next(x for x in rows if x['tvid'] == '102')['downloadProgress']['stage'], 'access')
        app.update_player_session({'authcookie': 'fresh-session', 'uid': '123'})
        self.assertEqual(self.request('/api/episodes')[0], 200)
        queue_mock.assert_not_called()
        with patch.object(app, 'queue_subtitle_downloads', wraps=self.queue_downloads), patch.object(
                app.DOWNLOAD_POOL, 'submit') as submit:
            self.assertEqual(self.request('/api/download', {'tvid': '102'})[0], 200)
            self.assertEqual(self.request('/api/download-all', {'albumId': '9'})[0], 200)
            submit.assert_called_once_with(app.download_episode_source, '102')

    def test_download_results_survive_restart_without_resuming_interrupted_jobs(self):
        for tvid, stage in [('101', 'error'), ('102', 'access'), ('103', 'queued'), ('104', 'downloading')]:
            self.request('/api/register', {'tvid': tvid, 'title': f'Show ep{tvid}', 'albumId': '9'})
            app.set_download_progress(tvid, stage, message='Saved status', sessionVersion=123)
        app.EPISODES.clear()
        app.DOWNLOAD_PROGRESS.clear()
        app.load_library()
        self.assertEqual(app.DOWNLOAD_PROGRESS['101'], {'stage': 'error', 'message': 'Saved status'})
        self.assertEqual(app.DOWNLOAD_PROGRESS['102'], {'stage': 'access', 'message': 'Saved status'})
        self.assertEqual(app.DOWNLOAD_PROGRESS['103']['stage'], 'error')
        self.assertEqual(app.DOWNLOAD_PROGRESS['104']['stage'], 'error')
        with patch.object(app.DOWNLOAD_POOL, 'submit') as submit:
            for _ in range(2):
                self.assertEqual(len(json.loads(self.request('/api/episodes')[2])['episodes']), 4)
            submit.assert_not_called()
        app.queue_subtitle_downloads.assert_not_called()
        self.assertEqual(self.request('/api/delete-subtitle', {'tvid': '101'})[0], 200)
        app.EPISODES.clear()
        app.DOWNLOAD_PROGRESS.clear()
        app.load_library()
        self.assertNotIn('101', app.DOWNLOAD_PROGRESS)

    def test_missing_sdk_vip_types_are_resolved_using_current_login(self):
        app.update_player_session({'authcookie': 'valid-session', 'uid': '123'})
        initial = app.current_player_session()['version']
        payload = {'code': 'A00000', 'data': {'web': {'vipType': 1, 'status': '1'},
                                            'expired': {'vipType': 4, 'status': '0'}}}
        with patch.object(app.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(json.dumps(payload).encode())
            self.refresh_rights('valid-session', '123')
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(app.urlsplit(request.full_url).hostname, 'vinfo.vip.iqiyi.com')
            self.assertIn('P00001=valid-session', request.get_header('Cookie'))
        self.assertEqual(app.current_player_session()['vipTypes'], ['1'])
        self.assertGreater(app.current_player_session()['version'], initial)
        version = app.current_player_session()['version']
        app.update_player_session({'authcookie': 'valid-session', 'uid': '123'})
        self.assertEqual(app.current_player_session()['vipTypes'], ['1'])
        self.assertEqual(app.current_player_session()['version'], version)
        app.update_player_session({})
        self.assertFalse(app.current_player_session().get('authcookie'))

    def test_api_rejects_untrusted_origins_missing_tokens_and_rebound_hosts(self):
        status, headers, _ = self.request('/api/register', {'tvid': '1'}, origin='https://untrusted.example')
        self.assertEqual(status, 403)
        self.assertIsNone(headers.get('Access-Control-Allow-Origin'))
        self.assertEqual(self.request('/api/episodes', token=False, origin='null')[0], 403)
        self.assertEqual(self.request('/', token=False, origin='null')[0], 403)
        self.assertEqual(self.request('/health', token=False, headers={'Host': 'untrusted.example'})[0], 403)
        self.assertEqual(self.request('/api/register', {'tvid': '1'}, token=False)[0], 403)
        self.assertEqual(app.EPISODES, {})
        status, headers, _ = self.request('/api/register', origin='https://www.iq.com', method='OPTIONS', token=False)
        self.assertEqual(status, 204)
        self.assertEqual(headers['Access-Control-Allow-Origin'], 'https://www.iq.com')
        self.assertIn('X-Iqiyi-Token', headers['Access-Control-Allow-Headers'])
        self.assertEqual(self.request('/api/episodes', origin='null')[0], 200)
        self.assertEqual(self.request('/api/episodes', origin='https://localwebapp.iqiyi.com')[0], 200)
        self.assertEqual(self.request('/health', token=False)[0], 200)
        status, headers, page = self.request('/', token=False)
        self.assertEqual(status, 200)
        self.assertIn(self.server.api_token.encode(), page)
        self.assertEqual(headers['X-Frame-Options'], 'DENY')
        self.assertEqual(self.request('/api/register', {'tvid': '1', 'albumId': "9');bad();//"})[0], 400)
        self.assertEqual(self.request('/api/register', {}, headers={'Content-Length': '-1'})[0], 400)

    def test_changing_source_archives_old_work_and_never_serves_it_as_current(self):
        source = self.episode()
        self.complete(source)
        self.assertEqual(self.request('/subtitle.xml?tvid=101&token=' + self.server.api_token, token=False)[0], 200)
        updated = [(10000, 11000, 'Changed source')]
        self.assertEqual(self.request('/api/capture', {'tvid': '101', 'format': 'srt', 'raw': app.to_srt(updated)})[0], 200)
        detail = json.loads(self.request('/api/detail?tvid=101')[2])
        self.assertEqual(detail['cues'][0]['source'], 'Changed source')
        self.assertEqual(detail['cues'][0]['translated'], '')
        self.assertEqual(self.request('/subtitle.xml?tvid=101')[0], 404)
        self.assertEqual(self.request('/api/file?tvid=101')[0], 404)
        rows = json.loads(self.request('/api/episodes')[2])['episodes']
        self.assertFalse(rows[0]['translated'])
        history = list((app.episode_dir('101') / 'history').iterdir())
        self.assertEqual(len(history), 1)
        self.assertTrue((history[0] / 'translations.json').is_file())
        self.assertIn('Old Vietnamese', (history[0] / 'translated.srt').read_text(encoding='utf-8'))
        before = (app.episode_dir('101') / 'source.srt').stat().st_mtime_ns
        self.request('/api/capture', {'tvid': '101', 'format': 'srt', 'raw': app.to_srt(updated)})
        self.assertEqual((app.episode_dir('101') / 'source.srt').stat().st_mtime_ns, before)

    def test_source_fingerprint_blocks_stale_srt_fallback_after_manual_change(self):
        source = self.episode()
        self.complete(source)
        iqiyi_common.atomic_write(app.episode_dir('101') / 'source.srt', app.to_srt([(1000, 2000, 'Different words')]))
        self.assertEqual(app.translated_cues('101'), [])

    def test_failed_source_write_keeps_current_source_and_paid_translation(self):
        source = self.episode()
        self.complete(source)
        folder = app.episode_dir('101')
        write = app.atomic_write

        def fail_source(path, data):
            if path == folder / 'source.srt':
                raise OSError('simulated source save failure')
            write(path, data)

        with patch.object(app, 'atomic_write', side_effect=fail_source):
            self.assertEqual(self.request('/api/capture', {'tvid': '101', 'format': 'srt',
                'raw': app.to_srt([(10000, 11000, 'Changed source')])})[0], 400)
        self.assertEqual(app.parse_source((folder / 'source.srt').read_text(encoding='utf-8'), 'srt'), source)
        self.assertEqual(app.translated_cues('101'), [(1000, 2000, 'Old Vietnamese')])
        self.assertTrue((folder / 'translated.srt').exists())

    def test_duplicate_translation_and_source_replacement_are_rejected_while_busy(self):
        source = self.episode()
        entered, release = threading.Event(), threading.Event()

        def completion(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise TimeoutError('Test worker was not released')
            return self.completion([{'id': 1, 'translation': 'Saved Vietnamese'}])

        settings = {'apiKey': 'offline', 'baseUrl': 'https://example.test/v1',
                    'model': 'provider/model', 'compatible': False}
        with patch.object(app, 'load_ai_settings', return_value=settings), patch.object(
                app, 'compatible_api_request', side_effect=completion) as api:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                first = pool.submit(self.request, '/api/translate', {'tvid': '101'})
                try:
                    self.assertTrue(entered.wait(3))
                    self.assertEqual(self.request('/api/translate', {'tvid': '101'})[0], 409)
                    self.assertEqual(self.request('/api/capture', {'tvid': '101', 'format': 'srt',
                        'raw': app.to_srt([(10000, 11000, 'Changed')])})[0], 409)
                    rows = json.loads(self.request('/api/episodes')[2])['episodes']
                    self.assertEqual(rows[0]['progress']['stage'], 'translating')
                finally:
                    release.set()
                self.assertEqual(first.result()[0], 200)
            self.assertEqual(api.call_count, 1)
            self.assertEqual(api.call_args.args[2], 'chat/completions')
        self.assertEqual(app.translated_cues('101'), [(1000, 2000, 'Saved Vietnamese')])
        self.assertEqual(app.parse_source((app.episode_dir('101') / 'source.srt').read_text(encoding='utf-8'), 'srt'), source)
        with patch.object(app, 'compatible_api_request') as api:
            self.assertEqual(self.request('/api/translate', {'tvid': '101'})[0], 200)
            api.assert_not_called()

    def configure_translation(self, count=3):
        self.episode()
        source = [(i * 1000, (i + 1) * 1000, f'Unique source {i}') for i in range(1, count + 1)]
        app.capture_source('101', source)
        app.AI_SETTINGS_PATH.write_text(json.dumps({'compatible': True, 'model': 'gemini-3.8-flash',
            'apiKey': 'offline-key', 'keyOverride': True, 'baseUrl': 'https://example.test/v1'}), encoding='utf-8')
        return source

    @staticmethod
    def completion(lines):
        content = {'results': lines} if isinstance(lines, list) else lines
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(content, ensure_ascii=False)}}]}

    def test_translation_uses_system_rules_and_source_only_once(self):
        source = self.configure_translation()
        response = self.completion([{'id': i, 'translation': f'Câu {i}'} for i in (3, 1, 2)])
        with patch.object(app, 'compatible_api_request', return_value=response) as api:
            result = app.translate_episode('101')
        self.assertEqual(result['status'], 'translated')
        self.assertEqual(api.call_count, 1)
        payload = api.call_args.args[4]
        self.assertEqual(payload['response_format']['type'], 'json_schema')
        self.assertEqual(payload['response_format']['json_schema']['schema'], {
            'type': 'object', 'properties': {'results': app.TRANSLATION_SCHEMA},
            'required': ['results'], 'additionalProperties': False})
        self.assertNotIn('reasoning_effort', payload)
        self.assertEqual(payload['temperature'], 0.2)
        self.assertGreaterEqual(payload['max_tokens'], 1024)
        self.assertEqual(payload['messages'][0], {'role': 'system', 'content': app.TRANSLATION_SYSTEM +
            '\n\nTrả về đúng MỘT đối tượng JSON có trường "results" chứa mảng JSON được yêu cầu.'})
        prompt = payload['messages'][1]['content']
        self.assertNotIn(app.TRANSLATION_SYSTEM, prompt)
        self.assertNotIn('TSV', prompt)
        self.assertTrue(prompt.endswith('[1,2,3]'))
        for _, _, text in source:
            self.assertEqual(prompt.count(text), 1)
        self.assertEqual(app.translated_cues('101'), [(a, b, f'Câu {i}') for i, (a, b, _) in enumerate(source, 1)])
        self.assertNotIn('album_title_vi', prompt)
        settings = app.load_ai_settings()
        settings['model'] = 'other-model'
        with patch.object(app, 'compatible_api_request', return_value=response) as api:
            app.compatible_chat_completion(settings, 'JSON', 1024)
        self.assertNotIn('reasoning_effort', api.call_args.args[4])
        self.assertEqual(api.call_args.args[4]['temperature'], 0.2)

    def test_missing_duplicate_and_empty_cues_are_repaired_without_overwriting_saved_work(self):
        source = self.configure_translation(4)
        folder = app.episode_dir('101')
        app.save_translation_state(folder, {'sourceHash': app.source_fingerprint(source),
            'translations': {'1': 'Đã lưu'}, 'albumTitleVi': '', 'lastError': ''})
        responses = [self.completion([
            {'id': 1, 'translation': 'Overwrite'}, {'id': 2, 'translation': 'Hai'},
            {'id': 3, 'translation': 'Ba'}, {'id': 3, 'translation': 'Conflicting duplicate'},
            {'id': 4, 'translation': None}, {'id': 999, 'translation': 'Wrong ID'},
            {'id': True, 'translation': 'Wrong type'}, {'id': '4', 'translation': 'Wrong type'}]),
            self.completion([{'id': 2, 'translation': 'Overwrite'}, {'id': 3, 'translation': 'Ba'}, {'id': 4, 'translation': '  '}]),
            self.completion([{'id': 4, 'translation': 'Bốn'}])]
        with patch.object(app, 'compatible_api_request', side_effect=responses) as api:
            self.assertEqual(app.translate_episode('101')['status'], 'translated')
        self.assertEqual(api.call_count, 3)
        prompts = [c.args[4]['messages'][1]['content'] for c in api.call_args_list]
        for prompt, ids in zip(prompts, ('[2,3,4]', '[3,4]', '[4]')):
            self.assertTrue(prompt.endswith(ids))
        self.assertIn('Đã lưu', prompts[1])
        self.assertEqual(app.load_translation_state(folder, source)['translations'],
                         {'1': 'Đã lưu', '2': 'Hai', '3': 'Ba', '4': 'Bốn'})
        self.assertEqual(len(app.parse_source((folder / 'translated.srt').read_text(encoding='utf-8'), 'srt')), 4)

    def test_array_contract_preserves_repeated_and_nonverbal_cues(self):
        self.configure_translation(6)
        source = [(i * 1000, (i + 1) * 1000, text) for i, text in enumerate(
            ['嗯', '嗯', '…', '♪', '[笑声]', '小明：\n等等'], 1)]
        app.capture_source('101', source)
        texts = ['Ừ', 'Ừ', '…', '♪', '[Tiếng cười]', 'Tiểu Minh：\nChờ đã']
        response = self.completion([{'id': i, 'translation': text} for i, text in enumerate(texts, 1)])
        with patch.object(app, 'compatible_api_request', return_value=response):
            self.assertEqual(app.translate_episode('101')['status'], 'translated')
        self.assertEqual(app.translated_cues('101'),
                         [(a, b, text) for (a, b, _), text in zip(source, texts)])
        for malformed in ({'translations': []}, '[]', None):
            with self.assertRaisesRegex(ValueError, 'JSON array'):
                app.valid_translations(malformed, [1])
        self.assertEqual(app.valid_translations([
            {'id': 1, 'text': 'Old field'},
            {'id': 2, 'translation': 'Extra field', 'note': 'No'},
            {'id': 3, 'translation': '…'}], [1, 2, 3]), ({'3': '…'}, []))

    def test_incomplete_translation_stops_after_three_requests_and_resumes_missing_only(self):
        source = self.configure_translation()
        responses = [self.completion([{'id': 1, 'translation': 'Một'}]), self.completion([]), self.completion([])]
        with patch.object(app, 'compatible_api_request', side_effect=responses) as api:
            result = app.translate_episode('101')
        self.assertEqual(api.call_count, 3)
        self.assertEqual((result['status'], result['completed']), ('partial', 1))
        self.assertFalse((app.episode_dir('101') / 'translated.srt').exists())
        response = self.completion([{'id': 3, 'translation': 'Ba'}, {'id': 2, 'translation': 'Hai'}])
        with patch.object(app, 'compatible_api_request', return_value=response) as api:
            self.assertEqual(app.translate_episode('101')['status'], 'translated')
        self.assertTrue(api.call_args.args[4]['messages'][1]['content'].endswith('[2,3]'))
        with patch.object(app, 'compatible_api_request') as api:
            self.assertEqual(app.translate_episode('101')['status'], 'translated')
            api.assert_not_called()

    def test_translation_keeps_saved_cues_if_repair_request_fails(self):
        source = self.configure_translation()
        responses = iter([self.completion([{'id': 1, 'translation': 'Một'}])])
        def fail_repair(*args, **kwargs):
            try:
                return next(responses)
            except StopIteration:
                raise RuntimeError('HTTP 429 offline')
        with patch.object(app, 'compatible_api_request', side_effect=fail_repair) as api, \
                patch.object(app.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, '429'):
                app.translate_episode('101')
        self.assertEqual(api.call_count, 4)
        state = app.load_translation_state(app.episode_dir('101'), source)
        self.assertEqual(state['translations'], {'1': 'Một'})
        self.assertIn('429', state['lastError'])
        self.assertFalse((app.episode_dir('101') / 'translated.srt').exists())

    def test_malformed_translation_is_bounded_and_never_marked_complete(self):
        self.configure_translation()
        malformed = {'choices': [{'message': {'content': '{"translations":['}, 'finish_reason': 'length'}]}
        with patch.object(app, 'compatible_api_request', return_value=malformed) as api:
            with self.assertRaisesRegex(ValueError, 'nội dung chưa hoàn chỉnh'):
                app.translate_episode('101')
        self.assertEqual(api.call_count, 3)
        self.assertEqual(app.TRANSLATION_PROGRESS['101']['stage'], 'error')
        self.assertFalse((app.episode_dir('101') / 'translated.srt').exists())

    def test_legacy_settings_also_use_compatible_api_and_repair_missing_ids(self):
        self.configure_translation(2)
        settings = app.load_ai_settings()
        settings['compatible'] = False
        responses = [self.completion([line])
            for line in ({'id': 2, 'translation': 'Hai'}, {'id': 1, 'translation': 'Một'})]
        with patch.object(app, 'load_ai_settings', return_value=settings), patch.object(
                app, 'compatible_api_request', side_effect=responses) as api:
            self.assertEqual(app.translate_episode('101')['status'], 'translated')
        self.assertEqual(api.call_count, 2)
        for call in api.call_args_list:
            self.assertEqual(call.args[2], 'chat/completions')
            payload = call.args[4]
            self.assertEqual(payload['model'], settings['model'])
            self.assertEqual(payload['response_format']['type'], 'json_schema')
            self.assertTrue(payload['messages'][0]['content'].startswith(app.TRANSLATION_SYSTEM))
        self.assertTrue(api.call_args_list[-1].args[4]['messages'][1]['content'].endswith('[1]'))

    @staticmethod
    def agent_memory():
        return {'setting': 'mixed', 'summary': 'Cổ trang có độc thoại hiện đại.',
                'characters': [{'name': '叶儿', 'translation': 'Diệp Nhi', 'role': 'Người được gọi là tỷ',
                    'address': 'Gọi Diệp Nhi là tỷ khi nguồn xác nhận quan hệ.',
                    'evidence': 'Các cue xác nhận có lời gọi Diệp Nhi là tỷ.'}],
                'glossary': [], 'uncertainties': ['Chưa rõ người đáp ở câu tiếp theo.']}

    def test_agent_detects_context_and_translates_without_a_review_stage(self):
        self.agent_profile.stop()
        source = self.configure_translation(2)
        replies = [self.completion(self.agent_memory()), self.completion([
            {'id': 1, 'translation': 'Chị có biết'}, {'id': 2, 'translation': 'Chị điên rồi sao?'}])]
        with patch.object(app, 'compatible_api_request', side_effect=replies) as api:
            self.assertEqual(app.translate_episode('101')['status'], 'translated')
        self.assertEqual(api.call_count, 2)
        payloads = [call.args[4] for call in api.call_args_list]
        self.assertEqual(payloads[0]['messages'][0]['content'], app.agent.PROFILE_SYSTEM)
        self.assertIn('Diệp Nhi', payloads[1]['messages'][1]['content'])
        self.assertTrue(all('reasoning_effort' not in p for p in payloads))
        self.assertEqual(payloads[0]['max_tokens'], 8192)
        state = app.load_translation_state(app.episode_dir('101'), source)
        self.assertEqual(state['translations'], {'1': 'Chị có biết', '2': 'Chị điên rồi sao?'})
        profile = app.agent.load_profile(app.LIBRARY, app.EPISODES['101'])
        self.assertEqual(profile['episodes']['101'], app.source_fingerprint(source))
        self.assertEqual(json.loads(self.request('/api/agent-profile?tvid=101')[2])['memory']['setting'], 'mixed')

    def test_agent_refreshes_old_rules_without_reusing_reference_aware_memory(self):
        self.agent_profile.stop()
        source = self.configure_translation(1)
        item = app.EPISODES['101']
        app.agent.save_profile(self.library, item, {'memory': self.agent_memory(),
            'episodes': {'101': app.source_fingerprint(source), '102': 'old-rules'},
            'profileVersion': 'old-rules', 'updatedAt': 1})
        with patch.object(app, 'compatible_api_request', return_value=self.completion(self.agent_memory())) as api:
            profile = app.ensure_agent_profile('101', source, app.load_ai_settings())
            app.ensure_agent_profile('101', source, app.load_ai_settings())
        self.assertEqual(api.call_count, 1)
        sent = json.loads(api.call_args.args[4]['messages'][1]['content'])
        self.assertEqual(sent['previous_memory'], {})
        self.assertEqual(sent['episode'][0]['start_ms'], source[0][0])
        self.assertEqual(profile['profileVersion'], app.agent.PROFILE_VERSION)
        self.assertEqual(profile['episodes'], {'101': app.source_fingerprint(source)})

    def test_agent_retries_profile_when_summary_contains_han_characters(self):
        self.agent_profile.stop()
        source = self.configure_translation(1)
        invalid_memory = self.agent_memory()
        invalid_memory['summary'] = '古装剧。 Bối cảnh cổ trang.'
        valid_memory = self.agent_memory()
        replies = [self.completion(invalid_memory), self.completion(valid_memory)]
        with patch.object(app, 'compatible_api_request', side_effect=replies) as api:
            profile = app.ensure_agent_profile('101', source, app.load_ai_settings())

        self.assertEqual(api.call_count, 2)
        retry_prompt = json.loads(api.call_args_list[1].args[4]['messages'][1]['content'])
        self.assertIn('correction_required', retry_prompt)
        self.assertIn('summary', retry_prompt['correction_required'])
        self.assertEqual(profile['memory']['summary'], valid_memory['summary'])

    def test_address_context_keeps_source_timing_and_target_ids(self):
        source = [(104319, 105400, '沈诺'), (106479, 108000, '你终于来了 蔓儿'),
                  (109878, 110840, '你这副模样是在')]
        translations = {'2': 'Cuối cùng huynh cũng tới rồi, Mạn Nhi.'}
        with patch.object(app.agent, 'international_reference', side_effect=AssertionError('offline only')) as reference:
            draft = app.translation_prompt({}, source, translations, [1, 3])
            profile = app.agent.profile_prompt({'provider': 'iqiyi', 'tvid': '101', 'albumId': 'series'},
                                               source, {'memory': {}})
        reference.assert_not_called()
        self.assertIn('"start_ms":106479', draft)
        self.assertNotIn('international_reference', draft + profile)
        self.assertNotIn('international_vi', draft + profile)
        self.assertIn("không dịch từng mảnh như câu độc lập", app.TRANSLATION_SYSTEM)
        self.assertIn("không chép cú pháp Trung", draft)
        self.assertNotIn("Nếu phải chọn giữa câu tự nhiên và câu đúng nghĩa", draft)
        self.assertIn(app.agent.ADDRESS_RULES, app.agent.PROFILE_SYSTEM)

    def test_episode_context_uses_latest_shared_memory_and_refreshes_snapshot(self):
        self.agent_profile.stop()
        source = self.configure_translation(1)
        item = app.EPISODES['101']
        with patch.object(app, 'compatible_api_request', return_value=self.completion(self.agent_memory())):
            original = app.ensure_agent_profile('101', source, app.load_ai_settings())
        later = json.loads(json.dumps(original))
        later['memory']['characters'] = []
        later['memory']['summary'] = 'Thông tin tập sau.'
        app.agent.save_profile(app.LIBRARY, item, later)
        with patch.object(app, 'compatible_api_request') as api:
            refreshed = app.ensure_agent_profile('101', source, app.load_ai_settings())
            self.assertEqual(refreshed['memory'], later['memory'])
            self.assertEqual(json.loads(self.request('/api/agent-profile?tvid=101')[2])['memory'], later['memory'])
            api.assert_not_called()
        snapshot = json.loads((app.episode_dir('101') / 'context-profile.json').read_text(encoding='utf-8'))
        self.assertEqual(snapshot['memory'], later['memory'])
        changed = [(0, 1000, 'Changed source')]
        with patch.object(app, 'compatible_api_request', return_value=self.completion(self.agent_memory())) as api:
            refreshed = app.ensure_agent_profile('101', changed, app.load_ai_settings())
        self.assertEqual(api.call_count, 1)
        self.assertEqual(refreshed['episodes']['101'], app.source_fingerprint(changed))

    def test_draft_batches_keep_absolute_ids_and_save_every_window(self):
        source = self.configure_translation(161)
        calls = []
        def response(*args, **kwargs):
            ids = json.loads(args[3].rsplit(': ', 1)[1])
            calls.append(ids)
            state = app.load_translation_state(app.episode_dir('101'), source)
            # Every batch sees only what earlier groups saved; with the default group size of 3 the
            # two batches of this episode start together, so neither sees the other's reply.
            seen = len(state['translations'])
            if len(ids) == 161 or ids[0] != 1:
                self.assertEqual(seen, 0)
            return [{'id': i, 'translation': f'Dịch đúng câu {i}'} for i in ids]
        with patch.object(app, 'request_translation', side_effect=response), \
                patch.object(app, 'TRANSLATION_BATCH_SIZE', 160):
            self.assertEqual(app.translate_episode('101')['status'], 'translated')
        self.assertEqual(sorted(calls), [list(range(1, 161)), [161]])
        cues = app.translated_cues('101')
        self.assertEqual(len(cues), 161)
        self.assertEqual(cues[80][2], 'Dịch đúng câu 81')

    def test_parallel_groups_keep_every_batch_translation_without_overwriting(self):
        # 355 cues with batch 160 => 3 batches; group size 3 runs them all at once.
        source = self.configure_translation(355)
        started = []

        def response(*args, **kwargs):
            ids = json.loads(args[3].rsplit(': ', 1)[1])
            started.append(ids[0])
            # Stagger replies so the group finishes out of order; a save-per-worker bug would lose cues.
            time.sleep(0.01 * (3 - len(started)))
            return [{'id': i, 'translation': f'Câu {i}'} for i in ids]

        with patch.object(app, 'request_translation', side_effect=response), \
                patch.object(app, 'TRANSLATION_BATCH_SIZE', 160), \
                patch.object(app, 'TRANSLATION_PARALLEL', 3):
            self.assertEqual(app.translate_episode('101')['status'], 'translated')
        state = app.load_translation_state(app.episode_dir('101'), source)
        self.assertEqual(len(state['translations']), 355)
        self.assertEqual(state['translations']['1'], 'Câu 1')
        self.assertEqual(state['translations']['355'], 'Câu 355')

    def test_parallel_one_keeps_serial_draft_visibility(self):
        source = self.configure_translation(355)
        seen = []

        def response(*args, **kwargs):
            ids = json.loads(args[3].rsplit(': ', 1)[1])
            seen.append(len(app.load_translation_state(app.episode_dir('101'), source)['translations']))
            return [{'id': i, 'translation': f'Câu {i}'} for i in ids]

        with patch.object(app, 'request_translation', side_effect=response), \
                patch.object(app, 'TRANSLATION_BATCH_SIZE', 160), \
                patch.object(app, 'TRANSLATION_PARALLEL', 1):
            self.assertEqual(app.translate_episode('101')['status'], 'translated')
        self.assertEqual(seen, [0, 160, 320])

    def test_parallel_group_member_failure_keeps_siblings_saved(self):
        source = self.configure_translation(355)

        def response(*args, **kwargs):
            ids = json.loads(args[3].rsplit(': ', 1)[1])
            if ids[0] == 161:
                raise RuntimeError('HTTP 500 down')
            return [{'id': i, 'translation': f'Câu {i}'} for i in ids]

        with patch.object(app, 'request_translation', side_effect=response), \
                patch.object(app, 'TRANSLATION_BATCH_SIZE', 160), \
                patch.object(app, 'TRANSLATION_PARALLEL', 3):
            result = app.translate_episode('101')
        self.assertEqual(result['status'], 'partial')
        state = app.load_translation_state(app.episode_dir('101'), source)
        # The two healthy batches were saved; only the failing batch is missing.
        self.assertEqual(sorted(int(k) for k in state['translations']),
                         [i for i in range(1, 356) if not 161 <= i <= 320])

    def test_agent_memory_is_scoped_by_provider_and_does_not_run_on_refresh(self):
        self.agent_profile.stop()
        source = self.configure_translation(1)
        item = app.EPISODES['101']
        self.assertNotEqual(app.agent.profile_path(self.library, item),
                            app.agent.profile_path(self.library, {**item, 'provider': 'youku'}))
        with patch.object(app, 'compatible_api_request', return_value=self.completion({'setting': 'historical'})) as api:
            with self.assertRaises(ValueError):
                app.ensure_agent_profile('101', source, app.load_ai_settings())
        self.assertEqual(api.call_count, 2)
        self.assertFalse(app.agent.profile_path(self.library, item).exists())
        with patch.object(app, 'compatible_api_request') as api:
            self.request('/api/episodes')
            self.request('/api/agent-profile?tvid=101')
        api.assert_not_called()

    def test_agent_next_episode_inherits_memory_and_deleting_film_removes_it(self):
        self.agent_profile.stop()
        source = self.configure_translation(1)
        item = app.EPISODES['101']
        with patch.object(app, 'compatible_api_request', return_value=self.completion(self.agent_memory())):
            app.ensure_agent_profile('101', source, app.load_ai_settings())
        next_source = self.episode('102', text='叶儿姐')
        with patch.object(app, 'compatible_api_request', return_value=self.completion(self.agent_memory())) as api:
            app.ensure_agent_profile('102', next_source, app.load_ai_settings())
        sent = json.loads(api.call_args.args[4]['messages'][1]['content'])
        self.assertEqual(sent['previous_memory']['characters'][0]['translation'], 'Diệp Nhi')
        self.assertEqual(set(app.agent.load_profile(self.library, item)['episodes']), {'101', '102'})
        self.assertEqual(app.agent.profile_path(self.library, {'title': 'Show ep1'}),
                         app.agent.profile_path(self.library, {'title': 'Show ep2'}))
        path = app.agent.profile_path(self.library, item)
        self.assertEqual(self.request('/api/delete-album', {'albumId': '9'})[0], 200)
        self.assertFalse(path.exists())

    def test_current_player_log_cannot_assign_previous_episode_tracks(self):
        log = app.PLAYER_LOG
        log.write_text(json.dumps({'albumId': '9', 'tvId': '1', 'entityTitle': 'Show ep1',
            'subtitleData': {'data': [{'lid': 1, 'xml': 'https://meta.video.iqiyi.com/ep1.xml'}]}})
            + '\n' + json.dumps({'albumId': '9', 'tvId': '2', 'entityTitle': 'Show ep2'}), encoding='utf-8')
        expected = [{'lid': '1', 'url': 'https://meta.video.iqiyi.com/ep2.xml'}]
        app.EPISODES['2'] = {'tracks': expected}
        app.sync_current_player()
        self.assertEqual(app.EPISODES['2']['tracks'], expected)
        with patch.object(Path, 'open', side_effect=AssertionError('Unchanged log must not be read again')):
            app.sync_current_player()

    def test_translate_all_uses_numeric_episode_order_instead_of_library_order(self):
        for tvid, order in [('100', 23), ('900', 2), ('800', 1), ('200', 10), ('700', 21)]:
            self.episode(tvid)
            app.EPISODES[tvid].update(order=order, title=f'Audit ep{order}')
        self.episode('500')
        app.EPISODES['500']['title'] = 'Audit 第22集'
        self.episode('400')
        app.EPISODES['400']['title'] = 'Unknown episode'
        self.episode('300')
        app.EPISODES['300']['albumId'] = 'other-album'
        app.EPISODES['600'] = {'albumId': '9', 'order': 3}  # No downloaded source.
        with patch.object(app, 'translate_episode', return_value={'status': 'translated'}) as translate:
            status, _, _ = self.request('/api/translate-all', {'albumId': '9'})
        self.assertEqual(status, 200)
        self.assertEqual([call.args[0] for call in translate.call_args_list],
                         ['800', '900', '200', '700', '500', '100', '400'])

    def test_legacy_complete_translation_is_preserved_and_bound_to_source(self):
        source = self.episode()
        folder = app.episode_dir('101')
        iqiyi_common.atomic_write(folder / 'translations.json', json.dumps({'translations': {'1': 'Existing paid translation'}}))
        with patch.object(app, 'compatible_api_request') as api:
            app.load_library()
            result = app.translate_episode('101')
            self.assertEqual(result['status'], 'translated')
            api.assert_not_called()
        state = json.loads((folder / 'translations.json').read_text(encoding='utf-8'))
        self.assertEqual(state['sourceHash'], app.source_fingerprint(source))
        self.assertEqual(state['translations']['1'], 'Existing paid translation')

    def test_atomic_write_failure_keeps_previous_file(self):
        path = self.root / 'atomic.json'
        path.write_bytes(b'original')
        with patch.object(iqiyi_common.os, 'replace', side_effect=OSError('simulated interrupted save')):
            with self.assertRaises(OSError):
                iqiyi_common.atomic_write(path, 'replacement')
        self.assertEqual(path.read_bytes(), b'original')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['atomic.json', 'library'])


if __name__ == '__main__':
    unittest.main()
