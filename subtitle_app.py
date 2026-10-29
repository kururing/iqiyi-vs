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
import app_integration
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
from iqcom_audio import IqcomAudio, byte_range
from proxy_support import DesktopProxyRelay
from launcher import apply_running_iqiyi_proxy, ensure_watcher
from iqcom_requests import PUBLIC_METADATA, RequestCache, pooled_open, read_response, singleflight
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
ALBUM_LIST_POOL = ThreadPoolExecutor(max_workers=3, thread_name_prefix="album-list")
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
# iq.com's country catalog is independent of the requested display language.
IQCOM_CATALOG_REGION = "vn"
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
        state = dict(APP_LOCALIZATION_STATE)
    state["installed"] = app_integration.installed(ROOT)
    return state


def _localization_command(action: str, elevated: bool = False) -> subprocess.CompletedProcess:
    args = app_integration.installer_args(ROOT, restore=action == "restore")
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
            if action in ("apply", "repair"):
                ensure_watcher()
            message = ("Đã khôi phục giao diện gốc. Hãy đóng rồi mở lại iQIYI để nạp thay đổi."
                       if action == "restore" else
                       "Đã cập nhật tiếng Việt. Đóng rồi mở lại iQIYI để nạp thay đổi." if action == "repair" else
                       "Đã cài đặt. Từ lần sau, mở iQIYI bình thường sẽ tự chạy dịch vụ quản lý phụ đề.")
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
    if action not in ("apply", "repair", "restore"):
        raise ValueError("Thao tác giao diện không hợp lệ.")
    with APP_LOCALIZATION_LOCK:
        if APP_LOCALIZATION_STATE.get("status") == "running":
            raise RuntimeError("Một thao tác iQIYI đang chạy.")
        if action == "apply" and app_integration.installed(ROOT):
            return {**APP_LOCALIZATION_STATE, "status":"done", "installed":True,
                    "message":"Đã cài đặt. Chỉ cần mở iQIYI bình thường để dùng quản lý phụ đề."}
        APP_LOCALIZATION_STATE.update(status="running", action=action,
                                      message=("Đang khôi phục giao diện tiếng Trung…" if action == "restore"
                                               else "Đang cài tích hợp iQIYI…"),
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
            payload = json.loads(read_response(response, 1_000_000))
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
        offset, page_size = 0, 20
        while offset < 1000:
            for attempt in range(3):
                # Keep the offset when shrinking a failed page, so no episodes are skipped.
                page = offset // page_size + 1
                url = ("https://pcw-api.iqiyi.com/albums/album/avlistinfo"
                       f"?aid={album_id}&page={page}&size={page_size}")
                try:
                    payload = public_iqiyi_json(url)
                    break
                except (OSError, ValueError, EOFError):
                    if attempt == 2:
                        raise
                    page_size = max(5, page_size // 2)
                    time.sleep(0.5 * (attempt + 1))
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
            offset += page_size
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
    except (OSError, ValueError, TypeError, AttributeError, EOFError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(exc, (json.JSONDecodeError, UnicodeError, EOFError)):
            message = "Dữ liệu danh sách tập nhận từ iQIYI bị thiếu hoặc không hợp lệ"
        elif isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            message = "iQIYI phản hồi quá chậm khi tải danh sách tập"
        else:
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
            ALBUM_LIST_POOL.submit(sync_album_list, album_id, title)


def queue_album_sync(album_id: str, title: str) -> str:
    with LOCK_GUARD:
        state = ALBUM_LISTS.get(album_id, {})
        if state.get("stage") in ("loading", "ready"):
            return state["stage"]
        ALBUM_LISTS[album_id] = {"stage": "loading"}
    ALBUM_LIST_POOL.submit(sync_album_list, album_id, title)
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
            "albumCoverUrl": series_cover_url(item),
            "originalTitle": title, "episodes": 0, "discoveredAt": item.get("discoveredAt", 0)})
        group["episodes"] += 1
    return sorted(groups.values(), key=lambda row: -float(row["discoveredAt"] or 0))


def decide_discovery(tvid: str, action: str) -> dict:
    if action not in ("accept", "dismiss") or tvid not in EPISODES:
        raise ValueError("Thông báo phim không hợp lệ.")
    with LOCK_GUARD:
        item = EPISODES[tvid]
        ids = album_episode_ids(str(item.get("albumId", "")), episode_series_title(item)) or [tvid]
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
        if not folder.is_dir() or not manifest.is_file() or not re.fullmatch(r"\d{1,20}", folder.name):
            continue
        try:
            item = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(item, dict):
                continue
            item.pop("albumTitleVi", None)
            if item.get("provider", "iqiyi") != "iqiyi":
                continue
            item["provider"] = "iqiyi"
            item["tvid"] = folder.name
            if item.get("albumId") and not re.fullmatch(r"\d{1,24}", str(item["albumId"])):
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
            raw = read_public_metadata(response)
        try:
            rows = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError):
            raise ValueError("Dịch nhanh nhận dữ liệu bị thiếu hoặc không hợp lệ; hãy thử lại.") from None
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
    return read_response(response, 4_000_000)


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
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeError):
        raise OSError("Metadata iQIYI nhận về bị thiếu hoặc không hợp lệ; hãy thử lại.") from None
    if not isinstance(payload, dict):
        raise ValueError("Metadata tên phim iQIYI không hợp lệ.")
    return payload


def movie_cover_url(value) -> str:
    """Only use public iQIYI artwork, over HTTPS."""
    if not isinstance(value, str) or len(value) > 2048 or re.search(r'[\s<>"\x00-\x1f]', value):
        return ""
    try:
        parsed = urlsplit("https:" + value if value.startswith("//") else value)
        host = parsed.hostname or ""
        if (parsed.scheme in ("http", "https") and
                (host == "iqiyipic.com" or host.endswith(".iqiyipic.com")) and
                not parsed.username and not parsed.password and parsed.port in (None, 80, 443)):
            return parsed._replace(scheme="https", netloc=host).geturl()
    except ValueError:
        pass
    return ""


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
        if cached and cached[0] > time.monotonic() and "coverUrl" in cached[1]:
            return dict(cached[1])

    def clean(value) -> str:
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]*>", "", str(value or "")))).strip()

    def title_key(value) -> str:
        return re.sub(r"[\s《》「」『』【】]", "", clean(value)).casefold()

    request_json = public_iqiyi_json

    result = {"title": "", "sourceTitle": "", "coverUrl": ""}
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
        artwork = domestic if kind == "album" else {}
        if kind == "video" and re.fullmatch(r"\d{1,24}", str(domestic.get("albumId") or "")):
            try:
                payload = request_json(f"https://pcw-api.iqiyi.com/album/album/baseinfo/{domestic['albumId']}")
                if payload.get("code") == "A00000" and isinstance(payload.get("data"), dict):
                    artwork = payload["data"]
            except (OSError, ValueError):
                pass
        result["coverUrl"] = movie_cover_url(artwork.get("imageUrl"))
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
                params = {"platformId": 4, "langCode": "zh_cn", "modeCode": IQCOM_CATALOG_REGION, "deviceId": "ew"}
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
                          "modeCode": IQCOM_CATALOG_REGION, "langCode": "zh_cn", "deviceId": "ew",
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
            if not candidates:
                # A searchable album is not required: some catalogs expose only its direct ID.
                album_id = str(domestic.get("albumId") or identifier)
                params = {"platformId": 4, "langCode": "zh_cn", "modeCode": IQCOM_CATALOG_REGION, "deviceId": "ew"}
                payload = request_json(f"https://pcw-api.iq.com/api/epgInfo/{album_id}?" + urlencode(params))
                data = payload.get("data")
                if (payload.get("code") in (0, "0") and isinstance(data, dict) and
                        str(data.get("qipuId")) == album_id and
                        title_key(data.get("albumName") or data.get("name")) == title_key(chinese) and
                        (not domestic.get("channelId") or str(data.get("chnId")) == str(domestic["channelId"])) and
                        (not year or str(data.get("publishTime") or "")[:4] == year)):
                    candidates[album_id] = data
            if len(candidates) == 1:
                qipu_id = next(iter(candidates))
                with INTERNATIONAL_TITLE_LOCK:
                    INTERNATIONAL_ALBUM_IDS[cache_key] = (time.monotonic() + 7 * 86400, qipu_id)
                    result["globalAlbumId"] = qipu_id
                params = {"platformId": 4, "langCode": "vi_vn", "modeCode": IQCOM_CATALOG_REGION,
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


@singleflight
def international_movie_title_by_name(name: str) -> dict:
    """Resolve title-only cards using one exact, verified catalog album."""
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    if (not name or len(name) > 200 or not re.search(r"[\u3400-\u9fff]", name) or
            re.search(r"[\x00-\x1f<>]", name)):
        raise ValueError("Tên phim iQIYI không hợp lệ.")
    result = {"title": "", "sourceTitle": name}
    key = lambda value: re.sub(r"[\s《》「」『』【】]", "", str(value or "")).lower()
    params = {"platformId": 3, "modeCode": IQCOM_CATALOG_REGION, "langCode": "zh_cn", "deviceId": "ew",
              "key": name, "pn": 1, "ps": 20, "intentPn": 1, "intentPs": 0, "chnId": 0,
              "dataType": "1;should,2;should", "isVip": 0}
    try:
        payload = public_iqiyi_json("https://pcw-api.iq.com/api/search2?" + urlencode(params))
        rows = payload.get("data", {}).get("epg", []) if payload.get("code") in (0, "0") else []
        candidates = {str(row.get("qipuId") or row.get("albumId") or ""): row for row in rows
                      if isinstance(row, dict) and row.get("type") in (0, 1) and
                      re.fullmatch(r"\d{8,24}", str(row.get("qipuId") or row.get("albumId") or "")) and
                      key(row.get("albumName") or row.get("name")) == key(name)}
        if len(candidates) != 1:
            return result
        identifier, row = next(iter(candidates.items()))
        params = {"platformId": 4, "modeCode": IQCOM_CATALOG_REGION, "langCode": "zh_cn", "deviceId": "ew"}

        def album():
            payload = public_iqiyi_json(f"https://pcw-api.iq.com/api/epgInfo/{identifier}?" + urlencode(params))
            data = payload.get("data")
            return data if (payload.get("code") in (0, "0") and isinstance(data, dict) and
                            str(data.get("qipuId")) == identifier) else {}

        original = album()
        if (key(original.get("albumName") or original.get("name")) != key(name) or
                (row.get("chnId") and str(original.get("chnId")) != str(row["chnId"])) or
                (row.get("publishTime") and str(original.get("publishTime") or "")[:4] != str(row["publishTime"])[:4])):
            return result
        params["langCode"] = "vi_vn"
        localized = album()
        title = re.sub(r"<[^>]*>", "", str(localized.get("albumName") or localized.get("name") or "")).strip()
        if title and len(title) <= 200 and not re.search(r"[\u3400-\u9fff]", title) and localized.get("matchedLang", 15) == 15:
            cache_international_cast(original, localized)
            result.update(title=title, globalAlbumId=identifier)
    except (OSError, ValueError, TypeError, AttributeError):
        result["retryAfterMs"] = 10000
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
                  "modeCode": IQCOM_CATALOG_REGION, "langCode": "vi_vn", "deviceId": "ew"}

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
    try:
        text = raw.decode("utf-8")
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', text, re.S)
        payload = json.loads(match[1]) if match else None
    except (json.JSONDecodeError, UnicodeError):
        raise OSError("Metadata iq.com nhận về bị thiếu hoặc không hợp lệ; hãy thử lại.") from None
    if not match:
        raise ValueError("iq.com chưa trả metadata tập phim.")
    return payload


@singleflight
def iqcom_album_metadata(global_album: str, *, refresh: bool = False) -> tuple[dict, dict, dict | None]:
    """Cache public catalog metadata for five minutes, never signed playback URLs."""
    with IQCOM_ALBUM_LOCK:
        cached = IQCOM_ALBUM_CACHE.get(global_album)
        if not refresh and cached and cached[0] > time.monotonic():
            return cached[1], cached[2], None
    params = urlencode({"platformId": 4, "langCode": "vi_vn", "modeCode": IQCOM_CATALOG_REGION, "deviceId": "ew"})
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
        raw = read_response(response, 4_000_000)
    if len(raw) > 4_000_000:
        raise ValueError("Tệp phụ đề iq.com quá lớn.")
    shift = (domestic_duration - global_duration) * 1000
    try:
        xml, count = official_subtitle_xml(raw.decode("utf-8-sig"), fmt, shift, domestic_duration * 1000)
    except (ValueError, ET.ParseError):
        raise OSError("Phụ đề iq.com nhận về bị thiếu hoặc không hợp lệ; hãy thử lại.") from None
    return {"xml": xml, "shiftMs": shift, "internationalTvid": global_tvid, "cues": count}


def resolve_official_audio(tvid: str):
    domestic = public_iqiyi_json(f"https://pcw-api.iqiyi.com/video/video/baseinfo/{tvid}").get("data", {})
    if str(domestic.get("tvId")) != tvid or not int(domestic.get("order") or 0):
        raise ValueError("Chưa xác nhận được phim và số tập đang phát.")
    album_id, order = str(domestic.get("albumId") or ""), int(domestic["order"])
    international_movie_title(album_id)
    with INTERNATIONAL_TITLE_LOCK:
        mapping = INTERNATIONAL_ALBUM_IDS.get(album_id)
    if not mapping or mapping[0] <= time.monotonic():
        raise ValueError("Chưa tìm được phim khớp chính xác trên iq.com.")
    params = {"platformId": 4, "langCode": "zh_cn", "modeCode": IQCOM_CATALOG_REGION, "deviceId": "ew"}

    def catalog(identifier):
        data = public_iqiyi_json(f"https://pcw-api.iq.com/api/epgInfo/{identifier}?" + urlencode(params)).get("data", {})
        if str(data.get("qipuId")) != identifier:
            raise ValueError("Metadata phim âm thanh iq.com không khớp.")
        return data

    original = catalog(mapping[1])
    name = str(original.get("albumName") or original.get("name") or "").strip()

    def vietnamese(row):
        return any(isinstance(audio, dict) and str(audio.get("id")) == "161" for audio in row.get("audioInfoList", []))

    selected = original if vietnamese(original) else None
    if selected is None:
        search = {"key": name, "pn": 1, "ps": 20, "intentPn": 1, "intentPs": 0, "chnId": 0,
                  "dataType": "1;should,2;should", "platformId": 3, "modeCode": IQCOM_CATALOG_REGION,
                  "langCode": "zh_cn", "deviceId": "ew", "isVip": 0}
        rows = public_iqiyi_json("https://pcw-api.iq.com/api/search2?" + urlencode(search)).get("data", {}).get("epg", [])
        candidates = {}
        for row in rows:
            title = str(row.get("name") or "").strip()
            base = re.sub(r"[（(]?\s*越南(?:语|語)(?:配音)?版\s*[）)]?$", "", title).strip()
            identifier = str(row.get("qipuId") or "")
            if (base != name or title == base or row.get("type") not in (0, 1) or
                    not re.fullmatch(r"\d{8,24}", identifier)):
                continue
            candidate = catalog(identifier)
            # Exact original title, release year, channel and episode count; never a fuzzy title match.
            candidate_base = re.sub(r"[（(]?\s*越南(?:语|語)(?:配音)?版\s*[）)]?$", "",
                                    str(candidate.get("name") or candidate.get("albumName") or "")).strip()
            if (candidate_base == name and vietnamese(candidate) and
                    str(candidate.get("publishTime", ""))[:4] == str(original.get("publishTime", ""))[:4] and
                    candidate.get("chnId") == original.get("chnId") and
                    candidate.get("total") == original.get("total")):
                candidates[identifier] = candidate
        if len(candidates) != 1:
            raise ValueError("Chưa tìm được duy nhất một bản lồng tiếng/thuyết minh Việt khớp phim trên iq.com.")
        selected = next(iter(candidates.values()))
    global_album = str(selected["qipuId"])
    album, lists, page = iqcom_album_metadata(global_album)
    episodes = {str(row.get("tvId") or row.get("qipuId") or ""): row
                for rows in lists.values() for row in rows
                if str(row.get("albumId")) == global_album and str(row.get("order")) == str(order)
                and str(row.get("contentType")) == "1"}
    if len(episodes) != 1:
        raise ValueError("Chưa tìm được đúng tập của bản âm thanh Việt.")
    global_tvid, episode = next(iter(episodes.items()))
    if not re.fullmatch(r"\d{8,24}", global_tvid):
        raise ValueError("Mã tập âm thanh Việt không hợp lệ.")
    suffix = str(episode.get("playLocSuffix") or "")
    if page is None or str(album.get("defaultTvId")) != global_tvid:
        page = public_iqcom_page(suffix)
    data = page.get("props", {}).get("initialProps", {}).get("pageProps", {}).get("prePlayerData", {}).get("dash", {}).get("data", {})

    def track_for(payload):
        if (str(payload.get("tvid")) != global_tvid or str(payload.get("aid")) != global_album or
                (payload.get("ctl") or {}).get("boss_not_pass")):
            return None
        tracks = [row for row in (payload.get("program") or {}).get("audio", [])
                  if str(row.get("lid")) == "161" and row.get("cf") == "aac" and row.get("ff") == "amp4" and row.get("fs")]
        return next((row for row in tracks if row.get("_selected")), tracks[0] if tracks else None)

    track = track_for(data)
    if track is None and IQCOM_SESSION.saved:
        data = IQCOM_SESSION.dash(suffix, global_tvid, audio=True)
        track = track_for(data)
    if track is None:
        raise ValueError("iq.com chưa cấp âm thanh Việt cho tập này. Kiểm tra phiên iq.com, quyền xem tập và khu vực.")
    global_duration, domestic_duration = float(track.get("duration") or 0), float(domestic.get("durationSec") or 0)
    if not 0 < global_duration <= 86400 or not 0 < domestic_duration <= 86400:
        raise ValueError("Chưa có thời lượng để đồng bộ âm thanh Việt.")
    return data, track, {"internationalTvid": global_tvid, "duration": global_duration,
                         "shiftSeconds": domestic_duration - global_duration, "episode": order}


IQCOM_AUDIO = IqcomAudio(ROOT / ".local" / "iqcom-audio.json", resolve_official_audio, lambda: IQCOM_SESSION.version)


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
    except (OSError, UnicodeError, ET.ParseError):
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
        result["title"] = exact[0]["title"]
        return result
    params = {"key": keyword, "pn": 1, "ps": 20, "intentPn": 1, "intentPs": 0,
              "chnId": 0, "dataType": "1;should,2;should", "platformId": 3,
              "modeCode": IQCOM_CATALOG_REGION, "langCode": "vi_vn", "deviceId": "ew", "isVip": 0}
    try:
        payload = public_iqiyi_json("https://pcw-api.iq.com/api/search2?" + urlencode(params))
        rows = (payload.get("data") or {}).get("epg", [])
        matches = {str(row.get("qipuId") or row.get("albumId") or ""): row for row in rows
                   if isinstance(row, dict) and row.get("type") in (0, 1) and
                   isinstance(row.get("name"), str) and not re.search(r"[\u3400-\u9fff\uf900-\ufaff]", row["name"]) and score(row["name"])}
        for identifier, row in sorted(matches.items(), key=lambda pair: score(pair[1]["name"]), reverse=True)[:5]:
            if not re.fullmatch(r"\d{8,24}", identifier):
                continue
            params = {"platformId": 4, "langCode": "zh_cn", "modeCode": IQCOM_CATALOG_REGION, "deviceId": "ew"}
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
        result["title"] = exact[0]["title"]
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
            raw = read_response(response, 8_000_000)
        if len(raw) > 8_000_000:
            raise ValueError("Kết quả tìm kiếm iQIYI quá lớn; thử tìm từ khóa ngắn, cụ thể hơn.")
        payload = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ValueError(f"API tìm kiếm iQIYI trả HTTP {exc.code}.") from None
    except OSError:
        raise ValueError("Không kết nối được API tìm kiếm iQIYI.") from None
    except (json.JSONDecodeError, UnicodeError):
        raise ValueError("Kết quả tìm kiếm iQIYI nhận về bị thiếu hoặc không hợp lệ; hãy thử lại.") from None
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
            payload = json.loads(read_response(response, 15_000_000))
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
        try:
            with iqiyi_open(url, timeout=20) as response:
                raw = read_response(response, 15_000_000)
        except OSError:
            raise ValueError("Kết nối tải phụ đề gốc bị gián đoạn; hãy thử tải lại.") from None
        if len(raw) > 15_000_000:
            raise ValueError("Subtitle file is too large")
        try:
            cues = parse_source(raw.decode("utf-8-sig"), track["format"])
        except (ValueError, ET.ParseError):
            raise OSError("Phụ đề gốc nhận về bị thiếu hoặc không hợp lệ; hãy thử lại.") from None
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
    if not re.fullmatch(r"\d{1,20}", str(tvid)):
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


def album_episode_ids(album_id: str, title: str = "") -> list[str]:
    rows = [(key, item) for key, item in list(EPISODES.items())
            if item.get("provider", "iqiyi") == "iqiyi"]
    if album_id and album_id != "0":
        return sorted(key for key, item in rows if str(item.get("albumId", "")) == album_id)
    title = title.casefold().strip()
    return sorted(key for key, item in rows if
                  title and episode_series_title(item).casefold() == title and
                  str(item.get("albumId") or "0") == "0")


def registered_episode_identity(tvid: str, data: dict, previous: dict) -> dict:
    # Track-only responses must not erase metadata from the page or album list.
    identity = {key: str(data.get(key) or previous.get(key) or "").strip()[:limit]
                for key, limit in (("title", 500), ("albumId", 100), ("albumTitle", 300))}
    if identity["albumId"] and not re.fullmatch(r"\d{1,24}", identity["albumId"]):
        raise ValueError("Invalid album ID")
    try:
        identity["order"] = max(0, min(int(data.get("order") or previous.get("order") or 0), 100000))
    except (TypeError, ValueError):
        raise ValueError("Invalid episode order") from None
    if not identity["title"] or not identity["albumId"] or not identity["order"]:
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


def international_series_metadata(item: dict) -> dict:
    identifier = next((str(value) for value in (item.get("albumId"), item.get("tvid"))
                       if re.fullmatch(r"\d{8,24}", str(value or ""))), "")
    if not identifier:
        return {}
    with INTERNATIONAL_TITLE_LOCK:
        cached = INTERNATIONAL_TITLE_CACHE.get(identifier)
        current = cached and cached[0] > time.monotonic()
        if (not current or "coverUrl" not in cached[1]) and identifier not in INTERNATIONAL_TITLE_PENDING:
            INTERNATIONAL_TITLE_PENDING.add(identifier)
            TITLE_LOOKUP_POOL.submit(_load_international_series_title, identifier)
        return dict(cached[1]) if current else {}


def vietnamese_series_title(item: dict) -> str:
    return international_series_metadata(item).get("title", "")


def series_cover_url(item: dict) -> str:
    return movie_cover_url(international_series_metadata(item).get("coverUrl"))


def official_series_title(item: dict) -> str:
    """Use the verified Vietnamese title from iq.com metadata."""
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


def capture_source(tvid: str, cues: list) -> None:
    lock = episode_lock(tvid)
    if not lock.acquire(blocking=False):
        raise EpisodeBusy("Tập này đang được xử lý; thử lưu phụ đề lại sau.")
    try:
        folder = episode_dir(tvid)
        path = folder / "source.srt"
        current = path.read_text(encoding="utf-8-sig") if path.exists() else ""
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
<title>iQIYI – Quản lý phụ đề</title>
<link rel="icon" href="/favicon.ico" type="image/x-icon">
<style>
*{box-sizing:border-box}
:root{color-scheme:dark;--bg:#101214;--panel:#191c20;--panel2:#23272b;--line:#2b3035;--muted:#a9afb6;--text:#f0f3f5;--blue:#00dc72;--focus:#00dc72}
[hidden]{display:none!important}
::-webkit-scrollbar{width:8px;height:8px;background:transparent}
::-webkit-scrollbar-track,::-webkit-scrollbar-corner{background:transparent}
::-webkit-scrollbar-thumb{background:#485159;border:2px solid transparent;background-clip:padding-box;border-radius:8px}
::-webkit-scrollbar-thumb:hover{background-color:#68747f}
::-webkit-scrollbar-button{display:none;width:0;height:0}
@supports not selector(::-webkit-scrollbar){*{scrollbar-width:thin;scrollbar-color:#485159 transparent}}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,sans-serif}
html{scroll-padding-top:100px}main{max-width:1280px;margin:36px auto;padding:0 32px}
button,input,select{font:inherit}
button{min-height:40px;border:1px solid transparent;border-radius:7px;padding:8px 13px;background:var(--blue);color:#052b19;cursor:pointer;font-size:14px;font-weight:600;white-space:nowrap}
button.secondary{background:transparent;border-color:var(--line);color:var(--text)}
button.danger{background:transparent;border-color:#644049;color:#ffb7bd}
button:hover:not(:disabled){filter:brightness(1.15)}button.secondary:hover:not(:disabled){background:var(--panel2)}
button:disabled{opacity:1;cursor:not-allowed;background:var(--panel2);border-color:var(--line);color:var(--muted)}
button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible,a:focus-visible{outline:2px solid var(--focus);outline-offset:3px}
input,select{min-height:44px;min-width:0;border:1px solid var(--line);border-radius:7px;padding:9px 12px;background:var(--bg);color:var(--text)}
input::placeholder{color:var(--muted)}
h1{font-size:24px;line-height:1.3;font-weight:650;margin:0}h3{font-size:16px;font-weight:600}
.hint,.settingsHint{color:var(--muted)}.settingsHint{font-size:13px;line-height:1.6}
.integrationPrompt{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:28px;padding:18px 20px;border:1px solid #00dc7240;border-radius:10px;background:#00dc7209}.integrationPrompt p{margin:4px 0 0;color:var(--muted);font-size:13px}.integrationPrompt button{flex-shrink:0}
@media(max-width:760px){.integrationPrompt{align-items:flex-start;flex-direction:column;gap:12px}}
.srOnly{position:absolute!important;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap;border:0}
.pageTop{position:sticky;top:0;z-index:20;background:#171a1df5;border-bottom:1px solid #ffffff0b;backdrop-filter:blur(16px)}
.topbarInner{max-width:1520px;min-height:84px;margin:auto;padding:0 32px;display:flex;align-items:center;gap:30px}
.managerBrand{display:flex;align-items:center;flex:0 0 auto;text-decoration:none}.managerBrand svg{display:block;width:104px;height:auto}
.primaryNav{display:flex;align-self:stretch;flex:0 0 auto}.primaryNav a{position:relative;display:flex;align-items:center;color:var(--text);text-decoration:none;font-size:15px;font-weight:650;white-space:nowrap}.primaryNav a[aria-current=page]{color:var(--blue)}.primaryNav a[aria-current=page]:after{content:"";position:absolute;bottom:0;left:0;right:0;height:3px;border-radius:3px 3px 0 0;background:var(--blue)}
.topActions{display:flex;align-items:center;gap:8px;flex:0 0 auto}.topActions button{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;border-radius:22px}.topActions .iconAction{width:44px;min-width:44px;padding:0;border-color:transparent;color:#c3c8ce;background:transparent}.topActions .iconAction:hover{color:var(--blue);background:#ffffff09}.topActions svg,.librarySearch>svg{width:20px;height:20px;flex-shrink:0}.topActions #addMovieButton{padding:9px 18px;margin-left:8px}
#notificationsButton{position:relative}#notificationsCount{position:absolute;top:1px;right:0;min-width:16px;padding:1px 4px;border-radius:9px;background:var(--blue);color:#052b19;font-size:10px;line-height:14px}
.libraryHeading{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:24px}.libraryHeading h1{font-size:25px;font-weight:650;letter-spacing:-.4px}.libraryHeading p{margin:5px 0 0;color:var(--muted);font-size:13px}.libraryHeading .secondary{border-radius:20px;color:#c4c9ce;font-size:13px;min-height:38px;padding:7px 15px}
.librarySearch{display:flex;align-items:center;gap:10px;flex:1;min-width:120px;max-width:440px;margin-left:auto;border:1px solid #ffffff0d;border-radius:24px;padding:0 14px;background:#25292e;color:#9fa6ae;transition:border-color .15s ease}.librarySearch:focus-within{border-color:var(--blue)}.librarySearch input{width:100%;min-width:0;min-height:42px;border:0;padding:9px 0;background:transparent;font-size:13px}.librarySearch input:focus-visible{outline:0}.librarySearch button{width:28px;height:28px;min-height:28px;border:0;border-radius:50%;padding:0;background:transparent;color:var(--muted);font-size:20px}
#librarySearchCount{margin:8px 0}#librarySearchCount:empty,#status:empty,#appLocalizationStatus:empty{display:none}
#status{color:#bdcfff;margin:12px 0}.platformSection{margin:0 0 32px}.platformEmpty{padding:32px 16px;text-align:center;color:var(--muted);border:1px dashed var(--line);border-radius:8px}
.album{border-bottom:1px solid var(--line)}.albumHead{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:18px 0}
.albumHeading{display:flex;align-items:center;gap:16px;min-width:0;flex:1;padding:0;border:0;background:transparent;color:var(--text);text-align:left;font:inherit;white-space:normal}.albumHeading:hover:not(:disabled){filter:none}.albumHeading:hover .seriesTitle{color:var(--blue)}.albumChevron{width:18px;height:18px;flex-shrink:0;color:var(--muted)}.albumHeading[aria-expanded=true] .albumChevron{transform:rotate(180deg)}.albumCover{position:relative;flex:0 0 72px;width:72px;height:108px;overflow:hidden;border:1px solid var(--line);border-radius:7px;background:var(--panel2);color:var(--muted);display:grid;place-items:center}.albumCover svg{width:26px;height:26px}.albumCover img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.albumIdentity{min-width:0;flex:1}.albumIdentity>span{display:block}.seriesTitle{font-size:16px;font-weight:600;line-height:1.5;overflow-wrap:anywhere}.originalTitle{color:var(--muted);font-size:13px;margin-top:2px}.albumSummary{color:var(--muted);font-size:13px;margin-top:4px}.albumSummary strong{font-weight:400}
.albumTools,.episodeActions{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.albumTools button,.episodeActions button{font-size:13px;min-height:36px;padding:7px 11px}
.menu{position:relative}.menu summary{list-style:none;cursor:pointer;min-width:36px;min-height:36px;display:inline-flex;align-items:center;justify-content:center;border:1px solid var(--line);border-radius:7px;background:transparent;padding:6px 10px;color:var(--text)}.menu summary::-webkit-details-marker{display:none}
.moreMenu{display:none;position:absolute;right:0;top:calc(100% + 6px);z-index:5;min-width:180px;max-width:calc(100vw - 32px);padding:6px;background:var(--panel);border:1px solid var(--line);border-radius:8px;box-shadow:0 12px 24px #0005}
.menu[open] .moreMenu{display:block}.moreMenu button{display:block;text-align:left;width:100%;border:0;background:transparent;color:var(--text);font-weight:400;white-space:normal;overflow-wrap:anywhere}.moreMenu button.danger{color:#ffb7bd}.moreMenu button:hover{background:var(--panel2)}
.episodeList{background:var(--panel);padding:4px 16px 12px;border-radius:8px;margin-bottom:16px}
.episodeLegendHelp{margin-top:8px;color:var(--muted);font-size:12px}.episodeLegendHelp>summary{padding:4px 0;cursor:pointer}.episodeLegend{display:flex;gap:12px;flex-wrap:wrap;padding:6px 0;font-size:12px;color:var(--muted)}.legendItem{display:flex;align-items:center;gap:5px}
:is(.episodeChip,.legendDot,.statusBadge){--state-bg:#242831;--state-border:#4b5260;--state-color:#c7cdd8}
:is(.episodeChip,.legendDot,.statusBadge).complete{--state-bg:#143d2b;--state-border:#2e8c5c;--state-color:#b4f5cf}
:is(.episodeChip,.legendDot,.statusBadge).sourceReady{--state-bg:#15354d;--state-border:#327da8;--state-color:#bbdffc}
:is(.episodeChip,.legendDot,.statusBadge).active{--state-bg:#392557;--state-border:#8b5cc7;--state-color:#e1c5ff}
:is(.episodeChip,.legendDot,.statusBadge).error{--state-bg:#4b202a;--state-border:#ba5265;--state-color:#ffd0d6}
:is(.episodeChip,.legendDot,.statusBadge).access{--state-bg:#493514;--state-border:#ab8133;--state-color:#ffe2a0}
.legendDot{width:8px;height:8px;border-radius:50%;background:var(--state-border)}
.episodeGrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(64px,1fr));gap:8px;padding:12px 0 16px;border-bottom:1px solid var(--line)}
.episodeChip{min-height:58px;padding:6px 4px;background:var(--state-bg);border:1px solid var(--state-border);color:var(--state-color);white-space:normal}
.episodeChip>span{display:block;font-weight:600;font-size:14px;color:var(--text)}.episodeChip small{display:block;font-size:12px;font-weight:400;line-height:1.4;overflow-wrap:anywhere}
.episodeChip[aria-pressed=true]{border-color:#f1f5ff;box-shadow:0 0 0 2px #f1f5ff}
.episodeRow{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:12px 16px;padding:16px 0 0}.episodeTitle{font-weight:600}.episodeMeta{color:var(--muted);font-size:13px;margin-top:4px}
.statusBadge{display:inline-block;margin-left:6px;padding:2px 7px;border:1px solid var(--state-border);border-radius:5px;background:var(--state-bg);font-size:12px;font-weight:400;color:var(--state-color)}
.needsAttention{color:#ffb7bd}.errorText{color:#ffb7bd;font-size:13px;margin-top:5px;overflow-wrap:anywhere}.actionNotice{color:#c0d1ff;margin-top:6px;font-size:13px}.progress{height:4px;background:var(--line);border-radius:4px;overflow:hidden;margin:8px 0}.progress i{display:block;height:100%;background:var(--focus)}
.detail{grid-column:1/-1;min-width:0;max-height:min(320px,45vh);overflow:auto;overscroll-behavior:contain;margin-top:4px}.detail table{width:100%;border-collapse:collapse}.detail th,.detail td{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid var(--line)}.detail th{color:var(--muted);position:sticky;top:0;background:var(--panel);font-weight:500}.source{color:var(--text)}.vi{color:#b5caff}.pending,.empty{color:var(--muted)}.empty{padding:28px;text-align:center}
.movieSearch{margin:0 0 20px;padding:18px;background:var(--panel);border-radius:8px}.movieSearch label{display:block;font-weight:600;margin-bottom:10px}.movieSearchControls{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px}.movieSearch input{width:100%}.movieSearchHint,.searchResultMeta{color:var(--muted);font-size:13px;margin-top:5px}#movieSearchStatus{color:#c0d1ff;margin-top:8px}.searchResults{display:grid;gap:8px;margin-top:8px;max-height:min(46vh,420px);overflow-y:auto;overscroll-behavior:contain}.searchResult{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 0;border-bottom:1px solid var(--line)}.searchResult>div{min-width:0;overflow-wrap:anywhere}.searchResultTitle{font-weight:600}.discoveryActions{display:flex;gap:8px;flex-wrap:wrap}
.discoveryIdentity{display:flex;align-items:center;gap:14px;flex:1}.discoveryIdentity>div{min-width:0;flex:1;overflow-wrap:anywhere}.discoveryActions{flex-shrink:0}
@media(max-width:760px){.discoveryIdentity{flex-basis:100%}.discoveryActions{margin-left:auto}}
dialog{width:min(560px,calc(100vw - 32px));max-height:calc(100vh - 32px);overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--panel);color:var(--text);padding:24px;box-shadow:0 20px 80px #0005}dialog::backdrop{background:#080a0dcc}
.settingsHead{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:20px}.settingsHead h2{font-size:20px;font-weight:600;margin:0}.settingsField{display:grid;gap:7px;margin:16px 0}.settingsField label{font-weight:500}.settingsField input,.settingsField select{width:100%}.settingsActions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:8px;margin-top:20px}
.settingsSection{border-top:1px solid var(--line);padding:18px 0;margin:0}.settingsSection h3{margin:0 0 12px}.settingsSection .settingsActions{justify-content:flex-start;margin-top:12px}.settingsSection>summary{cursor:pointer;padding:4px 0;font-weight:500}details>summary{cursor:pointer}
#accountStatus{font-size:13px;margin:0 0 14px;white-space:pre-wrap}#accountStatus.connected{color:#a2d1b6}.overview{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px;margin-top:20px}.metric strong{display:block;font-size:20px;font-weight:600}.metric span{font-size:13px;color:var(--muted)}
#notificationsDialog{width:min(720px,calc(100vw - 32px))}#notificationsCount{font-size:12px;margin-left:4px;color:#c0d1ff}#notificationsStatus{margin-top:12px}
#appLocalizationStatus{color:#c0d1ff;font-size:13px;margin:8px 0}#appLocalizationStatus.running{padding:10px 12px;border:1px solid var(--line);border-radius:7px}#appLocalizationStatus.error{color:#ffb7bd}
@media(max-width:1000px){.topbarInner{gap:22px;padding:0 24px}.managerBrand svg{width:90px}.primaryNav a{font-size:14px}.topActions{gap:3px}.topActions #addMovieButton{padding:9px 12px;margin-left:3px}}
@media(max-width:760px){html{scroll-padding-top:140px}.topbarInner{display:grid;grid-template-columns:auto 1fr auto;gap:0 16px;padding:0 16px 12px;min-height:120px}.managerBrand svg{width:80px}.primaryNav{height:64px;justify-self:start}.primaryNav a{font-size:13px}.librarySearch{grid-column:1/-1;grid-row:2;width:100%;max-width:none;margin:0}.topActions{grid-column:3;grid-row:1;gap:0}.topActions #addMovieButton{font-size:0;width:44px;min-width:44px;padding:0;margin:0 0 0 4px}.topActions #addMovieButton svg{width:20px;height:20px}.topActions .iconAction{width:44px;min-width:44px}.libraryHeading{gap:10px;margin-bottom:20px}.libraryHeading h1{font-size:21px}.libraryHeading .secondary{padding:7px 12px}main{margin:24px auto;padding:0 16px}.albumHead{gap:12px;flex-wrap:wrap;padding:16px 0}.albumHeading{flex:1 1 200px;gap:12px}.albumCover{flex-basis:60px;width:60px;height:90px}.albumTools{margin-left:auto}.albumTools button,.menu summary{min-height:44px}.episodeList{padding:4px 12px 12px}.episodeGrid{grid-template-columns:repeat(auto-fill,minmax(56px,1fr));gap:6px}.episodeRow{grid-template-columns:1fr}.episodeActions button{min-height:44px;flex:1}.episodeActions .menu{flex:0}.episodeActions .menu summary{min-width:44px}.movieSearchControls{grid-template-columns:1fr}.searchResult{align-items:flex-start;flex-wrap:wrap}.searchResult button{min-height:44px}.settingsActions button{min-height:44px}dialog{padding:20px}.settingsHead{gap:12px}.settingsHead h2{font-size:18px}}
@media(max-width:400px){.librarySearch{flex-basis:100%}.libraryTools>button{flex:1}.albumTools{margin-left:0}.albumTools .menu{margin-left:auto}.albumTools{width:100%}.albumTools button{flex:1}}
@media(prefers-reduced-motion:no-preference){button{transition:background-color .15s ease,border-color .15s ease}}
</style>
<header class="pageTop"><div class="topbarInner">
 <a class="managerBrand" href="/" aria-label="iQIYI – Quản lý phụ đề">__IQIYI_LOGO__</a>
 <nav class="primaryNav" aria-label="Điều hướng chính"><a href="#library" aria-current="page">Thư viện</a></nav>
 <div class="librarySearch" role="search" aria-label="Tìm phim trong thư viện"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><label class="srOnly" for="libraryQuery">Tìm phim trong thư viện</label><input id="libraryQuery" type="search" maxlength="200" placeholder="Tìm phim trong thư viện…" aria-describedby="librarySearchCount"><button id="libraryClearSearch" aria-label="Xóa tìm kiếm" title="Xóa tìm kiếm" hidden>×</button></div>
 <nav class="topActions" aria-label="Thao tác thư viện">
  <button id="notificationsButton" class="secondary iconAction" aria-label="Thông báo" title="Thông báo" aria-haspopup="dialog" aria-controls="notificationsDialog" onclick="document.getElementById('notificationsDialog').showModal()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/></svg><span id="notificationsCount" hidden>0</span></button>
  <button class="secondary iconAction" aria-label="Cài đặt" title="Cài đặt" aria-haspopup="dialog" aria-controls="appSettings" onclick="document.getElementById('appSettings').showModal()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 3-.6 2.3-2 .9-2.2-.6-2 3.4L4 10.7v2.6L2.2 15l2 3.4 2.2-.6 2 .9L9 21h4l.6-2.3 2-.9 2.2.6 2-3.4-1.8-1.7v-2.6L19.8 9l-2-3.4-2.2.6-2-.9L13 3Z"/><circle cx="11" cy="12" r="3"/></svg></button>
  <button id="addMovieButton" aria-label="Thêm phim" aria-controls="movieSearch" aria-expanded="false" onclick="toggleSearch()"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>Thêm phim</button>
 </nav>
</div></header>
<main id="library">
 <section id="integrationPrompt" class="integrationPrompt" aria-label="Cài đặt lần đầu" hidden><div><strong>Kết nối với app iQIYI</strong><p>Lần đầu, mở IQIYI-VI.exe rồi cài tích hợp tại đây. Những lần sau, mở quản lý bằng biểu tượng iQIYI trong app.</p></div><button onclick="openIntegrationSettings()">Cài đặt một lần</button></section>
 <div class="libraryHeading"><div><h1>Thư viện phụ đề</h1><p><span id="countIqiyi">0</span> tập · Phụ đề gốc và bản dịch</p></div><button id="toggleAllAlbums" class="secondary" onclick="toggleAllAlbums()">Mở tất cả</button></div>
 <div id="appLocalizationStatus" role="status" aria-live="polite"></div>
 __TRANSLATION_PANEL__
 <section id="movieSearch" class="movieSearch" role="search" aria-labelledby="movieSearchTitle" hidden><label id="movieSearchTitle" for="movieQuery">Tìm và thêm phim iQIYI</label><form id="movieSearchForm" autocomplete="off"><div class="movieSearchControls"><input id="movieQuery" name="iw_movie_q" type="text" maxlength="100" placeholder="Tên phim hoặc tên gốc tiếng Trung" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" required><button id="movieSearchButton">Tìm</button></div></form><div id="movieSearchStatus" role="status" aria-live="polite"></div><div id="movieSearchResults" class="searchResults" aria-live="polite"></div></section>

 <p id="librarySearchCount" class="settingsHint" role="status" aria-live="polite"></p>
 <div id="status" role="status" aria-live="polite"></div><section id="items"></section>
</main>
<dialog id="appSettings" aria-labelledby="appSettingsTitle"><div class="settingsHead"><h2 id="appSettingsTitle">Cài đặt</h2><button class="secondary" autofocus onclick="document.getElementById('appSettings').close()">Đóng</button></div>
 <section class="settingsSection"><h3>Dịch phụ đề</h3><button id="translationSettingsButton" class="secondary" aria-haspopup="dialog" aria-controls="translationSettings" onclick="document.getElementById('appSettings').close();openTranslationSettings()" disabled>Model & provider</button></section>
 <section class="settingsSection"><h3>Kết nối</h3><div id="accountStatus" class="hint" role="status" aria-atomic="true"></div><div id="iqcomAccount"><button id="iqcomLoginButton" class="secondary" onclick="loginIqcom()">Kiểm tra iq.com</button><p id="iqcomStatus" class="settingsHint" role="status" aria-live="polite">Dùng phiên iq.com của trình duyệt hiện tại</p></div><button class="secondary" onclick="document.getElementById('appSettings').close();openIqiyiProxySettings()">Proxy</button></section>
 <section id="iqiyiIntegration" class="settingsSection"><h3>Tích hợp iQIYI</h3><p class="settingsHint">Lần đầu, mở IQIYI-VI.exe trong thư mục đã giải nén rồi bấm Cài đặt một lần. Những lần sau chỉ cần mở iQIYI như bình thường; dịch vụ quản lý phụ đề sẽ tự chạy nền. Bấm biểu tượng iQIYI ở góc dưới bên phải trong app để mở cửa sổ quản lý.</p><div class="settingsActions"><button id="localizeIqiyiButton" onclick="runAppLocalization('apply')">Cài đặt một lần</button><button id="updateIqiyiButton" class="secondary" onclick="runAppLocalization('repair')" hidden>Cập nhật Việt hóa</button><button id="restoreIqiyiButton" class="secondary" onclick="runAppLocalization('restore')">Gỡ tích hợp</button></div></section>
 <details class="settingsSection"><summary>Thống kê thư viện</summary><section class="overview" aria-label="Tổng quan thư viện"><div class="metric"><strong id="metricTotal">0</strong><span>Tập trong thư viện</span></div><div class="metric"><strong id="metricDownloaded">0</strong><span>Có phụ đề gốc</span></div><div class="metric"><strong id="metricCueCount">0</strong><span>Câu phụ đề</span></div><div class="metric"><strong id="metricAttention">0</strong><span>Cần chú ý</span></div></section></details>
</dialog>
<dialog id="notificationsDialog" aria-labelledby="notificationsTitle"><div class="settingsHead"><h2 id="notificationsTitle">Phim vừa nhận diện</h2><button class="secondary" onclick="document.getElementById('notificationsDialog').close()" aria-label="Đóng thông báo">Đóng</button></div>
<p class="settingsHint">Phim chỉ được thêm vào thư viện khi bạn chấp nhận. Bỏ qua để không nhận lại thông báo cho phim đó.</p>
<div id="notificationsList"></div><div id="notificationsStatus" role="status" aria-live="polite"></div></dialog>
<dialog id="iqiyiProxyDialog" aria-labelledby="iqiyiProxyTitle"><div class="settingsHead"><h2 id="iqiyiProxyTitle">Proxy iQIYI và web</h2><button class="secondary" onclick="iqiyiProxyDialog.close()" aria-label="Đóng">Đóng</button></div>
<div class="settingsField"><label for="iqiyiProxyUrl">HTTP proxy Trung Quốc đại lục</label><input id="iqiyiProxyUrl" type="password" autocomplete="off" maxlength="4096" placeholder="host:port hoặc http://user:password@host:port"><p class="settingsHint">Lưu hoặc tắt proxy sẽ mở lại iQIYI và có thể ngắt video đang xem.</p><details><summary>Chi tiết kết nối</summary><p class="settingsHint">Proxy chỉ dùng cho web/player iQIYI và được lưu trong phiên này. App phụ đề kết nối trực tiếp. Tiện ích web đồng bộ trong khoảng 30 giây.</p></details></div>
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
document.addEventListener("click",event=>document.querySelectorAll(".menu[open]").forEach(menu=>{if(!menu.contains(event.target)||event.target.closest("button"))menu.open=false}));
document.addEventListener("keydown",event=>{if(event.key!=="Escape")return;const menu=document.querySelector(".menu[open]");if(menu){menu.open=false;menu.querySelector("summary").focus();event.preventDefault()}});
const iqiyiProxyDialog=document.getElementById("iqiyiProxyDialog");
const expandedAlbums=new Set(),collapsedAlbums=new Set(),expandedCues=new Set(),detailCache=new Map(),selectedEpisodes=new Map(),episodeMessages=new Map();
let albumLists={},episodeData=[],lastRenderSignature="",refreshBusy=false,refreshPending=false,refreshError="";
const pendingActions=new Set(),detailPending=new Set();
let allAlbumsOpen=false,iqiyiSynced=false,iqiyiSources={};
let iqcomChecking=false;
let discoveries=[],discoveriesSignature="";
const discoveryBusy=new Set();
function renderDiscoveries(){
 const count=document.getElementById("notificationsCount");count.textContent=String(discoveries.length);count.hidden=!discoveries.length;
 document.getElementById("notificationsButton").setAttribute("aria-label","Thông báo: "+discoveries.length+" phim chờ chấp nhận");
 const signature=JSON.stringify([discoveries,[...discoveryBusy]]);if(signature===discoveriesSignature)return;discoveriesSignature=signature;
 document.getElementById("notificationsList").innerHTML=discoveries.length?discoveries.map(movie=>"<article class='searchResult'><div class='discoveryIdentity'>"+movieCoverMarkup(movie.albumCoverUrl)+"<div><div class='searchResultTitle'>"+esc(movie.title)+"</div><div class='searchResultMeta'>"+"iQIYI"+" · "+movie.episodes+" tập đã nhận diện</div>"+(movie.originalTitle&&movie.originalTitle!==movie.title?"<div class='searchResultMeta'>Tên gốc: "+esc(movie.originalTitle)+"</div>":"")+"</div></div><div class='discoveryActions'><button class='secondary' onclick=\"decideDiscovery("+jsArg(movie.tvid)+",'dismiss')\" "+(discoveryBusy.has(movie.tvid)?"disabled":"")+">Bỏ qua</button><button onclick=\"decideDiscovery("+jsArg(movie.tvid)+",'accept')\" "+(discoveryBusy.has(movie.tvid)?"disabled":"")+">Chấp nhận</button></div></article>").join(""):"<p class='hint'>Chưa có phim mới chờ chấp nhận.</p>";
}
async function decideDiscovery(tvid,action){
 if(discoveryBusy.has(tvid))return;discoveryBusy.add(tvid);renderDiscoveries();const status=document.getElementById("notificationsStatus");status.textContent="Đang xử lý…";
 try{const r=await apiFetch("/api/discoveries/decide",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({tvid,action})}),x=await r.json();if(!r.ok)throw Error(x.error||"Không xử lý được thông báo.");status.textContent=safeStatusText(x.message,"Đã cập nhật thông báo.");await refresh(true)}catch(e){status.textContent=safeStatusText(e.message,"Đã xảy ra lỗi. Thông báo chưa có bản tiếng Việt.")}finally{discoveryBusy.delete(tvid);renderDiscoveries()}
}
function updateIqcomStatus(state){const button=document.getElementById("iqcomLoginButton"),status=document.getElementById("iqcomStatus");button.disabled=iqcomChecking;button.textContent=iqcomChecking?"Đang kiểm tra…":"Kiểm tra iq.com";if(!iqcomChecking)status.textContent=safeStatusText(state.message,"Kiểm tra phiên iq.com của trình duyệt hiện tại; không mở cửa sổ mới.");status.setAttribute("aria-busy",String(iqcomChecking))}
async function loginIqcom(){if(window.pywebview){window.open(location.origin+"/?connect=iqcom","_blank");updateIqcomStatus({message:"Chọn phiên iq.com bằng nút Kiểm tra iq.com trong trang trình duyệt vừa mở."});return}if(iqcomChecking)return;iqcomChecking=true;updateIqcomStatus({});document.getElementById("iqcomStatus").textContent="Đang kiểm tra phiên iq.com của trình duyệt này…";try{const state=await new Promise((resolve,reject)=>{const requestId=crypto.randomUUID();let timer;function receive(event){if(event.source!==window||event.origin!==location.origin||event.data?.type!=="iqcom-session-result"||event.data.requestId!==requestId)return;clearTimeout(timer);window.removeEventListener("message",receive);event.data.error?reject(Error(event.data.error)):resolve(event.data.state||{})}window.addEventListener("message",receive);timer=setTimeout(()=>{window.removeEventListener("message",receive);reject(Error("Tải lại tiện ích Việt hóa và trang này để kiểm tra phiên của trình duyệt."))},8000);window.postMessage({type:"iqcom-session-check",requestId},location.origin)});iqcomChecking=false;updateIqcomStatus(state)}catch(e){iqcomChecking=false;updateIqcomStatus({message:e.message})}}
let appLocalizationPoll=0;
function openIntegrationSettings(){document.getElementById("appSettings").showModal();document.getElementById("iqiyiIntegration").scrollIntoView({block:"center"})}
let searchMoviesData=[];
const addingAlbums=new Set(),movieSearchStatus=document.getElementById("movieSearchStatus");
document.getElementById("movieSearchForm").addEventListener("submit",event=>{event.preventDefault();searchMovies()});
function toggleSearch(){const panel=document.getElementById("movieSearch"),q=document.getElementById("movieQuery");panel.hidden=!panel.hidden;document.getElementById("addMovieButton").setAttribute("aria-expanded",String(!panel.hidden));if(panel.hidden){q.value=""}else{q.focus()}}
async function refreshAppLocalization(){clearTimeout(appLocalizationPoll);try{const r=await apiFetch("/api/app-localization"),x=await r.json();if(!r.ok)throw Error(x.error||"Không đọc được trạng thái iQIYI");const busy=x.status==="running",status=document.getElementById("appLocalizationStatus");document.getElementById("integrationPrompt").hidden=!!x.installed;const installButton=document.getElementById("localizeIqiyiButton");installButton.disabled=busy||!!x.installed;installButton.textContent=x.installed?"Đã cài đặt":"Cài đặt một lần";const updateButton=document.getElementById("updateIqiyiButton");updateButton.hidden=!x.installed;updateButton.disabled=busy;document.getElementById("restoreIqiyiButton").disabled=busy;status.className=busy?"running":x.status==="error"?"error":"";status.setAttribute("aria-busy",String(busy));status.textContent=x.status==="idle"?(x.installed?"Đã cài đặt. Mở iQIYI bình thường để dùng quản lý phụ đề.":""):safeStatusText(x.message,"Trạng thái Việt hóa chưa có bản tiếng Việt.");if(busy)appLocalizationPoll=setTimeout(refreshAppLocalization,1000)}catch(e){const status=document.getElementById("appLocalizationStatus");status.className="error";status.setAttribute("aria-busy","false");status.textContent=safeStatusText(e.message,"Đã xảy ra lỗi. Thông báo chưa có bản tiếng Việt.")}}
async function runAppLocalization(action){if(action==="restore"&&!confirm("Khôi phục các file giao diện iQIYI từ bản sao lưu? Đóng và mở lại iQIYI sau khi hoàn tất."))return;const status=document.getElementById("appLocalizationStatus");document.getElementById("localizeIqiyiButton").disabled=true;document.getElementById("updateIqiyiButton").disabled=true;document.getElementById("restoreIqiyiButton").disabled=true;status.className="running";status.setAttribute("aria-busy","true");status.textContent=action==="restore"?"Đang khôi phục giao diện tiếng Trung…":action==="repair"?"Đang cập nhật tiếng Việt…":"Đang cài tích hợp iQIYI…";try{const r=await apiFetch("/api/app-localization",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action})}),x=await r.json();if(!r.ok)throw Error(x.error||"Không chạy được thao tác");status.textContent=safeStatusText(x.message,status.textContent);refreshAppLocalization()}catch(e){status.className="error";status.setAttribute("aria-busy","false");status.textContent=safeStatusText(e.message,"Đã xảy ra lỗi. Thông báo chưa có bản tiếng Việt.");refreshAppLocalization()}}
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
function albumIsOpen(key){return allAlbumsOpen?!collapsedAlbums.has(key):expandedAlbums.has(key)}
function toggleAlbum(key){if(allAlbumsOpen){if(collapsedAlbums.has(key))collapsedAlbums.delete(key);else collapsedAlbums.add(key)}else{if(expandedAlbums.has(key))expandedAlbums.delete(key);else expandedAlbums.add(key)}render(episodeData)}
function toggleAllAlbums(){allAlbumsOpen=!allAlbumsOpen;collapsedAlbums.clear();expandedAlbums.clear();render(episodeData)}
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
  return {label:"Đã nhận diện · Chưa tải phụ đề",short:"Chưa tải",style:""};
 }
 function episodePanel(x){
  const state=episodeState(x),dl=x.downloadProgress||{},downloadBusy=["queued","downloading"].includes(dl.stage);
  const tr=x.translation,trBusy=tr&&!["complete","error","cancelled"].includes(tr.stage);
  const total=Number(x.cues)||0;
  const error=["error","access"].includes(dl.stage)?dl.message:"";
  const actionMessage=episodeMessages.get(x.tvid)||"";
  return `<article class='episodeRow' id='panel-${esc(x.tvid)}'><div><div class='episodeTitle'>${esc(episodeLabel(x))} <span class='statusBadge ${state.style}'>${esc(state.label)}</span></div>`+
   (total?`<div class='episodeMeta'>${total} câu phụ đề gốc</div>`:"")+
   (tr&&(trBusy||tr.stage==="error"||tr.stage==="cancelled")?`<div class='${tr.stage==="error"?"errorText":"episodeMeta"}' role='status'>${esc(tr.message)}</div>`:"")+
   (error?`<div role='status' aria-live='polite' class='errorText'>${esc(error)}</div>`:"")+
   (actionMessage?`<div class='actionNotice' role='status'>${esc(actionMessage)}</div>`:"")+`</div><div class='episodeActions'>`+
   (x.downloaded?"":`<button class='secondary' title='Tải phụ đề gốc' onclick="retryDownload('${esc(x.tvid)}')" ${downloadBusy||!x.downloadAvailable?"disabled":""}>${downloadBusy?"Đang tải…":"Tải gốc"}</button>`)+
   (x.downloaded&&tr?.stage!=="complete"?`<button data-translate-episode='${esc(x.tvid)}' onclick="${tr?.resumable?"resumeTranslationJob('"+esc(tr.id)+"')":"translateEpisode('"+esc(x.tvid)+"')"}" ${trBusy?"disabled":""}>${trBusy?"Đang dịch…":tr?.resumable?"Dịch tiếp":"Dịch"}</button>`:"")+
   (tr?`<button class='${tr.stage==="complete"?"":"secondary"}' onclick="showTranslationJob('${esc(tr.id)}')">${tr.stage==="complete"?"Xem bản dịch":"Tiến độ dịch"}</button>`:"")+
   (x.downloaded?`<details class='menu' data-menu-key='episode:${esc(x.tvid)}'><summary class='secondary' aria-label='Thao tác khác cho tập'>···</summary><div class='moreMenu'>${total?`<button onclick="detail('${esc(x.tvid)}')">${expandedCues.has(x.tvid)?"Ẩn phụ đề gốc":"Xem phụ đề gốc"}</button>`:""}${tr?.stage==="complete"?`<button onclick="downloadTranslation('${esc(tr.id)}','translated.srt',this)">Tải SRT Việt</button><button onclick="translateEpisode('${esc(x.tvid)}')">Dịch lại</button>`:""}${tr?.resumable?`<button onclick="translateEpisode('${esc(x.tvid)}')">Dịch từ đầu</button>`:""}<button class='danger' onclick="deleteSubtitle('${esc(x.tvid)}')">Xóa phụ đề gốc</button></div></details>`:"")+`</div>`+
   (expandedCues.has(x.tvid)?`<div id='cues-${esc(x.tvid)}' class='detail' role='region' aria-label='Phụ đề gốc ${esc(episodeLabel(x))}' tabindex='0'>${detailCache.get(x.tvid)||""}</div>`:"")+`</article>`;
 }
 function updateTranslationEpisode(state){
  const row=episodeData.find(x=>x.tvid===state.episode_id);
  if(row?.translation?.id===state.id){row.translation={id:state.id,stage:state.stage,message:state.message,step:state.step,resumable:state.resumable,saved_batches:state.saved_batches,total_batches:state.total_batches,retry_at:state.retry_at,memory_available:state.memory_available};render(episodeData)}
  if(row&&(!row.translation||row.translation.id!==state.id||["complete","error","cancelled"].includes(state.stage)))refresh(true);
 }
 function updateProviderChrome(data){
 document.getElementById("countIqiyi").textContent=data.filter(x=>(x.provider||"iqiyi")==="iqiyi").length;
 document.getElementById("toggleAllAlbums").textContent=allAlbumsOpen?"Thu gọn tất cả":"Mở tất cả";
 const account=document.getElementById("accountStatus"),loginStatus=source=>!source?.synced?"Chưa kết nối":source.connected?"Đã đăng nhập":"Chưa đăng nhập";
 const accountText="iQIYI · App: "+loginStatus(iqiyiSources.app)+" · Web: "+loginStatus(iqiyiSources.web);
 if(account.textContent!==accountText)account.textContent=accountText;
 account.classList.toggle("connected",iqiyiSynced);
}
function movieCoverMarkup(url){
 const placeholder="<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.5'><rect x='3' y='3' width='18' height='18' rx='2'/><path d='M7 3v18M17 3v18M3 8h4M3 16h4M17 8h4M17 16h4'/></svg>";
 return "<span class='albumCover' aria-hidden='true'>"+placeholder+(url?"<img src='"+esc(url)+"' alt='' width='72' height='108' loading='lazy' decoding='async' referrerpolicy='no-referrer' onerror='this.remove()'>":"")+"</span>";
}
function render(data){
 const providerRows=data.filter(x=>(x.provider||"iqiyi")==="iqiyi"),label="iQIYI",groups=new Map();
 const query=normalizeMovieQuery(libraryQuery.value);libraryClearSearch.hidden=!libraryQuery.value;
 updateProviderChrome(data);
  const downloaded=providerRows.filter(x=>x.downloaded).length,cueCount=providerRows.reduce((sum,x)=>sum+(Number(x.cues)||0),0),attention=providerRows.filter(x=>["error","access"].includes((x.downloadProgress||{}).stage)||x.translation?.stage==="error").length;
  document.getElementById("metricTotal").textContent=providerRows.length;document.getElementById("metricDownloaded").textContent=downloaded;document.getElementById("metricCueCount").textContent=cueCount;document.getElementById("metricAttention").textContent=attention;
 providerRows.forEach(x=>{const key=albumKey(x);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(x)});
 let html="<section class='platformSection' aria-labelledby='platform-title'><h2 id='platform-title' class='srOnly'>"+label+" · "+providerRows.length+" tập</h2>";
 let visibleAlbums=0;
 if(!providerRows.length)html+="<div class='platformEmpty'>"+"Mở iQIYI hoặc dùng Thêm phim để bắt đầu thư viện."+"</div>";
 else{
  groups.forEach((rows,key)=>{
   if(query&&!rows.some(x=>normalizeMovieQuery(seriesDisplayName(x)+" "+seriesName(x)).includes(query)))return;
   rows.sort((a,b)=>(orderOf(a)||9999)-(orderOf(b)||9999));
   const first=rows[0],original=seriesName(first),title=seriesDisplayName(first)||"Phim đang phát";
   const shown=rows;visibleAlbums++;
   const list=albumLists[String(first.albumId||"")]||{},total=list.stage==="ready"?list.total:Math.max(rows.length,...rows.map(x=>Number(x.albumTotal)||0));
   const sourceCount=rows.filter(x=>x.downloaded).length;
   const issueCount=rows.filter(x=>["error","access"].includes(x.downloadProgress?.stage)||x.translation?.stage==="error").length;
   const open=albumIsOpen(key),listId="episode-list-"+String(first.albumId||first.tvid).replace(/[^a-z0-9_-]/gi,"-");
   const selected=shown.find(x=>x.tvid===selectedEpisodes.get(key))||shown[0];
   const grid=open?shown.map(x=>{const state=episodeState(x);return "<button id='episode-"+esc(x.tvid)+"' class='episodeChip "+state.style+"' aria-pressed='"+(x===selected)+"' aria-label='"+esc(episodeLabel(x)+": "+state.label)+"' title='"+esc(episodeLabel(x)+": "+state.label)+"' onclick=\"selectEpisode("+jsArg(key)+","+jsArg(x.tvid)+")\"><span>"+esc(orderOf(x)||"?")+"</span><small>"+esc(state.short)+"</small></button>"}).join(""):"";
   html+="<section class='album'><div class='albumHead'><button type='button' class='albumHeading' id='album-toggle-"+listId+"' aria-expanded='"+open+"' aria-controls='"+listId+"' onclick=\"toggleAlbum("+jsArg(key)+")\">"+movieCoverMarkup(rows.find(x=>x.albumCoverUrl)?.albumCoverUrl)+"<span class='albumIdentity'><span class='seriesTitle'>"+esc(title)+"</span>"+
    (title!==original?"<span class='originalTitle'>"+esc(original)+"</span>":"")+
    "<span class='albumSummary'><strong>"+rows.length+(total>rows.length?" / "+total:"")+" tập</strong> · "+(sourceCount?sourceCount+" đã tải":"Chưa tải phụ đề")+(issueCount?"<span class='needsAttention'> · "+issueCount+" cần kiểm tra</span>":"")+"</span>"+
    (list.stage==="loading"?"<span class='albumSummary' role='status'>Đang lấy toàn bộ danh sách tập từ iQIYI…</span>":list.stage==="error"?"<span class='errorText'>Chưa lấy đủ danh sách tập: "+esc(list.message)+". App sẽ tự thử lại.</span>":"")+"</span>"+
    "<svg class='albumChevron' aria-hidden='true' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.5'><path d='m6 9 6 6 6-6'/></svg></button><div class='albumTools'>"+
    (rows.some(x=>x.translation?.memory_available)?"<button class='secondary' onclick=\"showMovieMemory("+jsArg(first.tvid)+")\">Hồ sơ dịch</button>":"")+
    "<details class='menu' data-menu-key='album:"+esc(key)+"'><summary class='secondary' aria-label='Thao tác phim'>···</summary><div class='moreMenu'>"+("<button onclick=\"post('/api/download-all',{albumId:'"+esc(first.albumId||"")+"'},this)\">Tải phụ đề gốc</button>")+"<button class='danger' onclick=\"deleteAlbum('"+esc(first.tvid)+"')\">Xóa phim</button></div></details></div></div>"+
    "<div id='"+listId+"' class='episodeList' "+(open?"":"hidden")+">"+(open?"<details class='episodeLegendHelp'><summary>Chú giải trạng thái</summary><div class='episodeLegend' aria-label='Chú giải trạng thái'><span class='legendItem'><i class='legendDot'></i>Chưa tải</span><span class='legendItem'><i class='legendDot sourceReady'></i>Đã tải gốc</span><span class='legendItem'><i class='legendDot complete'></i>Đã dịch</span><span class='legendItem'><i class='legendDot active'></i>Đang xử lý</span><span class='legendItem'><i class='legendDot error'></i>Lỗi</span><span class='legendItem'><i class='legendDot access'></i>Cần quyền</span></div></details><div class='episodeGrid' role='group' aria-label='Chọn tập phim'>"+grid+"</div>"+episodePanel(selected):"")+"</div></section>";
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
async function refresh(force){if(refreshBusy){refreshPending=refreshPending||!!force;return}refreshBusy=true;try{const r=await apiFetch("/api/episodes"),payload=await r.json();if(!r.ok)throw Error(payload.error||"Không tải được thư viện.");const data=payload.episodes||[];if(refreshError&&statusNode.textContent===refreshError)statusNode.textContent="";refreshError="";albumLists=payload.albums||{};discoveries=payload.discoveries||[];renderDiscoveries();iqiyiSynced=!!(payload.session&&payload.session.synced);iqiyiSources=payload.session?.sources||{};updateIqcomStatus(payload.iqcomSession||{});episodeData=data;const signature=JSON.stringify([albumLists,data.map(x=>[x.tvid,x.provider,x.title,x.albumTitle,x.albumTitleVi,x.albumCoverUrl,x.albumId,x.albumTotal,x.cues,x.downloadAvailable,x.downloadProgress,x.translation])]);if(force||signature!==lastRenderSignature){lastRenderSignature=signature;render(data);renderMovieSearchResults()}else updateProviderChrome(data)}catch(e){refreshError=safeStatusText(e.message,"Không kết nối được app quản lý.");statusNode.textContent=refreshError}finally{refreshBusy=false;if(refreshPending){refreshPending=false;queueMicrotask(()=>refresh(true))}}}
function refreshVisible(){if(!document.hidden)refresh(false)}
document.addEventListener("visibilitychange",()=>{if(!document.hidden)refresh(false)});
if(new URLSearchParams(location.search).get("connect")==="iqcom")document.getElementById("appSettings").showModal();
refreshAppLocalization();refresh(true);setInterval(refreshVisible,5000);
</script>'''
PAGE = PAGE.replace("__TRANSLATION_PANEL__", (ROOT / "translation_ui.html").read_text(encoding="utf-8"))
PAGE = PAGE.replace("__IQIYI_LOGO__", re.sub(r"<\?xml[^>]*>\s*", "", (ROOT / "assets/iqiyi-logo.svg").read_text(encoding="utf-8")))


PLAYER_API_ROUTES = {
    "GET": frozenset(("/health", "/api/extension-token", "/subtitle.xml", "/audio.mp4", "/api/audio-state",
                      "/api/official-subtitle-state",
                      "/api/international-title", "/api/international-actor", "/api/international-search")),
    "HEAD": frozenset(("/audio.mp4",)),
    "POST": frozenset(("/api/session", "/api/register", "/api/album/register", "/api/capture", "/api/localize-remaining", "/api/audio-playback", "/api/audio-settings", "/api/open-manager")),
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
        if urlsplit(self.path).path == "/api/open-manager":
            return origin is None or origin in (*local, "https://localwebapp.iqiyi.com")
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
                    (host == "iqiyi.com" or host.endswith(".iqiyi.com")))
        except ValueError:
            return False

    def authorized(self) -> bool:
        if not self.allowed_request():
            self.send_json(403, {"error": "Origin or Host is not allowed"})
            return False
        request = urlsplit(self.path)
        if self.command == "GET" and request.path in ("/", "/health", "/favicon.ico"):
            return True
        origin = self.headers.get("Origin")
        if (self.command == "GET" and request.path == "/api/extension-token" and
                self.is_iqiyi_origin(origin)):
            return True
        supplied = self.headers.get("X-Iqiyi-Token", "")
        if request.path in ("/subtitle.xml", "/api/official-subtitle-state", "/audio.mp4"):
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
        try:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Vary", "Accept-Encoding")
            if compressed:
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            self.wfile.write(body)
        except ConnectionError:
            self.close_connection = True

    def send_json(self, code: int, data):
        self.send_body(code, "application/json; charset=utf-8", json.dumps(data, ensure_ascii=False).encode())

    def do_OPTIONS(self):
        if not self.allowed_request():
            self.send_json(403, {"error": "Origin or Host is not allowed"})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Iqiyi-Token, Range")
        self.end_headers()

    def do_HEAD(self):
        if not self.authorized():
            return
        if urlsplit(self.path).path != "/audio.mp4":
            self.send_error(404)
            return
        try:
            self.send_audio(head=True)
        except (ValueError, OSError):
            self.send_response(410)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def send_audio(self, *, head=False):
        params = parse_qs(urlsplit(self.path).query)
        tvid = params.get("tvid", [""])[0]
        source = IQCOM_AUDIO.source(tvid, params.get("stream", [""])[0])
        try:
            start, end = byte_range(self.headers.get("Range"), source.size)
        except ValueError:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{source.size}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        chunks = iter(source.read(start, end)) if not head else iter(())
        first = next(chunks, b"")  # Resolve upstream errors before committing response headers.
        self.send_response(206 if self.headers.get("Range") else 200)
        self.send_header("Content-Type", "audio/mp4")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if self.headers.get("Range"):
            self.send_header("Content-Range", f"bytes {start}-{end}/{source.size}")
        try:
            self.end_headers()
            if first:
                self.wfile.write(first)
            for chunk in chunks:
                # Logout and disabling the setting also stop already open streams.
                IQCOM_AUDIO.source(tvid, source.key)
                self.wfile.write(chunk)
        except (OSError, ValueError):
            self.close_connection = True
        finally:
            close = getattr(chunks, "close", None)
            if close:
                close()

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
        elif request.path == "/favicon.ico":
            self.send_body(200, "image/x-icon", (ROOT / "assets/iqiyi.ico").read_bytes())
        elif request.path == "/api/audio-state":
            self.send_json(200, IQCOM_AUDIO.status(parse_qs(request.query).get("tvid", [""])[0]))
        elif request.path == "/audio.mp4":
            self.send_audio()
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
            params = parse_qs(request.query, keep_blank_values=True)
            self.send_json(200, international_movie_title(params["id"][0]) if "id" in params else
                           international_movie_title_by_name(params.get("name", [""])[0]))
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
                             "albumCoverUrl": series_cover_url(item),
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
            episode_dir(tvid)
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
            # The SDK preloads both local tracks. Availability comes from the state API;
            # a valid track with no cues yet is an empty document, not a missing route.
            self.send_body(200, "text/xml; charset=utf-8", body or b"<?xml version='1.0'?><xml />")
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
            if route == "/api/audio-settings":
                self.send_json(200, IQCOM_AUDIO.configure(data))
                return
            if route == "/api/open-manager":
                from desktop import open_window
                try:
                    open_window()
                except (OSError, RuntimeError) as exc:
                    self.send_json(503, {"error": str(exc)[:500]})
                    return
                self.send_json(200, {"ok": True})
                return
            if route == "/api/audio-playback":
                IQCOM_AUDIO.report(data)
                self.send_json(200, {"ok": True})
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
                    try:
                        relay = DESKTOP_PROXY.url() if proxy_url else ""
                        if app_integration.read_state(ROOT):
                            app_integration.set_proxy(ROOT, relay)
                        with IQIYI_PROXY_LOCK:
                            IQIYI_PROXY_URL = proxy_url
                        desktop = apply_running_iqiyi_proxy(relay)
                    except (OSError, RuntimeError):
                        desktop = {"status": "error", "message": "Đã lưu cấu hình nhưng chưa kết nối lại được iQIYI. Đóng rồi mở lại iQIYI."}
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
                if provider != "iqiyi":
                    raise ValueError("Invalid provider")
                if not re.fullmatch(r"\d{1,20}", tvid):
                    raise ValueError("Invalid iQIYI episode ID")
                tracks = []
                for track in data.get("tracks", [])[:40]:
                    try:
                        tracks.append({"lid": str(track.get("lid", "")), "name": str(track.get("name", ""))[:120],
                                       "url": normalize_track(str(track.get("url", ""))),
                                       "format": str(track.get("format", "xml"))})
                    except ValueError:
                        continue
                previous = EPISODES.get(tvid, {})
                identity = registered_episode_identity(tvid, data, previous)
                album_id = identity["albumId"]
                EPISODES[tvid] = {**previous, "provider": provider, **identity,
                                  "tracks": tracks or previous.get("tracks", [])}
                folder.mkdir(parents=True, exist_ok=True)
                save_episode(tvid, EPISODES[tvid])
                if album_id and library_status(EPISODES[tvid]) == "accepted":
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
                        {**episode, "albumId": album_id, "albumTitle": album_title}, previous)
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
                if EPISODES[tvid].get("downloadDisabled"):
                    raise ValueError("Phụ đề tập này đã bị xóa; hãy chọn Tải gốc nếu muốn lấy lại.")
                raw = str(data.get("raw", ""))
                if len(raw.encode("utf-8")) > 15_000_000:
                    raise ValueError("Subtitle file is too large")
                fmt = str(data.get("format", "xml"))
                cues = parse_source(raw, fmt)
                capture_source(tvid, cues)
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
                if data.get("provider", "iqiyi") != "iqiyi":
                    raise ValueError("Invalid provider")
                album_id = str(data.get("albumId", ""))
                title = str(data.get("seriesTitle", ""))[:500].casefold().strip()
                if album_id and not re.fullmatch(r"\d{1,24}", album_id):
                    raise ValueError("Invalid album ID")
                with LOCK_GUARD:
                    if not (album_id and album_id != "0") and not title:
                        raise ValueError("Invalid movie identity")
                    ids = album_episode_ids(album_id, title)
                    if not ids:
                        raise ValueError("Không tìm thấy phim này trong thư viện.")
                    album_ids = {album_id} | {str(EPISODES[key].get("albumId", "")) for key in ids}
                    if any(ALBUM_LISTS.get(key, {}).get("stage") == "loading" for key in album_ids):
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
                ids = album_episode_ids(album_id)
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
