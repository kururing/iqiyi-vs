"""Small stdlib-only Chrome DevTools Protocol websocket transport."""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import select
import time


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


def evaluate(target: dict, expression: str) -> dict:
    sock = ws_connect(target["webSocketDebuggerUrl"])
    try:
        return call(sock, "Runtime.evaluate", {"expression": expression, "returnByValue": True}, 1)
    finally:
        sock.close()


class ScriptSession:
    """Keep init scripts registered across navigation by keeping their CDP session open."""

    def __init__(self, target: dict):
        self.sock = ws_connect(target["webSocketDebuggerUrl"])
        self.command_id = 0
        self.script_ids: list[str] = []
        self.scripts: list[str] = []
        try:
            self.command("Page.enable", {})
        except (OSError, ValueError, RuntimeError):
            self.close()
            raise

    def command(self, method: str, params: dict) -> dict:
        self.command_id += 1
        return call(self.sock, method, params, self.command_id)

    def install(self, scripts: list[str]) -> None:
        if self.scripts == scripts:
            # A cheap command also detects a closed/replaced target connection.
            self.command("Runtime.evaluate", {"expression": "0"})
            return
        for identifier in self.script_ids:
            self.command("Page.removeScriptToEvaluateOnNewDocument", {"identifier": identifier})
        self.script_ids.clear()
        for script in scripts:
            result = self.command("Page.addScriptToEvaluateOnNewDocument", {"source": script})
            self.script_ids.append(result["identifier"])
        self.command("Runtime.runIfWaitingForDebugger", {})
        result = self.command("Runtime.evaluate", {
            "expression": "\n".join(scripts), "awaitPromise": True, "returnByValue": False,
        })
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            raise RuntimeError(details.get("exception", {}).get("description") or details.get("text", "Script injection failed"))
        self.scripts = list(scripts)

    def close(self) -> None:
        self.sock.close()


class EarlyScriptSession:
    """Pause newly created WebViews until their document-start script is registered."""

    def __init__(self, url: str):
        self.sock = ws_connect(url)
        self.sock.settimeout(3)
        self.command_id = 0
        self.source = ""
        self.sessions: dict[str, dict] = {}
        self.pending: dict[int, tuple] = {}
        self.errors: list[str] = []

    def command(self, method: str, params: dict, session: str = "", done=None) -> None:
        self.command_id += 1
        message = {"id": self.command_id, "method": method, "params": params}
        if session:
            message["sessionId"] = session
        self.pending[self.command_id] = (time.monotonic(), session, done,
                                         method == "Runtime.evaluate" and "contextId" in params)
        send(self.sock, message)

    def install(self, source: str) -> None:
        if not self.source:
            self.source = source
            self.command("Target.setAutoAttach", {
                "autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True,
            })
        elif self.source != source:
            self.source = source
            for session in list(self.sessions):
                self.register(session)
        self.poll()

    def resume(self, session: str) -> None:
        self.command("Runtime.runIfWaitingForDebugger", {}, session)

    def register(self, session: str) -> None:
        state = self.sessions[session]
        source = self.source
        old = state.get("identifier")
        if old:
            self.command("Page.removeScriptToEvaluateOnNewDocument", {"identifier": old}, session)

        def registered(response):
            if session not in self.sessions:
                return
            if "error" not in response:
                state["identifier"] = response["result"]["identifier"]
                # Also update an already loaded page; the engine is idempotent.
                self.command("Runtime.evaluate", {"expression": source}, session,
                             lambda result: self.resume(session))
                for context in state.get("contexts", ()):
                    self.command("Runtime.evaluate", {"expression": source, "contextId": context}, session)
            else:
                self.resume(session)

        self.command("Page.addScriptToEvaluateOnNewDocument", {
            "source": source, "runImmediately": True,
        }, session, registered)

    def handle(self, message: dict) -> None:
        if message.get("method") == "Target.attachedToTarget":
            params = message["params"]
            session = params["sessionId"]
            target = params["targetInfo"]
            if target.get("type") in {"page", "iframe", "webview"}:
                self.sessions[session] = {"contexts": set()}
                # Same-process child frames do not create separate Target attachments.
                self.command("Runtime.enable", {}, session)
                self.command("Page.enable", {}, session,
                             lambda response: self.register(session) if session in self.sessions else None)
            else:
                self.resume(session)
        elif message.get("method") == "Target.detachedFromTarget":
            self.sessions.pop(message["params"]["sessionId"], None)
        elif message.get("method") == "Runtime.executionContextCreated":
            session = message.get("sessionId")
            context = message["params"]["context"]
            if session in self.sessions and context.get("auxData", {}).get("isDefault"):
                self.sessions[session]["contexts"].add(context["id"])
                self.command("Runtime.evaluate", {"expression": self.source, "contextId": context["id"]}, session)
        elif message.get("method") == "Runtime.executionContextDestroyed":
            state = self.sessions.get(message.get("sessionId"))
            if state is not None:
                state["contexts"].discard(message["params"]["executionContextId"])
        elif message.get("method") == "Runtime.executionContextsCleared":
            state = self.sessions.get(message.get("sessionId"))
            if state is not None:
                state["contexts"].clear()
        elif "id" in message:
            entry = self.pending.pop(message["id"], None)
            if entry:
                context_gone = entry[3] and message.get("error", {}).get("message") in {
                    "Cannot find context with specified id", "Execution context was destroyed."}
                if "error" in message and not context_gone:
                    self.errors.append(message["error"].get("message", "Early script registration failed"))
                if entry[2]:
                    entry[2](message)

    def poll(self) -> None:
        for _ in range(200):
            if not select.select([self.sock], [], [], 0)[0]:
                break
            self.handle(receive(self.sock))
        expired = [identifier for identifier, entry in self.pending.items()
                   if time.monotonic() - entry[0] > 5]
        for identifier in expired:
            _, session, done, _ = self.pending.pop(identifier)
            if session:
                self.resume(session)
            self.errors.append("Timed out preparing WebView before playback")
        if self.errors:
            error = self.errors.pop(0)
            self.errors.clear()
            raise RuntimeError(error)

    def close(self) -> None:
        try:
            for session in self.sessions:
                self.resume(session)
            self.command("Target.setAutoAttach", {
                "autoAttach": False, "waitForDebuggerOnStart": False, "flatten": True,
            })
        except OSError:
            pass
        self.sock.close()
