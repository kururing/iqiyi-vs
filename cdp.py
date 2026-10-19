"""Small stdlib-only Chrome DevTools Protocol websocket transport."""
from __future__ import annotations

import base64
import json
import os
import socket
import struct


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
