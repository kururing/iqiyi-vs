"""Session-bound Vietnamese audio and a seekable MP4 assembled from iq.com segments."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import gzip
import io
import json
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request

from iqcom_requests import pooled_open, read_response
from iqiyi_common import atomic_write


def audio_url(url: str) -> str:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    port_allowed = parsed.port in (None, 80, 443) or (
        parsed.scheme == "https" and host.endswith(".71edge.com") and parsed.port == 8402)
    if (parsed.scheme not in ("http", "https") or parsed.username or parsed.password or
            not port_allowed or parsed.fragment or
            not any(host.endswith("." + suffix) for suffix in ("iqiyi.com", "iq.com", "71edge.com"))):
        raise ValueError("Địa chỉ âm thanh iq.com không hợp lệ.")
    return "https://" + parsed.netloc + parsed.path + ("?" + parsed.query if parsed.query else "")


@contextmanager
def audio_open(url, *, byte_range=None):
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.iq.com/", "Accept-Encoding": "identity"}
    if byte_range:
        headers["Range"] = f"bytes={byte_range[0]}-{byte_range[1]}"
    # No domestic cookies, authorization headers, redirects, or system proxy.
    with pooled_open(Request(audio_url(url), headers=headers), timeout=15) as response:
        yield response


def byte_range(value: str | None, size: int) -> tuple[int, int]:
    if not value:
        return 0, size - 1
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if not match or not any(match.groups()):
        raise ValueError("Invalid byte range")
    first, last = match.groups()
    if not first:
        count = int(last)
        if count < 1:
            raise ValueError("Invalid byte range")
        return max(0, size - count), size - 1
    start, end = int(first), min(int(last), size - 1) if last else size - 1
    if start >= size or start > end:
        raise ValueError("Unsatisfiable byte range")
    return start, end


class AudioSource:
    def __init__(self, data: dict, track: dict, info: dict):
        self.info = info
        self.key = secrets.token_urlsafe(18)
        self.lock = threading.Lock()
        self.locations = {}
        self.base = audio_url(data.get("dd", "")).rstrip("/")
        self.parts = track.get("fs") or []
        if (track.get("ff") != "amp4" or not 2 <= len(self.parts) <= 512 or
                str(track.get("lid")) != "161" or track.get("cf") != "aac"):
            raise ValueError("iq.com chưa cung cấp track AAC Việt có thể phát riêng.")
        for part in self.parts:
            location = str(part.get("l", "")) if isinstance(part, dict) else ""
            parsed = urlsplit(location)
            if (not isinstance(part, dict) or parsed.scheme or parsed.netloc or parsed.fragment or
                    len(location) > 8192 or re.search(r"[\x00-\x20]", location) or
                    not re.fullmatch(r"/v0/[\w/.-]+\.amp4", parsed.path) or
                    type(part.get("b")) is not int or not 0 < part["b"] <= 64_000_000):
                raise ValueError("Danh sách đoạn âm thanh iq.com không hợp lệ.")
        with audio_open(self.location(0)) as response:
            raw = read_response(response, 4_000_000)
        if raw.startswith(b"\x1f\x8b"):
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                raw = stream.read(4_000_001)
        if (len(raw) > 4_000_000 or raw[4:8] != b"ftyp" or b"moov" not in raw or b"mp4a" not in raw or
                any(marker in raw for marker in (b"enca", b"sinf", b"tenc"))):
            raise ValueError("Track âm thanh này không có định dạng MP4 được hỗ trợ.")
        self.init = raw
        self.size = len(raw) + sum(part["b"] for part in self.parts[1:])
        if self.size > 1_000_000_000:
            raise ValueError("Track âm thanh quá lớn.")

    def location(self, index):
        with self.lock:
            cached = self.locations.get(index)
            if cached and cached[0] > time.monotonic():
                return cached[1]
            request_url = self.base + self.parts[index]["l"]
        with audio_open(request_url) as response:
            result = json.loads(read_response(response, 32_000))
        if not result.get("l"):
            raise ValueError("iq.com chưa cấp đường phát âm thanh cho tập này. Kiểm tra phiên và quyền xem tập.")
        location = audio_url(result.get("l", ""))
        with self.lock:
            self.locations[index] = (time.monotonic() + 120, location)
        return location

    def read(self, start, end):
        """Yield exact byte ranges; do not buffer or download the entire episode."""
        offset = 0
        for index, size in enumerate([len(self.init)] + [part["b"] for part in self.parts[1:]]):
            low, high = max(0, start - offset), min(size - 1, end - offset)
            offset += size
            if low > high:
                continue
            if index == 0:
                yield self.init[low:high + 1]
                continue
            with audio_open(self.location(index), byte_range=(low, high)) as response:
                expected = f"bytes {low}-{high}/{size}"
                if response.status != 206 or response.headers.get("Content-Range") != expected:
                    raise OSError("Máy chủ âm thanh không trả đúng đoạn cần phát; thử bật lại âm thanh Việt.")
                remaining = high - low + 1
                while remaining:
                    chunk = response.read(min(65536, remaining))
                    if not chunk:
                        raise OSError("Đoạn âm thanh tải về bị gián đoạn.")
                    remaining -= len(chunk)
                    yield chunk


class IqcomAudio:
    def __init__(self, path: Path, resolve, session_version):
        self.path, self.resolve, self.session_version = path, resolve, session_version
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="iqcom-audio")
        self.states = {}
        self.playback = {}
        self.settings = {"enabled": False}
        try:
            self.settings = self.validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            pass

    @staticmethod
    def validate(data):
        if not isinstance(data, dict):
            raise ValueError("Cài đặt âm thanh không hợp lệ.")
        enabled = data.get("enabled")
        if not isinstance(enabled, bool):
            raise ValueError("Chọn âm thanh gốc hoặc tiếng Việt iq.com.")
        return {"enabled": enabled}

    def configure(self, data):
        settings = self.validate(data)
        with self.lock:
            atomic_write(self.path, json.dumps(settings))
            self.settings = settings
            self.states.clear()
            self.playback.clear()
        return self.status()

    def status(self, tvid=""):
        if tvid and not re.fullmatch(r"\d{8,24}", tvid):
            raise ValueError("Mã tập âm thanh không hợp lệ.")
        with self.lock:
            state = self.states.get(tvid)
            version = self.session_version()
            if tvid and self.settings["enabled"] and (not state or state["session"] != version or
                    (not state.get("source") and state["expires"] <= time.monotonic())):
                state = {"loading": True, "available": False, "error": "", "session": version,
                         "expires": time.monotonic() + 180, "source": None}
                if len(self.states) >= 16:
                    self.states.pop(next(iter(self.states)))
                self.states[tvid] = state
                self.pool.submit(self._load, tvid, state)
            elif tvid and self.settings["enabled"] and state.get("source") and state["expires"] <= time.monotonic():
                state["expires"] = time.monotonic() + 180
                self.pool.submit(self._refresh, tvid, state)
            result = {**self.settings, "loading": False, "available": False, "error": ""}
            if self.settings["enabled"] and state:
                result.update({k: state[k] for k in ("loading", "available", "error")})
                if state.get("source"):
                    result.update(state["source"].info, stream=state["source"].key)
            result["playback"] = dict(self.playback)
            return result

    def _load(self, tvid, state):
        try:
            data, track, info = self.resolve(tvid)
            source = AudioSource(data, track, info)
            values = {"source": source, "available": True, "error": "", "expires": time.monotonic() + 900}
        except Exception as exc:
            message = (str(exc)[:300] if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError)
                       else "Không tải được âm thanh iq.com. Kiểm tra kết nối và phiên iq.com rồi thử lại.")
            values = {"source": None, "available": False, "error": message, "expires": time.monotonic() + 30}
        with self.lock:
            if self.states.get(tvid) is state:
                state.update(values, loading=False)

    def _refresh(self, tvid, state):
        try:
            data, track, info = self.resolve(tvid)
            refreshed = AudioSource(data, track, info)
            with self.lock:
                if self.states.get(tvid) is state and state["session"] == self.session_version():
                    source = state["source"]
                    if source and source.size == refreshed.size and source.init == refreshed.init:
                        with source.lock:
                            source.base, source.parts, source.locations = refreshed.base, refreshed.parts, {}
                        state["expires"] = time.monotonic() + 900
                    else:
                        state["expires"] = time.monotonic() + 30
        except Exception:
            with self.lock:
                if self.states.get(tvid) is state:
                    state["expires"] = time.monotonic() + 30

    def source(self, tvid, key):
        with self.lock:
            state = self.states.get(tvid, {})
            source = state.get("source")
            if (not self.settings["enabled"] or state.get("session") != self.session_version() or
                    not source or not secrets.compare_digest(source.key, str(key))):
                raise ValueError("Nguồn âm thanh đã thay đổi. Tắt rồi bật lại âm thanh Việt.")
            return source

    def report(self, data):
        tvid, message = str(data.get("tvid", "")), str(data.get("message", ""))
        if not re.fullmatch(r"\d{8,24}", tvid) or len(message) > 300:
            raise ValueError("Trạng thái âm thanh không hợp lệ.")
        with self.lock:
            self.playback = {"tvid": tvid, "message": message, "updated": time.time()}
