# -*- coding: utf-8 -*-
"""Inject isolated Youku UI/subtitle translators into its Electron pages."""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit
from iqiyi_common import api_token

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("YOUKU_CDP_PORT", "9224"))
APP_PORT = 18766
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


LAST_MANAGER_CHECK = 0.0


def start_manager() -> None:
    global LAST_MANAGER_CHECK
    now = time.monotonic()
    if now - LAST_MANAGER_CHECK < 10:
        return
    LAST_MANAGER_CHECK = now
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{APP_PORT}/health", timeout=0.6) as response:
            if response.status == 200:
                return
    except (TimeoutError, OSError):
        pass
    try:
        subprocess.Popen([sys.executable, str(ROOT / "subtitle_app.py")], cwd=str(ROOT),
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True)
    except OSError as exc:
        log("subtitle manager start failed: " + str(exc))


def targets() -> list[dict]:
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


def ws_connect(url: str) -> socket.socket:
    if not url.startswith("ws://"):
        raise ValueError("Unexpected CDP websocket URL")
    hostpath = url[5:].split("/", 1)
    host, port = hostpath[0].split(":", 1)
    path = "/" + (hostpath[1] if len(hostpath) > 1 else "")
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    sock = socket.create_connection((host, int(port)), timeout=3)
    sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
                  f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    response = sock.recv(4096)
    if b" 101 " not in response.split(b"\r\n", 1)[0]:
        sock.close()
        raise RuntimeError("CDP websocket handshake failed")
    return sock


def send(sock: socket.socket, value: dict) -> None:
    raw = json.dumps(value, ensure_ascii=False).encode("utf-8")
    mask = os.urandom(4)
    size = len(raw)
    header = bytearray([0x81])
    if size < 126:
        header.append(0x80 | size)
    elif size < 65536:
        header.append(0x80 | 126)
        header.extend(struct.pack(">H", size))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack(">Q", size))
    header.extend(mask)
    sock.sendall(header + bytes(byte ^ mask[index % 4] for index, byte in enumerate(raw)))


def recv_exact(sock: socket.socket, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        part = sock.recv(size - len(result))
        if not part:
            raise ConnectionError("CDP websocket closed")
        result.extend(part)
    return bytes(result)


def receive(sock: socket.socket) -> dict:
    first, second = recv_exact(sock, 2)
    opcode, size = first & 0x0F, second & 0x7F
    if size == 126:
        size = struct.unpack(">H", recv_exact(sock, 2))[0]
    elif size == 127:
        size = struct.unpack(">Q", recv_exact(sock, 8))[0]
    mask = recv_exact(sock, 4) if second & 0x80 else b""
    body = recv_exact(sock, size)
    if mask:
        body = bytes(byte ^ mask[index % 4] for index, byte in enumerate(body))
    if opcode == 8:
        raise ConnectionError("CDP websocket closed")
    if opcode != 1:
        return {}
    return json.loads(body.decode("utf-8"))


def call(sock: socket.socket, method: str, params: dict, command_id: int) -> dict:
    send(sock, {"id": command_id, "method": method, "params": params})
    sock.settimeout(3)
    while True:
        response = receive(sock)
        if response.get("id") == command_id:
            if "error" in response:
                raise RuntimeError(response["error"].get("message", "CDP command failed"))
            return response.get("result", {})


def inject(target: dict, scripts: list[str]) -> None:
    sock = ws_connect(target["webSocketDebuggerUrl"])
    try:
        call(sock, "Page.enable", {}, 1)
        for index, script in enumerate(scripts):
            call(sock, "Page.addScriptToEvaluateOnNewDocument", {"source": script}, index + 2)
        result = call(sock, "Runtime.evaluate", {
            "expression": "\n".join(scripts), "awaitPromise": True, "returnByValue": False,
        }, len(scripts) + 2)
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            raise RuntimeError(details.get("exception", {}).get("description") or details.get("text", "Script injection failed"))
    finally:
        sock.close()


def has_hooks(target: dict, revision: str) -> bool:
    sock = ws_connect(target["webSocketDebuggerUrl"])
    try:
        result = call(sock, "Runtime.evaluate", {
            "expression": "!!window.__youkuVi && !!window.__youkuViSubtitle && window.__youkuViRevision === " + json.dumps(revision),
            "returnByValue": True,
        }, 1)
        return bool(result.get("result", {}).get("value"))
    finally:
        sock.close()


def acquire_lock() -> bool:
    global LOCK_HANDLE
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.wintypes.BOOL, ctypes.wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = ctypes.wintypes.HANDLE
    kernel.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
    handle = kernel.CreateMutexW(None, False, "Local\\youku-vi-watch")
    if not handle:
        return False
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle(handle)
        return False
    LOCK_HANDLE = handle
    return True


def main() -> int:
    global LAST_ERROR, NO_TARGETS_SINCE
    if os.name != "nt" or not acquire_lock():
        return 0
    log("watcher started")
    while True:
        try:
            start_manager()
            current = targets()
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
                inject(target, scripts)
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


if __name__ == "__main__":
    raise SystemExit(main())
