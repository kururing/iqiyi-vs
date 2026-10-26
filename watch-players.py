# -*- coding: utf-8 -*-
"""Watch iQIYI and Youku players and install their Vietnamese hooks."""
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
    SIGNED_LWA_HTML, api_token, atomic_write, installation_lock, iqiyi_install_roots, iqiyi_skin_dir,
    lwa_backup_dir, patch_subtitle_tag, patch_ui_tag, python_executable, subtitle_hook,
    subtitle_manager_alive, update_lwa_ini_flags, player_token,
)
from windows_runtime import create_named_mutex

CDP = cdp
ROOT = Path(__file__).resolve().parent
APP_PORT = 18766
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

LWA_JS = ROOT / "lwa-vi.js"
SUB_HOOK_JS = ROOT / "sub-hook.js"
WRAPPER_APP = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/iQIYI/resources/app"
WRAPPER_SUB_HOOK = WRAPPER_APP / "iqiyi-vi-subtitle.js"
BACKUP_LWA = ROOT / "backup-lwa"
APPDATA_LWA = Path(os.environ.get("APPDATA", "")) / "IQIYI Video" / "localwebapp"
PPSTREAM_INI = Path(os.environ.get("APPDATA", "")) / "IQIYI Video" / "LStyle" / "PPStream.ini"
WATCH_LOCK_FILE = None
MANAGER_PROCESS = None
LAST_MANAGER_CHECK = 0.0
RUNTIME_SESSIONS: dict[str, CDP.ScriptSession] = {}
EARLY_RUNTIME = None


def python_exe() -> str:
    return str(python_executable(ROOT, background=True))


def revision_of(*scripts: str) -> str:
    return hashlib.sha256("\n".join(scripts).encode("utf-8")).hexdigest()


def runtime_current(target: dict, probe: str, revision: str) -> bool:
    """True when the page already runs the hooks for this exact script revision."""
    result = CDP.evaluate(target, probe + " === " + json.dumps(revision))
    return bool(result.get("result", {}).get("value"))


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
    if (ROOT / "watch-iqiyi-vi.disabled").exists() or not LWA_JS.exists():
        return
    payload = LWA_JS.read_bytes()
    hook = subtitle_hook(ROOT) if SUB_HOOK_JS.exists() else None
    for webapp in find_lwa_dirs():
        write_if_changed(webapp / "lwa-vi.js", payload)
        if hook is not None:
            write_if_changed(webapp / "sub-hook.js", hook)
        for html in webapp.glob("*.html"):
            # These native bootstrap pages are signature-checked by QyClient.
            if html.name.casefold() in SIGNED_LWA_HTML:
                continue
            try:
                text = html.read_text(encoding="utf-8-sig")
                backup = lwa_backup_dir(BACKUP_LWA, webapp) / html.name
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
                write_if_changed(WRAPPER_SUB_HOOK, LWA_JS.read_bytes() + b"\n" + subtitle_hook(ROOT))
            except OSError:
                pass


def persist_ini() -> None:
    if (ROOT / "watch-iqiyi-vi.disabled").exists() or not PPSTREAM_INI.exists():
        return
    try:
        raw = PPSTREAM_INI.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    new = update_lwa_ini_flags(raw)
    if new == raw:
        return
    try:
        atomic_write(PPSTREAM_INI, new)
    except OSError:
        pass


def start_manager() -> None:
    """Start subtitle_app.py when nothing serves the manager port (shared by iQIYI and Youku)."""
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
        script = ("window.__iqiyiViTokenPending = true;\n" + LWA_JS.read_text(encoding="utf-8")
                  + "\n" + subtitle_hook(ROOT).decode("utf-8"))
        revision = revision_of(script)
        script += "\nwindow.__iqiyiRuntimeVi = " + json.dumps(revision) + ";"
        script = "if (/(^|\\.)iqiyi\\.com$/i.test(location.hostname)) {\n" + script + "\n}"
        if EARLY_RUNTIME is None:
            EARLY_RUNTIME = CDP.EarlyScriptSession(address)
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
        script = ("window.__iqiyiViTokenPending = true;\n" + LWA_JS.read_text(encoding="utf-8")
                  + "\n" + subtitle_hook(ROOT).decode("utf-8"))
        revision = revision_of(script)
        try:
            script += "\nwindow.__iqiyiRuntimeVi = " + json.dumps(revision) + ";"
            script = "if (/(^|\\.)iqiyi\\.com$/i.test(location.hostname)) {\n" + script + "\n}"
            if key not in RUNTIME_SESSIONS:
                RUNTIME_SESSIONS[key] = CDP.ScriptSession(target)
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
    global WATCH_LOCK_FILE, EARLY_RUNTIME
    handle = create_named_mutex("Local\\iqiyi-vi-watch")
    if not handle:
        return 0
    WATCH_LOCK_FILE = handle
    next_maintenance = 0.0
    while True:
        try:
            if not (ROOT / "watch-iqiyi-vi.disabled").exists():
                inject_runtime()
                if time.monotonic() >= next_maintenance:
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

PORT = int(os.environ.get("YOUKU_CDP_PORT", "9224"))
LOG = ROOT / "youku-vi.log"
LOCK_HANDLE = None
INSTALLED: set[str] = set()
LAST_ERROR = ""
NO_TARGETS_SINCE = time.monotonic()


def log(message: str) -> None:
    try:
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(time.strftime("%H:%M:%S") + " " + message + "\n")
    except OSError:
        pass


def read_scripts() -> list[str]:
    engine = (ROOT / "ui-engine.js").read_text(encoding="utf-8")
    engine = (engine.replace("iqiyiVi", "youkuVi").replace("iqiyi-vi", "youku-vi")
              .replace("subtitleContainer|caption-main", "subtitleContainer|caption-main|kui-subtitle|youku-vi-subtitle"))
    manager_config = "window.__youkuViApi = 'http://127.0.0.1:18766'; window.__youkuViToken = " + json.dumps(player_token(api_token(ROOT))) + ";\n"
    return [
        engine,
        manager_config + SUB_HOOK_JS.read_text(encoding="utf-8"),
    ]


def youku_targets() -> list[dict]:
    request = urllib.request.Request(f"http://127.0.0.1:{PORT}/json", headers={"Host": f"127.0.0.1:{PORT}"})
    with urllib.request.urlopen(request, timeout=1.5) as response:
        value = json.loads(response.read().decode("utf-8"))
    return [item for item in value if item.get("type") == "page" and item.get("webSocketDebuggerUrl")
            and is_youku_page(item.get("url", ""))]


def is_youku_page(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if parsed.username or parsed.password:
            return False
        return ((parsed.scheme == "https" and parsed.port in (None, 443) and
                 (host == "youku.com" or host.endswith(".youku.com"))) or
                (parsed.scheme == "client" and host == "iku.youku.com" and parsed.port is None))
    except ValueError:
        return False


YOUKU_PROBE = "!!window.__youkuVi && !!window.__youkuViSubtitle && window.__youkuViRevision"


def acquire_youku_lock() -> bool:
    global LOCK_HANDLE
    LOCK_HANDLE = create_named_mutex("Local\\youku-vi-watch")
    return bool(LOCK_HANDLE)


def run_youku() -> int:
    global LAST_ERROR, NO_TARGETS_SINCE
    if os.name != "nt" or not acquire_youku_lock():
        return 0
    log("watcher started")
    while True:
        try:
            start_manager()
            current = youku_targets()
            if current:
                NO_TARGETS_SINCE = time.monotonic()
            elif time.monotonic() - NO_TARGETS_SINCE > 60:
                log("no Youku page targets; watcher stopped")
                return 0
            active = {item["id"] for item in current}
            INSTALLED.intersection_update(active)
            scripts = read_scripts()
            revision = revision_of(*scripts)
            scripts.append("window.__youkuViRevision = " + json.dumps(revision) + ";")
            for target in current:
                if target["id"] in INSTALLED and runtime_current(target, YOUKU_PROBE, revision):
                    continue
                cdp.inject(target, scripts)
                INSTALLED.add(target["id"])
                log("injected " + target.get("url", target["id"]))
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            message = type(exc).__name__ + ": " + str(exc)
            if message != LAST_ERROR:
                log(message)
                LAST_ERROR = message
        else:
            LAST_ERROR = ""
        time.sleep(1)

def main() -> int:
    parser = argparse.ArgumentParser(description="Watch supported video players")
    parser.add_argument("player", choices=("iqiyi", "youku"))
    player = parser.parse_args().player
    return run_iqiyi() if player == "iqiyi" else run_youku()


if __name__ == "__main__":
    raise SystemExit(main())
