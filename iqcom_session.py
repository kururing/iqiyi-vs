"""A private, persistent iq.com browser profile; all browser work stays on one thread."""
from __future__ import annotations

import atexit
import hashlib
import json
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit


def login_cookie(cookies: list[dict]) -> str:
    active = {row["name"]: row["value"] for row in cookies
              if row.get("expires", -1) == -1 or row["expires"] > time.time()}
    # The international site uses I00001/I00019; P00001 belongs to older players.
    if active.get("I00001"):
        return active["I00001"] if active.get("I00019", "1") == "1" else ""
    return active.get("P00001", "")


def episode_url(suffix: str) -> str:
    url = urljoin("https://www.iq.com/play/", suffix)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "www.iq.com" or not parsed.path.startswith("/play/"):
        raise ValueError("Liên kết tập iq.com không hợp lệ.")
    return url


def dash_data(raw: str, tvid: str) -> dict:
    """Accept JSON and the player's JSONP, always checking the exact episode."""
    if len(raw) > 4_000_000:
        raise ValueError("Metadata phát iq.com quá lớn.")
    raw = raw.strip()
    if not raw.startswith("{"):
        match = re.fullmatch(r"[\w.$]+\s*\(([\s\S]*)\)\s*;?", raw)
        if not match:
            raise ValueError("Metadata phát iq.com không hợp lệ.")
        raw = match[1]
    payload = json.loads(raw)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or str(data.get("tvid")) != tvid:
        raise ValueError("Metadata phát iq.com không đúng tập.")
    return data


def has_vietnamese_track(data: dict, tvid: str) -> bool:
    if not isinstance(data, dict) or str(data.get("tvid")) != tvid:
        return False
    program = data.get("program")
    return isinstance(program, dict) and any(
        isinstance(row, dict) and str(row.get("lid")) == "23" and
        any(row.get(fmt) for fmt in ("xml", "webvtt", "vtt", "srt"))
        for row in (program.get("stl") or []))


class IqcomSession:
    def __init__(self, profile: Path):
        self.profile = profile
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="iqcom-browser")
        self.lock = threading.Lock()
        self.state = {"connected": False, "browserOpen": False, "opening": False,
                      "synced": False, "message": "", "version": 0}
        self.context = self.playwright = None
        self.headed = False
        self.cookie_signature = hashlib.sha256(b"").hexdigest()
        self.auth_signature = hashlib.sha256(b"").hexdigest()
        self.last_poll = 0.0
        self.poll_pending = False
        self.browser_cookies = None
        self.applied_signature = None
        try:
            self.source = (self.profile / "browser-source").read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            self.source = ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", self.source):
            self.source = ""
        self.state["message"] = "Bấm Kiểm tra iq.com để chọn phiên của trình duyệt đang dùng."
        atexit.register(self.close)

    @property
    def saved(self) -> bool:
        return self.browser_cookies is not None or (self.profile / "Default").is_dir()

    @property
    def version(self) -> int:
        with self.lock:
            return self.state["version"]

    def status(self) -> dict:
        with self.lock:
            return {**self.state, "saved": self.saved}

    def login(self) -> dict:
        # Kept for old UI clients; checking a login must never open a window.
        return self.status()

    def update(self, rows, source: str, *, select: bool = False) -> dict:
        if not isinstance(source, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", source):
            raise ValueError("Tải lại tiện ích và trang quản lý để chọn phiên iq.com của trình duyệt.")
        if not isinstance(select, bool):
            raise ValueError("Yêu cầu chọn phiên iq.com không hợp lệ.")
        if not isinstance(rows, list) or len(rows) > 200:
            raise ValueError("Cookie iq.com không hợp lệ.")
        cookies = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Cookie iq.com không hợp lệ.")
            domain = str(row.get("domain", "")).lower()
            name, value = row.get("name", ""), row.get("value", "")
            path = row.get("path", "/")
            if (domain.lstrip(".") not in ("iq.com", "www.iq.com") or
                    not isinstance(name, str) or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]{1,256}", name) or
                    not isinstance(value, str) or len(value) > 8192 or re.search(r"[\x00-\x1f\x7f;]", value) or
                    not isinstance(path, str) or not path.startswith("/") or len(path) > 1024):
                raise ValueError("Cookie không thuộc phiên iq.com hợp lệ.")
            expires = row.get("expirationDate", -1)
            if isinstance(expires, bool) or not isinstance(expires, (int, float)) or not math.isfinite(expires):
                raise ValueError("Thời hạn cookie iq.com không hợp lệ.")
            if expires != -1 and expires <= time.time():
                continue
            cookie = {"name": name, "value": value, "domain": domain, "path": path,
                      "secure": bool(row.get("secure", True)), "httpOnly": bool(row.get("httpOnly", False))}
            if expires != -1:
                cookie["expires"] = expires
            same_site = {"strict": "Strict", "lax": "Lax", "no_restriction": "None"}.get(row.get("sameSite"))
            if same_site:
                cookie["sameSite"] = same_site
            cookies.append(cookie)
        signature = hashlib.sha256(json.dumps(cookies, sort_keys=True).encode()).hexdigest()
        auth = login_cookie(cookies)
        connected = bool(auth)
        auth_signature = hashlib.sha256(auth.encode()).hexdigest()
        with self.lock:
            if select and source != self.source:
                self.profile.mkdir(parents=True, exist_ok=True)
                (self.profile / "browser-source").write_text(source, encoding="utf-8")
                self.source = source
            if source != self.source:
                return {**self.state, "saved": self.saved}
            # Playback cache depends on the login, not frequently changing analytics cookies.
            changed = auth_signature != self.auth_signature
            if changed:
                self.state["version"] += 1
            self.auth_signature = auth_signature
            self.cookie_signature, self.browser_cookies = signature, cookies
            self.state.update(synced=True, connected=connected, opening=False,
                message=("Đã nhận phiên iq.com của trình duyệt hiện tại. Quyền VIP được kiểm tra khi lấy phụ đề." if connected else
                         "Chưa đăng nhập iq.com trong trình duyệt hiện tại."))
        if signature != self.applied_signature:
            self.pool.submit(self._store_browser_cookies)
        return self.status()

    def _store_browser_cookies(self):
        try:
            context = self._browser()
            with self.lock:
                cookies, signature = self.browser_cookies, self.cookie_signature
            if cookies is not None and signature != self.applied_signature:
                context.clear_cookies()
                if cookies:
                    context.add_cookies(cookies)
                self.applied_signature = signature
            return True
        except Exception:
            self._set(message="Đã kiểm tra phiên trình duyệt nhưng chưa lưu được hồ sơ iq.com. Thử kiểm tra lại.")
            return False

    def dash(self, suffix: str, tvid: str) -> dict:
        url = episode_url(suffix)
        if not re.fullmatch(r"\d{8,24}", tvid):
            raise ValueError("Mã tập iq.com không hợp lệ.")
        return self.pool.submit(self._dash, url, tvid).result(timeout=150)

    def _set(self, **values):
        with self.lock:
            self.state.update(values)

    def _closed(self, *_):
        self.context = None
        self.applied_signature = None
        self._set(browserOpen=False)

    def _browser(self, headed: bool = False):
        if self.context is not None:
            return self.context
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise ValueError("Chưa cài trình hỗ trợ iq.com. Chạy: python -m pip install -r requirements.txt") from None
        if self.playwright is None:
            self.playwright = sync_playwright().start()
        options = {"headless": True, "locale": "vi-VN", "accept_downloads": False,
                   "service_workers": "block", "args": ["--restore-last-session", "--autoplay-policy=user-gesture-required",
                   "--disable-background-mode", "--disable-quic", "--no-proxy-server"]}
        # Use an installed browser; no separate browser download on Windows.
        for channel, vendor in (("msedge", "Microsoft/Edge"), ("chrome", "Google/Chrome")):
            executable = "msedge.exe" if channel == "msedge" else "chrome.exe"
            if any((Path(os.environ.get(env, "")) / vendor / "Application" / executable).is_file()
                   for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")):
                options["channel"] = channel
                break
        self.profile.mkdir(parents=True, exist_ok=True)
        try:
            self.context = self.playwright.chromium.launch_persistent_context(str(self.profile), **options)
        except Exception:
            raise ValueError("Không mở được hồ sơ iq.com. Đóng cửa sổ iq.com cũ rồi thử lại; "
                             "cần Edge/Chrome hoặc chạy: python -m playwright install chromium") from None
        self.context.on("close", self._closed)
        self.headed = False
        return self.context

    def _poll(self):
        try:
            if self.context is None or self.state["synced"]:
                return
            cookies = self.context.cookies("https://www.iq.com/")
            auth = login_cookie(cookies)
            signature = hashlib.sha256(auth.encode()).hexdigest()
            with self.lock:
                changed = signature != self.auth_signature
                if changed:
                    self.auth_signature = signature
                    self.state["version"] += 1
                self.state["connected"] = bool(auth)
                if not self.state["opening"] and (changed or not self.state["message"]):
                    self.state["message"] = ("Đã nhận phiên iq.com; quyền VIP được kiểm tra khi lấy phụ đề." if auth else
                                             "Phiên iq.com chưa đăng nhập hoặc đã hết hạn. Bấm Mở đăng nhập iq.com.")
        except Exception:
            self._set(browserOpen=False)
        finally:
            with self.lock:
                self.last_poll = time.monotonic()
                self.poll_pending = False

    def _login(self):
        return self.status()

    def _dash(self, url: str, tvid: str) -> dict:
        page = None
        try:
            context = self._browser()
            if not self._store_browser_cookies():
                raise ValueError("Chưa lưu được phiên iq.com của trình duyệt hiện tại. Bấm Kiểm tra iq.com để thử lại.")
            self._poll()
            page = context.new_page()
            # Metadata/subtitles only: do not download the video or its segments.
            page.route("**/*", lambda route: route.abort() if route.request.resource_type in ("media", "image", "font") or
                       re.search(r"\.(?:m4s|mp4|flv|f4v|ts)(?:\?|$)", route.request.url, re.I) else route.fallback())
            captured = []

            def capture(response):
                parsed = urlsplit(response.url)
                if (parsed.scheme != "https" or parsed.hostname not in ("cache.video.iq.com", "cache.video.iqiyi.com") or
                        parsed.path != "/dash" or parse_qs(parsed.query).get("tvid") != [tvid]):
                    return
                try:
                    captured.append(dash_data(response.text(), tvid))
                except Exception:
                    pass

            page.on("response", capture)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Read server-rendered metadata before waiting for the player's DASH.
            data = {}
            try:
                script = page.locator("script#__NEXT_DATA__")
                if script.count():
                    payload = json.loads(script.text_content(timeout=1000) or "{}")
                    data = payload.get("props", {}).get("initialProps", {}).get("pageProps", {}).get("prePlayerData", {}).get("dash", {}).get("data", {})
            except (ValueError, TypeError, AttributeError):
                pass
            if has_vietnamese_track(data, tvid):
                self._poll()
                return data
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                ready = next((row for row in reversed(captured) if has_vietnamese_track(row, tvid)), None)
                if ready is not None:
                    self._poll()
                    return ready
                page.wait_for_timeout(250)
            self._poll()
            if captured:
                return captured[-1]
            raise ValueError("iq.com chưa trả metadata phụ đề. Mở Đăng nhập iq.com để kiểm tra phiên và quyền xem tập.")
        except ValueError:
            raise
        except Exception:
            raise ValueError("Không đọc được phụ đề bằng hồ sơ iq.com. Kiểm tra kết nối hoặc mở Đăng nhập iq.com rồi thử lại.") from None
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass

    def _close(self):
        if self.context is not None:
            self.context.close()
        if self.playwright is not None:
            self.playwright.stop()
            self.playwright = None

    def close(self):
        try:
            self.pool.submit(self._close).result(timeout=5)
        except Exception:
            pass
        self.pool.shutdown(wait=False, cancel_futures=True)
