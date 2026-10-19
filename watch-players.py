# -*- coding: utf-8 -*-
"""Watch iQIYI and Youku players and install their Vietnamese hooks."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import cdp
from iqiyi_common import (
    api_token, atomic_write, installation_lock, iqiyi_install_roots, iqiyi_skin_dir,
    lwa_backup_dir, patch_subtitle_tag, subtitle_hook, subtitle_manager_alive,
    update_lwa_ini_flags,
)
from windows_runtime import create_named_mutex

CDP = cdp
ROOT = Path(__file__).resolve().parent
APP_PORT = 18766
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

SCRIPT_TAG = '<script src="./lwa-vi.js"></script>'
LWA_JS = ROOT / "lwa-vi.js"
SUB_HOOK_JS = ROOT / "sub-hook.js"
WRAPPER_APP = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/iQIYI/resources/app"
WRAPPER_SUB_HOOK = WRAPPER_APP / "iqiyi-vi-subtitle.js"
BACKUP_LWA = ROOT / "backup-lwa"
APPDATA_LWA = Path(os.environ.get("APPDATA", "")) / "IQIYI Video" / "localwebapp"
PPSTREAM_INI = Path(os.environ.get("APPDATA", "")) / "IQIYI Video" / "LStyle" / "PPStream.ini"
WATCH_LOCK_FILE = None
IQIYI_MANAGER_PROCESS = None
IQIYI_LAST_MANAGER_CHECK = 0.0

def python_exe() -> str:
    for name in ("pythonw.exe", "python.exe"):
        path = ROOT / ".venv" / "Scripts" / name
        if path.exists():
            return str(path)
    return sys.executable


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
            if html.name in {
                "compactPlayer.html", "compactPlayer_mac.html", "download.html", "index.html", "login.html",
                "mac.html", "mini.html", "placeholder.html", "player.html", "player_mac.html",
            }:
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
            if "lwa-vi.js" in text and "sub-hook.js" in text:
                write_if_changed(html, text)
                continue
            if "lwa-vi.js" in text:
                continue
            if "</head>" in text:
                text = text.replace("</head>", SCRIPT_TAG + "</head>", 1)
            elif "</body>" in text:
                text = text.replace("</body>", SCRIPT_TAG + "</body>", 1)
            else:
                text += SCRIPT_TAG
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
                write_if_changed(WRAPPER_SUB_HOOK, subtitle_hook(ROOT))
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


def iqiyi_manager_alive() -> bool:
    return subtitle_manager_alive(APP_PORT)


def start_iqiyi_manager() -> None:
    global IQIYI_MANAGER_PROCESS, IQIYI_LAST_MANAGER_CHECK
    if IQIYI_MANAGER_PROCESS is not None and IQIYI_MANAGER_PROCESS.poll() is None:
        return
    now = time.monotonic()
    if now - IQIYI_LAST_MANAGER_CHECK < 10:
        return
    IQIYI_LAST_MANAGER_CHECK = now
    if iqiyi_manager_alive():
        return
    with (ROOT / "subtitle-manager.stderr.log").open("a", encoding="utf-8") as errors:
        IQIYI_MANAGER_PROCESS = subprocess.Popen(
            [python_exe(), str(ROOT / "subtitle_app.py")],
            cwd=str(ROOT), creationflags=CREATE_NO_WINDOW, close_fds=True,
            stdout=subprocess.DEVNULL, stderr=errors,
        )


def inject_runtime() -> None:
    """Load Vietnamese in WebView2 memory, preserving signed application files."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("http://127.0.0.1:9223/json/list", timeout=1) as response:
            targets = json.load(response)
    except OSError:
        return  # The native app is closed or still starting.
    if not isinstance(targets, list):
        return
    for target in targets:
        if not isinstance(target, dict) or target.get("type") != "page":
            continue
        page = urlsplit(target.get("url", ""))
        host = (page.hostname or "").lower()
        if page.scheme != "https" or not (host == "iqiyi.com" or host.endswith(".iqiyi.com")):
            continue
        websocket = urlsplit(target.get("webSocketDebuggerUrl", ""))
        if websocket.scheme != "ws" or websocket.hostname != "127.0.0.1" or websocket.port != 9223:
            continue
        script = LWA_JS.read_text(encoding="utf-8") + "\n" + subtitle_hook(ROOT).decode("utf-8")
        revision = hashlib.sha256(script.encode("utf-8")).hexdigest()
        state = CDP.evaluate(target, "!!window.__iqiyiVi && window.__iqiyiRuntimeVi === " + json.dumps(revision))
        if state.get("result", {}).get("value"):
            continue
        script += "\nwindow.__iqiyiRuntimeVi = " + json.dumps(revision) + ";"
        script = "if (/(^|\\.)iqiyi\\.com$/i.test(location.hostname)) {\n" + script + "\n}"
        CDP.inject(target, [script])


def run_iqiyi() -> int:
    global WATCH_LOCK_FILE
    handle = create_named_mutex("Local\\iqiyi-vi-watch")
    if not handle:
        return 0
    WATCH_LOCK_FILE = handle
    while True:
        try:
            if not (ROOT / "watch-iqiyi-vi.disabled").exists():
                start_iqiyi_manager()
                with installation_lock(ROOT):
                    patch_lwa()
                    sync_wrapper_hook()
                    persist_ini()
                inject_runtime()
        except (OSError, ValueError, RuntimeError) as exc:
            with (ROOT / "watch-iqiyi.runtime.log").open("a", encoding="utf-8") as errors:
                errors.write(time.strftime("%H:%M:%S ") + str(exc) + "\n")
        time.sleep(2)

PORT = int(os.environ.get("YOUKU_CDP_PORT", "9224"))
LOG = ROOT / "youku-vi.log"
LOCK_HANDLE = None
SCRIPTS = ("youku-ui.js", "youku-subtitle.js")
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
    dictionary = json.loads((ROOT / "youku-vi.json").read_text(encoding="utf-8"))
    engine = (ROOT / "ui-engine.js").read_text(encoding="utf-8")
    engine = (engine.replace("iqiyiVi", "youkuVi").replace("iqiyi-vi", "youku-vi")
              .replace("subtitleContainer|caption-main", "subtitleContainer|caption-main|kui-subtitle|youku-vi-subtitle"))
    manager_config = "window.__youkuViApi = 'http://127.0.0.1:18766'; window.__youkuViToken = " + json.dumps(api_token(ROOT)) + ";\n"
    return [
        "window.__youkuViDict = " + json.dumps(dictionary, ensure_ascii=False, separators=(",", ":")) + ";\n" + engine,
        (ROOT / "youku-ui.js").read_text(encoding="utf-8"),
        manager_config + (ROOT / "youku-subtitle.js").read_text(encoding="utf-8"),
    ]


YOUKU_LAST_MANAGER_CHECK = 0.0


def start_youku_manager() -> None:
    global YOUKU_LAST_MANAGER_CHECK
    now = time.monotonic()
    if now - YOUKU_LAST_MANAGER_CHECK < 10:
        return
    YOUKU_LAST_MANAGER_CHECK = now
    if subtitle_manager_alive(APP_PORT):
        return
    try:
        subprocess.Popen([sys.executable, str(ROOT / "subtitle_app.py")], cwd=str(ROOT),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True)
    except OSError as exc:
        log("subtitle manager start failed: " + str(exc))


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


def has_hooks(target: dict, revision: str) -> bool:
    result = cdp.evaluate(
        target, "!!window.__youkuVi && !!window.__youkuViSubtitle && window.__youkuViRevision === " + json.dumps(revision))
    return bool(result.get("result", {}).get("value"))


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
            start_youku_manager()
            current = youku_targets()
            if current:
                NO_TARGETS_SINCE = time.monotonic()
            elif time.monotonic() - NO_TARGETS_SINCE > 60:
                log("no Youku page targets; watcher stopped")
                return 0
            active = {item["id"] for item in current}
            INSTALLED.intersection_update(active)
            scripts = read_scripts()
            revision = hashlib.sha256("\n".join(scripts).encode("utf-8")).hexdigest()
            scripts.append("window.__youkuViRevision = " + json.dumps(revision) + ";")
            for target in current:
                if target["id"] in INSTALLED and has_hooks(target, revision):
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
