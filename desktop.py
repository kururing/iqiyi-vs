"""Portable Windows webapp launcher; the manager stays alive for player subtitles."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from iqiyi_common import atomic_write, installation_lock
from windows_runtime import focus_app_window

ROOT = Path(__file__).resolve().parent
URL = "http://127.0.0.1:18766/"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
MANAGER_TITLES = ("iQIYI – Quản lý phụ đề", "Quản lý phụ đề")
WINDOW_LOCK = threading.Lock()


def health():
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(URL + "health", timeout=2) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError("Cổng 18766 đang được ứng dụng khác sử dụng.") from exc
    except ValueError as exc:
        raise RuntimeError("Cổng 18766 trả dữ liệu không hợp lệ.") from exc
    except OSError:
        return None
    expected = hashlib.sha256(str(ROOT.resolve()).casefold().encode()).hexdigest()[:16]
    if not isinstance(data, dict) or not data.get("ok") or data.get("app") != "subtitle-manager":
        raise RuntimeError("Cổng 18766 đang được ứng dụng khác sử dụng.")
    if data.get("rootId") != expected:
        raise RuntimeError("Một bản quản lý phụ đề khác đang chạy. Đóng dịch vụ của bản đó trước khi mở bản này.")
    return data


def ensure_manager() -> bool:
    if health():
        return False
    from iqiyi_common import python_executable
    with (ROOT / "subtitle-manager.stderr.log").open("a", encoding="utf-8") as errors:
        process = subprocess.Popen(
            [str(python_executable(ROOT, background=True)), str(ROOT / "subtitle_app.py")],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=errors, creationflags=NO_WINDOW,
        )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if health():
            return True
        if process.poll() is not None:
            raise RuntimeError("Không mở được dịch vụ phụ đề. Xem subtitle-manager.stderr.log trong thư mục app.")
        time.sleep(0.1)
    # Do not kill an unrelated instance if two launches raced to bind the same port.
    raise RuntimeError("Dịch vụ phụ đề chưa sẵn sàng sau 15 giây. Xem subtitle-manager.stderr.log.")


def open_window():
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    # Serialize API threads and separate launcher processes, including the time
    # between starting the browser and its first visible window.
    with WINDOW_LOCK, installation_lock(local, "manager-window.lock"):
        pending = local / "manager-window-pending"
        if focus_app_window(MANAGER_TITLES, ROOT / "manager_window.py"):
            pending.unlink(missing_ok=True)
            return
        try:
            age = time.time() - float(pending.read_text(encoding="ascii"))
            if 0 <= age < 15:
                return
        except (FileNotFoundError, ValueError):
            pass
        process = _launch_window()
        atomic_write(pending, str(time.time()))
        for _ in range(50):
            time.sleep(0.1)
            if focus_app_window(MANAGER_TITLES, ROOT / "manager_window.py"):
                pending.unlink(missing_ok=True)
                return
            if process is not None and process.poll() is not None:
                pending.unlink(missing_ok=True)
                raise RuntimeError("Không mở được cửa sổ quản lý. Xem .local/manager-window.log; cài đủ requirements.txt và WebView2 Runtime.")


def _launch_window():
    from iqiyi_common import python_executable
    with (ROOT / ".local" / "manager-window.log").open("a", encoding="utf-8") as log:
        return subprocess.Popen(
            [str(python_executable(ROOT, background=True)), str(ROOT / "manager_window.py")],
            cwd=ROOT, stdout=log, stderr=log, creationflags=NO_WINDOW,
        )


def check_bundle():
    """A read-only smoke check on an ephemeral port; never opens the user's library."""
    import urllib3
    import subtitle_app as app
    import app_integration
    import manager_window
    from iqiyi_common import python_executable

    assert all((ROOT / "ext" / name).is_file() for name in ("content.js", "sub-hook.js")), "Missing player scripts"
    assert (ROOT / "apply-vi.py").is_file() and (ROOT / "watch-players.py").is_file()
    assert Path(app_integration.__file__).resolve().parent == ROOT.resolve(), "Missing packaged integration module"
    assert Path(manager_window.__file__).resolve().parent == ROOT.resolve(), "Missing packaged manager window"
    assert all((ROOT / "assets" / name).is_file() for name in ("iqiyi-logo.svg", "iqiyi.ico")), "Missing app branding"
    # These are real child interpreters, including the one used by elevated apply/restore.
    for background in (False, True):
        subprocess.run([str(python_executable(ROOT, background)), "-c",
                        "import ssl, ctypes, sqlite3, urllib3, playwright.sync_api, subtitle_app, webview, manager_window"],
                       check=True, cwd=ROOT, creationflags=NO_WINDOW, timeout=30)
    server = app.SubtitleHTTPServer(("127.0.0.1", 0), app.Handler)
    server.api_token = "package-smoke-check"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base = f"http://127.0.0.1:{server.server_port}"
        with opener.open(base + "/health", timeout=5) as response:
            assert json.load(response)["app"] == "subtitle-manager"
        with opener.open(base, timeout=5) as response:
            assert b"package-smoke-check" in response.read()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    print(json.dumps({"ok": True, "python": sys.version.split()[0], "urllib3": urllib3.__version__}))
    return 0


def main():
    parser = argparse.ArgumentParser(description="iQIYI Việt hóa — desktop webapp")
    parser.add_argument("action", nargs="?", default="open", choices=("open", "iqiyi", "restore", "stop", "background", "uninstall"))
    parser.add_argument("--check", action="store_true", help="Kiểm tra gói app mà không mở player hay thư viện")
    args = parser.parse_args()
    if args.check:
        return check_bundle()
    if os.name != "nt":
        raise RuntimeError("Bản desktop này dành cho Windows.")
    (ROOT / ".local").mkdir(exist_ok=True)
    import launcher
    if args.action in ("stop", "uninstall"):
        processes = list(launcher.script_processes({"watch-players.py", "subtitle_app.py", "manager_window.py"}))
        try:
            status = health()
        except RuntimeError:
            if processes:
                raise
            status = None  # Another checkout may run while this inactive copy is removed.
        unknown_manager = status is None and any("subtitle_app.py" in process.command_line.lower() for process in processes)
        if unknown_manager or (status and status.get("busy") is not False):
            raise RuntimeError("App đang xử lý phụ đề hoặc chưa xác nhận được trạng thái. Chờ hoàn tất trước khi dừng dịch vụ.")
        if args.action == "uninstall" and (ROOT / ".local/iqiyi-integration.json").exists():
            if launcher.run_apply(restore=True):
                raise RuntimeError("Chưa gỡ được tích hợp iQIYI. Dữ liệu và app được giữ lại; thử Gỡ tích hợp trong Cài đặt.")
        launcher.stop_processes(processes)
        return 0
    ensure_manager()
    if args.action == "background":
        if launcher.integration_installed(ROOT):
            launcher.ensure_watcher()
        return 0
    if args.action == "iqiyi":
        result = launcher.launch_iqiyi(open_ui=False)
        if result:
            raise RuntimeError("Không mở được player. Xem .local/desktop.log trong thư mục app.")
        return 0  # The manager window opens on demand from iQIYI's tool cluster.
    elif args.action == "restore":
        if launcher.run_apply(restore=True):
            raise RuntimeError("Không khôi phục được giao diện. Xem .local/desktop.log.")
    open_window()
    return 0


if __name__ == "__main__":
    if "--check" not in sys.argv:
        try:
            (ROOT / ".local").mkdir(exist_ok=True)
            sys.stdout = sys.stderr = (ROOT / ".local" / "desktop.log").open("a", encoding="utf-8", buffering=1)
        except OSError:
            pass
    try:
        raise SystemExit(main())
    except Exception as exc:
        if sys.stderr:
            import traceback
            traceback.print_exc()
        if os.name == "nt" and "--check" not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None, str(exc), "iQIYI Việt hóa", 0x10)
        raise SystemExit(1)
