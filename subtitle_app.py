"""Local manager for downloading and managing original subtitle tracks."""
from __future__ import annotations

import html
import copy
import difflib
import gzip
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urljoin, urlsplit

from iqiyi_common import api_token, atomic_write, browser_proxy_token, browser_session_token, player_token, python_executable
from windows_runtime import run_elevated
from iqcom_session import IqcomSession, has_vietnamese_track
from proxy_support import DesktopProxyRelay
from launcher import apply_running_iqiyi_proxy
from iqcom_requests import PUBLIC_METADATA, RequestCache, pooled_open, singleflight
from translation_ai import PRESETS as TRANSLATION_PROVIDERS, list_models
from translation_pipeline import TranslationJobs

ROOT = Path(__file__).resolve().parent
TRANSLATION_JOBS = TranslationJobs(ROOT / ".local" / "translations")
RUNTIME_VERSION = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:16]
LIBRARY = ROOT / "subtitles" / "library"
PLAYER_LOG = Path(os.environ.get("APPDATA", "")) / "IQIYI Video" / "LStyle" / "playerh5.log"
PORT = 18766
EPISODES: dict[str, dict] = {}
LIBRARY_ADMISSIONS_PATH = ROOT / ".local" / "library-admissions.json"
LIBRARY_ADMISSIONS: dict[str, str] = {}
LIBRARY_ADMISSIONS_LOCK = threading.RLock()
SUMMARY_CACHE = RequestCache(capacity=512)
UI_FAST_CACHE = RequestCache(capacity=512)
EPISODE_LOCKS: dict[str, threading.Lock] = {}
LOCK_GUARD = threading.Lock()
PLAYER_LOG_SIGNATURE = None
ALBUM_LISTS: dict[str, dict] = {}
DOWNLOAD_PROGRESS: dict[str, dict] = {}
DOWNLOAD_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="subtitle-download")
PLAYER_SESSIONS: dict[str, dict] = {}
SESSION_LOCK = threading.Lock()
SESSION_VERSION = 0
IQIYI_PROXY_URL = ""
IQIYI_PROXY_LOCK = threading.Lock()
IQIYI_PROXY_APPLY_LOCK = threading.Lock()


def current_player_proxy() -> str:
    with IQIYI_PROXY_LOCK:
        return IQIYI_PROXY_URL


IQCOM_SESSION = IqcomSession(ROOT / ".local" / "iqcom-browser")
DESKTOP_PROXY = DesktopProxyRelay(current_player_proxy)
INTERNATIONAL_TITLE_CACHE: dict[str, tuple[float, dict]] = {}
INTERNATIONAL_ACTOR_CACHE: dict[str, tuple[float, dict]] = {}
INTERNATIONAL_TITLE_LOCK = threading.Lock()
INTERNATIONAL_METADATA_CACHE_PATH = ROOT / ".local" / "international-metadata.json"
INTERNATIONAL_TITLE_PENDING: set[str] = set()
INTERNATIONAL_ALBUM_IDS: dict[str, tuple[float, str]] = {}
IQCOM_ALBUM_CACHE: dict[str, tuple[float, dict, dict]] = {}
IQCOM_ALBUM_LOCK = threading.Lock()
PUBLIC_METADATA_SLOTS = threading.BoundedSemaphore(6)
TITLE_LOOKUP_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="movie-title")
OFFICIAL_SUBTITLE_CACHE: dict[str, dict] = {}
OFFICIAL_SUBTITLE_LOCK = threading.Lock()
OFFICIAL_SUBTITLE_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="official-subtitle")
APP_LOCALIZATION_LOCK = threading.Lock()
APP_LOCALIZATION_STATE = {"status": "idle", "action": "", "message": ""}


def _load_international_metadata_cache() -> None:
    try:
        data = json.loads(INTERNATIONAL_METADATA_CACHE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            return
        now = time.time()
        for key, row in list(data.get("titles", {}).items())[-512:]:
            value = row.get("value") if isinstance(row, dict) else None
            expires = float(row.get("expires", 0)) if isinstance(row, dict) else 0
            remaining = expires - now
            if (re.fullmatch(r"\d{8,24}", key) and 0 < remaining <= 7 * 86400 and isinstance(value, dict)
                    and value.get("sourceTitle") and re.search(r"[\u3400-\u9fff]", value["sourceTitle"])
                    and value.get("title") and not re.search(r"[\u3400-\u9fff\x00-\x1f<>]", value["title"])):
                INTERNATIONAL_TITLE_CACHE[key] = (time.monotonic() + remaining, value)
                album = str(value.get("globalAlbumId") or "")
                if re.fullmatch(r"\d{8,24}", album):
                    INTERNATIONAL_ALBUM_IDS[key] = (time.monotonic() + remaining, album)
        for key, row in list(data.get("actors", {}).items())[-512:]:
            value = row.get("value") if isinstance(row, dict) else None
            expires = float(row.get("expires", 0)) if isinstance(row, dict) else 0
            remaining = expires - now
            if (0 < remaining <= 7 * 86400 and isinstance(value, dict) and value.get("sourceName") == key
                    and value.get("name") and not re.search(r"[\u3400-\u9fff\x00-\x1f<>]", value["name"])):
                INTERNATIONAL_ACTOR_CACHE[key] = (time.monotonic() + remaining, value)
    except (OSError, ValueError, TypeError, AttributeError):
        return


def _save_international_metadata_cache() -> None:
    now_mono, now_wall = time.monotonic(), time.time()
    titles = {key: {"expires": now_wall + expires - now_mono, "value": value}
              for key, (expires, value) in INTERNATIONAL_TITLE_CACHE.items()
              if expires > now_mono and value.get("title") and value.get("sourceTitle")}
    actors = {key: {"expires": now_wall + expires - now_mono, "value": value}
              for key, (expires, value) in INTERNATIONAL_ACTOR_CACHE.items()
              if expires > now_mono and value.get("name")}
    try:
        atomic_write(INTERNATIONAL_METADATA_CACHE_PATH,
                     json.dumps({"version": 1, "titles": titles, "actors": actors}, ensure_ascii=False))
    except OSError:
        pass


_load_international_metadata_cache()


def app_localization_status() -> dict:
    with APP_LOCALIZATION_LOCK:
        return dict(APP_LOCALIZATION_STATE)


def _localization_command(action: str, elevated: bool = False) -> subprocess.CompletedProcess:
    script = ROOT / "apply-vi.py"
    args = [str(script)] + (["--restore"] if action == "restore" else [])
    python = python_executable(ROOT)
    if not elevated:
        return subprocess.run([str(python), *args], cwd=ROOT, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=1800,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    return run_elevated(str(python), args, str(ROOT))


def _run_app_localization(action: str) -> None:
    try:
        result = _localization_command(action)
        if result.returncode == 2:
            result = _localization_command(action, elevated=True)
        if result.returncode == 0:
            message = ("Đã khôi phục giao diện gốc. Hãy đóng rồi mở lại iQIYI để nạp thay đổi."
                       if action == "restore" else
                       "Đã Việt hóa iQIYI. Hãy đóng rồi mở lại iQIYI để nạp giao diện.")
            status = "done"
        elif result.returncode == 1223:
            message, status = ("Đã hủy yêu cầu quyền Administrator; thao tác có thể mới hoàn thành một phần. "
                               "Bạn có thể chạy lại sau.", "error")
        else:
            detail = (result.stdout + "\n" + result.stderr).strip()
            message = "Thao tác thất bại" + (f": {detail[-1200:]}" if detail else f" (mã {result.returncode}).")
            status = "error"
    except subprocess.TimeoutExpired:
        message, status = "Thao tác quá 30 phút và đã dừng.", "error"
    except Exception as exc:
        message, status = f"Không chạy được thao tác: {type(exc).__name__}: {str(exc)[:500]}", "error"
    with APP_LOCALIZATION_LOCK:
        APP_LOCALIZATION_STATE.update(status=status, message=message, finishedAt=time.time())


def start_app_localization(action: str) -> dict:
    if action not in ("apply", "restore"):
        raise ValueError("Thao tác giao diện không hợp lệ.")
    with APP_LOCALIZATION_LOCK:
        if APP_LOCALIZATION_STATE.get("status") == "running":
            raise RuntimeError("Một thao tác iQIYI đang chạy.")
        APP_LOCALIZATION_STATE.update(status="running", action=action,
                                      message=("Đang khôi phục giao diện tiếng Trung…" if action == "restore"
                                               else "Đang Việt hóa giao diện iQIYI…"),
                                      startedAt=time.time())
    threading.Thread(target=_run_app_localization, args=(action,),
                     name="iqiyi-localization", daemon=True).start()
    return app_localization_status()


def current_player_session(source: str | None = None) -> dict:
    with SESSION_LOCK:
        fresh = {key: value for key, value in PLAYER_SESSIONS.items()
                 if time.monotonic() - value["received"] <= 180 and (source is None or key == source)}
        if not fresh:
            return {"version": SESSION_VERSION}
        # Prefer a logged-in app, then a logged-in web session, then a guest connection.
        session = max(fresh.values(), key=lambda value: (bool(value.get("authcookie")), value["source"] == "app"))
        return {**session, "vipTypes": list(session.get("resolvedVipTypes", session.get("vipTypes", []))), "version": SESSION_VERSION}


def player_session_status() -> dict:
    sources = {}
    for source in ("app", "web"):
        session = current_player_session(source)
        sources[source] = {"connected": bool(session.get("authcookie")), "synced": "received" in session}
    return {"connected": any(value["connected"] for value in sources.values()),
            "synced": any(value["synced"] for value in sources.values()), "sources": sources}


def update_player_session(data: dict) -> None:
    global SESSION_VERSION
    source = data.get("source", "app")
    if source not in ("app", "web"):
        raise ValueError("Invalid session source")
    auth = str(data.get("authcookie", ""))
    uid = str(data.get("uid", ""))
    if auth and (len(auth) > 4096 or re.search(r"[\s;\r\n]", auth) or not re.fullmatch(r"\d{1,24}", uid)):
        raise ValueError("Invalid player session")
    vip_types = data.get("vipTypes", [])
    if not isinstance(vip_types, list) or len(vip_types) > 40:
        raise ValueError("Invalid VIP types")
    vip_types = sorted({str(value) for value in vip_types if re.fullmatch(r"\d{1,4}", str(value))})
    device = str(data.get("deviceId", ""))
    dfp = str(data.get("dfp", ""))
    if any(len(value) > 512 or re.search(r"[\s;\r\n]", value) for value in (device, dfp)):
        raise ValueError("Invalid player device")
    session = {"source": source, "authcookie": auth, "uid": uid if auth else "", "vipTypes": vip_types if auth else [],
               "deviceId": device, "dfp": dfp}
    refresh_rights = False
    with SESSION_LOCK:
        previous = PLAYER_SESSIONS.get(source, {})
        old = {key: previous.get(key) for key in session}
        changed = old != session or time.monotonic() - previous.get("received", 0) > 180
        if changed:
            SESSION_VERSION += 1
        retained = {} if changed else {key: value for key, value in previous.items() if key not in session}
        PLAYER_SESSIONS[source] = session = {**retained, **session, "received": time.monotonic()}
        if auth and not vip_types and not session.get("rightsPending") and time.monotonic() - session.get("rightsChecked", -600) >= 600:
            session["rightsPending"] = True
            refresh_rights = True
    if refresh_rights:
        threading.Thread(target=refresh_player_entitlements, args=(auth, uid, source), daemon=True).start()


def refresh_player_entitlements(auth: str, uid: str, source: str = "app") -> None:
    global SESSION_VERSION
    types = None
    try:
        query = urlencode({"platform": "01010031010000000000", "version": "5.0", "appVersion": "1.0",
                           "bizSource": "vip_web_player", "vipTypes": "1,3,4,5,7,8,10,13,14,16,18,56,58"})
        request = urllib.request.Request("https://vinfo.vip.iqiyi.com/external/vip_users?" + query,
            headers={"Cookie": "P00001=" + auth + "; P00003=" + uid,
                     "Referer": "https://www.iqiyi.com/", "User-Agent": "Mozilla/5.0"})
        with iqiyi_open(request, timeout=15, no_session_redirect=True) as response:
            payload = json.loads(response.read(1_000_001))
        if payload.get("code") == "A00000" and isinstance(payload.get("data"), dict):
            types = sorted({str(value["vipType"]) for value in payload["data"].values()
                            if isinstance(value, dict) and str(value.get("status")) == "1"
                            and re.fullmatch(r"\d{1,4}", str(value.get("vipType", "")))})
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    with SESSION_LOCK:
        session = PLAYER_SESSIONS.get(source, {})
        if session.get("authcookie") != auth or session.get("uid") != uid:
            return
        session["rightsPending"] = False
        session["rightsChecked"] = time.monotonic()
        if types is not None:
            if types != session.get("resolvedVipTypes", session.get("vipTypes", [])):
                SESSION_VERSION += 1
            session["resolvedVipTypes"] = types


def sync_album_list(album_id: str, title: str) -> None:
    """Load the album's episode identities, including IDs for subtitle lookup."""
    with LOCK_GUARD:
        ALBUM_LISTS.setdefault(album_id, {})["stage"] = "loading"
    try:
        episodes = {}
        for page in range(1, 11):
            url = ("https://pcw-api.iqiyi.com/albums/album/avlistinfo"
                   f"?aid={album_id}&page={page}&size=100")
            with iqiyi_open(url, timeout=15) as response:
                payload = json.loads(response.read(15_000_001))
            if not isinstance(payload, dict) or payload.get("code") != "A00000" or not isinstance(payload.get("data"), dict):
                raise ValueError("iQIYI không trả được danh sách tập.")
            data = payload["data"]
            if str(data.get("albumId")) != album_id:
                raise ValueError("Danh sách tập không thuộc phim đang yêu cầu.")
            rows = data.get("epsodelist", [])
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError("Danh sách tập iQIYI không hợp lệ.")
            before = len(episodes)
            for row in rows:
                episode_id = str(row.get("tvId", ""))
                episode_dir(episode_id)
                order = int(row.get("order") or 0)
                if order > 0:
                    episodes[episode_id] = {"title": str(row.get("name") or f"{title} ep{order}")[:500],
                                            "order": order, "vid": str(row.get("vid") or "")}
            total = int(data.get("total") or 0)
            if not data.get("hasMore") and (not total or len(episodes) >= total):
                break
            if len(episodes) == before:
                raise ValueError("iQIYI chưa trả đủ các trang danh sách tập.")
        else:
            raise ValueError("Danh sách phim vượt giới hạn 1.000 tập.")
        if not episodes:
            raise ValueError("iQIYI chưa công bố danh sách tập cho phim này.")
        # Numbered names in the album's own list identify the series; player titles
        # can be episode descriptions (e.g. 无衣嘉鱼的混乱初遇).
        series_names = set()
        for metadata in episodes.values():
            match = re.fullmatch(r"(.+?)\s*(?:第\s*\d+\s*集|(?:episode|ep)\s*\d+)",
                                 metadata["title"], re.I)
            if match and match.group(1).strip():
                series_names.add(match.group(1).strip())
        album_title = series_names.pop() if len(series_names) == 1 else ""
        # ponytail: serialize album writes with deletes; use per-album locks if contention grows.
        with LOCK_GUARD:
            ALBUM_LISTS[album_id] = {"stage": "loading", "title": album_title}
            for episode_id, metadata in episodes.items():
                previous = EPISODES.get(episode_id, {})
                item = {**previous, **metadata, "tvid": episode_id, "albumId": album_id,
                        "albumTitle": previous.get("albumTitle") or title, "albumTotal": len(episodes)}
                EPISODES[episode_id] = item
                save_episode(episode_id, item)
            ALBUM_LISTS[album_id] = {"stage": "ready", "title": album_title,
                                     "total": len(episodes), "checked": time.monotonic()}
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        reason = getattr(exc, "reason", exc)
        message = ("Kết nối bị từ chối quyền truy cập (WinError 10013). Kiểm tra firewall/antivirus và proxy của ứng dụng"
                   if getattr(reason, "winerror", None) == 10013 else str(exc)[:250])
        ALBUM_LISTS[album_id] = {"stage": "error", "message": message, "checked": time.monotonic()}


def refresh_album_lists() -> None:
    with LOCK_GUARD:
        albums = {str(item.get("albumId", "")): episode_series_title(item)
                  for item in list(EPISODES.values()) if library_status(item) == "accepted"}
        for album_id, title in albums.items():
            if not re.fullmatch(r"\d{1,24}", album_id) or album_id == "0":
                continue
            state = ALBUM_LISTS.get(album_id, {})
            interval = 600 if state.get("stage") == "ready" else 60
            if state.get("stage") == "loading" or time.monotonic() - state.get("checked", -interval) < interval:
                continue
            ALBUM_LISTS[album_id] = {"stage": "loading"}
            threading.Thread(target=sync_album_list, args=(album_id, title), daemon=True).start()


def queue_album_sync(album_id: str, title: str) -> str:
    with LOCK_GUARD:
        state = ALBUM_LISTS.get(album_id, {})
        if state.get("stage") in ("loading", "ready"):
            return state["stage"]
        ALBUM_LISTS[album_id] = {"stage": "loading"}
    threading.Thread(target=sync_album_list, args=(album_id, title), daemon=True).start()
    return "loading"


class EpisodeBusy(ValueError):
    pass


def episode_lock(tvid: str):
    episode_dir(tvid)
    with LOCK_GUARD:
        return EPISODE_LOCKS.setdefault(tvid, threading.Lock())


def library_keys(item: dict) -> list[str]:
    provider = item.get("provider", "iqiyi")
    if item.get("albumId") and str(item["albumId"]) != "0":
        return [f"{provider}:album:{item['albumId']}"]
    title = episode_series_title(item).casefold().strip()
    if title:
        return [f"{provider}:title:{title}"]
    return [f"{provider}:episode:{item.get('tvid', '')}"]


def library_status(item: dict) -> str:
    with LIBRARY_ADMISSIONS_LOCK:
        states = {LIBRARY_ADMISSIONS.get(key) for key in library_keys(item)}
        return "accepted" if "accepted" in states else "dismissed" if "dismissed" in states else "pending"


def set_library_status(items, status: str) -> None:
    with LIBRARY_ADMISSIONS_LOCK:
        updated = dict(LIBRARY_ADMISSIONS)
        for item in items:
            for key in library_keys(item):
                if status == "accepted" and updated.get(key) != "accepted":
                    updated.pop(key, None)
                updated[key] = status
        atomic_write(LIBRARY_ADMISSIONS_PATH, json.dumps(updated, ensure_ascii=False, indent=2))
        LIBRARY_ADMISSIONS.clear()
        LIBRARY_ADMISSIONS.update(updated)


def load_library_admissions() -> None:
    with LIBRARY_ADMISSIONS_LOCK:
        if LIBRARY_ADMISSIONS_PATH.exists():
            saved = json.loads(LIBRARY_ADMISSIONS_PATH.read_text(encoding="utf-8"))
            if not isinstance(saved, dict) or any(value not in ("accepted", "dismissed") for value in saved.values()):
                raise ValueError("Danh sách chấp nhận phim không hợp lệ.")
            LIBRARY_ADMISSIONS.clear()
            LIBRARY_ADMISSIONS.update(saved)
        else:
            # Preserve the existing library once; future discoveries require acceptance.
            set_library_status(EPISODES.values(), "accepted")


def sort_library_rows(rows: list[dict]) -> None:
    # JSON preserves admission order, including after a restart. Repeated syncs
    # leave that order alone; accepting a dismissed movie moves it to the end.
    with LIBRARY_ADMISSIONS_LOCK:
        added_order = {key: index for index, (key, status) in enumerate(LIBRARY_ADMISSIONS.items())
                       if status == "accepted"}
    first_seen = {}
    for row in rows:
        key = tuple(library_keys(row))
        first_seen[key] = min(first_seen.get(key, float("inf")), float(row.get("discoveredAt") or 0))
    rows.sort(key=lambda row: (-max((added_order.get(key, -1) for key in library_keys(row))),
                               -first_seen[tuple(library_keys(row))], tuple(library_keys(row)),
                               row.get("order") or 9999))


def pending_movies() -> list[dict]:
    groups = {}
    for tvid, item in list(EPISODES.items()):
        if library_status(item) != "pending":
            continue
        provider = item.get("provider", "iqiyi")
        title = episode_series_title(item)
        key = tuple(library_keys(item))
        group = groups.setdefault(key, {"tvid": tvid, "provider": provider,
            "title": vietnamese_series_title(item) or title or tvid,
            "originalTitle": title, "episodes": 0, "discoveredAt": item.get("discoveredAt", 0)})
        group["episodes"] += 1
    return sorted(groups.values(), key=lambda row: -float(row["discoveredAt"] or 0))


def decide_discovery(tvid: str, action: str) -> dict:
    if action not in ("accept", "dismiss") or tvid not in EPISODES:
        raise ValueError("Thông báo phim không hợp lệ.")
    with LOCK_GUARD:
        item = EPISODES[tvid]
        ids = album_episode_ids(str(item.get("albumId", "")), item.get("provider", "iqiyi"), episode_series_title(item)) or [tvid]
        if action == "dismiss" and library_status(item) == "accepted":
            raise ValueError("Phim đã có trong thư viện.")
        set_library_status([EPISODES[key] for key in ids], "accepted" if action == "accept" else "dismissed")
    if action == "accept" and item.get("provider", "iqiyi") == "iqiyi" and item.get("albumId"):
        queue_album_sync(str(item["albumId"]), episode_series_title(item))
    return {"message": "Đã thêm phim vào thư viện." if action == "accept" else "Đã bỏ qua phim này."}


def save_episode(tvid: str, item: dict) -> None:
    item["tvid"] = tvid
    if item.get("provider", "iqiyi") == "iqiyi":
        album_title = ALBUM_LISTS.get(str(item.get("albumId", "")), {}).get("title")
        if album_title:
            item["albumTitle"] = album_title
    item.pop("albumTitleVi", None)
    item.setdefault("discoveredAt", EPISODES.get(tvid, {}).get("discoveredAt") or time.time())
    EPISODES[tvid] = item
    atomic_write(episode_dir(tvid) / "episode.json", json.dumps(item, ensure_ascii=False, indent=2))


def load_library() -> None:
    LIBRARY.mkdir(parents=True, exist_ok=True)
    for folder in LIBRARY.iterdir():
        manifest = folder / "episode.json"
        if not folder.is_dir() or not manifest.is_file() or not re.fullmatch(r"(?:\d{1,20}|yk-[A-Za-z0-9_-]{1,100})", folder.name):
            continue
        try:
            item = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(item, dict):
                continue
            item.pop("albumTitleVi", None)
            if item.get("provider") not in ("iqiyi", "youku"):
                item["provider"] = "youku" if folder.name.startswith("yk-") else "iqiyi"
            item["tvid"] = folder.name
            album_pattern = r"\d{1,24}" if item["provider"] == "iqiyi" else r"yk-[A-Za-z0-9_-]{1,100}"
            if item.get("albumId") and not re.fullmatch(album_pattern, str(item["albumId"])):
                item["albumId"] = ""
            if "discoveredAt" not in item:
                stat = folder.stat()
                item["discoveredAt"] = getattr(stat, "st_birthtime", stat.st_ctime)
                save_episode(folder.name, item)
            EPISODES[folder.name] = item
            progress = item.get("downloadProgress", {})
            if (not (folder / "source.srt").exists() and isinstance(progress, dict)
                    and progress.get("stage") in ("error", "access", "queued", "downloading")):
                if progress["stage"] in ("queued", "downloading"):
                    progress = {"stage": "error", "message": "Lần tải trước đã dừng; chọn Tải gốc hoặc Tải lại để tải thủ công."}
                DOWNLOAD_PROGRESS[folder.name] = progress
        except (OSError, ValueError, ET.ParseError):
            continue
    load_library_admissions()


def sync_current_player() -> None:
    """Pick up the currently playing episode from iQIYI's local player log."""
    global PLAYER_LOG_SIGNATURE
    try:
        stat = PLAYER_LOG.stat()
        signature = (str(PLAYER_LOG), stat.st_mtime_ns, stat.st_size)
        if signature == PLAYER_LOG_SIGNATURE:
            return
        with PLAYER_LOG.open("rb") as handle:
            handle.seek(max(0, handle.seek(0, 2) - 1_500_000))
            raw = handle.read().decode("utf-8", errors="ignore")
    except OSError:
        return
    PLAYER_LOG_SIGNATURE = signature
    pattern = re.compile(r'"tvId"\s*:\s*"?(\d+)"(?P<body>.{0,3500}?"entityTitle"\s*:\s*("(?:\\.|[^"\\])*"))', re.S)
    rows = list(pattern.finditer(raw))
    if not rows:
        return
    match = rows[-1]
    tvid = match.group(1)
    try:
        title = json.loads(match.group(3))
    except (ValueError, TypeError):
        return
    before = raw[max(0, match.start() - 250):match.start()]
    album_match = re.search(r'"albumId"\s*:\s*"?(\d+)', before)
    if not album_match:
        album_match = re.search(r'"albumId"\s*:\s*"?(\d+)', match.group("body"))
    album_id = album_match.group(1) if album_match else ""
    order_match = re.search(r"第\s*(\d+)\s*集|(?:episode|ep)\s*(\d+)", title, re.I)
    order = int(order_match.group(1) or order_match.group(2)) if order_match else 0
    item = dict(EPISODES.get(tvid, {}))
    item.update({"tvid":tvid,"title":title,"albumId":album_id or item.get("albumId", ""),
                 "order":order or item.get("order",0)})
    # Track ownership comes from the structured player hook, not adjacent log lines.
    if not item.get("albumTitle"):
        item["albumTitle"] = re.sub(r"\s*第\s*\d+\s*集.*$", "", title)
    counts = re.findall(r'"albumId"\s*:\s*"?' + re.escape(item["albumId"]) +
                        r'"?.{0,12000}?"listLength"\s*:\s*(\d+)', raw, re.S) if item.get("albumId") else []
    counts += re.findall(r'provideLegacyRefreshListForSeries\s*\{"count":(\d+)\}', raw)
    if counts and ALBUM_LISTS.get(album_id, {}).get("stage") != "ready":
        item["albumTotal"] = max(map(int, counts))
    EPISODES[tvid] = item
    folder = episode_dir(tvid)
    folder.mkdir(parents=True, exist_ok=True)
    save_episode(tvid, item)


def localize_ui_texts(texts: list[str]) -> list[str]:
    """Translate UI through the fast service and cache; never call the subtitle AI."""
    def load_fast():
        body = urlencode([("q", text) for text in texts]).encode()
        request = urllib.request.Request(
            "https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=zh-CN&tl=vi",
            data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        with pooled_open(request, timeout=6) as response:
            rows = json.loads(read_public_metadata(response))
        if (not isinstance(rows, list) or len(rows) != len(texts) or
                any(not isinstance(row, str) or not row.strip() or len(row) > 8000 or
                    re.search(r"[\u3400-\u9fff]", row) for row in rows)):
            raise ValueError("Dịch nhanh chưa trả đủ nội dung tiếng Việt; sẽ thử lại.")
        return rows
    return UI_FAST_CACHE.run(tuple(texts), load_fast, ttl=86400, error_ttl=2)


def normalize_track(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in (
        "meta.video.iqiyi.com", "www.iq.com", "pcw-api.iq.com"
    ):
        raise ValueError("Track source is not provided by iQIYI player")
    return url


class SubtitleAccessRequired(ValueError):
    pass


def validate_iqiyi_proxy_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("Địa chỉ proxy không hợp lệ hoặc quá dài.")
    proxy_url = str(value or "").strip()
    if not proxy_url:
        return ""
    if "://" not in proxy_url:
        proxy_url = "http://" + proxy_url
    try:
        parsed = urlsplit(proxy_url)
        port = parsed.port
    except ValueError:
        raise ValueError("Nhập proxy dạng máy-chủ:cổng hoặc http://tài-khoản:mật-khẩu@máy-chủ:cổng.") from None
    if (parsed.scheme != "http" or not parsed.hostname or not port or parsed.path not in ("", "/")
            or parsed.query or parsed.fragment or re.search(r"[\s\r\n]", proxy_url)):
        raise ValueError("Nhập proxy dạng máy-chủ:cổng hoặc http://tài-khoản:mật-khẩu@máy-chủ:cổng.")
    return proxy_url


def iqiyi_open(request, timeout: int = 15, no_session_redirect: bool = False):
    # Metadata, film titles and subtitle files always bypass player/system proxies.
    if no_session_redirect:
        return pooled_open(request, timeout=timeout)
    return urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout)


def public_iqiyi_json(url: str, *, refresh: bool = False) -> dict:
    parsed = urlsplit(url)
    cacheable = ((parsed.hostname == "pcw-api.iq.com" and
                  (parsed.path == "/api/search2" or parsed.path.startswith("/api/epgInfo/"))) or
                 (parsed.hostname == "pcw-api.iqiyi.com" and "/baseinfo/" in parsed.path))
    if not cacheable:
        return _fetch_public_iqiyi_json(url)
    # These empty anonymous fields are optional; other query fields, especially language, stay in the key.
    query = tuple(sorted((key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                         if value or key not in ("uid", "pspStatus")))
    key = (parsed.scheme, parsed.hostname, parsed.path, query)
    lifetime = 120 if parsed.path == "/api/search2" else 300
    payload = PUBLIC_METADATA.run(key, lambda: _fetch_public_iqiyi_json(url), error_ttl=10, refresh=refresh,
        ttl=lambda value: lifetime if value.get("code") in (0, "0", "A00000") and isinstance(value.get("data"), dict) else 10)
    return copy.deepcopy(payload)


def read_public_metadata(response) -> bytes:
    if response.headers.get("Content-Encoding", "").strip().lower() == "gzip":
        with gzip.GzipFile(fileobj=response) as compressed:
            return compressed.read(4_000_001)
    return response.read(4_000_001)


def _fetch_public_iqiyi_json(url: str) -> dict:
    host = urlsplit(url).hostname or ""
    referer = "https://www.iqiyi.com/" if host.endswith(".iqiyi.com") else "https://www.iq.com/"
    request = urllib.request.Request(url, headers={
        "Accept": "application/json", "Accept-Encoding": "gzip", "Referer": referer,
        "User-Agent": "Mozilla/5.0"})
    with PUBLIC_METADATA_SLOTS, iqiyi_open(request, timeout=8, no_session_redirect=True) as response:
        raw = read_public_metadata(response)
    if len(raw) > 4_000_000:
        raise ValueError("Metadata tên phim iQIYI quá lớn.")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Metadata tên phim iQIYI không hợp lệ.")
    return payload


@singleflight
def international_movie_title(identifier: str) -> dict:
    """Resolve a domestic title through iqiyi metadata, then search iq.com's Chinese catalog."""
    identifier = str(identifier or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{8,24}", identifier):
        raise ValueError("Mã phim iQIYI không hợp lệ.")
    if not identifier.isdigit():
        # Decode iqiyi.com page IDs using its original player's patchToID algorithm.
        value = int(identifier, 36) ^ 0x75706971676C
        identifier = str(100 * (value + 900000) if value < 900000 else value)
    cache_key = identifier
    with INTERNATIONAL_TITLE_LOCK:
        cached = INTERNATIONAL_TITLE_CACHE.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return dict(cached[1])

    def clean(value) -> str:
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", "", str(value or "")))).strip()

    def title_key(value) -> str:
        return re.sub(r"[\s《》「」『』【】]", "", clean(value)).casefold()

    request_json = public_iqiyi_json

    result = {"title": "", "sourceTitle": ""}
    retry_lifetime = 120
    try:
        domestic = {}
        kinds = ("album", "video") if identifier.endswith("01") else ("video", "album")
        for kind in kinds:
            payload = request_json(f"https://pcw-api.iqiyi.com/{kind}/{kind}/baseinfo/{identifier}")
            data = payload.get("data")
            if payload.get("code") == "A00000" and isinstance(data, dict):
                domestic = data
                break
        chinese = clean(domestic.get("albumName") or domestic.get("name"))
        result["sourceTitle"] = chinese
        if chinese and re.search(r"[\u3400-\u9fff]", chinese):
            year = str(domestic.get("year") or domestic.get("publishDate") or
                       (domestic.get("firstVideo") or {}).get("publishDate") or "")[:4]
            year = year if re.fullmatch(r"(?:19|20)\d{2}", year) else ""
            candidates = {}
            # Separate regional editions can be absent from search. Verify catalog IDs
            # against Chinese metadata before fetching their Vietnamese title.
            # https://www.iq.com/album/19rrhxoou9?lang=vi_vn
            catalog_id = {"236709101": "249155501"}.get(str(domestic.get("albumId") or identifier))
            if catalog_id:
                params = {"platformId": 4, "langCode": "zh_cn", "modeCode": "intl", "deviceId": "ew"}
                payload = request_json(f"https://pcw-api.iq.com/api/epgInfo/{catalog_id}?" + urlencode(params))
                data = payload.get("data")
                if (payload.get("code") in (0, "0") and isinstance(data, dict) and
                        str(data.get("qipuId")) == catalog_id and
                        title_key(data.get("albumName") or data.get("name")) == title_key(chinese) and
                        (not domestic.get("channelId") or str(data.get("chnId")) == str(domestic["channelId"])) and
                        (not year or str(data.get("publishTime") or "")[:4] == year)):
                    candidates[catalog_id] = data
            if not candidates:
                params = {"key": chinese, "pn": 1, "ps": 10, "intentPn": 1, "intentPs": 0,
                          "chnId": 0, "dataType": "1;should,2;should", "platformId": 3,
                          "modeCode": "intl", "langCode": "zh_cn", "deviceId": "ew",
                          "isVip": 0, "pspUid": "", "pspStatus": "-1"}
                payload = request_json("https://pcw-api.iq.com/api/search2?" + urlencode(params))
                data = payload.get("data")
                if payload.get("code") in (0, "0") and isinstance(data, dict):
                    for row in data.get("epg", []):
                        if not isinstance(row, dict) or row.get("type") not in (0, 1):
                            continue
                        if title_key(row.get("name")) != title_key(chinese):
                            continue
                        if year and str(row.get("publishTime") or "")[:4] != year:
                            continue
                        if domestic.get("channelId") and str(row.get("chnId")) != str(domestic["channelId"]):
                            continue
                        qipu_id = str(row.get("qipuId") or row.get("albumId") or "")
                        if re.fullmatch(r"\d{8,24}", qipu_id):
                            candidates[qipu_id] = row
            if len(candidates) == 1:
                qipu_id = next(iter(candidates))
                with INTERNATIONAL_TITLE_LOCK:
                    INTERNATIONAL_ALBUM_IDS[cache_key] = (time.monotonic() + 7 * 86400, qipu_id)
                    result["globalAlbumId"] = qipu_id
                params = {"platformId": 4, "langCode": "vi_vn", "modeCode": "intl",
                          "deviceId": "ew", "uid": "", "pspStatus": ""}
                payload = request_json(f"https://pcw-api.iq.com/api/epgInfo/{qipu_id}?" + urlencode(params))
                data = payload.get("data")
                if (payload.get("code") in (0, "0") and isinstance(data, dict) and
                        str(data.get("qipuId")) == qipu_id):
                    cache_international_cast(candidates[qipu_id], data)
                    title = clean(data.get("albumName") or data.get("name"))
                    if (title and len(title) <= 200 and not re.search(r"[\u3400-\u9fff]", title) and
                            data.get("matchedLang", 15) == 15):
                        result["title"] = title
    except OSError:
        retry_lifetime = 10
        result["retryAfterMs"] = 10000
    except (ValueError, TypeError, AttributeError):
        pass

    with INTERNATIONAL_TITLE_LOCK:
        if len(INTERNATIONAL_TITLE_CACHE) >= 512:
            oldest = min(INTERNATIONAL_TITLE_CACHE, key=lambda key: INTERNATIONAL_TITLE_CACHE[key][0])
            INTERNATIONAL_TITLE_CACHE.pop(oldest, None)
            INTERNATIONAL_ALBUM_IDS.pop(oldest, None)
        INTERNATIONAL_TITLE_CACHE[cache_key] = (time.monotonic() + (7 * 86400 if result["title"] else retry_lifetime), dict(result))
        if result["title"]:
            _save_international_metadata_cache()
    return result


def cache_international_cast(source: dict, localized: dict) -> None:
    """Reuse already verified album cast records, matching people by ID rather than order."""
    def people(data):
        cast = data.get("cast")
        if not isinstance(cast, dict):
            return {}
        return {str(row.get("id")): row.get("n")
                for group in ("mainActor", "actor", "star", "host", "guest")
                for row in (cast.get(group) or []) if isinstance(row, dict)}
    original, vietnamese = people(source), people(localized)
    with INTERNATIONAL_TITLE_LOCK:
        changed = False
        for person_id, name in original.items():
            translated = vietnamese.get(person_id)
            if (not re.fullmatch(r"\d{1,24}", person_id) or not isinstance(name, str) or len(name) > 80 or
                    not re.search(r"[\u3400-\u9fff]", name) or not isinstance(translated, str) or
                    not translated.strip() or len(translated) > 200 or
                    re.search(r"[\u3400-\u9fff\x00-\x1f<>]", translated)):
                continue
            if len(INTERNATIONAL_ACTOR_CACHE) >= 512 and name not in INTERNATIONAL_ACTOR_CACHE:
                oldest = min(INTERNATIONAL_ACTOR_CACHE, key=lambda key: INTERNATIONAL_ACTOR_CACHE[key][0])
                INTERNATIONAL_ACTOR_CACHE.pop(oldest, None)
            INTERNATIONAL_ACTOR_CACHE[name] = (time.monotonic() + 7 * 86400,
                {"name": translated.strip(), "sourceName": name, "id": person_id})
            changed = True
        if changed:
            _save_international_metadata_cache()


@singleflight
def international_actor_name(name: str) -> dict:
    """Use iq.com's localized person record, verified by source name and person ID."""
    name = str(name or "").strip()
    if (not name or len(name) > 80 or not re.search(r"[\u3400-\u9fff]", name) or
            not re.fullmatch(r"[\w\s·・.（）()\-]+", name)):
        raise ValueError("Tên diễn viên iQIYI không hợp lệ.")
    with INTERNATIONAL_TITLE_LOCK:
        cached = INTERNATIONAL_ACTOR_CACHE.get(name)
        if cached and cached[0] > time.monotonic():
            return dict(cached[1])
    result = {"name": "", "sourceName": name, "id": ""}
    retry_lifetime = 120
    try:
        params = {"key": name, "pn": 1, "ps": 1, "intentPn": 1, "intentPs": 0,
                  "chnId": 0, "dataType": "4;should", "platformId": 3,
                  "modeCode": "intl", "langCode": "vi_vn", "deviceId": "ew"}

        def person() -> dict:
            payload = public_iqiyi_json("https://pcw-api.iq.com/api/search2?" + urlencode(params))
            data = payload.get("data")
            if payload.get("code") in (0, "0") and isinstance(data, dict):
                row = data.get("starsInfo")
                if isinstance(row, dict):
                    return row
            return {}

        localized = person()
        person_id = str(localized.get("qipuId") or "")
        translated = str(localized.get("name") or "").strip()
        if (re.fullmatch(r"\d{1,24}", person_id) and translated and len(translated) <= 200 and
                not re.search(r"[\u3400-\u9fff\x00-\x1f<>]", translated)):
            # The localized person record often includes the exact original name already.
            verified = localized.get("nationalityName") == name
            if not verified:
                params["langCode"] = "zh_cn"
                source = person()
                verified = source.get("name") == name and str(source.get("qipuId")) == person_id
            if verified:
                result.update(name=translated, id=person_id)
    except OSError:
        retry_lifetime = 10
        result["retryAfterMs"] = 10000
    except (ValueError, TypeError, AttributeError):
        pass
    with INTERNATIONAL_TITLE_LOCK:
        cached = INTERNATIONAL_ACTOR_CACHE.get(name)
        if not result["name"] and cached and cached[0] > time.monotonic() and cached[1].get("name"):
            return dict(cached[1])
        if len(INTERNATIONAL_ACTOR_CACHE) >= 512:
            oldest = min(INTERNATIONAL_ACTOR_CACHE, key=lambda key: INTERNATIONAL_ACTOR_CACHE[key][0])
            INTERNATIONAL_ACTOR_CACHE.pop(oldest, None)
        INTERNATIONAL_ACTOR_CACHE[name] = (time.monotonic() + (7 * 86400 if result["name"] else retry_lifetime), dict(result))
        if result["name"]:
            _save_international_metadata_cache()
    return result


@singleflight
def public_iqcom_page(suffix: str) -> dict:
    url = urljoin("https://www.iq.com/play/", suffix)
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "www.iq.com" or not parsed.path.startswith("/play/"):
        raise ValueError("Liên kết tập iq.com không hợp lệ.")
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.iq.com/",
                                                 "Accept-Encoding": "gzip"})
    # Public iq.com requests never receive the domestic player's login cookies.
    with pooled_open(request, timeout=15, public_iqcom_page=True) as response:
        raw = read_public_metadata(response)
    if len(raw) > 4_000_000:
        raise ValueError("Metadata tập iq.com quá lớn.")
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', raw.decode("utf-8"), re.S)
    if not match:
        raise ValueError("iq.com chưa trả metadata tập phim.")
    return json.loads(match[1])


@singleflight
def iqcom_album_metadata(global_album: str, *, refresh: bool = False) -> tuple[dict, dict, dict | None]:
    """Cache public catalog metadata for five minutes, never signed playback URLs."""
    with IQCOM_ALBUM_LOCK:
        cached = IQCOM_ALBUM_CACHE.get(global_album)
        if not refresh and cached and cached[0] > time.monotonic():
            return cached[1], cached[2], None
    params = urlencode({"platformId": 4, "langCode": "vi_vn", "modeCode": "intl", "deviceId": "ew"})
    album = public_iqiyi_json(f"https://pcw-api.iq.com/api/epgInfo/{global_album}?{params}", refresh=refresh).get("data", {})
    if str(album.get("qipuId")) != global_album:
        raise ValueError("Metadata phim iq.com không khớp.")
    page = public_iqcom_page(str(album.get("playLocSuffix") or ""))
    lists = page.get("props", {}).get("initialState", {}).get("play", {}).get("cachePlayList", {})
    if not isinstance(lists, dict) or not any(isinstance(rows, list) and rows for rows in lists.values()):
        raise ValueError("iq.com chưa trả danh sách tập phim.")
    # Keep only catalog fields; the first caller can still reuse the freshly read page.
    album = {key: album.get(key) for key in ("qipuId", "defaultTvId", "playLocSuffix")}
    lists = {key: [{field: row.get(field) for field in
                   ("tvId", "qipuId", "albumId", "order", "contentType", "playLocSuffix")}
                  for row in rows if isinstance(row, dict)]
             for key, rows in lists.items() if isinstance(rows, list)}
    with IQCOM_ALBUM_LOCK:
        if len(IQCOM_ALBUM_CACHE) >= 128 and global_album not in IQCOM_ALBUM_CACHE:
            oldest = min(IQCOM_ALBUM_CACHE, key=lambda key: IQCOM_ALBUM_CACHE[key][0])
            IQCOM_ALBUM_CACHE.pop(oldest)
        IQCOM_ALBUM_CACHE[global_album] = (time.monotonic() + 300, album, lists)
    return album, lists, page


def fetch_official_subtitle(tvid: str) -> dict:
    """Resolve the exact international episode and shift its Vietnamese track by video ends."""
    domestic = public_iqiyi_json(f"https://pcw-api.iqiyi.com/video/video/baseinfo/{tvid}").get("data", {})
    if str(domestic.get("tvId")) != tvid:
        raise ValueError("Không xác nhận được tập iqiyi.com.")
    album_id = str(domestic.get("albumId") or "")
    order = int(domestic.get("order") or 0)
    if not re.fullmatch(r"\d{8,24}", album_id) or order < 1:
        raise ValueError("Chưa xác nhận được số tập của phim.")
    international_movie_title(album_id)
    with INTERNATIONAL_TITLE_LOCK:
        mapping = INTERNATIONAL_ALBUM_IDS.get(album_id)
    if not mapping or mapping[0] <= time.monotonic():
        raise ValueError("Chưa tìm được phim khớp chính xác trên iq.com.")
    global_album = mapping[1]
    for attempt in range(2):
        album, lists, page = iqcom_album_metadata(global_album, refresh=bool(attempt))
        candidates = {}
        for rows in lists.values():
            for row in rows:
                if (str(row.get("albumId")) == global_album and str(row.get("order")) == str(order) and
                        str(row.get("contentType")) == "1"):
                    identifier = str(row.get("tvId") or row.get("qipuId") or "")
                    if re.fullmatch(r"\d{8,24}", identifier):
                        candidates[identifier] = row
        # A newly released episode may be absent from a still-valid cached list.
        if candidates or page is not None:
            break
    if len(candidates) != 1:
        raise ValueError("Chưa tìm được duy nhất một tập chính thức khớp số tập trên iq.com.")
    global_tvid, episode = next(iter(candidates.items()))
    # Once the episode is resolved, its duration and public page are independent.
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="iqcom-metadata") as pool:
        metadata = pool.submit(public_iqiyi_json,
                               f"https://pcw-api.iqiyi.com/video/video/baseinfo/{global_tvid}")
        if page is None or global_tvid != str(album.get("defaultTvId")):
            page = public_iqcom_page(str(episode.get("playLocSuffix") or album.get("playLocSuffix") or ""))
        international = metadata.result().get("data", {})
    if (str(international.get("tvId")) != global_tvid or str(international.get("albumId")) != global_album or
            str(international.get("order")) != str(order)):
        raise ValueError("Tập iq.com không khớp phim hoặc số tập.")
    domestic_duration = int(domestic.get("durationSec") or 0)
    global_duration = int(international.get("durationSec") or 0)
    if not (0 < domestic_duration <= 86400 and 0 < global_duration <= 86400):
        raise ValueError("Chưa lấy được thời lượng hai video để căn theo cuối.")
    data = page.get("props", {}).get("initialProps", {}).get("pageProps", {}).get("prePlayerData", {}).get("dash", {}).get("data", {})
    public_track = has_vietnamese_track(data, global_tvid)
    if not public_track and IQCOM_SESSION.saved:
        data = IQCOM_SESSION.dash(str(episode.get("playLocSuffix") or album.get("playLocSuffix") or ""), global_tvid)
    if str(data.get("tvid")) != global_tvid:
        raise ValueError("Metadata phát iq.com không đúng tập.")
    tracks = (data.get("program") or {}).get("stl") or []
    track = next((row for row in tracks if isinstance(row, dict) and str(row.get("lid")) == "23"), None)
    if not track:
        raise ValueError(f"iq.com chưa trả phụ đề Việt cho tập này (trạng thái {data.get('st', 'không rõ')}). "
                         "Đăng nhập iq.com trong trình duyệt đã cài tiện ích, rồi bấm Kiểm tra iq.com "
                         "trong app quản lý. Tài khoản cần có quyền xem tập này.")
    fmt = next((key for key in ("xml", "webvtt", "vtt", "srt") if track.get(key)), None)
    if not fmt:
        raise ValueError("iq.com chưa cung cấp tệp phụ đề Việt.")
    url = normalize_track(urljoin(data.get("dstl") or "https://meta.video.iqiyi.com/", track[fmt]))
    if url.startswith("http:"):
        url = "https:" + url[5:]
    with iqiyi_open(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.iq.com/"}),
                    timeout=15, no_session_redirect=True) as response:
        raw = response.read(4_000_001)
    if len(raw) > 4_000_000:
        raise ValueError("Tệp phụ đề iq.com quá lớn.")
    shift = (domestic_duration - global_duration) * 1000
    xml, count = official_subtitle_xml(raw.decode("utf-8-sig"), fmt, shift, domestic_duration * 1000)
    return {"xml": xml, "shiftMs": shift, "internationalTvid": global_tvid, "cues": count}


def official_subtitle_xml(raw: str, fmt: str, shift: int, duration: int) -> tuple[bytes, int]:
    """Keep official placement separate from dialogue; the player stacks upper cues."""
    source = ET.fromstring(raw) if fmt == "xml" else ET.fromstring(to_xml(parse_source(raw, fmt)))
    output = ET.Element("xml")
    for dia in source.iter("dia"):
        start, end, text = (dia.findtext(k, "") for k in ("st", "et", "sub"))
        if not start.isdigit() or not end.isdigit() or not text.strip():
            continue
        if int(end) <= int(start):
            raise ValueError("Invalid subtitle interval")
        start, end = max(0, int(start) + shift), min(duration, int(end) + shift)
        if end <= start:
            continue
        text = html.unescape(text).replace("\r\n", "\n").replace("\r", "\n").strip()
        position = dia.find("style/position")
        upper = False
        if position is not None:
            margin = position.get("vertical-margin", "").rstrip("%")
            upper = position.get("alignment", "").lower().startswith("top") or (
                bool(re.fullmatch(r"\d+(?:\.\d+)?", margin)) and float(margin) < 50)
        else:
            upper = bool(re.fullmatch(r"\[[\s\S]*\]|【[\s\S]*】", text))
        # Preserve the source's bottom placement for bracketed thoughts; lyrics stay above.
        upper = upper or bool(re.search(r"[♪♫♬]", text))
        node = ET.SubElement(output, "dia")
        # The native SDK splits sub at CR/LF into main/sub tracks, discarding later lines.
        # Keep the full cue for our renderer and give the SDK a single-line fallback.
        for key, value in (("st", start), ("et", end), ("sub", text.replace("\n", " ")),
                           ("iqcomText", text), ("iqcomRegion", "top" if upper else "bottom")):
            ET.SubElement(node, key).text = str(value)
    if not len(output):
        raise ValueError("Phụ đề iq.com không có câu hợp lệ sau khi căn giờ.")
    return ET.tostring(output, encoding="utf-8", xml_declaration=True), len(output)


def _load_official_subtitle(tvid: str, session_version: int) -> None:
    if session_version != IQCOM_SESSION.version:
        with OFFICIAL_SUBTITLE_LOCK:
            if OFFICIAL_SUBTITLE_CACHE.get(tvid, {}).get("sessionVersion") == session_version:
                OFFICIAL_SUBTITLE_CACHE.pop(tvid, None)
        return
    lifetime = 120
    try:
        value = {**fetch_official_subtitle(tvid), "available": True, "loading": False, "error": ""}
        lifetime = 3600
    except OSError:
        value = {"available": False, "loading": False, "error": "Kết nối iq.com chưa thành công; sẽ thử lại sau ít giây."}
        lifetime = 10
    except Exception as exc:
        value = {"available": False, "loading": False, "error": str(exc)[:250]}
    value["expires"] = time.monotonic() + lifetime
    value["sessionVersion"] = session_version
    with OFFICIAL_SUBTITLE_LOCK:
        if session_version == IQCOM_SESSION.version:
            OFFICIAL_SUBTITLE_CACHE[tvid] = value
        elif OFFICIAL_SUBTITLE_CACHE.get(tvid, {}).get("sessionVersion") == session_version:
            OFFICIAL_SUBTITLE_CACHE.pop(tvid, None)


def official_subtitle_status(tvid: str) -> dict:
    if not re.fullmatch(r"\d{8,24}", tvid):
        return {"available": False, "loading": False, "error": "Mã tập không hợp lệ."}
    with OFFICIAL_SUBTITLE_LOCK:
        value = OFFICIAL_SUBTITLE_CACHE.get(tvid)
        if (not value or value.get("sessionVersion", 0) != IQCOM_SESSION.version
                or (not value.get("loading") and value.get("expires", 0) <= time.monotonic())):
            if sum(bool(row.get("loading")) for row in OFFICIAL_SUBTITLE_CACHE.values()) >= 8:
                return {"available": False, "loading": True, "error": "Đang chờ tra phụ đề iq.com."}
            if len(OFFICIAL_SUBTITLE_CACHE) >= 128:
                oldest = next((key for key, row in OFFICIAL_SUBTITLE_CACHE.items() if not row.get("loading")), None)
                if oldest:
                    OFFICIAL_SUBTITLE_CACHE.pop(oldest)
            value = {"available": False, "loading": True, "error": "Đang tìm phụ đề Việt chính thức trên iq.com.",
                     "sessionVersion": IQCOM_SESSION.version}
            OFFICIAL_SUBTITLE_CACHE[tvid] = value
            OFFICIAL_SUBTITLE_POOL.submit(_load_official_subtitle, tvid, value["sessionVersion"])
        return {key: value[key] for key in ("available", "loading", "error")}


@singleflight
def international_search_query(keyword: str) -> dict:
    """Resolve exact titles; offer verified choices for partial or misspelled names."""
    keyword = str(keyword or "").strip()
    if not keyword or len(keyword) > 100 or re.search(r"[\x00-\x1f\x7f]", keyword):
        raise ValueError("Từ khóa tìm kiếm không hợp lệ hoặc quá dài.")
    result = {"query": keyword, "title": keyword, "suggestions": []}
    if re.search(r"[\u3400-\u9fff\uf900-\ufaff]", keyword):
        return result

    def key(value):
        value = unicodedata.normalize("NFD", str(value)).casefold().replace("đ", "d")
        return re.sub(r"[^a-z0-9]", "", "".join(c for c in value if not unicodedata.combining(c)))

    query_key = key(keyword)
    def score(title):
        title_key = key(title)
        if title_key == query_key:
            return 2.0
        if len(query_key) < 3:
            return 0
        if query_key in title_key:
            return 1 + len(query_key) / max(1, len(title_key))
        ratio = difflib.SequenceMatcher(None, query_key, title_key).ratio()
        return ratio if ratio >= .72 else 0

    candidates = {}
    with INTERNATIONAL_TITLE_LOCK:
        cached_rows = [dict(row[1]) for row in INTERNATIONAL_TITLE_CACHE.values()]
    for row in cached_rows:
        if row.get("sourceTitle") and row.get("title") and score(row["title"]):
            candidates[row["sourceTitle"]] = {"title": row["title"], "query": row["sourceTitle"]}
    exact = [row for row in candidates.values() if score(row["title"]) == 2]
    if len(exact) == 1:
        result["query"] = exact[0]["query"]
        return result
    params = {"key": keyword, "pn": 1, "ps": 20, "intentPn": 1, "intentPs": 0,
              "chnId": 0, "dataType": "1;should,2;should", "platformId": 3,
              "modeCode": "intl", "langCode": "vi_vn", "deviceId": "ew", "isVip": 0}
    try:
        payload = public_iqiyi_json("https://pcw-api.iq.com/api/search2?" + urlencode(params))
        rows = (payload.get("data") or {}).get("epg", [])
        matches = {str(row.get("qipuId") or row.get("albumId") or ""): row for row in rows
                   if isinstance(row, dict) and row.get("type") in (0, 1) and
                   isinstance(row.get("name"), str) and not re.search(r"[\u3400-\u9fff\uf900-\ufaff]", row["name"]) and score(row["name"])}
        for identifier, row in sorted(matches.items(), key=lambda pair: score(pair[1]["name"]), reverse=True)[:5]:
            if not re.fullmatch(r"\d{8,24}", identifier):
                continue
            params = {"platformId": 4, "langCode": "zh_cn", "modeCode": "intl", "deviceId": "ew"}
            try:
                payload = public_iqiyi_json(f"https://pcw-api.iq.com/api/epgInfo/{identifier}?" + urlencode(params))
                data = payload.get("data") or {}
                original = data.get("albumName") or data.get("name") or ""
                if (payload.get("code") in (0, "0") and str(data.get("qipuId")) == identifier and
                        isinstance(original, str) and len(original) <= 200 and re.search(r"[\u3400-\u9fff\uf900-\ufaff]", original)):
                    candidates[original] = {"title": row["name"], "query": original,
                        "year": str(row.get("publishTime") or "")[:4]}
            except (OSError, ValueError, TypeError, AttributeError):
                continue
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    choices = sorted(candidates.values(), key=lambda row: score(row["title"]), reverse=True)
    exact = [row for row in choices if score(row["title"]) == 2]
    if len(exact) == 1:
        result["query"] = exact[0]["query"]
    else:
        result["suggestions"] = choices[:5]
    return result


def search_iqiyi_albums(keyword: str) -> list[dict]:
    keyword = str(keyword).strip()
    if not keyword:
        return []
    if len(keyword) > 100 or re.search(r"[\x00-\x1f\x7f]", keyword):
        raise ValueError("Từ khóa tìm kiếm không hợp lệ hoặc quá dài.")
    query = urlencode({"if": "html5", "key": keyword, "pageNum": 1, "pos": 1,
                       "pageSize": 20, "site": "iqiyi"})
    request = urllib.request.Request("https://search.video.iqiyi.com/o?" + query, headers={
        "Accept": "application/json", "Referer": "https://www.iqiyi.com/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"})
    try:
        with iqiyi_open(request, timeout=12, no_session_redirect=True) as response:
            raw = response.read(8_000_001)
        if len(raw) > 8_000_000:
            raise ValueError("Kết quả tìm kiếm iQIYI quá lớn; thử tìm từ khóa ngắn, cụ thể hơn.")
        payload = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ValueError(f"API tìm kiếm iQIYI trả HTTP {exc.code}.") from None
    except (urllib.error.URLError, TimeoutError):
        raise ValueError("Không kết nối được API tìm kiếm iQIYI.") from None
    data = payload.get("data") if isinstance(payload, dict) else None
    docs = data.get("docinfos") if isinstance(data, dict) else None
    if not isinstance(docs, list):
        message = payload.get("msg") or payload.get("message") if isinstance(payload, dict) else ""
        raise ValueError(str(message or "iQIYI không trả được kết quả tìm kiếm.")[:250])
    results, seen = [], set()
    for doc in docs:
        album = doc.get("albumDocInfo") if isinstance(doc, dict) else None
        if not isinstance(album, dict):
            continue
        album_id = str(album.get("albumId") or "")
        if not re.fullmatch(r"\d{1,24}", album_id) or album_id in seen:
            continue
        title = album.get("albumTitle") or album.get("name") or ""
        if not isinstance(title, str) or not title.strip():
            continue
        clean = lambda value, limit: re.sub(r"\s+", " ", html.unescape(
            re.sub(r"<[^>]*>", "", str(value or "")))).strip()[:limit]
        seen.add(album_id)
        results.append({"albumId": album_id, "title": clean(title, 300),
                        "year": clean(album.get("year") or album.get("releaseYear"), 40),
                        "description": clean(album.get("tvFocus") or album.get("description"), 240)})
    return results


def fetch_episode_tracks(tvid: str, vid: str, session: dict | None = None) -> list[dict]:
    episode_dir(tvid)
    if not re.fullmatch(r"[a-fA-F0-9]{32}", vid):
        raise ValueError("Chưa có mã video; đang chờ cập nhật danh sách tập.")
    md5 = lambda value: hashlib.md5(value.encode()).hexdigest()
    bits = lambda *positions: sum(1 << (position - 1) for position in positions)
    now = str(int(time.time() * 1000))
    session = current_player_session() if session is None else session
    auth = session.get("authcookie", "")
    # Match the metadata request in the installed iQIYI web player; no video is fetched.
    params = {"tvid": tvid, "bid": 200, "vid": vid, "src": "01010031010000000000",
              "vt": 0, "rs": 1, "uid": session.get("uid", ""), "ori": "pcw", "ps": 0,
              "k_uid": session.get("deviceId") or secrets.token_hex(16), "pt": 0, "d": 0, "s": "", "lid": 0,
              "cf": 0, "ct": 0, "authKey": md5(md5("") + now + tvid), "k_tag": 1,
              "dfp": session.get("dfp", ""), "locale": "zh_cn", "up": "", "qd_v": "a1", "tm": now,
              "k_ft1": bits(3, 40, 48, 50), "k_ft4": bits(3, 14, 27, 38, 46, 51, 44),
              "k_ft5": bits(1, 25, 28, 45), "k_ft7": bits(36, 26, 29, 44, 45),
              "k_ftx2": "g", "bop": json.dumps({"version": "10.0", "dfp": session.get("dfp", ""), "b_ft1": 60}, separators=(",", ":")), "sr": 1}
    if auth:
        params["pck"] = auth
    path = "/dash?" + urlencode(params) + "".join("&ut=" + value for value in session.get("vipTypes", []) or ["0"])
    salt = ""
    for t in range(4):
        for i in range(2):
            for r in range(4):
                n = (70 * t + 677 * i + 21 * r + 87 * t * i * r + 59) % 30
                salt += chr(n + (48 if n < 9 else 88))
    headers = {"Referer": "https://www.iqiyi.com/", "User-Agent": "Mozilla/5.0"}
    if auth:
        headers["Cookie"] = "P00001=" + auth + "; P00003=" + session["uid"]
    request = urllib.request.Request("https://cache.video.iqiyi.com" + path + "&vf=" + md5(path + salt), headers=headers)
    try:
        with iqiyi_open(request, timeout=20, no_session_redirect=bool(auth)) as response:
            payload = json.loads(response.read(15_000_001))
    except (OSError, ValueError):
        raise ValueError("Không lấy được metadata phụ đề từ iQIYI; hãy thử lại.") from None
    if not isinstance(payload, dict):
        raise ValueError("Metadata phụ đề iQIYI không hợp lệ.")
    data = payload.get("data")
    if not isinstance(data, dict) or payload.get("code") != "A00000" or str(data.get("tvid")) != tvid:
        raise ValueError("iQIYI chưa cho phép lấy phụ đề của tập này.")
    control = data.get("ctl")
    if not isinstance(control, dict):
        control = {}
    if control.get("boss_not_pass"):
        if auth and str(control.get("uid", "")) == session.get("uid"):
            message = "iQIYI đã xác nhận tài khoản đang đăng nhập, nhưng tài khoản chưa có quyền xem tập này."
        elif auth:
            message = "Máy chủ iQIYI chưa chấp nhận phiên đăng nhập. Hãy đăng nhập lại iQIYI trên app hoặc web."
        else:
            message = "Chưa nhận phiên đăng nhập. Hãy đăng nhập app iQIYI hoặc mở web iQIYI có tiện ích Việt hóa; không cần mở tập phim."
        raise SubtitleAccessRequired(message)
    tracks = []
    program = data.get("program")
    if not isinstance(program, dict):
        program = {}
    tracks_data = program.get("stl", []) or []
    if not isinstance(tracks_data, list):
        tracks_data = []
    for track in tracks_data:
        if not isinstance(track, dict):
            continue
        fmt = next((key for key in ("xml", "srt", "webvtt", "vtt") if track.get(key)), None)
        if fmt:
            tracks.append({"lid": str(track.get("lid", "")), "name": str(track.get("name", "")),
                           "format": fmt, "url": normalize_track(urljoin(
                               data.get("dstl") or "https://meta.video.iqiyi.com/", track[fmt]))})
    if not tracks:
        if data.get("st") not in (None, 200, "200"):
            raise ValueError(f"iQIYI không trả danh sách phụ đề (trạng thái metadata: {str(data['st'])[:40]}).")
        raise ValueError("iQIYI chưa cung cấp phụ đề rời hoặc yêu cầu quyền xem cho tập này.")
    return tracks


def set_download_progress(tvid: str, stage: str, **details) -> None:
    progress = {"stage": stage, **details}
    DOWNLOAD_PROGRESS[tvid] = progress
    item = EPISODES[tvid]
    item["downloadProgress"] = {key: value for key, value in progress.items()
                                if key in ("stage", "message", "cues")}
    save_episode(tvid, item)


def download_episode_source(tvid: str) -> None:
    session = current_player_session()
    try:
        set_download_progress(tvid, "downloading")
        item = EPISODES[tvid]
        tracks = item.get("tracks") or fetch_episode_tracks(tvid, str(item.get("vid", "")), session)
        track = next((track for track in tracks if str(track.get("lid")) == "1"), None)
        if track is None:
            raise ValueError("Tập này chưa có phụ đề gốc tiếng Trung.")
        url = normalize_track(track["url"])
        with iqiyi_open(url, timeout=20) as response:
            raw = response.read(15_000_001)
        if len(raw) > 15_000_000:
            raise ValueError("Subtitle file is too large")
        cues = parse_source(raw.decode("utf-8-sig"), track["format"])
        capture_source(tvid, cues)
        item = {**EPISODES[tvid], "tracks": tracks}
        EPISODES[tvid] = item
        save_episode(tvid, item)
        set_download_progress(tvid, "ready", cues=len(cues))
    except SubtitleAccessRequired as exc:
        set_download_progress(tvid, "access", message=str(exc), sessionVersion=session["version"])
    except Exception as exc:
        set_download_progress(tvid, "error", message=str(exc)[:250])


def queue_subtitle_downloads(episode_ids, retry: bool = False) -> int:
    count = 0
    tvids = list(episode_ids)
    if any(tvid not in EPISODES for tvid in tvids):
        raise ValueError("Episode was not registered")
    tvids = sorted(
        dict.fromkeys(tvids),
        key=lambda tvid: (
            str(EPISODES[tvid].get("albumId") or ""),
            episode_order(EPISODES[tvid]) or float("inf"),
            str(tvid),
        ),
    )
    with LOCK_GUARD:
        for tvid in tvids:
            if EPISODES[tvid].get("downloadDisabled") and not retry:
                continue
            if retry and EPISODES[tvid].pop("downloadDisabled", False):
                save_episode(tvid, EPISODES[tvid])
            if (episode_dir(tvid) / "source.srt").exists():
                continue
            item = EPISODES[tvid]
            state = DOWNLOAD_PROGRESS.get(tvid, {})
            if state.get("stage") in ("queued", "downloading", "ready") or (state and not retry):
                continue
            if not item.get("vid") and not item.get("tracks"):
                continue
            set_download_progress(tvid, "queued")
            DOWNLOAD_POOL.submit(download_episode_source, tvid)
            count += 1
    return count


def timestamp(ms: int) -> str:
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def parse_source(raw: str, fmt: str) -> list[tuple[int, int, str]]:
    if fmt == "xml" or raw.lstrip().startswith("<"):
        root = ET.fromstring(raw)
        cues = []
        for dia in root.iter("dia"):
            start, end, text = (dia.findtext(k, "") for k in ("st", "et", "sub"))
            if start.isdigit() and end.isdigit() and text.strip():
                if int(end) <= int(start):
                    raise ValueError("Invalid subtitle interval")
                cues.append((int(start), int(end), html.unescape(text)))
        if cues:
            return cues
    raw = raw.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if fmt in ("vtt", "webvtt") or raw.startswith("WEBVTT"):
        raw = re.sub(r"\AWEBVTT[^\n]*\n+", "", raw, flags=re.I)
        blocks = []
        for block in re.split(r"\n\s*\n", raw.strip()):
            if block.lstrip().startswith(("NOTE", "STYLE", "REGION")):
                continue
            lines = block.splitlines()
            for i, line in enumerate(lines):
                if "-->" in line:
                    left, right = line.split("-->", 1)
                    def vtt_stamp(value):
                        value = value.strip().split()[0]
                        return ("00:" + value if value.count(":") == 1 else value).replace(".", ",")
                    lines[i] = vtt_stamp(left) + " --> " + vtt_stamp(right)
                    break
            blocks.append("\n".join(lines))
        raw = "\n\n".join(blocks)
    cues = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = block.splitlines()
        if not lines:
            continue
        time_index = 0 if "-->" in lines[0] else 1
        if len(lines) <= time_index or "-->" not in lines[time_index]:
            continue
        left, right = lines[time_index].split("-->", 1)
        def stamp(value):
            match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})", value.strip().split()[0])
            if not match:
                raise ValueError("Invalid subtitle timestamp")
            h, m, s, ms = map(int, match.groups())
            return ((h * 60 + m) * 60 + s) * 1000 + ms
        start, end = stamp(left), stamp(right)
        text = html.unescape(re.sub(r"<[^>]*>", "", "\n".join(lines[time_index + 1:]))).strip()
        if end <= start:
            raise ValueError("Invalid subtitle interval")
        if text:
            cues.append((start, end, text))
    if not cues:
        raise ValueError("Subtitle has no cues")
    return cues


def to_srt(cues: list[tuple[int, int, str]]) -> str:
    return "\n\n".join(
        f"{i}\n{timestamp(start)} --> {timestamp(end)}\n{text}"
        for i, (start, end, text) in enumerate(cues, 1)
    ) + "\n"


def to_xml(cues: list[tuple[int, int, str]], *, for_player: bool = False) -> bytes:
    root = ET.Element("xml")
    for start, end, text in cues:
        if for_player:
            text = text.replace("\r\n", "\n").replace("\r", "\n")
        dia = ET.SubElement(root, "dia")
        for key, value in (("st", start), ("et", end), ("sub", text.replace("\n", " ") if for_player else text)):
            ET.SubElement(dia, key).text = str(value)
        if for_player:
            ET.SubElement(dia, "viText").text = text
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def ai_subtitle_job(tvid: str) -> dict | None:
    """Only expose a completed translation still bound to this episode's source."""
    try:
        state = TRANSLATION_JOBS.episode_status(episode_dir(tvid))
        if state and state["stage"] == "complete" and (TRANSLATION_JOBS.folder(state["id"]) / "translated.srt").is_file():
            return state
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def episode_dir(tvid: str) -> Path:
    if not re.fullmatch(r"(?:\d{1,20}|yk-[A-Za-z0-9_-]{1,100})", str(tvid)):
        raise ValueError("Invalid episode ID")
    return LIBRARY / tvid


def episode_series_title(item: dict) -> str:
    title = str(item.get("albumTitle") or item.get("title") or "")
    title = re.sub(r"\s*第\s*\d+\s*集.*$|\s*(?:episode|ep)\s*\d+.*$", "", title, flags=re.I)
    return title.strip().strip("《》「」『』【】[]（）() ").strip()


def episode_order(item: dict) -> int:
    try:
        if int(item.get("order") or 0) > 0:
            return int(item["order"])
    except (TypeError, ValueError):
        pass
    match = re.search(r"第\s*(\d+)\s*集|(?:episode|ep)\s*(\d+)", str(item.get("title", "")), re.I)
    return int(match.group(1) or match.group(2)) if match else 0


def album_episode_ids(album_id: str, provider: str, title: str = "") -> list[str]:
    rows = [(key, item) for key, item in list(EPISODES.items())
            if item.get("provider", "iqiyi") == provider]
    if album_id and album_id != "0":
        return sorted(key for key, item in rows if str(item.get("albumId", "")) == album_id)
    title = title.casefold().strip()
    return sorted(key for key, item in rows if
                  title and episode_series_title(item).casefold() == title and
                  str(item.get("albumId") or "0") == "0")


def registered_episode_identity(tvid: str, data: dict, previous: dict, provider: str) -> dict:
    # Track-only responses must not erase metadata from the page or album list.
    identity = {key: str(data.get(key) or previous.get(key) or "").strip()[:limit]
                for key, limit in (("title", 500), ("albumId", 100), ("albumTitle", 300))}
    pattern = r"\d{1,24}" if provider == "iqiyi" else r"yk-[A-Za-z0-9_-]{1,100}"
    if identity["albumId"] and not re.fullmatch(pattern, identity["albumId"]):
        raise ValueError("Invalid album ID")
    try:
        identity["order"] = max(0, min(int(data.get("order") or previous.get("order") or 0), 100000))
    except (TypeError, ValueError):
        raise ValueError("Invalid episode order") from None
    if provider == "iqiyi" and (not identity["title"] or not identity["albumId"] or not identity["order"]):
        metadata = public_iqiyi_json(f"https://pcw-api.iqiyi.com/video/video/baseinfo/{tvid}").get("data", {})
        album_id = str(metadata.get("albumId") or "")
        if (str(metadata.get("tvId")) != tvid or not re.fullmatch(r"\d{1,24}", album_id)
                or (identity["albumId"] and identity["albumId"] != album_id)):
            raise ValueError("Không xác nhận được thông tin tập iQIYI.")
        identity["title"] = identity["title"] or str(metadata.get("name") or "")[:500]
        identity["albumId"] = album_id
        identity["albumTitle"] = identity["albumTitle"] or str(metadata.get("albumName") or "")[:300]
        identity["order"] = identity["order"] or max(0, min(int(metadata.get("order") or 0), 100000))
        if not identity["title"]:
            raise ValueError("iQIYI chưa trả tên phim cho tập này.")
    return identity


def vietnamese_series_title(item: dict) -> str:
    if item.get("provider") == "youku":
        return ""
    identifier = next((str(value) for value in (item.get("albumId"), item.get("tvid"))
                       if re.fullmatch(r"\d{8,24}", str(value or ""))), "")
    if not identifier:
        return ""
    with INTERNATIONAL_TITLE_LOCK:
        cached = INTERNATIONAL_TITLE_CACHE.get(identifier)
        if cached and cached[0] > time.monotonic():
            return cached[1]["title"]
        if identifier not in INTERNATIONAL_TITLE_PENDING:
            INTERNATIONAL_TITLE_PENDING.add(identifier)
            TITLE_LOOKUP_POOL.submit(_load_international_series_title, identifier)
    return ""


def official_series_title(item: dict) -> str:
    """Use iq.com metadata or the title already attached to a Youku item."""
    return vietnamese_series_title(item)


def _load_international_series_title(identifier: str) -> None:
    try:
        international_movie_title(identifier)
    finally:
        with INTERNATIONAL_TITLE_LOCK:
            INTERNATIONAL_TITLE_PENDING.discard(identifier)


def episode_view_summary(folder: Path) -> dict:
    signature = []
    for name in ("source.srt",):
        try:
            stat = (folder / name).stat()
            signature.append((stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino))
        except FileNotFoundError:
            signature.append(None)
    return SUMMARY_CACHE.run((folder, tuple(signature)), lambda: _read_episode_summary(folder), ttl=300)


def _read_episode_summary(folder: Path) -> dict:
    source_path = folder / "source.srt"
    source = parse_source(source_path.read_text(encoding="utf-8-sig"), "srt") if source_path.exists() else []
    return {"downloaded": bool(source), "total": len(source)}


def capture_source(tvid: str, cues: list, append: bool = False) -> None:
    lock = episode_lock(tvid)
    if not lock.acquire(blocking=False):
        raise EpisodeBusy("Tập này đang được xử lý; thử lưu phụ đề lại sau.")
    try:
        folder = episode_dir(tvid)
        path = folder / "source.srt"
        current = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        if append and EPISODES.get(tvid, {}).get("provider") == "youku":
            previous = parse_source(current, "srt") if current else []
            merged = sorted(set(previous).union(cues), key=lambda cue: (cue[0], cue[1], cue[2]))
            if merged == previous:
                return
            if current and merged[:len(previous)] != previous:
                archive = folder / "history" / (hashlib.sha256(current.encode()).hexdigest()[:16] + "-" + str(time.time_ns()))
                atomic_write(archive / "source.srt", current.encode("utf-8"))
            atomic_write(path, to_srt(merged))
            return
        updated = to_srt(cues)
        if current == updated:
            return
        if current:
            archive = folder / "history" / (hashlib.sha256(current.encode()).hexdigest()[:16] + "-" + str(time.time_ns()))
            atomic_write(archive / "source.srt", current.encode("utf-8"))
        atomic_write(path, updated)
    finally:
        lock.release()


PAGE = r'''<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Quản lý phụ đề</title>
<style>
*{box-sizing:border-box}
 :root{color-scheme:dark;--bg:#101318;--panel:#191e26;--panel2:#202631;--line:#303947;--muted:#a7b1c2;--text:#edf1f8;--blue:#5278ed;--focus:#a9c2ff}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 system-ui,sans-serif}
main{max-width:1240px;margin:28px auto;padding:0 22px}
button,input,select{font:inherit}button{min-height:36px;border:0;border-radius:8px;padding:7px 11px;background:var(--blue);color:white;cursor:pointer;font-size:14px;font-weight:600;white-space:nowrap}
button.secondary{background:#303845}button.danger{background:#65313b}button:hover:not(:disabled){filter:brightness(1.12)}button:focus-visible,input:focus-visible,select:focus-visible{outline:3px solid var(--focus);outline-offset:2px}button:disabled{opacity:1;cursor:not-allowed;background:#424c5b;color:#f0f3f8}button:disabled.danger{background:#57343c;color:#ffe8eb}
.pageTop{display:flex;justify-content:space-between;align-items:center;gap:18px}h1{font-size:26px;line-height:1.2;margin:0}.hint{color:var(--muted)}.pageTop .hint{font-size:13px;margin:4px 0 0}.topActions{display:flex;gap:7px;flex-wrap:wrap}.topActions button{min-height:38px}
#accountStatus{font-size:13px;margin:14px 0 12px;display:flex;align-items:center;gap:8px}#accountStatus:before{content:"";width:8px;height:8px;border-radius:50%;background:#667386}#accountStatus.connected:before{background:#50c38a;box-shadow:0 0 0 3px #50c38a22}
.overview{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:14px 0 22px}.metric{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:11px 14px;min-width:0}.metric strong{display:block;font-size:20px;line-height:1.2}.metric span{font-size:12px;color:var(--muted)}
.providerNav{display:flex;gap:7px;margin:0 0 16px;border-bottom:1px solid var(--line)}.providerNav a{display:flex;align-items:center;gap:8px;padding:9px 13px;margin-bottom:-1px;border:1px solid transparent;border-bottom:2px solid transparent;border-radius:9px 9px 0 0;color:var(--muted);text-decoration:none;font-weight:650}.providerNav a:hover{color:var(--text);background:#1b212a}.providerNav a[aria-current=page]{color:#fff;background:#1e2c4a;border-color:#34435d;border-bottom-color:#7090ff}.providerNav span{font-size:11px;color:#c2ccdb;background:#313a48;border-radius:20px;padding:1px 7px}.providerNav a[aria-current=page] span{background:#334a7a;color:#e1eaff}
.libraryTools button{min-height:40px}
.libraryTools{display:flex;align-items:flex-end;flex-wrap:wrap;gap:9px;margin:0 0 18px}.libraryTools button{min-height:44px}
.librarySearch{display:grid;gap:6px;flex:1;min-width:200px}.librarySearch label{font-weight:600}.librarySearch input{width:100%;min-height:44px;border:1px solid #465162;border-radius:8px;padding:8px 12px;background:#11151b;color:var(--text)}#librarySearchCount{margin:-8px 0 16px}
#status{min-height:0;color:#b6c8ff;margin:6px 0}.platformSection{margin:24px 0 30px}.platformSection>h2{font-size:16px;display:flex;align-items:center;gap:8px;margin:0 0 10px;color:#c5d0e2}.platformSection>h2 .count{font-size:12px;font-weight:500;color:var(--muted);background:#242b36;border-radius:20px;padding:2px 8px}.platformEmpty{padding:18px;color:var(--muted);background:var(--panel);border:1px dashed #3b4656;border-radius:10px}
 #appLocalizationStatus{min-height:0;color:#b6c8ff;font-size:13px;margin:5px 0}
 #appLocalizationStatus.running{display:flex;align-items:center;gap:9px;min-height:36px;padding:7px 10px;background:#202a3b;border-left:3px solid #7798ff;border-radius:5px}
 #appLocalizationStatus.running:before{content:"";width:14px;height:14px;flex:0 0 14px;border:2px solid #7188bc;border-right-color:transparent;border-radius:50%;animation:appLocalizationSpin .8s linear infinite}
 #appLocalizationStatus.error{color:#ffb7bd}
 @keyframes appLocalizationSpin{to{transform:rotate(360deg)}}
.album{background:var(--panel);border:1px solid var(--line);border-radius:12px;margin:10px 0;overflow:visible}.albumHead{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:13px 14px}.albumIdentity{min-width:0;flex:1}.seriesTitle{font-size:16px;font-weight:700;line-height:1.3;overflow-wrap:anywhere}.providerTag{font-size:10px;letter-spacing:.04em;text-transform:uppercase;color:#9fb4e9;margin-left:7px}.originalTitle{color:var(--muted);font-size:12px;margin-top:2px}.albumSummary{color:var(--muted);font-size:12px;margin-top:4px}.albumSummary strong{color:#dce4f3;font-weight:600}.albumTools,.episodeActions{display:flex;gap:6px;flex-wrap:wrap;align-items:center}.albumTools .menu,.episodeActions .menu{position:relative}.albumTools button,.episodeActions button{min-height:34px;padding:6px 9px;font-size:13px}.menu summary{list-style:none;cursor:pointer;min-height:34px;display:inline-flex;align-items:center;justify-content:center;border-radius:8px;background:#303845;padding:6px 9px;color:#fff;font-size:14px}.menu summary:focus-visible{outline:3px solid var(--focus);outline-offset:2px}.menu summary::-webkit-details-marker{display:none}.moreMenu{position:absolute;right:0;top:calc(100% + 5px);z-index:5;min-width:150px;padding:5px;background:#252c37;border:1px solid #414c5c;border-radius:9px;box-shadow:0 10px 28px #0007}.moreMenu button{display:block;text-align:left;width:100%;background:transparent;font-weight:500}.moreMenu button:hover{background:#353f4e}.menu[open] .moreMenu{display:block}.moreMenu{display:none}
.album[hidden],.episodeList[hidden]{display:none}.episodeList{border-top:1px solid var(--line);padding:0 14px 8px}.episodeLegend{display:flex;gap:14px;flex-wrap:wrap;padding:10px 0 0;color:var(--muted);font-size:11px}.legendItem{display:flex;align-items:center;gap:5px}.legendDot{width:8px;height:8px;border-radius:50%;background:#697486}.legendDot.complete{background:#52c786}.legendDot.partial{background:#e8b650}.legendDot.error{background:#ed7680}.legendDot.active{background:#6f91ff}.episodeGrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(64px,1fr));gap:6px;padding:10px 0 12px;border-bottom:1px solid var(--line)}.episodeChip{position:relative;min-height:56px;padding:5px 3px;background:#292f39;border:1px solid transparent;color:#e3e9f5}.episodeChip>span{font-weight:700;font-size:13px}.episodeChip small{display:block;font:10px/1.2 system-ui,sans-serif;white-space:nowrap;max-width:100%;overflow:hidden;text-overflow:ellipsis}.episodeChip[aria-pressed=true]{border-color:var(--focus);box-shadow:0 0 0 1px var(--focus)}.episodeChip.complete{background:#174a31;color:#effff4}.episodeChip.sourceReady{background:#244a70;color:#f1f7ff}.episodeChip.partial{background:#5b4613;color:#fff5d4}.episodeChip.error,.episodeChip.access{background:#572e35;color:#ffe9ec}.episodeChip.active{background:#3b5db0;color:#fff}.episodeTitle{font-weight:650}.episodeMeta{color:var(--muted);font-size:13px;margin-top:3px}.episodeRow{display:grid;grid-template-columns:minmax(200px,1fr) auto;gap:10px 16px;align-items:center;padding:12px 0 8px}.statusBadge{display:inline-block;border-radius:20px;padding:2px 8px;font-size:11px;vertical-align:1px;background:#303845;color:#d7dde8}.statusBadge.complete{background:#183b2a;color:#a7e5bd}.statusBadge.partial{background:#493719;color:#f4ce83}.statusBadge.error{background:#48262b;color:#ffb7bd}.statusBadge.active{background:#293d71;color:#c8d6ff}.progress{height:5px;background:#303743;border-radius:5px;overflow:hidden;margin:7px 0 2px;max-width:520px}.progress i{display:block;height:100%;background:#6f91ff}.errorText{color:#ff9fa8;font-size:13px;margin-top:4px;overflow-wrap:anywhere}.errorText details{margin-top:4px}.errorText summary{cursor:pointer;color:#ffd0d4}.actionNotice{color:#b6c8ff;margin-top:6px;padding:5px 8px;background:#252d3a;border-left:3px solid #6f91ff;border-radius:4px;font-size:13px}.detail{grid-column:1/-1;min-width:0;max-height:min(300px,45vh);overflow:auto;overscroll-behavior:contain;scrollbar-gutter:stable;scrollbar-width:thin;scrollbar-color:#626f85 #252c37;margin-top:4px}.detail:focus-visible{outline:2px solid var(--focus);outline-offset:2px}.detail table{width:100%;border-collapse:collapse}.detail th,.detail td{text-align:left;vertical-align:top;padding:8px;border-bottom:1px solid #333b47}.detail th{color:var(--muted);position:sticky;top:0;background:var(--panel);z-index:1}.source{color:#d4d9e2}.vi{color:#a9c2ff}.pending{color:var(--muted)}.empty{padding:30px;text-align:center;color:var(--muted)}
.movieSearch{margin:8px 0 14px;padding:14px;background:var(--panel);border:1px solid var(--line);border-radius:10px}.movieSearch label{display:block;font-weight:650;margin-bottom:8px}.movieSearchControls{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px}.movieSearch input{width:100%}.movieSearchHint,.searchResultMeta{color:var(--muted);font-size:13px;margin-top:6px}#movieSearchStatus{min-height:22px;color:#b6c8ff;margin-top:8px}.searchResults{display:grid;gap:8px;margin-top:8px;max-height:min(46vh,420px);overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin;scrollbar-color:#4a5568 #1a2028}.searchResult{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px;background:#151a21;border:1px solid var(--line);border-radius:9px}.searchResultTitle{font-weight:650}.searchResults::-webkit-scrollbar{width:9px}.searchResults::-webkit-scrollbar-track{background:#1a2028;border-radius:6px}.searchResults::-webkit-scrollbar-thumb{background:#4a5568;border-radius:6px}.searchResults::-webkit-scrollbar-thumb:hover{background:#62708a}
dialog{width:min(560px,calc(100vw - 28px));max-height:calc(100vh - 32px);overflow:auto;border:1px solid #424c5b;border-radius:14px;background:var(--panel);color:var(--text);padding:20px;box-shadow:0 22px 70px #0009}dialog::backdrop{background:#080a0dcc}.settingsHead{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:16px}.settingsHead h2{font-size:20px;margin:0}.settingsField{display:grid;gap:6px;margin:14px 0}.settingsField label{font-weight:600}.settingsField input,.settingsField select{width:100%;min-height:42px;border:1px solid #465162;border-radius:7px;padding:8px 10px;background:#11151b;color:var(--text)}.settingsHint{color:var(--muted);font-size:13px}.settingsActions{display:flex;justify-content:flex-end;gap:8px;margin-top:20px}
@media(min-width:900px){.albumHead{padding:12px 14px}.albumTools{flex-shrink:0}}
@media(max-width:760px){main{margin:18px auto;padding:0 12px}.pageTop{align-items:flex-start;flex-direction:column}.topActions{width:100%}.topActions button{flex:1;min-height:44px}.overview{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin:12px 0 18px}.metric{padding:9px 11px}.metric strong{font-size:18px}.providerNav a{flex:1;justify-content:center;min-height:44px}.albumHead{align-items:flex-start;flex-direction:column;gap:9px}.albumTools{width:100%}.albumTools button,.albumTools .menu summary{min-height:44px}.episodeGrid{grid-template-columns:repeat(auto-fill,minmax(58px,1fr));gap:5px}.episodeChip{min-height:54px}.episodeRow{grid-template-columns:1fr}.episodeActions button,.episodeActions .menu summary{min-height:44px;flex:1 1 90px}.episodeRow .detail{grid-column:1}.movieSearchControls{grid-template-columns:1fr}.searchResult{align-items:flex-start;flex-direction:column}.searchResult button{width:100%;min-height:44px}.settingsActions button{flex:1;min-height:44px}}
@media(prefers-reduced-motion:no-preference){button{transition:filter .15s ease}}
@media(max-width:760px){.libraryTools button{grid-column:1/-1;width:100%;min-height:44px}}
:root{--font-caption:12px;--font-meta:13px;--font-control:14px;--font-section:16px}
.providerTag,.providerNav span,.episodeLegend,.statusBadge,.metric span{font-size:var(--font-caption)}
.platformSection>h2 .count{font-size:var(--font-caption)}
.pageTop .hint,#accountStatus,#appLocalizationStatus,.episodeMeta,.errorText,.actionNotice,.movieSearchHint,.searchResultMeta,.settingsHint{font-size:var(--font-meta)}
.originalTitle,.albumSummary,.mCount{font-size:var(--font-meta)}
.platformSection>h2,.seriesTitle{font-size:var(--font-section)}
.albumTools button,.episodeActions button,.moreMenu button{font-size:var(--font-control)}
.episodeChip>span{font-size:var(--font-control)}
.episodeChip{white-space:normal;min-height:58px}
.episodeChip small{font-size:var(--font-caption);line-height:1.25;white-space:normal;max-width:none;overflow:visible;text-overflow:clip;overflow-wrap:anywhere}
.searchResult>div{min-width:0;overflow-wrap:anywhere}
.moreMenu{max-width:calc(100vw - 32px)}.moreMenu button{white-space:normal;line-height:1.35;overflow-wrap:anywhere}
.providerRow{grid-template-columns:minmax(0,1fr) minmax(0,1.4fr) minmax(0,1fr) auto auto}
.pickerRow{grid-template-columns:repeat(2,minmax(0,1fr))}.pickerRow>*{min-width:0;max-width:100%}
@media(max-width:760px){.topActions button{flex:1 1 140px;white-space:normal;line-height:1.25;min-height:44px}.providerRow{grid-template-columns:repeat(2,minmax(0,1fr))}.providerRow input{grid-column:1/-1;min-height:44px}.providerRow button{min-height:44px;white-space:normal}.providerAdd,.pickerRow{grid-template-columns:minmax(0,1fr)}}
.discoveryActions{display:flex;gap:8px;flex-wrap:wrap}#notificationsDialog{width:min(720px,calc(100vw - 32px));box-sizing:border-box}#notificationsCount{display:inline-block;min-width:18px;padding:1px 5px;margin-left:4px;border-radius:12px;background:#4e73e5;color:white}#notificationsList{max-height:60vh;overflow:auto}#notificationsStatus{margin-top:12px}

.modelPicker{display:grid;grid-template-columns:1fr auto;gap:8px}
.modelPicker{grid-template-columns:1fr}
.providerList{display:grid;gap:10px}
.providerRow .removeProvider{background:#4a2b33}
.providerRow .loadModels{background:#2b3a55}
.providerAdd select{min-height:42px;border:1px solid #465162;border-radius:7px;padding:8px 10px;background:#11151b;color:var(--text)}
.tierBlock{border:1px solid #3a4555;border-radius:10px;padding:12px;background:#161c25}
.tierBlock h3{font-size:15px;margin:0 0 10px}
</style>
<main>
 <header class="pageTop"><div><h1>Thư viện phụ đề</h1><p class="hint">iQIYI · Youku</p></div><nav class="topActions" aria-label="Thao tác thư viện"><button id="localizeIqiyiButton" onclick="runAppLocalization('apply')">Việt hóa iQIYI</button><button id="restoreIqiyiButton" class="secondary" onclick="runAppLocalization('restore')">Khôi phục tiếng Trung</button><button id="addMovieButton" class="secondary" aria-controls="movieSearch" aria-expanded="false" onclick="toggleSearch()">+ Thêm phim</button><button id="notificationsButton" class="secondary" aria-haspopup="dialog" aria-controls="notificationsDialog" onclick="document.getElementById('notificationsDialog').showModal()">Thông báo <span id="notificationsCount">0</span></button><button id="translationSettingsButton" class="secondary" aria-haspopup="dialog" aria-controls="translationSettings" onclick="openTranslationSettings()" disabled>Cài đặt dịch</button><button class="secondary" onclick="openIqiyiProxySettings()">Proxy</button></nav></header>
 <div id="appLocalizationStatus" role="status" aria-live="polite"></div>
 <div id="iqcomAccount" class="hint"><button id="iqcomLoginButton" class="secondary" onclick="loginIqcom()">Kiểm tra iq.com</button> <span id="iqcomStatus" role="status" aria-live="polite">Dùng phiên iq.com của trình duyệt hiện tại</span></div>
 <div id="accountStatus" class="hint" role="status" aria-atomic="true"></div>
 __TRANSLATION_PANEL__
 <section class="overview" aria-label="Tổng quan thư viện"><div class="metric"><strong id="metricTotal">0</strong><span>Tập trong thư viện</span></div><div class="metric"><strong id="metricDownloaded">0</strong><span>Đã có phụ đề gốc</span></div><div class="metric"><strong id="metricCueCount">0</strong><span>Câu phụ đề gốc</span></div><div class="metric"><strong id="metricAttention">0</strong><span>Cần chú ý</span></div></section>
 <nav class="providerNav" aria-label="Điều hướng nền tảng"><a id="navIqiyi" href="#iqiyi" aria-current="page">iQIYI <span id="countIqiyi">0</span></a><a id="navYouku" href="#youku">Youku <span id="countYouku">0</span></a></nav>
 <section id="movieSearch" class="movieSearch" role="search" aria-labelledby="movieSearchTitle" hidden><label id="movieSearchTitle" for="movieQuery">Tìm và thêm phim iQIYI</label><form id="movieSearchForm" autocomplete="off"><div class="movieSearchControls"><input id="movieQuery" name="iw_movie_q" type="text" maxlength="100" placeholder="Tên phim hoặc tên gốc tiếng Trung" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" required><button id="movieSearchButton">Tìm</button></div></form><div id="movieSearchStatus" role="status" aria-live="polite"></div><div id="movieSearchResults" class="searchResults" aria-live="polite"></div></section>
 <div class="libraryTools" role="search" aria-label="Tìm phim trong thư viện"><div class="librarySearch"><label for="libraryQuery">Tìm phim trong thư viện</label><input id="libraryQuery" type="search" maxlength="200" placeholder="Nhập tên tiếng Việt hoặc tên gốc…" aria-describedby="librarySearchCount"></div><button id="libraryClearSearch" class="secondary" hidden>Xóa tìm kiếm</button><button id="toggleAllAlbums" class="secondary" onclick="toggleAllAlbums()">Mở tất cả</button></div>
 <p id="librarySearchCount" class="settingsHint" role="status" aria-live="polite"></p>
 <div id="status" role="status" aria-live="polite"></div><section id="items"></section>
</main>
<dialog id="notificationsDialog" aria-labelledby="notificationsTitle"><div class="settingsHead"><h2 id="notificationsTitle">Phim vừa nhận diện</h2><button class="secondary" onclick="document.getElementById('notificationsDialog').close()" aria-label="Đóng thông báo">Đóng</button></div>
<p class="settingsHint">Phim chỉ được thêm vào thư viện khi bạn chấp nhận. Bỏ qua để không nhận lại thông báo cho phim đó.</p>
<div id="notificationsList"></div><div id="notificationsStatus" role="status" aria-live="polite"></div></dialog>
<dialog id="iqiyiProxyDialog" aria-labelledby="iqiyiProxyTitle"><div class="settingsHead"><h2 id="iqiyiProxyTitle">Proxy iQIYI và web</h2><button class="secondary" onclick="iqiyiProxyDialog.close()" aria-label="Đóng">Đóng</button></div>
<div class="settingsField"><label for="iqiyiProxyUrl">HTTP proxy đặt tại Trung Quốc đại lục</label><input id="iqiyiProxyUrl" type="password" autocomplete="off" maxlength="4096" placeholder="host:port hoặc http://user:password@host:port"><div class="settingsHint">Proxy dùng cho web/player iQIYI. App phụ đề luôn lấy tên phim, metadata và tải phụ đề trực tiếp, kể cả trình đọc iq.com nền. Khi lưu hoặc tắt proxy, iQIYI đang mở sẽ tự khởi động lại; video đang xem có thể bị gián đoạn. Tiện ích web đồng bộ trong khoảng 30 giây. Proxy chỉ được lưu trong phiên chạy hiện tại.</div></div>
<div id="iqiyiProxyStatus" role="status" aria-live="polite"></div><div class="settingsActions"><button class="secondary" onclick="clearIqiyiProxy(this)">Tắt proxy</button><button onclick="saveIqiyiProxy(this)">Lưu proxy</button></div></dialog>
<script>
const API_TOKEN=__IQIYI_TOKEN__;
function apiFetch(url,options={}){const signal=options.signal||((options.method||"GET")==="GET"?AbortSignal.timeout(20000):undefined);return fetch(url,{...options,signal,headers:{...options.headers,"X-Iqiyi-Token":API_TOKEN}}).catch(error=>{if(error.name==="TimeoutError")throw Error("Kết nối quá thời gian chờ. Hãy kiểm tra app quản lý và thử lại.");throw error})}
const esc=s=>String(s==null?"":s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
function safeStatusText(value,fallback="Thông báo chưa có bản tiếng Việt."){const valueText=String(value??"").trim();return valueText&&!/[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/.test(valueText)?valueText:fallback}
const jsArg=value=>esc(JSON.stringify(String(value)));
const statusNode=document.getElementById("status"),itemsNode=document.getElementById("items");
const libraryQuery=document.getElementById("libraryQuery"),libraryClearSearch=document.getElementById("libraryClearSearch");
function normalizeMovieQuery(value){return String(value).normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/[đĐ]/g,"d").toLowerCase().replace(/\s+/g," ").trim()}
libraryQuery.addEventListener("input",()=>render(episodeData));
libraryClearSearch.addEventListener("click",()=>{libraryQuery.value="";render(episodeData);libraryQuery.focus()});
const iqiyiProxyDialog=document.getElementById("iqiyiProxyDialog");
const expandedAlbums=new Set(),collapsedAlbums=new Set(),providerAlbumsOpen={iqiyi:false,youku:false},expandedCues=new Set(),detailCache=new Map(),selectedEpisodes=new Map(),episodeMessages=new Map();
let albumLists={},episodeData=[],lastRenderSignature="",refreshBusy=false,refreshPending=false,refreshError="";
const pendingActions=new Set(),detailPending=new Set();
let activeProvider=location.hash.toLowerCase()==="#youku"?"youku":"iqiyi",iqiyiSynced=false,iqiyiSources={};
let iqcomChecking=false;
let discoveries=[],discoveriesSignature="";
const discoveryBusy=new Set();
function renderDiscoveries(){
 const count=document.getElementById("notificationsCount");count.textContent=String(discoveries.length);
 document.getElementById("notificationsButton").setAttribute("aria-label","Thông báo: "+discoveries.length+" phim chờ chấp nhận");
 const signature=JSON.stringify([discoveries,[...discoveryBusy]]);if(signature===discoveriesSignature)return;discoveriesSignature=signature;
 document.getElementById("notificationsList").innerHTML=discoveries.length?discoveries.map(movie=>"<article class='searchResult'><div><div class='searchResultTitle'>"+esc(movie.title)+"</div><div class='searchResultMeta'>"+esc(movie.provider==="youku"?"Youku":"iQIYI")+" · "+movie.episodes+" tập đã nhận diện</div>"+(movie.originalTitle&&movie.originalTitle!==movie.title?"<div class='searchResultMeta'>Tên gốc: "+esc(movie.originalTitle)+"</div>":"")+"</div><div class='discoveryActions'><button class='secondary' onclick=\"decideDiscovery("+jsArg(movie.tvid)+",'dismiss')\" "+(discoveryBusy.has(movie.tvid)?"disabled":"")+">Bỏ qua</button><button onclick=\"decideDiscovery("+jsArg(movie.tvid)+",'accept')\" "+(discoveryBusy.has(movie.tvid)?"disabled":"")+">Chấp nhận</button></div></article>").join(""):"<p class='hint'>Chưa có phim mới chờ chấp nhận.</p>";
}
async function decideDiscovery(tvid,action){
 if(discoveryBusy.has(tvid))return;discoveryBusy.add(tvid);renderDiscoveries();const status=document.getElementById("notificationsStatus");status.textContent="Đang xử lý…";
 try{const r=await apiFetch("/api/discoveries/decide",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({tvid,action})}),x=await r.json();if(!r.ok)throw Error(x.error||"Không xử lý được thông báo.");status.textContent=safeStatusText(x.message,"Đã cập nhật thông báo.");await refresh(true)}catch(e){status.textContent=safeStatusText(e.message,"Đã xảy ra lỗi. Thông báo chưa có bản tiếng Việt.")}finally{discoveryBusy.delete(tvid);renderDiscoveries()}
}
function updateIqcomStatus(state){const button=document.getElementById("iqcomLoginButton"),status=document.getElementById("iqcomStatus");button.disabled=iqcomChecking;button.textContent=iqcomChecking?"Đang kiểm tra…":"Kiểm tra iq.com";if(!iqcomChecking)status.textContent=safeStatusText(state.message,"Kiểm tra phiên iq.com của trình duyệt hiện tại; không mở cửa sổ mới.");status.setAttribute("aria-busy",String(iqcomChecking))}
async function loginIqcom(){if(iqcomChecking)return;iqcomChecking=true;updateIqcomStatus({});document.getElementById("iqcomStatus").textContent="Đang kiểm tra phiên iq.com của trình duyệt này…";try{const state=await new Promise((resolve,reject)=>{const requestId=crypto.randomUUID();let timer;function receive(event){if(event.source!==window||event.origin!==location.origin||event.data?.type!=="iqcom-session-result"||event.data.requestId!==requestId)return;clearTimeout(timer);window.removeEventListener("message",receive);event.data.error?reject(Error(event.data.error)):resolve(event.data.state||{})}window.addEventListener("message",receive);timer=setTimeout(()=>{window.removeEventListener("message",receive);reject(Error("Tải lại tiện ích Việt hóa và trang này để kiểm tra phiên của trình duyệt."))},8000);window.postMessage({type:"iqcom-session-check",requestId},location.origin)});iqcomChecking=false;updateIqcomStatus(state)}catch(e){iqcomChecking=false;updateIqcomStatus({message:e.message})}}
let appLocalizationPoll=0;
let searchMoviesData=[];
const addingAlbums=new Set(),movieSearchStatus=document.getElementById("movieSearchStatus");
document.getElementById("movieSearchForm").addEventListener("submit",event=>{event.preventDefault();searchMovies()});
window.addEventListener("hashchange",()=>{const provider=location.hash.toLowerCase()==="#youku"?"youku":"iqiyi";if(provider!==activeProvider){activeProvider=provider;if(provider==="youku"){document.getElementById("movieSearch").hidden=true;document.getElementById("addMovieButton").setAttribute("aria-expanded","false")}render(episodeData)}});
function toggleSearch(){const panel=document.getElementById("movieSearch"),q=document.getElementById("movieQuery");panel.hidden=!panel.hidden;document.getElementById("addMovieButton").setAttribute("aria-expanded",String(!panel.hidden));if(panel.hidden){q.value=""}else{q.focus()}}
async function refreshAppLocalization(){clearTimeout(appLocalizationPoll);try{const r=await apiFetch("/api/app-localization"),x=await r.json();if(!r.ok)throw Error(x.error||"Không đọc được trạng thái iQIYI");const busy=x.status==="running",status=document.getElementById("appLocalizationStatus");document.getElementById("localizeIqiyiButton").disabled=busy;document.getElementById("restoreIqiyiButton").disabled=busy;status.className=busy?"running":x.status==="error"?"error":"";status.setAttribute("aria-busy",String(busy));status.textContent=x.status==="idle"?"":safeStatusText(x.message,"Trạng thái Việt hóa chưa có bản tiếng Việt.");if(busy)appLocalizationPoll=setTimeout(refreshAppLocalization,1000)}catch(e){const status=document.getElementById("appLocalizationStatus");status.className="error";status.setAttribute("aria-busy","false");status.textContent=safeStatusText(e.message,"Đã xảy ra lỗi. Thông báo chưa có bản tiếng Việt.")}}
async function runAppLocalization(action){if(action==="restore"&&!confirm("Khôi phục các file giao diện iQIYI từ bản sao lưu? Đóng và mở lại iQIYI sau khi hoàn tất."))return;const status=document.getElementById("appLocalizationStatus");document.getElementById("localizeIqiyiButton").disabled=true;document.getElementById("restoreIqiyiButton").disabled=true;status.className="running";status.setAttribute("aria-busy","true");status.textContent=action==="restore"?"Đang khôi phục giao diện tiếng Trung…":"Đang Việt hóa giao diện iQIYI…";try{const r=await apiFetch("/api/app-localization",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action})}),x=await r.json();if(!r.ok)throw Error(x.error||"Không chạy được thao tác");status.textContent=safeStatusText(x.message,status.textContent);refreshAppLocalization()}catch(e){status.className="error";status.setAttribute("aria-busy","false");status.textContent=safeStatusText(e.message,"Đã xảy ra lỗi. Thông báo chưa có bản tiếng Việt.");document.getElementById("localizeIqiyiButton").disabled=false;document.getElementById("restoreIqiyiButton").disabled=false}}
function renderMovieSearchResults(){
 const node=document.getElementById("movieSearchResults");
 node.innerHTML=searchMoviesData.map((movie,index)=>{
  const exists=episodeData.some(x=>(x.provider||"iqiyi")==="iqiyi"&&String(x.albumId||"")===movie.albumId),sync=albumLists[movie.albumId]||{},adding=addingAlbums.has(movie.albumId)||sync.stage==="loading",failed=sync.stage==="error";
  const meta=[movie.year,movie.description].filter(Boolean).join(" · ");
  return "<article class='searchResult'><div><div class='searchResultTitle'>"+esc(movie.title)+"</div>"+(meta?"<div class='searchResultMeta'>"+esc(meta)+"</div>":"")+(failed?"<div class='errorText'>"+esc(sync.message||"Không lấy được danh sách tập.")+"</div>":"")+"</div><button class='secondary' onclick='addSearchMovie("+index+")' "+(exists||adding?"disabled":"")+">"+(exists?"Trong thư viện":adding?"Đang lấy tập…":failed?"Thử lại":"Thêm phim")+"</button></article>";
 }).join("");
}
async function searchMovies(){
 const query=document.getElementById("movieQuery").value.trim(),button=document.getElementById("movieSearchButton");
 if(!query)return;
 button.disabled=true;movieSearchStatus.textContent="Đang tìm trên iQIYI…";searchMoviesData=[];renderMovieSearchResults();
 try{const r=await apiFetch("/api/search?q="+encodeURIComponent(query)),x=await r.json();if(!r.ok)throw Error(x.error||"Không tìm được phim");searchMoviesData=Array.isArray(x.results)?x.results:[];movieSearchStatus.textContent=searchMoviesData.length?"Tìm thấy "+searchMoviesData.length+" phim.":"Không tìm thấy phim phù hợp.";renderMovieSearchResults()}
 catch(e){movieSearchStatus.textContent=safeStatusText(e.message,"Đã xảy ra lỗi. Thông báo chưa có bản tiếng Việt.")}
 finally{button.disabled=false}
}
async function addSearchMovie(index){
 const movie=searchMoviesData[index];if(!movie||addingAlbums.has(movie.albumId))return;
 if(episodeData.some(x=>(x.provider||"iqiyi")==="iqiyi"&&String(x.albumId||"")===movie.albumId)){movieSearchStatus.textContent="Phim đã có trong thư viện.";return}
 addingAlbums.add(movie.albumId);movieSearchStatus.textContent="Đang thêm “"+movie.title+"”…";renderMovieSearchResults();
 try{const r=await apiFetch("/api/album/add",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({albumId:movie.albumId,title:movie.title})}),x=await r.json();if(!r.ok)throw Error(x.error||"Không thêm được phim");movieSearchStatus.textContent=safeStatusText(x.message,"Đã thêm phim vào thư viện.");await refresh(true)}
 catch(e){movieSearchStatus.textContent=safeStatusText(e.message,"Đã xảy ra lỗi. Thông báo chưa có bản tiếng Việt.")}
 finally{addingAlbums.delete(movie.albumId);renderMovieSearchResults()}
}
function seriesName(x){return String(x.albumTitle||x.title||"").replace(/\s*第\s*\d+\s*集.*$|\s*(?:episode|ep)\s*\d+.*$/i,"").trim().replace(/^[《「『【\s]+|[》」』】\s]+$/g,"").trim()}
function seriesDisplayName(x){return x.albumTitleVi||seriesName(x)}
function albumKey(x){const provider=x.provider||"iqiyi",id=String(x.albumId||"").trim(),title=seriesName(x).toLowerCase();return provider+":"+(id&&id!=="0"?"id:"+encodeURIComponent(id):title?"title:"+encodeURIComponent(title).replace(/'/g,"%27"):"episode:"+x.tvid)}
function orderOf(x){if(Number(x.order)>0)return Number(x.order);const m=String(x.title||"").match(/第\s*(\d+)\s*集|(?:episode|ep)\s*(\d+)/i);return m?Number(m[1]||m[2]):0}
function episodeLabel(x){return "Tập "+(orderOf(x)||"?")}
function albumIsOpen(key){return providerAlbumsOpen[activeProvider]?!collapsedAlbums.has(key):expandedAlbums.has(key)}
function toggleAlbum(key){if(providerAlbumsOpen[activeProvider]){if(collapsedAlbums.has(key))collapsedAlbums.delete(key);else collapsedAlbums.add(key)}else{if(expandedAlbums.has(key))expandedAlbums.delete(key);else expandedAlbums.add(key)}render(episodeData)}
function toggleAllAlbums(){const prefix=activeProvider+":";providerAlbumsOpen[activeProvider]=!providerAlbumsOpen[activeProvider];for(const key of [...collapsedAlbums])if(key.startsWith(prefix))collapsedAlbums.delete(key);for(const key of [...expandedAlbums])if(key.startsWith(prefix))expandedAlbums.delete(key);render(episodeData)}
function selectEpisode(key,id){selectedEpisodes.set(key,id);render(episodeData);document.getElementById("episode-"+id)?.focus?.({preventScroll:true})}
function retryDownload(id){return post("/api/download",{tvid:id})}
async function post(url,data,button){const actionKey=url+JSON.stringify(data);if(pendingActions.has(actionKey))return;pendingActions.add(actionKey);if(button)button.disabled=true;const localId=["/api/download","/api/delete-subtitle"].includes(url)?String(data.tvid||""):"";statusNode.textContent=localId?"":"Đang xử lý…";if(localId){episodeMessages.set(localId,"Đang xử lý phụ đề gốc…");render(episodeData)}try{const r=await apiFetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)}),x=await r.json();if(!r.ok)throw Error(x.error||"Thao tác thất bại");if(localId){episodeMessages.set(localId,safeStatusText(x.message,"Đã xong."));render(episodeData)}else statusNode.textContent=safeStatusText(x.message,"Đã xong.");await refresh(true)}catch(e){if(localId){episodeMessages.set(localId,safeStatusText(e.message,"Đã xảy ra lỗi."));render(episodeData)}else statusNode.textContent=safeStatusText(e.message,"Đã xảy ra lỗi.");await refresh(true)}finally{pendingActions.delete(actionKey);if(button)button.disabled=false}}
function deleteSubtitle(id){const x=episodeData.find(item=>item.tvid===id);if(!x||!confirm("Xóa phụ đề gốc của "+episodeLabel(x)+"? Có thể tải lại phụ đề sau."))return;detailCache.delete(id);expandedCues.delete(id);post("/api/delete-subtitle",{tvid:id})}
function deleteAlbum(tvid){const first=episodeData.find(item=>item.tvid===tvid);if(!first)return;const rows=episodeData.filter(item=>albumKey(item)===albumKey(first)),title=seriesName(first);if(!confirm("Xóa phim “"+title+"” cùng toàn bộ "+rows.length+" tập và phụ đề gốc đã lưu? Thao tác này không thể hoàn tác."))return;post("/api/delete-album",{provider:first.provider||"iqiyi",albumId:first.albumId||"",seriesTitle:seriesName(first)})}
async function openIqiyiProxySettings(){iqiyiProxyDialog.showModal();const message=document.getElementById("iqiyiProxyStatus");message.textContent="Đang kiểm tra…";try{const r=await apiFetch("/api/iqiyi-proxy"),x=await r.json();if(!r.ok)throw Error(x.error||"Không kiểm tra được proxy");message.textContent=x.configured?"Proxy đang bật trong phiên chạy này; nhập URL mới để thay thế.":"Đang kết nối trực tiếp."}catch(e){message.textContent=safeStatusText(e.message,"Đã xảy ra lỗi. Thông báo chưa có bản tiếng Việt.")}}
async function saveIqiyiProxy(button){if(button)button.disabled=true;const message=document.getElementById("iqiyiProxyStatus");message.textContent="Đang áp dụng và kết nối lại iQIYI…";try{const r=await apiFetch("/api/iqiyi-proxy",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:document.getElementById("iqiyiProxyUrl").value})}),x=await r.json();if(!r.ok)throw Error(x.error||"Không lưu được proxy");document.getElementById("iqiyiProxyUrl").value="";message.textContent=(x.configured?"Đã bật proxy. ":"Đã tắt proxy. ")+(safeStatusText(x.desktop?.message,""))+" Tiện ích web đồng bộ trong khoảng 30 giây."}catch(e){message.textContent=safeStatusText(e.message,"Đã xảy ra lỗi. Thông báo chưa có bản tiếng Việt.")}finally{if(button)button.disabled=false}}
async function clearIqiyiProxy(button){document.getElementById("iqiyiProxyUrl").value="";return saveIqiyiProxy(button)}
async function detail(id){
  if(detailPending.has(id))return;
  if(expandedCues.has(id)){expandedCues.delete(id);render(episodeData);return}
  expandedCues.add(id);
  if(detailPending.has(id)){render(episodeData);return}
  detailPending.add(id);detailCache.set(id,"<p role='status'>Đang tải phụ đề gốc…</p>");render(episodeData);
  try{
   const r=await apiFetch("/api/detail?tvid="+encodeURIComponent(id)),x=await r.json();
   if(!r.ok)throw Error(x.error||"Không đọc được phụ đề.");
   detailCache.set(id,x.cues.length?`<table><thead><tr><th># / thời gian</th><th>Phụ đề gốc</th></tr></thead><tbody>${x.cues.map(c=>`<tr><td>${c.n}<br>${esc(c.time)}</td><td class='source'>${esc(c.source)}</td></tr>`).join("")}</tbody></table>`:`<div class='episodeMeta'>${esc(safeStatusText(x.message,"Chưa có dữ liệu phụ đề."))}</div>`);
  }catch(e){detailCache.set(id,"<p class='errorText' role='alert'>"+esc(safeStatusText(e.message,"Không đọc được phụ đề."))+" Đóng rồi mở lại để thử lại.</p>")}
  finally{detailPending.delete(id);render(episodeData)}
 }
 function episodeState(x){
  const dl=x.downloadProgress||{};
  const tr=x.translation;
  if(tr&&!["complete","error","cancelled"].includes(tr.stage))return {label:"Đang dịch phụ đề",short:"Đang dịch",style:"active"};
  if(tr?.stage==="complete")return {label:"Đã dịch tiếng Việt",short:"Đã dịch",style:"complete"};
  if(tr?.stage==="error")return {label:"Dịch chưa hoàn tất",short:"Lỗi dịch",style:"error"};
  if(x.downloaded)return {label:"Đã tải phụ đề gốc",short:"Đã tải",style:"sourceReady"};
  if(dl.stage==="access")return {label:"Cần phiên đăng nhập/quyền xem",short:"Cần quyền",style:"access"};
  if(dl.stage==="error")return {label:"Lỗi tải phụ đề",short:"Lỗi tải",style:"error"};
  if(dl.stage==="downloading")return {label:"Đang tải phụ đề gốc",short:"Đang tải",style:"active"};
  if(dl.stage==="queued")return {label:"Chờ tải phụ đề gốc",short:"Chờ tải",style:""};
  return x.provider==="youku"?{label:"Chờ phụ đề từ Youku",short:"Chờ phụ đề",style:""}:{label:"Đã nhận diện · Chưa tải phụ đề",short:"Chưa tải",style:""};
 }
 function episodePanel(x){
  const state=episodeState(x),dl=x.downloadProgress||{},downloadBusy=["queued","downloading"].includes(dl.stage);
  const tr=x.translation,trBusy=tr&&!["complete","error","cancelled"].includes(tr.stage);
  const isYouku=x.provider==="youku",total=Number(x.cues)||0;
  const error=["error","access"].includes(dl.stage)?dl.message:"";
  const actionMessage=episodeMessages.get(x.tvid)||"";
  return `<article class='episodeRow' id='panel-${esc(x.tvid)}'><div><div class='episodeTitle'>${esc(episodeLabel(x))} <span class='statusBadge ${state.style}'>${esc(state.label)}</span></div>`+
   (total?`<div class='episodeMeta'>${total} câu phụ đề gốc</div>`:"")+
   (tr?`<div class='${tr.stage==="error"?"errorText":"episodeMeta"}' role='status'>${esc(tr.message)}</div>`:"")+
   (error?`<div role='status' aria-live='polite' class='errorText'>${esc(error)}</div>`:"")+
   (actionMessage?`<div class='actionNotice' role='status'>${esc(actionMessage)}</div>`:"")+`</div><div class='episodeActions'>`+
   (total?`<button class='secondary' title='Xem nội dung phụ đề gốc' onclick="detail('${esc(x.tvid)}')">${expandedCues.has(x.tvid)?"Ẩn câu":"Câu "+total}</button>`:"")+
   (isYouku||x.downloaded?"":`<button class='secondary' title='Tải phụ đề gốc' onclick="retryDownload('${esc(x.tvid)}')" ${downloadBusy||!x.downloadAvailable?"disabled":""}>${downloadBusy?"Đang tải…":"Tải gốc"}</button>`)+
   (x.downloaded?`<button data-translate-episode='${esc(x.tvid)}' onclick="${tr?.resumable?"resumeTranslationJob('"+esc(tr.id)+"')":"translateEpisode('"+esc(x.tvid)+"')"}" ${trBusy?"disabled":""}>${trBusy?"Đang dịch…":tr?.resumable?"Dịch tiếp":tr?.stage==="complete"?"Dịch lại":"Dịch"}</button>`:"")+
   (tr?`<button class='secondary' onclick="showTranslationJob('${esc(tr.id)}')">${tr.stage==="complete"?"Xem bản dịch":"Tiến độ dịch"}</button>`:"")+
   (tr?.stage==="complete"?`<button class='secondary' onclick="downloadTranslation('${esc(tr.id)}','translated.srt',this)">Tải SRT Việt</button>`:"")+
   (x.downloaded?`<details class='menu' data-menu-key='episode:${esc(x.tvid)}'><summary class='secondary' aria-label='Thao tác khác cho tập'>···</summary><div class='moreMenu'>${tr?.resumable?`<button onclick="translateEpisode('${esc(x.tvid)}')">Dịch từ đầu</button>`:""}<button class='danger' onclick="deleteSubtitle('${esc(x.tvid)}')">Xóa phụ đề gốc</button></div></details>`:"")+`</div>`+
   (expandedCues.has(x.tvid)?`<div id='cues-${esc(x.tvid)}' class='detail' role='region' aria-label='Phụ đề gốc ${esc(episodeLabel(x))}' tabindex='0'>${detailCache.get(x.tvid)||""}</div>`:"")+`</article>`;
 }
 function updateTranslationEpisode(state){
  const row=episodeData.find(x=>x.tvid===state.episode_id);
  if(row?.translation?.id===state.id){row.translation={id:state.id,stage:state.stage,message:state.message,step:state.step,resumable:state.resumable,saved_batches:state.saved_batches,total_batches:state.total_batches,retry_at:state.retry_at};render(episodeData)}
  if(row&&(!row.translation||row.translation.id!==state.id||["complete","error","cancelled"].includes(state.stage)))refresh(true);
 }
 function updateProviderChrome(data){
 const iqiyi=data.filter(x=>(x.provider||"iqiyi")==="iqiyi"),youku=data.filter(x=>x.provider==="youku");
 document.getElementById("countIqiyi").textContent=iqiyi.length;document.getElementById("countYouku").textContent=youku.length;
 document.getElementById("navIqiyi").setAttribute("aria-current",activeProvider==="iqiyi"?"page":"false");document.getElementById("navYouku").setAttribute("aria-current",activeProvider==="youku"?"page":"false");
 document.getElementById("addMovieButton").hidden=activeProvider==="youku";
 document.getElementById("iqcomAccount").hidden=activeProvider==="youku";
 document.getElementById("toggleAllAlbums").textContent=providerAlbumsOpen[activeProvider]?"Thu gọn tất cả":"Mở tất cả";
 const account=document.getElementById("accountStatus"),loginStatus=source=>!source?.synced?"Chưa kết nối":source.connected?"Đã đăng nhập":"Chưa đăng nhập";
 const accountText=activeProvider==="iqiyi"?"iQIYI · App: "+loginStatus(iqiyiSources.app)+" · Web: "+loginStatus(iqiyiSources.web):"Youku lưu phụ đề khi bạn phát phim có phụ đề tiếng Trung";
 if(account.textContent!==accountText)account.textContent=accountText;
 account.classList.toggle("connected",activeProvider==="iqiyi"&&iqiyiSynced);
}
function render(data){
 const providerRows=data.filter(x=>(x.provider||"iqiyi")==activeProvider),label=activeProvider==="iqiyi"?"iQIYI":"Youku",groups=new Map();
 const query=normalizeMovieQuery(libraryQuery.value);libraryClearSearch.hidden=!libraryQuery.value;
 updateProviderChrome(data);
  const downloaded=providerRows.filter(x=>x.downloaded).length,cueCount=providerRows.reduce((sum,x)=>sum+(Number(x.cues)||0),0),attention=providerRows.filter(x=>["error","access"].includes((x.downloadProgress||{}).stage)||x.translation?.stage==="error").length;
  document.getElementById("metricTotal").textContent=providerRows.length;document.getElementById("metricDownloaded").textContent=downloaded;document.getElementById("metricCueCount").textContent=cueCount;document.getElementById("metricAttention").textContent=attention;
 providerRows.forEach(x=>{const key=albumKey(x);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(x)});
 let html="<section class='platformSection' aria-labelledby='platform-title'><h2 id='platform-title'>"+label+" <span class='count'>"+providerRows.length+" tập</span></h2>";
 let visibleAlbums=0;
 if(!providerRows.length)html+="<div class='platformEmpty'>"+(activeProvider==="youku"?"Mở Youku và phát phim có phụ đề tiếng Trung để thêm tập vào thư viện.":"Mở iQIYI hoặc dùng Thêm phim để bắt đầu thư viện.")+"</div>";
 else{
  groups.forEach((rows,key)=>{
   if(query&&!rows.some(x=>normalizeMovieQuery(seriesDisplayName(x)+" "+seriesName(x)).includes(query)))return;
   rows.sort((a,b)=>(orderOf(a)||9999)-(orderOf(b)||9999));
   const first=rows[0],original=seriesName(first),title=seriesDisplayName(first)||"Phim đang phát";
   const shown=rows;visibleAlbums++;
   const list=albumLists[String(first.albumId||"")]||{},total=list.stage==="ready"?list.total:Math.max(rows.length,...rows.map(x=>Number(x.albumTotal)||0));
   const sourceCount=rows.filter(x=>x.downloaded).length;
   const open=albumIsOpen(key),listId="episode-list-"+String(first.albumId||first.tvid).replace(/[^a-z0-9_-]/gi,"-");
   const selected=shown.find(x=>x.tvid===selectedEpisodes.get(key))||shown[0];
   const grid=open?shown.map(x=>{const state=episodeState(x);return "<button id='episode-"+esc(x.tvid)+"' class='episodeChip "+state.style+"' aria-pressed='"+(x===selected)+"' aria-label='"+esc(episodeLabel(x)+": "+state.label)+"' title='"+esc(episodeLabel(x)+": "+state.label)+"' onclick=\"selectEpisode("+jsArg(key)+","+jsArg(x.tvid)+")\"><span>"+esc(orderOf(x)||"?")+"</span><small>"+esc(state.short)+"</small></button>"}).join(""):"";
   html+="<section class='album'><div class='albumHead'><div class='albumIdentity'><div class='seriesTitle'>"+esc(title)+"</div>"+
    (title!==original?"<div class='originalTitle'>"+esc(original)+"</div>":"")+
    "<div class='albumSummary'><strong>"+rows.length+(total>rows.length?" / "+total:"")+" tập</strong> · Có phụ đề gốc "+sourceCount+"</div>"+
    (first.provider!=="youku"&&list.stage==="loading"?"<div class='albumSummary' role='status'>Đang lấy toàn bộ danh sách tập từ iQIYI…</div>":first.provider!=="youku"&&list.stage==="error"?"<div class='errorText'>Chưa lấy đủ danh sách tập: "+esc(list.message)+". App sẽ tự thử lại.</div>":"")+"</div>"+
    "<div class='albumTools'>"+

    "<button class='secondary' aria-expanded='"+open+"' aria-controls='"+listId+"' onclick=\"toggleAlbum("+jsArg(key)+")\">"+(open?"Ẩn tập":"Tập "+rows.length)+"</button>"+
    "<details class='menu' data-menu-key='album:"+esc(key)+"'><summary class='secondary' aria-label='Thao tác phim'>···</summary><div class='moreMenu'>"+(first.provider==="youku"?"":"<button onclick=\"post('/api/download-all',{albumId:'"+esc(first.albumId||"")+"'},this)\">Tải phụ đề gốc</button>")+"<button class='danger' onclick=\"deleteAlbum('"+esc(first.tvid)+"')\">Xóa phim</button></div></details></div></div>"+
    "<div id='"+listId+"' class='episodeList' "+(open?"":"hidden")+">"+(open?"<div class='episodeLegend' aria-label='Chú giải trạng thái'><span class='legendItem'><i class='legendDot'></i>Chưa tải</span><span class='legendItem'><i class='legendDot sourceReady'></i>Đã tải gốc</span><span class='legendItem'><i class='legendDot complete'></i>Đã dịch</span><span class='legendItem'><i class='legendDot active'></i>Đang xử lý</span><span class='legendItem'><i class='legendDot error'></i>Cần xử lý</span></div><div class='episodeGrid' role='group' aria-label='Chọn tập phim'>"+grid+"</div>"+episodePanel(selected):"")+"</div></section>";
  });
  if(!visibleAlbums)html+="<div class='platformEmpty'>Không tìm thấy phim phù hợp. Thử tên ngắn hơn, tên gốc hoặc xóa tìm kiếm.</div>";
 }
 const searchCount=document.getElementById("librarySearchCount"),searchText=query?"Hiển thị "+visibleAlbums+" / "+groups.size+" phim trong "+label:"";if(searchCount.textContent!==searchText)searchCount.textContent=searchText;
 html+="</section>";
 const scrollY=window.scrollY,focusedId=document.activeElement?.id,focusedControl=itemsNode.contains(document.activeElement)?{tag:document.activeElement.tagName,action:document.activeElement.getAttribute("onclick"),menu:document.activeElement.closest(".menu")?.dataset.menuKey}:null,openMenus=new Set(Array.from(itemsNode.querySelectorAll(".menu[open]")).map(node=>node.dataset.menuKey)),scrollPositions=Array.from(itemsNode.querySelectorAll(".detail")||[]).map(node=>[node.id,node.scrollTop,node.scrollLeft]);
 itemsNode.innerHTML=html;
 itemsNode.querySelectorAll(".menu[data-menu-key]").forEach(node=>{if(openMenus.has(node.dataset.menuKey))node.open=true});
 scrollPositions.forEach(([id,top,left])=>{const node=document.getElementById(id);if(node){node.scrollTop=top;node.scrollLeft=left}});
 if(focusedId)document.getElementById(focusedId)?.focus({preventScroll:true});
 else if(focusedControl)Array.from(itemsNode.querySelectorAll("button,summary,a")).find(node=>node.tagName===focusedControl.tag&&node.getAttribute("onclick")===focusedControl.action&&node.closest(".menu")?.dataset.menuKey===focusedControl.menu)?.focus({preventScroll:true});
 window.scrollTo(0,scrollY);
}
async function refresh(force){if(refreshBusy){refreshPending=refreshPending||!!force;return}refreshBusy=true;try{const r=await apiFetch("/api/episodes"),payload=await r.json();if(!r.ok)throw Error(payload.error||"Không tải được thư viện.");const data=payload.episodes||[];if(refreshError&&statusNode.textContent===refreshError)statusNode.textContent="";refreshError="";albumLists=payload.albums||{};discoveries=payload.discoveries||[];renderDiscoveries();iqiyiSynced=!!(payload.session&&payload.session.synced);iqiyiSources=payload.session?.sources||{};updateIqcomStatus(payload.iqcomSession||{});episodeData=data;const signature=JSON.stringify([albumLists,data.map(x=>[x.tvid,x.provider,x.title,x.albumTitle,x.albumTitleVi,x.albumId,x.albumTotal,x.cues,x.downloadAvailable,x.downloadProgress,x.translation])]);if(force||signature!==lastRenderSignature){lastRenderSignature=signature;render(data);renderMovieSearchResults()}else updateProviderChrome(data)}catch(e){refreshError=safeStatusText(e.message,"Không kết nối được app quản lý.");statusNode.textContent=refreshError}finally{refreshBusy=false;if(refreshPending){refreshPending=false;queueMicrotask(()=>refresh(true))}}}
function refreshVisible(){if(!document.hidden)refresh(false)}
document.addEventListener("visibilitychange",()=>{if(!document.hidden)refresh(false)});
refreshAppLocalization();refresh(true);setInterval(refreshVisible,5000);
</script>'''
PAGE = PAGE.replace("__TRANSLATION_PANEL__", (ROOT / "translation_ui.html").read_text(encoding="utf-8"))


PLAYER_API_ROUTES = {
    "GET": frozenset(("/health", "/api/extension-token", "/subtitle.xml",
                      "/api/official-subtitle-state",
                      "/api/international-title", "/api/international-actor", "/api/international-search")),
    "POST": frozenset(("/api/session", "/api/register", "/api/album/register", "/api/capture", "/api/localize-remaining")),
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    @staticmethod
    def is_iqiyi_origin(origin: str | None) -> bool:
        try:
            parsed = urlsplit(origin or "")
            host = (parsed.hostname or "").lower()
            return (parsed.scheme == "https" and parsed.netloc.lower() == host and
                    (host == "iqiyi.com" or host.endswith(".iqiyi.com")))
        except ValueError:
            return False

    def allowed_request(self) -> bool:
        port = self.server.server_port
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return False
        origin = self.headers.get("Origin")
        local = (f"http://127.0.0.1:{port}", f"http://localhost:{port}")
        if urlsplit(self.path).path in ("/api/browser-proxy", "/api/browser-session"):
            methods = ("POST", "OPTIONS") if urlsplit(self.path).path == "/api/browser-session" else ("GET", "OPTIONS")
            return (self.command in methods and
                    (origin is None or bool(re.fullmatch(r"chrome-extension://[a-p]{32}", origin))))
        if urlsplit(self.path).path == "/":
            return origin is None or origin in local
        if origin is not None and origin not in local:
            methods = ("GET", "POST") if self.command == "OPTIONS" else (self.command,)
            if not any(urlsplit(self.path).path in PLAYER_API_ROUTES.get(method, ()) for method in methods):
                return False
            if re.fullmatch(r"chrome-extension://[a-p]{32}", origin):
                return True  # Player-only token is still required; admin routes stay local.
        if origin is None or origin in (*local, "null", "https://localwebapp.iqiyi.com",
                                        "https://iqiyi.com", "https://www.iqiyi.com"):
            return True
        try:
            parsed = urlsplit(origin)
            host = (parsed.hostname or "").lower()
            return (parsed.scheme == "https" and parsed.netloc.lower() == host and
                    (host == "youku.com" or host.endswith(".youku.com") or
                     host == "iqiyi.com" or host.endswith(".iqiyi.com")))
        except ValueError:
            return False

    def authorized(self) -> bool:
        if not self.allowed_request():
            self.send_json(403, {"error": "Origin or Host is not allowed"})
            return False
        request = urlsplit(self.path)
        if self.command == "GET" and request.path in ("/", "/health"):
            return True
        origin = self.headers.get("Origin")
        if (self.command == "GET" and request.path == "/api/extension-token" and
                self.is_iqiyi_origin(origin)):
            return True
        supplied = self.headers.get("X-Iqiyi-Token", "")
        if request.path in ("/subtitle.xml", "/api/official-subtitle-state"):
            supplied = supplied or parse_qs(request.query).get("token", [""])[0]
        if (self.command == "GET" and request.path == "/subtitle.xml" and not supplied and
                self.is_iqiyi_origin(origin)):
            return True
        expected = getattr(self.server, "api_token", "")
        if request.path in ("/api/browser-proxy", "/api/browser-session"):
            credential = browser_session_token(expected) if request.path == "/api/browser-session" else browser_proxy_token(expected)
            if expected and secrets.compare_digest(supplied.encode(), credential.encode()):
                return True
            self.send_json(403, {"error": "Browser token is invalid"})
            return False
        local = (f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}")
        tokens = [expected] if origin is None or origin in local else []
        if expected and request.path in PLAYER_API_ROUTES.get(self.command, ()):
            tokens.append(player_token(expected))
        if not expected or not any(secrets.compare_digest(supplied.encode(), token.encode()) for token in tokens):
            self.send_json(403, {"error": "Kết nối phụ đề đã hết hiệu lực. Khởi động lại app quản lý và trình phát."})
            return False
        return True

    def end_headers(self):
        origin = self.headers.get("Origin")
        if origin and self.allowed_request() and urlsplit(self.path).path != "/":
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Vary", "Origin")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def send_body(self, code: int, content_type: str, body: bytes):
        compressed = False
        encoding_values = {}
        for entry in self.headers.get("Accept-Encoding", "").split(","):
            parts = [part.strip() for part in entry.split(";")]
            if not parts[0]:
                continue
            quality = 1.0
            for option in parts[1:]:
                if option.startswith("q="):
                    try:
                        quality = float(option[2:])
                    except ValueError:
                        quality = 0.0
            encoding_values[parts[0].lower()] = quality
        accepts_gzip = encoding_values.get("gzip", encoding_values.get("*", 0)) > 0
        if len(body) >= 1024 and accepts_gzip:
            body = gzip.compress(body, compresslevel=4, mtime=0)
            compressed = True
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Vary", "Accept-Encoding")
        if compressed:
            self.send_header("Content-Encoding", "gzip")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code: int, data):
        self.send_body(code, "application/json; charset=utf-8", json.dumps(data, ensure_ascii=False).encode())

    def do_OPTIONS(self):
        if not self.allowed_request():
            self.send_json(403, {"error": "Origin or Host is not allowed"})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Iqiyi-Token")
        self.end_headers()

    def do_GET(self):
        if not self.authorized():
            return
        try:
            self.get_response()
        except (ValueError, KeyError, OSError, ET.ParseError) as exc:
            self.send_json(400, {"error": str(exc)[:500]})

    def get_response(self):
        request = urlsplit(self.path)
        if request.path == "/":
            body = PAGE.replace("__IQIYI_TOKEN__", json.dumps(self.server.api_token)).encode()
            self.send_body(200, "text/html; charset=utf-8", body)
        elif request.path == "/health":
            with LOCK_GUARD:
                busy = (any(lock.locked() for lock in EPISODE_LOCKS.values()) or
                        any(state.get("stage") in ("queued", "downloading") for state in list(DOWNLOAD_PROGRESS.values())) or
                        any(state.get("stage") == "loading" for state in list(ALBUM_LISTS.values())) or
                        app_localization_status().get("status") == "running" or TRANSLATION_JOBS.busy()
                        or any(state.get("loading") for state in list(OFFICIAL_SUBTITLE_CACHE.values())))
            self.send_json(200, {"ok": True, "app": "subtitle-manager", "version": 25, "busy": busy,
                                 "runtimeVersion": RUNTIME_VERSION,
                                 "rootId": hashlib.sha256(str(ROOT.resolve()).casefold().encode()).hexdigest()[:16]})
        elif request.path == "/api/translation/providers":
            self.send_json(200, {"providers": TRANSLATION_PROVIDERS, "active_id": TRANSLATION_JOBS.active_id()})
        elif request.path == "/api/translation/status":
            self.send_json(200, TRANSLATION_JOBS.status(parse_qs(request.query).get("id", [""])[0]))
        elif request.path == "/api/translation/artifact":
            query = parse_qs(request.query)
            name = query.get("name", [""])[0]
            body = TRANSLATION_JOBS.artifact(query.get("id", [""])[0], name)
            self.send_body(200, "application/json; charset=utf-8" if name.endswith(".json") else "application/x-subrip; charset=utf-8", body)
        elif request.path == "/api/extension-token":
            self.send_json(200, {"token": player_token(self.server.api_token)})
        elif request.path == "/api/app-localization":
            self.send_json(200, app_localization_status())
        elif request.path == "/api/iqcom-session":
            self.send_json(200, IQCOM_SESSION.status())
        elif request.path == "/api/iqiyi-proxy":
            with IQIYI_PROXY_LOCK:
                configured = bool(IQIYI_PROXY_URL)
            self.send_json(200, {"configured": configured})
        elif request.path == "/api/browser-proxy":
            with IQIYI_PROXY_LOCK:
                proxy = urlsplit(IQIYI_PROXY_URL) if IQIYI_PROXY_URL else None
            if proxy and parse_qs(request.query).get("desktop") == ["1"]:
                proxy = urlsplit(DESKTOP_PROXY.url())
            self.send_json(200, {"proxy": {"host": proxy.hostname, "port": proxy.port,
                                         "username": unquote(proxy.username or ""),
                                         "password": unquote(proxy.password or "")} if proxy else None})
        elif request.path == "/api/international-title":
            identifier = parse_qs(request.query).get("id", [""])[0]
            self.send_json(200, international_movie_title(identifier))
        elif request.path == "/api/international-search":
            self.send_json(200, international_search_query(parse_qs(request.query).get("q", [""])[0]))
        elif request.path == "/api/international-actor":
            name = parse_qs(request.query).get("name", [""])[0]
            self.send_json(200, international_actor_name(name))
        elif request.path == "/api/search":
            keyword = parse_qs(request.query).get("q", [""])[0]
            self.send_json(200, {"results": search_iqiyi_albums(keyword)})
        elif request.path == "/api/episodes":
            sync_current_player()
            refresh_album_lists()
            rows = []
            for tvid, item in list(EPISODES.items()):
                if library_status(item) != "accepted":
                    continue
                folder = episode_dir(tvid)
                try:
                    summary = episode_view_summary(folder)
                except (OSError, ValueError, ET.ParseError):
                    summary = {"downloaded": (folder / "source.srt").exists(), "total": 0}
                rows.append({"tvid": tvid, "provider": item.get("provider", "iqiyi"),
                             "title": item.get("title", ""),
                             "albumTitle": item.get("albumTitle") or episode_series_title(item),
                             "albumTitleVi": official_series_title(item),
                             "albumId": item.get("albumId", ""),
                             "albumTotal": item.get("albumTotal", 0),
                             "discoveredAt": item.get("discoveredAt", 0),
                             "order": episode_order(item), "downloaded": summary["downloaded"],
                             "downloadAvailable": bool(item.get("vid") or item.get("tracks")),
                             "cues": summary["total"],
                             "translation": TRANSLATION_JOBS.episode_status(folder),
                             "downloadProgress": DOWNLOAD_PROGRESS.get(tvid)})
            sort_library_rows(rows)
            for row in rows:
                row.pop("discoveredAt", None)
            self.send_json(200, {"episodes": rows, "albums": dict(ALBUM_LISTS),
                                 "discoveries": pending_movies(),
                                 "session": player_session_status(), "iqcomSession": IQCOM_SESSION.status()})
        elif request.path == "/api/official-subtitle-state":
            tvid = parse_qs(request.query).get("tvid", [""])[0]
            status = official_subtitle_status(tvid)
            ai = ai_subtitle_job(tvid)
            self.send_json(200, {"officialAvailable": status["available"],
                                 "officialLoading": status["loading"], "officialError": status["error"],
                                 "aiAvailable": ai is not None, "aiVersion": ai["id"] if ai else ""})
        elif request.path == "/api/detail":
            tvid = parse_qs(request.query).get("tvid", [""])[0]
            source_path = episode_dir(tvid) / "source.srt"
            if not source_path.exists():
                self.send_json(200, {"cues": [], "message": "Chưa tải phụ đề của nguồn đã chọn."})
                return
            source = parse_source(source_path.read_text(encoding="utf-8-sig"), "srt")
            cues = [{"n": i + 1, "time": timestamp(start) + " → " + timestamp(end), "source": text}
                    for i, (start, end, text) in enumerate(source)]
            self.send_json(200, {"cues": cues, "total": len(source)})
        elif request.path == "/subtitle.xml":
            query = parse_qs(request.query)
            source = query.get("source", [""])[0]
            if source not in ("iqcom", "ai"):
                self.send_error(404)
                return
            tvid = query.get("tvid", [""])[0]
            if source == "ai":
                body = None
                try:
                    with episode_lock(tvid):
                        state = ai_subtitle_job(tvid)
                        if state:
                            raw = TRANSLATION_JOBS.artifact(state["id"], "translated.srt").decode("utf-8-sig")
                            body = to_xml(parse_source(raw, "srt"), for_player=True)
                except (OSError, ValueError):
                    pass
            else:
                official_subtitle_status(tvid)
                with OFFICIAL_SUBTITLE_LOCK:
                    official = OFFICIAL_SUBTITLE_CACHE.get(tvid, {})
                    body = official.get("xml") if official.get("available") else None
            body, code = (body, 200) if body else (b"<?xml version='1.0'?><xml />", 404)
            self.send_response(code)
            self.send_header("Content-Type", "text/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        if not self.authorized():
            return
        route = urlsplit(self.path).path
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 <= size <= 25_000_000:
                raise ValueError("Request too large")
            data = json.loads(self.rfile.read(size) or b"{}")
            if not isinstance(data, dict):
                raise ValueError("Request must be a JSON object")
            if route == "/api/translation/models":
                self.send_json(200, {"models": list_models(data)})
                return
            if route == "/api/translation/resume":
                previous = TRANSLATION_JOBS.status(data.get("id"))
                tvid = previous.get("episode_id")
                if tvid:
                    if tvid not in EPISODES or library_status(EPISODES[tvid]) != "accepted":
                        raise ValueError("Không tìm thấy tập của phiên dịch trong thư viện.")
                    lock = episode_lock(tvid)
                    if not lock.acquire(blocking=False):
                        raise EpisodeBusy("Phụ đề tập đang cập nhật. Hãy thử lại sau.")
                    try:
                        state = TRANSLATION_JOBS.resume_episode(data, episode_dir(tvid))
                    finally:
                        lock.release()
                else:
                    state = TRANSLATION_JOBS.resume(data)
                self.send_json(202, state)
                return
            if route == "/api/translation/start":
                if "tvid" in data:
                    tvid = data["tvid"]
                    if not isinstance(tvid, str) or tvid not in EPISODES or library_status(EPISODES[tvid]) != "accepted":
                        raise ValueError("Không tìm thấy tập này trong thư viện.")
                    lock = episode_lock(tvid)
                    if not lock.acquire(blocking=False):
                        raise EpisodeBusy("Phụ đề tập đang được cập nhật; hãy thử lại sau.")
                    try:
                        item = EPISODES[tvid]
                        label = f"{official_series_title(item) or episode_series_title(item)} · Tập {episode_order(item) or '?'}"
                        state = TRANSLATION_JOBS.start_episode(data, episode_dir(tvid), tvid, label)
                    finally:
                        lock.release()
                else:
                    state = TRANSLATION_JOBS.start(data)
                self.send_json(202, state)
                return
            if route == "/api/translation/cancel":
                self.send_json(200, TRANSLATION_JOBS.cancel(data.get("id")))
                return
            if route == "/api/localize-remaining":
                texts = data.get("texts")
                if (not isinstance(texts, list) or not 1 <= len(texts) <= 20 or
                        any(not isinstance(t, str) or not 1 <= len(t) <= 2000 for t in texts)):
                    raise ValueError("Mỗi lượt Việt hóa cần 1–20 đoạn, tối đa 2000 ký tự mỗi đoạn.")
                self.send_json(200, {"translations": localize_ui_texts(texts)})
                return
            if route == "/api/browser-session":
                self.send_json(200, IQCOM_SESSION.update(data.get("cookies"), data.get("sourceId"),
                                                       select=data.get("select", False)))
                return
            if route == "/api/iqcom-session":
                self.send_json(200, IQCOM_SESSION.status())
                return
            if route == "/api/app-localization":
                action = str(data.get("action", ""))
                try:
                    state = start_app_localization(action)
                except RuntimeError as exc:
                    self.send_json(409, {"error": str(exc)})
                    return
                self.send_json(202, state)
                return
            if route == "/api/iqiyi-proxy":
                proxy_url = validate_iqiyi_proxy_url(data.get("url", ""))
                global IQIYI_PROXY_URL
                with IQIYI_PROXY_APPLY_LOCK:
                    with IQIYI_PROXY_LOCK:
                        IQIYI_PROXY_URL = proxy_url
                    try:
                        desktop = apply_running_iqiyi_proxy(DESKTOP_PROXY.url() if proxy_url else "")
                    except (OSError, RuntimeError):
                        desktop = {"status": "error", "message": "Đã lưu cấu hình nhưng chưa kết nối lại được iQIYI. Đóng iQIYI rồi mở lại bằng launcher."}
                self.send_json(200, {"configured": bool(proxy_url), "desktop": desktop})
                return
            if route == "/api/session":
                update_player_session(data)
                self.send_json(200, {"ok": True})
                return
            if route == "/api/discoveries/decide":
                self.send_json(200, decide_discovery(str(data.get("tvid", "")), str(data.get("action", ""))))
                return
            if route == "/api/album/add":
                album_id = str(data.get("albumId", ""))
                title = str(data.get("title", "")).strip()
                if not re.fullmatch(r"\d{1,24}", album_id) or not title or len(title) > 300:
                    raise ValueError("Phim iQIYI không hợp lệ.")
                set_library_status([{"provider": "iqiyi", "albumId": album_id, "albumTitle": title}], "accepted")
                stage = queue_album_sync(album_id, title)
                message = "Phim đã có trong thư viện." if stage == "ready" else "Đang lấy danh sách tập iQIYI…"
                self.send_json(200, {"stage": stage, "message": message})
                return
            tvid = str(data.get("tvid", ""))
            folder = LIBRARY if route in ("/api/download-all", "/api/delete-album") else None if route == "/api/album/register" else episode_dir(tvid)
            if route == "/api/register":
                provider = str(data.get("provider", "iqiyi"))
                if provider not in ("iqiyi", "youku"):
                    raise ValueError("Invalid provider")
                if provider == "iqiyi" and not re.fullmatch(r"\d{1,20}", tvid):
                    raise ValueError("Invalid iQIYI episode ID")
                if provider == "youku" and not re.fullmatch(r"yk-[A-Za-z0-9_-]{1,100}", tvid):
                    raise ValueError("Invalid Youku episode ID")
                tracks = []
                for track in (data.get("tracks", [])[:40] if provider == "iqiyi" else []):
                    try:
                        tracks.append({"lid": str(track.get("lid", "")), "name": str(track.get("name", ""))[:120],
                                       "url": normalize_track(str(track.get("url", ""))),
                                       "format": str(track.get("format", "xml"))})
                    except ValueError:
                        continue
                previous = EPISODES.get(tvid, {})
                identity = registered_episode_identity(tvid, data, previous, provider)
                album_id = identity["albumId"]
                EPISODES[tvid] = {**previous, "provider": provider, **identity,
                                  "tracks": tracks or previous.get("tracks", [])}
                folder.mkdir(parents=True, exist_ok=True)
                save_episode(tvid, EPISODES[tvid])
                if provider == "iqiyi" and album_id and library_status(EPISODES[tvid]) == "accepted":
                    queue_album_sync(album_id, episode_series_title(EPISODES[tvid]))
                self.send_json(200, {"ok": True})
                return
            if route == "/api/album/register":
                album_id = str(data.get("albumId", ""))
                if not re.fullmatch(r"\d{1,24}", album_id):
                    raise ValueError("Invalid album ID")
                album_title = str(data.get("title", ""))[:300]
                episodes = data.get("episodes", [])
                if not isinstance(episodes, list) or any(not isinstance(episode, dict) for episode in episodes[:1000]):
                    raise ValueError("Danh sách tập iQIYI không hợp lệ.")
                episodes = episodes[:1000]
                for episode in episodes:
                    episode_id = str(episode.get("tvid", ""))
                    episode_folder = episode_dir(episode_id)
                    previous = EPISODES.get(episode_id, {})
                    tracks = []
                    episode_tracks = episode.get("tracks", [])
                    if not isinstance(episode_tracks, list):
                        episode_tracks = []
                    for track in episode_tracks[:40]:
                        if not isinstance(track, dict):
                            continue
                        try:
                            tracks.append({"lid":str(track.get("lid", "")),"name":str(track.get("name", ""))[:120],
                                           "url":normalize_track(str(track.get("url", ""))),
                                           "format":str(track.get("format", "xml"))})
                        except ValueError:
                            continue
                    identity = registered_episode_identity(episode_id,
                        {**episode, "albumId": album_id, "albumTitle": album_title}, previous, "iqiyi")
                    item = {**previous, **identity,
                            "tracks":tracks or previous.get("tracks", [])}
                    EPISODES[episode_id] = item
                    episode_folder.mkdir(parents=True, exist_ok=True)
                    save_episode(episode_id, item)
                self.send_json(200,{"ok":True,"episodes":len(episodes)})
                return
            if route == "/api/capture":
                if tvid not in EPISODES:
                    raise ValueError("Episode was not registered by the player")
                provider = EPISODES[tvid].get("provider", "iqiyi")
                if EPISODES[tvid].get("downloadDisabled") and provider != "youku":
                    raise ValueError("Phụ đề tập này đã bị xóa; hãy chọn Tải gốc nếu muốn lấy lại.")
                raw = str(data.get("raw", ""))
                if len(raw.encode("utf-8")) > 15_000_000:
                    raise ValueError("Subtitle file is too large")
                fmt = str(data.get("format", "xml"))
                cues = parse_source(raw, fmt)
                if provider == "youku" and EPISODES[tvid].pop("downloadDisabled", None):
                    save_episode(tvid, EPISODES[tvid])
                capture_source(tvid, cues, append=bool(data.get("append")) and provider == "youku")
                self.send_json(200, {"ok": True, "cues": len(cues)})
                return
            if route == "/api/delete-subtitle":
                if tvid not in EPISODES:
                    raise ValueError("Không tìm thấy tập này trong thư viện.")
                lock = episode_lock(tvid)
                with LOCK_GUARD:
                    if DOWNLOAD_PROGRESS.get(tvid, {}).get("stage") in ("queued", "downloading"):
                        raise EpisodeBusy("Tập đang tải phụ đề; hãy thử xóa lại sau khi tải xong.")
                    if not lock.acquire(blocking=False):
                        raise EpisodeBusy("Tập đang được xử lý; hãy thử xóa lại sau khi hoàn tất.")
                    try:
                        folder = episode_dir(tvid)
                        for name in ("source.srt", "translations.json", "translated.srt", "review-progress.json", "review-audit.json", "context-profile.json", "translation-job.json"):
                            (folder / name).unlink(missing_ok=True)
                        shutil.rmtree(folder / "history", ignore_errors=True)
                        EPISODES[tvid]["downloadDisabled"] = True
                        EPISODES[tvid].pop("downloadProgress", None)
                        save_episode(tvid, EPISODES[tvid])
                        DOWNLOAD_PROGRESS.pop(tvid, None)
                    finally:
                        lock.release()
                self.send_json(200, {"message": "Đã xóa phụ đề gốc và lịch sử của tập."})
                return
            if route == "/api/delete-album":
                provider = str(data.get("provider", ""))
                if provider not in ("iqiyi", "youku"):
                    raise ValueError("Invalid provider")
                album_id = str(data.get("albumId", ""))
                title = str(data.get("seriesTitle", ""))[:500].casefold().strip()
                if album_id and not re.fullmatch(r"(?:\d{1,24}|yk-[A-Za-z0-9_-]{1,100})", album_id):
                    raise ValueError("Invalid album ID")
                with LOCK_GUARD:
                    if not (album_id and album_id != "0") and not title:
                        raise ValueError("Invalid movie identity")
                    ids = album_episode_ids(album_id, provider, title)
                    if not ids:
                        raise ValueError("Không tìm thấy phim này trong thư viện.")
                    album_ids = {album_id} | {str(EPISODES[key].get("albumId", "")) for key in ids}
                    if provider == "iqiyi" and any(ALBUM_LISTS.get(key, {}).get("stage") == "loading" for key in album_ids):
                        raise EpisodeBusy("Phim đang đồng bộ danh sách tập; hãy thử xóa lại sau khi đồng bộ xong.")
                    if any(DOWNLOAD_PROGRESS.get(key, {}).get("stage") in ("queued", "downloading") for key in ids):
                        raise EpisodeBusy("Phim có tập đang tải phụ đề; hãy thử xóa lại sau khi tải xong.")
                    locks = [EPISODE_LOCKS.setdefault(key, threading.Lock()) for key in ids]
                    acquired = []
                    staged = []
                    try:
                        for lock in locks:
                            if not lock.acquire(blocking=False):
                                raise EpisodeBusy("Phim có tập đang được xử lý; hãy thử xóa lại sau khi hoàn tất.")
                            acquired.append(lock)
                        staging = LIBRARY / (".deleted-" + secrets.token_hex(8))
                        staging.mkdir(parents=True)
                        try:
                            for key in ids:
                                source = episode_dir(key)
                                if source.exists():
                                    target = staging / key
                                    source.replace(target)
                                    staged.append((target, source))
                            set_library_status([EPISODES[key] for key in ids], "dismissed")
                        except OSError:
                            for target, source in reversed(staged):
                                if target.exists():
                                    target.replace(source)
                            shutil.rmtree(staging, ignore_errors=True)
                            raise
                        for key in ids:
                            EPISODES.pop(key, None)
                            DOWNLOAD_PROGRESS.pop(key, None)
                        ALBUM_LISTS.pop(album_id, None)
                        shutil.rmtree(staging, ignore_errors=True)
                    finally:
                        for lock in reversed(acquired):
                            lock.release()
                self.send_json(200, {"message": f"Đã xóa phim cùng {len(ids)} tập và toàn bộ phụ đề gốc đã lưu."})
                return
            folder.mkdir(parents=True, exist_ok=True)
            if route == "/api/download":
                queued = queue_subtitle_downloads([tvid], retry=True)
                self.send_json(200, {"message": "Đã xếp lịch tải phụ đề." if queued else "Phụ đề đã tải hoặc đang chờ tải."})
            elif route == "/api/download-all":
                album_id = str(data.get("albumId", ""))
                if not re.fullmatch(r"\d{1,24}", album_id):
                    raise ValueError("Invalid album ID")
                ids = album_episode_ids(album_id, "iqiyi")
                queued = queue_subtitle_downloads(ids, retry=True)
                self.send_json(200, {"message": f"Đã xếp lịch tải phụ đề cho {queued} tập."})
            else:
                self.send_error(404)
        except EpisodeBusy as exc:
            self.send_json(409, {"error": str(exc)})
        except (ValueError, KeyError, OSError, ET.ParseError) as exc:
            self.send_json(400, {"error": str(exc)[:500]})
        except Exception as exc:
            message = str(exc)
            action = "Việt hóa giao diện" if route == "/api/localize-remaining" else "Tải phụ đề"
            message = f"{action} thất bại: {type(exc).__name__}: {message}"
            self.send_json(502, {"error": message[:500]})


class SubtitleHTTPServer(ThreadingHTTPServer):
    # Windows SO_REUSEADDR lets separate managers serve conflicting proxy state.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve():
    with SubtitleHTTPServer(("127.0.0.1", PORT), Handler) as server:
        load_library()
        server.api_token = api_token(ROOT)
        atomic_write(ROOT / "ext" / "proxy-token.json", json.dumps({"token": browser_proxy_token(server.api_token),
                     "sessionToken": browser_session_token(server.api_token), "playerToken": player_token(server.api_token)}))
        try:
            server.serve_forever()
        finally:
            DESKTOP_PROXY.close()
            IQCOM_SESSION.close()


if __name__ == "__main__":
    serve()
