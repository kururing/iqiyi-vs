"""Run: python test-p1.py. Uses temporary data, loopback HTTP and mocked providers."""
from contextlib import ExitStack
import http.client
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

import iqiyi_common as common
import subtitle_app as app


def check():
    admin = "synthetic-admin-token-for-tests-only"
    provider = {"id": "p1", "name": "Test", "baseUrl": "https://provider.invalid/v1",
                "apiKey": "synthetic-provider-key"}
    original = {"providers": [provider], "translateProviderId": "p1", "translateModel": "test",
                "profileProviderId": "p1", "profileModel": "test"}
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        root = Path(temporary)
        settings = root / "settings.json"
        settings.write_text(json.dumps(original), encoding="utf-8")
        for name, value in {"LIBRARY": root / "library", "AI_SETTINGS_PATH": settings,
                            "EPISODES": {}, "ALBUM_LISTS": {}, "EPISODE_LOCKS": {},
                            "DOWNLOAD_PROGRESS": {}, "TRANSLATION_PROGRESS": {}}.items():
            stack.enter_context(patch.object(app, name, value))
        stack.enter_context(patch.object(app, "_env_value", return_value=""))
        localization = stack.enter_context(patch.object(app, "start_app_localization"))
        api = stack.enter_context(patch.object(app, "compatible_api_request", return_value={"data": []}))
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        server.api_token = admin
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def request(method, path, data=None, token=None, origin=None):
            headers = {"Content-Type": "application/json"}
            if token is not None:
                headers["X-Iqiyi-Token"] = token
            if origin is not None:
                headers["Origin"] = origin
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                conn.request(method, path, json.dumps(data) if data is not None else None, headers)
                response = conn.getresponse()
                raw = response.read()
                body = json.loads(raw) if raw and response.getheader("Content-Type", "").startswith("application/json") else raw
                return response.status, body
            finally:
                conn.close()

        try:
            website = "https://www.iqiyi.com"
            local = f"http://127.0.0.1:{server.server_port}"
            status, config = request("GET", "/api/extension-token", origin=website)
            player = config["token"]
            assert status == 200 and player == common.player_token(admin) and player != admin
            assert request("GET", "/api/extension-token", origin="https://evil.invalid")[0] == 403
            assert request("GET", "/api/settings", token=admin, origin=local)[0] == 200
            for origin in (website, "https://www.iq.com", "https://localwebapp.iqiyi.com",
                           "https://www.youku.com", "null"):
                for token in (player, admin):
                    assert request("GET", "/api/settings", token=token, origin=origin)[0] == 403
                    assert request("POST", "/api/ai/models", {"providerId": "p1",
                        "baseUrl": "https://foreign.invalid/v1"}, token, origin)[0] == 403
                    assert request("POST", "/api/app-localization", {"action": "restore"}, token, origin)[0] == 403
                    assert request("POST", "/api/delete-album", {"provider": "iqiyi",
                        "seriesTitle": "Shared"}, token, origin)[0] == 403
                assert request("OPTIONS", "/api/settings", origin=origin)[0] == 403
            for origin in (None, local):
                assert request("GET", "/api/settings", token=player, origin=origin)[0] == 403
                assert request("POST", "/api/settings", original, player, origin)[0] == 403
                assert request("POST", "/api/app-localization", {"action": "apply"}, player, origin)[0] == 403
            localization.assert_not_called()
            api.assert_not_called()

            # Scoped credentials must still support real player registration/capture/read flows.
            episode = {"tvid": "101", "provider": "iqiyi", "title": "Shared", "albumTitle": "Shared"}
            assert request("OPTIONS", "/api/register", origin=website)[0] == 204
            assert request("POST", "/api/register", episode, player, website)[0] == 200
            assert request("POST", "/api/session", {}, player, "https://localwebapp.iqiyi.com")[0] == 200
            assert request("POST", "/api/capture", {"tvid": "101", "format": "srt",
                "raw": "1\n00:00:00,000 --> 00:00:01,000\nsource\n"}, player, website)[0] == 200
            source = [(0, 1000, "source")]
            app.save_translation_state(app.episode_dir("101"), {
                "sourceHash": app.source_fingerprint(source), "translations": {"1": "Bản dịch"}})
            assert request("GET", "/api/translation-state?tvid=101", token=player, origin=website)[1]["available"]
            assert request("GET", "/api/file?tvid=101", token=player, origin="https://www.youku.com")[0] == 200
            assert request("GET", "/api/file?tvid=101&token=" + player)[0] == 200
            assert request("GET", "/subtitle.xml?tvid=101", origin=website)[0] == 200
            with patch.object(app, "international_movie_title", return_value="Official title"):
                assert request("GET", "/api/international-title?id=1234567890123456",
                               token=player, origin=website) == (200, {"title": "Official title"})

            # Changing endpoint cannot silently carry a stored key, even from the local admin UI.
            status, _ = request("POST", "/api/ai/models", {"providerId": "p1",
                "baseUrl": "https://foreign.invalid/v1"}, admin, local)
            assert status == 400
            api.assert_not_called()
            assert request("POST", "/api/ai/models", {"providerId": "p1"}, admin, local)[0] == 200
            assert api.call_args.args[:2] == (provider["baseUrl"], provider["apiKey"])
            assert request("POST", "/api/ai/models", {"providerId": "p1",
                "baseUrl": "https://foreign.invalid/v1", "apiKey": "explicit-new-key"}, admin, local)[0] == 200
            assert api.call_args.args[:2] == ("https://foreign.invalid/v1", "explicit-new-key")
            unchanged = {**original, "providers": [{**provider, "apiKey": ""}]}
            assert request("POST", "/api/settings", unchanged, admin, local)[0] == 200
            assert json.loads(settings.read_text(encoding="utf-8"))["providers"][0]["apiKey"] == provider["apiKey"]
            changed = {**unchanged, "providers": [{**unchanged["providers"][0], "baseUrl": "https://foreign.invalid/v1"}]}
            assert request("POST", "/api/settings", changed, admin, local)[0] == 200
            assert json.loads(settings.read_text(encoding="utf-8"))["providers"][0]["apiKey"] == ""

            # UI confirms one provider: same-name episodes belonging to the other must survive.
            app.save_episode("yk-test", {"tvid": "yk-test", "provider": "youku",
                "albumId": "yk-show", "albumTitle": "Shared"})
            app.capture_source("yk-test", source)
            deletion = {"provider": "iqiyi", "albumId": "", "seriesTitle": "Shared"}
            assert request("POST", "/api/delete-album", {"seriesTitle": "Shared"}, admin)[0] == 400
            assert request("POST", "/api/delete-album", deletion, admin)[0] == 200
            assert "101" not in app.EPISODES and "yk-test" in app.EPISODES
            assert (app.episode_dir("yk-test") / "source.srt").exists()
            # Also scope the album-ID branch, including legacy/malformed cross-provider metadata.
            app.save_episode("102", {"tvid": "102", "albumId": "123", "albumTitle": "Shared"})
            app.save_episode("yk-test", {**app.EPISODES["yk-test"], "albumId": "123"})
            assert request("POST", "/api/delete-album", {"provider": "iqiyi", "albumId": "123"}, admin)[0] == 200
            assert "102" not in app.EPISODES and "yk-test" in app.EPISODES
            assert 'provider:first.provider||"iqiyi",albumId:first.albumId' in app.PAGE
        finally:
            server.shutdown()
            server.server_close()
            worker.join(3)

        # A clean checkout can inject subtitles without any local dictionary.
        spec = importlib.util.spec_from_file_location("watch_p1", Path(__file__).with_name("watch-players.py"))
        watcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(watcher)
        (root / "ui-engine.js").write_text("/* engine */", encoding="utf-8")
        hook = root / "sub-hook.js"
        hook.write_text("/* hook */", encoding="utf-8")
        with patch.object(watcher, "ROOT", root), patch.object(watcher, "SUB_HOOK_JS", hook), \
                patch.object(watcher, "api_token", return_value=admin):
            scripts = watcher.read_scripts()
            assert "window.__youkuViDict = {};" in scripts[0]
            assert common.player_token(admin) in scripts[1] and admin not in scripts[1]
            (root / ".local").mkdir()
            (root / ".local" / "youku-vi.json").write_text('{"local":"fallback"}', encoding="utf-8")
            assert '"local":"fallback"' in watcher.read_scripts()[0]
            (root / "youku-vi.json").write_text('{"release":"first"}', encoding="utf-8")
            assert '"release":"first"' in watcher.read_scripts()[0]
        with patch.object(common, "api_token", return_value=admin):
            injected = common.subtitle_hook(root).decode("utf-8")
            assert common.player_token(admin) in injected and admin not in injected
    print("PASS: scoped player/admin access, endpoint-bound keys, provider-scoped deletion, Youku dictionary fallback")


if __name__ == "__main__":
    check()
