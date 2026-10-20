"""Run: python test-session.py. App/web session isolation and public API contract."""
import http.client
import json
import threading
from unittest.mock import patch

import subtitle_app as app


def check():
    with patch.object(app, "PLAYER_SESSIONS", {}), patch.object(app, "SESSION_VERSION", 0), \
            patch.object(app.time, "monotonic", return_value=1000) as clock, \
            patch.object(app, "refresh_player_entitlements"), \
            patch.object(app, "sync_current_player"), patch.object(app, "EPISODES", {}):
        assert not app.player_session_status()["synced"]
        app.update_player_session({"authcookie": "app-auth", "uid": "123", "vipTypes": ["1"]})
        app.update_player_session({"source": "web"})
        assert app.current_player_session()["authcookie"] == "app-auth"
        assert app.player_session_status()["sources"] == {
            "app": {"connected": True, "synced": True},
            "web": {"connected": False, "synced": True}}
        app.update_player_session({"source": "web", "authcookie": "web-auth", "uid": "456", "vipTypes": ["3"]})
        assert app.current_player_session()["source"] == "app"
        app.update_player_session({})  # Native logout must leave the web login intact.
        assert app.current_player_session()["authcookie"] == "web-auth"
        version = app.current_player_session()["version"]
        app.update_player_session({"source": "web", "authcookie": "web-auth", "uid": "456", "vipTypes": ["3"]})
        assert app.current_player_session()["version"] == version
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        server.api_token = "test-admin"
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            connection.request("GET", "/api/episodes", headers={"X-Iqiyi-Token": server.api_token})
            response = connection.getresponse()
            payload = json.loads(response.read())
            assert response.status == 200
            assert payload["session"]["sources"]["web"]["connected"]
            assert not payload["session"]["sources"]["app"]["connected"]
            assert "web-auth" not in json.dumps(payload) and "456" not in json.dumps(payload)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            worker.join()
        clock.return_value = 1181
        assert not app.player_session_status()["synced"]
        assert "authcookie" not in app.current_player_session()
        app.update_player_session({"source": "web", "authcookie": "new-web-auth", "uid": "789", "vipTypes": ["1"]})
        assert app.current_player_session()["uid"] == "789"
        assert not app.player_session_status()["sources"]["app"]["synced"]
        for invalid in ({"source": "unknown"}, {"source": "web", "authcookie": "bad;cookie", "uid": "1"}):
            try:
                app.update_player_session(invalid)
            except ValueError:
                pass
            else:
                raise AssertionError("Invalid session accepted")


if __name__ == "__main__":
    check()
    print("PASS: app/web login isolation, logout, expiry, fallback and credential-free status API")
