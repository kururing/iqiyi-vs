# -*- coding: utf-8 -*-
"""Keep the iQIYI hook installed and run the local subtitle manager."""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from iqiyi_common import atomic_write, installation_lock, iqiyi_install_roots, lwa_backup_dir, subtitle_hook, patch_subtitle_tag

ROOT = Path(__file__).resolve().parent
SCRIPT_TAG = '<script src="./lwa-vi.js"></script>'
LWA_JS = ROOT / "lwa-vi.js"
SUB_HOOK_JS = ROOT / "sub-hook.js"
WRAPPER_APP = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/iQIYI/resources/app"
WRAPPER_SUB_HOOK = WRAPPER_APP / "iqiyi-vi-subtitle.js"
BACKUP_LWA = ROOT / "backup-lwa"
APPDATA_LWA = Path(os.environ.get("APPDATA", "")) / "IQIYI Video" / "localwebapp"
PPSTREAM_INI = Path(os.environ.get("APPDATA", "")) / "IQIYI Video" / "LStyle" / "PPStream.ini"
APP_PORT = 18766
CREATE_NO_WINDOW = 0x08000000
WATCH_LOCK_FILE = None
MANAGER_PROCESS = None
LAST_MANAGER_CHECK = 0.0
CDP = None
LWA_INI_FLAGS = {
    "lwa_disable_checksign_pcafx": "1",
    "lwa_disable_update": "1",
    "lwa_disable_repalce_update": "1",
    "lwa_disable_load_copy": "1",
}


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
        if not base.exists():
            continue
        versions = sorted((p for p in base.iterdir() if p.is_dir() and (p / "skin").exists()),
                          key=lambda p: tuple(int(n) for n in re.findall(r"\d+", p.name)), reverse=True)
        if versions:
            pf = versions[0] / "skin" / "LwaRes" / "iqiyi_webapp"
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
    new = raw
    for key, val in LWA_INI_FLAGS.items():
        if re.search(rf"(?m)^{re.escape(key)}=.*$", new):
            new = re.sub(rf"(?m)^{re.escape(key)}=.*$", f"{key}={val}", new)
        else:
            new += f"\n{key}={val}\n"
    if new == raw:
        return
    try:
        atomic_write(PPSTREAM_INI, new)
    except OSError:
        pass


def manager_alive() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{APP_PORT}/health", timeout=0.6) as response:
            return response.status == 200
    except (TimeoutError, OSError):
        return False


def start_manager() -> None:
    global MANAGER_PROCESS, LAST_MANAGER_CHECK
    if MANAGER_PROCESS is not None and MANAGER_PROCESS.poll() is None:
        return
    now = time.monotonic()
    if now - LAST_MANAGER_CHECK < 10:
        return
    LAST_MANAGER_CHECK = now
    if manager_alive():
        return
    with (ROOT / "subtitle-manager.stderr.log").open("a", encoding="utf-8") as errors:
        MANAGER_PROCESS = subprocess.Popen(
            [python_exe(), str(ROOT / "subtitle_app.py")],
            cwd=str(ROOT), creationflags=CREATE_NO_WINDOW, close_fds=True,
            stdout=subprocess.DEVNULL, stderr=errors,
        )


def inject_runtime() -> None:
    """Load Vietnamese in WebView2 memory, preserving signed application files."""
    global CDP
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
        if CDP is None:
            CDP = importlib.import_module("watch-youku-vi")  # Reuse the existing stdlib CDP transport.
        script = LWA_JS.read_text(encoding="utf-8") + "\n" + subtitle_hook(ROOT).decode("utf-8")
        revision = hashlib.sha256(script.encode("utf-8")).hexdigest()
        sock = CDP.ws_connect(target["webSocketDebuggerUrl"])
        try:
            state = CDP.call(sock, "Runtime.evaluate", {
                "expression": "!!window.__iqiyiVi && window.__iqiyiRuntimeVi === " + json.dumps(revision),
                "returnByValue": True,
            }, 1)
        finally:
            sock.close()
        if state.get("result", {}).get("value"):
            continue
        script += "\nwindow.__iqiyiRuntimeVi = " + json.dumps(revision) + ";"
        script = "if (/(^|\\.)iqiyi\\.com$/i.test(location.hostname)) {\n" + script + "\n}"
        CDP.inject(target, [script])


def main() -> int:
    global WATCH_LOCK_FILE
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.wintypes.BOOL, ctypes.wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = ctypes.wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
    handle = kernel32.CreateMutexW(None, False, "Local\\iqiyi-vi-watch")
    if not handle or ctypes.get_last_error() == 183:
        if handle:
            kernel32.CloseHandle(handle)
        return 0
    WATCH_LOCK_FILE = handle
    while True:
        try:
            if not (ROOT / "watch-iqiyi-vi.disabled").exists():
                start_manager()
                with installation_lock(ROOT):
                    patch_lwa()
                    sync_wrapper_hook()
                    persist_ini()
                inject_runtime()
        except (OSError, ValueError, RuntimeError) as exc:
            with (ROOT / "watch-iqiyi.runtime.log").open("a", encoding="utf-8") as errors:
                errors.write(time.strftime("%H:%M:%S ") + str(exc) + "\n")
        time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
