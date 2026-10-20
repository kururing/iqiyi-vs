"""Check manager-to-desktop proxy wiring without launching or closing user apps."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from unittest.mock import patch

import launcher
import subtitle_app as app
from windows_runtime import Process


def check():
    with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
        root = Path(temporary)
        token = "synthetic-admin-token-for-launcher-test"
        (root / ".iqiyi-vi-token").write_text(token, encoding="ascii")
        client = root / "Client" / "QyClient.exe"
        client.parent.mkdir()
        client.touch()
        server = app.SubtitleHTTPServer(("127.0.0.1", 0), app.Handler)
        server.api_token = token
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        stack.enter_context(patch.object(launcher, "ROOT", root))
        stack.enter_context(patch.object(launcher, "MANAGER_URL", f"http://127.0.0.1:{server.server_port}/"))
        stack.enter_context(patch.object(app, "IQIYI_PROXY_URL", ""))
        stack.enter_context(patch.dict(os.environ, {
            "IQIYI_PLAYER_PROXY": "http://stale.example:9999",
            "HTTP_PROXY": "http://system.example:8888", "HTTPS_PROXY": "http://system.example:8888"}))
        manager = Process(1, "pythonw.exe", "pythonw.exe", str(root / "subtitle_app.py"))
        watcher = Process(2, "pythonw.exe", "pythonw.exe", str(root / "watch-players.py") + " iqiyi")
        native = Process(3, "QyClient.exe", str(client), str(client))
        stack.enter_context(patch.object(launcher, "script_processes", side_effect=lambda names, argument=None:
                                          iter([watcher] if "watch-players.py" in names else [manager])))
        stack.enter_context(patch.object(launcher, "list_processes", return_value=[native]))
        stack.enter_context(patch.object(launcher, "manager_busy", return_value=False))
        stopped = stack.enter_context(patch.object(launcher, "stop_processes"))
        stack.enter_context(patch.object(launcher, "run_apply", return_value=0))
        stack.enter_context(patch.object(launcher.subprocess, "run", return_value=
                                          subprocess.CompletedProcess([], 0, str(client) + "\n", "")))
        launched = stack.enter_context(patch.object(launcher.subprocess, "Popen"))
        stack.enter_context(patch.object(launcher, "webview_runtime", return_value=""))
        stack.enter_context(patch.object(launcher, "open_manager_when_ready", return_value=0))
        stack.enter_context(patch.object(launcher.time, "sleep"))
        try:
            for proxy in ("http://127.0.0.1:17981", "http://user:p%40ss@127.0.0.1:17981", ""):
                app.IQIYI_PROXY_URL = proxy
                assert launcher.iqiyi_player_proxy() == proxy
                assert launcher.launch_iqiyi() == 0
                env = launched.call_args.kwargs["env"]
                args = env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"]
                if proxy:
                    assert all(env[key] == proxy for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"))
                    assert "--proxy-server=http://127.0.0.1:17981" in args
                    assert "--proxy-bypass-list=localhost;127.0.0.1;[::1]" in args
                    assert "user" not in args and "p%40ss" not in args
                else:
                    assert "--proxy-server" not in args
                    assert not any(key.lower() in ("http_proxy", "https_proxy", "all_proxy") for key in env)
                assert app.IQIYI_PROXY_URL == proxy, "Launching desktop must preserve the manager's setting"
            assert all(manager not in call.args[0] for call in stopped.call_args_list)
            assert any(watcher in call.args[0] for call in stopped.call_args_list)
            with patch.object(launcher, "ROOT", root / "missing"):
                assert launcher.iqiyi_player_proxy() == "http://stale.example:9999"
        finally:
            server.shutdown()
            server.server_close()
            worker.join()


if __name__ == "__main__":
    check()
    print("PASS: manager proxy reaches desktop launch, credentials stay out of browser arguments, direct mode and manager preservation")
