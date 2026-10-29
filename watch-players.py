# -*- coding: utf-8 -*-
"""Watch iQIYI players and install their Vietnamese hooks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import cdp
from iqiyi_common import (
    signed_lwa_html, atomic_write, installation_lock, iqiyi_install_roots, iqiyi_skin_dir,
    lwa_backup_dir, patch_subtitle_tag, patch_ui_tag, python_executable, subtitle_hook,
    subtitle_manager_alive,
)
from windows_runtime import create_named_mutex, list_processes

ROOT = Path(__file__).resolve().parent
APP_PORT = 18766
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

UI_ENGINE = ROOT / "ext" / "content.js"
SUB_HOOK_JS = ROOT / "ext" / "sub-hook.js"
WRAPPER_APP = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/iQIYI/resources/app"
WRAPPER_SUB_HOOK = WRAPPER_APP / "iqiyi-vi-subtitle.js"
BACKUP_LWA = ROOT / "backup-lwa"
APPDATA_LWA = Path(os.environ.get("APPDATA", "")) / "IQIYI Video" / "localwebapp"
MANAGER_PROCESS = None
LAST_MANAGER_CHECK = 0.0
RUNTIME_SESSIONS: dict[str, cdp.ScriptSession] = {}
EARLY_RUNTIME = None


def python_exe() -> str:
    return str(python_executable(ROOT, background=True))


def revision_of(*scripts: str) -> str:
    return hashlib.sha256("\n".join(scripts).encode("utf-8")).hexdigest()


def find_lwa_dirs() -> list[Path]:
    found: list[Path] = []
    if APPDATA_LWA.exists():
        found.extend(index.parent for index in APPDATA_LWA.rglob("index.html"))
    for base in iqiyi_install_roots(ROOT):
        skin = iqiyi_skin_dir(base)
        if skin:
            pf = skin / "LwaRes" / "iqiyi_webapp"
            if (pf / "index.html").exists():
                found.append(pf)
    return found


def write_if_changed(path: Path, data: str | bytes) -> None:
    try:
        atomic_write(path, data)
    except OSError:
        pass


def patch_lwa() -> None:
    if (ROOT / "watch-iqiyi-vi.disabled").exists() or not UI_ENGINE.exists():
        return
    payload = UI_ENGINE.read_bytes()
    hook = subtitle_hook(ROOT) if SUB_HOOK_JS.exists() else None
    for webapp in find_lwa_dirs():
        write_if_changed(webapp / "lwa-vi.js", payload)
        if hook is not None:
            write_if_changed(webapp / "sub-hook.js", hook)
        protected = signed_lwa_html(webapp)
        for html in webapp.glob("*.html"):
            backup = lwa_backup_dir(BACKUP_LWA, webapp) / html.name
            # Repair pages altered by older patchers and preserve their signed bytes.
            if html.name.casefold() in protected:
                if backup.is_file():
                    write_if_changed(html, backup.read_bytes())
                continue
            try:
                text = html.read_text(encoding="utf-8-sig")
                if not backup.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(html, backup)
            except (OSError, UnicodeError):
                continue
            if hook is not None:
                text = patch_subtitle_tag(text, hook)
            text = patch_ui_tag(text, payload)
            write_if_changed(html, text)


def sync_wrapper_hook() -> None:
    """Keep the iQ.com wrapper's pre-page hook current for the next app launch."""
    if (ROOT / "watch-iqiyi-vi.disabled").exists():
        return
    main = WRAPPER_APP / "main.js"
    if main.is_file() and SUB_HOOK_JS.is_file():
        try:
            patched = "IQIYI-VI EARLY SUBTITLE HOOK" in main.read_text(encoding="utf-8")
        except OSError:
            return
        if patched:
            try:
                write_if_changed(WRAPPER_SUB_HOOK, UI_ENGINE.read_bytes() + b"\n" + subtitle_hook(ROOT))
            except OSError:
                pass


def start_manager() -> None:
    """Start subtitle_app.py when nothing serves the manager port."""
    global MANAGER_PROCESS, LAST_MANAGER_CHECK
    if MANAGER_PROCESS is not None and MANAGER_PROCESS.poll() is None:
        return
    now = time.monotonic()
    if now - LAST_MANAGER_CHECK < 10:
        return
    LAST_MANAGER_CHECK = now
    if subtitle_manager_alive(APP_PORT):
        return
    with (ROOT / "subtitle-manager.stderr.log").open("a", encoding="utf-8") as errors:
        MANAGER_PROCESS = subprocess.Popen(
            [python_exe(), str(ROOT / "subtitle_app.py")],
            cwd=str(ROOT), creationflags=CREATE_NO_WINDOW, close_fds=True,
            stdout=subprocess.DEVNULL, stderr=errors,
        )


def inject_runtime() -> None:
    """Load Vietnamese in WebView2 memory, preserving signed application files."""
    global EARLY_RUNTIME
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:9223/json/version", timeout=1) as response:
            browser = json.load(response)
        address = browser.get("webSocketDebuggerUrl", "")
        endpoint = urlsplit(address)
        if endpoint.scheme != "ws" or endpoint.hostname != "127.0.0.1" or endpoint.port != 9223:
            raise ValueError("Unexpected WebView debugger endpoint")
        script = ("window.__iqiyiViTokenPending = true;\n" + UI_ENGINE.read_text(encoding="utf-8")
                  + "\n" + subtitle_hook(ROOT).decode("utf-8"))
        revision = revision_of(script)
        script += "\nwindow.__iqiyiRuntimeVi = " + json.dumps(revision) + ";"
        script = "if (/(^|\\.)iqiyi\\.com$/i.test(location.hostname)) {\n" + script + "\n}"
        if EARLY_RUNTIME is None:
            EARLY_RUNTIME = cdp.EarlyScriptSession(address)
        EARLY_RUNTIME.install(script)
        return
    except (OSError, ValueError, RuntimeError):
        if EARLY_RUNTIME is not None:
            EARLY_RUNTIME.close()
            EARLY_RUNTIME = None
        # Older WebViews still get a document-start script and are resumed below.
    try:
        with opener.open("http://127.0.0.1:9223/json/list", timeout=1) as response:
            targets = json.load(response)
    except OSError:
        for session in RUNTIME_SESSIONS.values():
            session.close()
        RUNTIME_SESSIONS.clear()
        return  # The native app is closed or still starting.
    if not isinstance(targets, list):
        return
    errors = []
    active = set()
    for target in targets:
        if not isinstance(target, dict) or target.get("type") not in {"page", "iframe", "webview"}:
            continue
        page = urlsplit(target.get("url", ""))
        host = (page.hostname or "").lower()
        if not ((page.scheme == "https" and (host == "iqiyi.com" or host.endswith(".iqiyi.com"))) or
                (page.scheme == "about" and page.path == "blank")):
            continue
        websocket = urlsplit(target.get("webSocketDebuggerUrl", ""))
        if websocket.scheme != "ws" or websocket.hostname != "127.0.0.1" or websocket.port != 9223:
            continue
        key = target["webSocketDebuggerUrl"]
        active.add(key)
        script = ("window.__iqiyiViTokenPending = true;\n" + UI_ENGINE.read_text(encoding="utf-8")
                  + "\n" + subtitle_hook(ROOT).decode("utf-8"))
        revision = revision_of(script)
        try:
            script += "\nwindow.__iqiyiRuntimeVi = " + json.dumps(revision) + ";"
            script = "if (/(^|\\.)iqiyi\\.com$/i.test(location.hostname)) {\n" + script + "\n}"
            if key not in RUNTIME_SESSIONS:
                RUNTIME_SESSIONS[key] = cdp.ScriptSession(target)
            RUNTIME_SESSIONS[key].install([script])
        except (OSError, ValueError, RuntimeError) as exc:
            session = RUNTIME_SESSIONS.pop(key, None)
            if session:
                session.close()
            errors.append(str(exc))
    for key in set(RUNTIME_SESSIONS) - active:
        RUNTIME_SESSIONS.pop(key).close()
    if errors:
        raise RuntimeError(f"{len(errors)} app target(s): " + errors[0])



def run_iqiyi() -> int:
    global EARLY_RUNTIME
    handle = create_named_mutex("Local\\iqiyi-vi-watch")
    if not handle:
        return 0
    next_maintenance = 0.0
    while True:
        try:
            if not (ROOT / "watch-iqiyi-vi.disabled").exists():
                inject_runtime()
                # Finish preparing frames before disk maintenance can delay CDP polling.
                if time.monotonic() >= next_maintenance and (EARLY_RUNTIME is None or not EARLY_RUNTIME.pending):
                    if any(process.name.lower() in {"qyclient.exe", "qyplayer.exe"}
                           for process in list_processes(include_command_line=False)):
                        start_manager()
                    with installation_lock(ROOT):
                        patch_lwa()
                        sync_wrapper_hook()
                    next_maintenance = time.monotonic() + 2
            else:
                if EARLY_RUNTIME is not None:
                    EARLY_RUNTIME.close()
                    EARLY_RUNTIME = None
                for session in RUNTIME_SESSIONS.values():
                    session.close()
                RUNTIME_SESSIONS.clear()
        except (OSError, ValueError, RuntimeError) as exc:
            with (ROOT / "watch-iqiyi.runtime.log").open("a", encoding="utf-8") as errors:
                errors.write(time.strftime("%H:%M:%S ") + str(exc) + "\n")
        time.sleep(0.2)

def main() -> int:
    parser = argparse.ArgumentParser(description="Watch iQIYI video players")
    parser.add_argument("player", choices=("iqiyi",))
    parser.parse_args()
    return run_iqiyi()


if __name__ == "__main__":
    raise SystemExit(main())
