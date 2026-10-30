"""Windows launchers for the iQIYI Việt hóa tools."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from iqiyi_common import browser_proxy_token
from app_integration import installed as integration_installed
from app_integration import installer_args
from iqiyi_common import python_executable as _python_executable
from windows_runtime import command_line_args, list_processes, run_elevated, stop_background_browsers, terminate_process

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except OSError:
            pass

ROOT = Path(__file__).resolve().parent
MANAGER_URL = "http://127.0.0.1:18766/"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def python_executable(background: bool = False) -> Path:
    return _python_executable(ROOT, background)


def script_processes(names: set[str], argument: str | None = None):
    targets = {os.path.normcase(str(ROOT / name)).replace("/", "\\") for name in names}
    for process in list_processes():
        if Path(process.name).name.lower() not in {"python.exe", "pythonw.exe"}:
            continue
        arguments = command_line_args(process.command_line)
        if len(arguments) < 2 or (argument is not None and arguments[-1] != argument):
            continue
        if os.path.normcase(arguments[1]).replace("/", "\\") in targets:
            # Only the actual script argument can own a process in this checkout.
            yield process


def manager_busy() -> bool:
    from desktop import health
    try:
        status = health()
        return not status or status.get("busy") is not False
    except (OSError, RuntimeError, ValueError):
        return True  # Unknown state must protect active subtitle work.


def stop_processes(processes) -> None:
    processes = list(processes)
    if any(len(args := command_line_args(process.command_line)) > 1 and
           Path(args[1]).resolve() == (ROOT / "subtitle_app.py").resolve() for process in processes):
        stop_background_browsers(ROOT / ".local" / "iqcom-browser")
    failed = {process.pid for process in processes if not terminate_process(process.pid)}
    deadline = time.monotonic() + 0.5
    while failed:
        failed.intersection_update(process.pid for process in list_processes(include_command_line=False))
        if not failed:
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Không dừng được dịch vụ hoặc watcher. Kiểm tra quyền chạy app rồi thử lại.")
        time.sleep(min(0.05, remaining))


def stop_previous_run(player: str, legacy_scripts: set[str], keep_manager: bool = False) -> bool:
    """Stop the old watcher/manager of one player; False while subtitle work is active."""
    related = list(script_processes({"watch-players.py"}, player))
    related.extend(script_processes(legacy_scripts | {"subtitle_app.py"}))
    managers = [process for process in related if "subtitle_app.py" in process.command_line.lower()]
    if managers and not keep_manager and manager_busy():
        print(f"App phụ đề đang xử lý dữ liệu hoặc chưa xác nhận được trạng thái. "
              f"Chờ xử lý xong rồi chạy lại launcher {player}.")
        return False
    stop_processes([process for process in related if not keep_manager or process not in managers])
    return True


def run_apply(restore: bool = False) -> int:
    python = python_executable()
    args = installer_args(ROOT, restore)
    result = subprocess.run([str(python), *args], cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=1800,
                            creationflags=CREATE_NO_WINDOW)
    if result.returncode == 2:
        print("Đang xin quyền Administrator...")
        result = run_elevated(str(python), args, str(ROOT))
    if result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr).strip()
        print(detail or f"Thao tác thất bại (mã {result.returncode}).")
    elif not restore:
        ensure_watcher()
    return result.returncode


def ensure_watcher() -> None:
    """Start in the normal caller's session after the privileged installer returns."""
    if list(script_processes({"watch-players.py"}, "iqiyi")):
        return
    with (ROOT / "watch-iqiyi.runtime.log").open("a", encoding="utf-8") as log:
        subprocess.Popen([str(python_executable(background=True)), str(ROOT / "watch-players.py"), "iqiyi"],
                         cwd=ROOT, creationflags=CREATE_NO_WINDOW, close_fds=True, stdout=log, stderr=log)


def webview_runtime() -> str:
    base = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    root = base / "Microsoft" / "EdgeWebView" / "Application"
    versions = []
    if root.is_dir():
        for folder in root.iterdir():
            if folder.is_dir() and (folder / "msedgewebview2.exe").is_file():
                numbers = tuple(int(n) for n in re.findall(r"\d+", folder.name))
                versions.append((numbers, folder))
    return str(max(versions, default=((), None), key=lambda item: item[0])[1]) if versions else ""


def ensure_manager() -> bool:
    """Start the relay's owner if needed; preserve an already-running manager."""
    from desktop import ensure_manager as start_manager
    return start_manager()


def iqiyi_player_proxy() -> str:
    """Use the manager's current setting, including an explicit direct connection."""
    try:
        started = ensure_manager()
        token = (ROOT / ".iqiyi-vi-token").read_text(encoding="ascii").strip()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        fallback = os.environ.get("IQIYI_PLAYER_PROXY", "").strip() if started else ""
        if fallback:
            request = urllib.request.Request(MANAGER_URL + "api/iqiyi-proxy",
                data=json.dumps({"url": fallback}).encode(), headers={
                    "X-Iqiyi-Token": token, "Content-Type": "application/json"})
            with opener.open(request, timeout=160):
                pass
        request = urllib.request.Request(MANAGER_URL + "api/browser-proxy?desktop=1", headers={
            "X-Iqiyi-Token": browser_proxy_token(token)})
        with opener.open(request, timeout=2) as response:
            proxy = json.load(response)["proxy"]
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Không đọc được proxy từ app phụ đề (HTTP {exc.code}).") from None
    except (OSError, urllib.error.URLError):
        raise RuntimeError("Không kết nối được app phụ đề để cấu hình proxy desktop.") from None
    if not proxy:
        return ""
    host = proxy["host"]
    if ":" in host:
        host = "[" + host + "]"
    if proxy.get("username") or proxy.get("password"):
        raise RuntimeError("Khởi động lại app phụ đề để cập nhật hỗ trợ proxy desktop có mật khẩu.")
    return f"http://{host}:{proxy['port']}"


def launch_iqiyi(open_ui: bool = False) -> int:
    proxy = iqiyi_player_proxy()
    if not integration_installed(ROOT):
        if not stop_previous_run("iqiyi", {"watch-iqiyi-vi.py", "inject-cdp.py"}, keep_manager=True):
            return 1
        print("Đang cài tích hợp iQIYI lần đầu...")
        if run_apply() != 0:
            return 1
    else:
        ensure_watcher()
    try:
        path_result = subprocess.run([str(python_executable()), str(ROOT / "apply-vi.py"), "--client-path"],
                                     cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                                     errors="replace", timeout=30, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Không tìm thấy QyClient.exe. Hãy mở iQIYI một lần hoặc kiểm tra đường dẫn cài đặt. ({exc})")
        return 1
    if path_result.returncode:
        print("Không tìm thấy QyClient.exe. Hãy mở iQIYI một lần hoặc kiểm tra đường dẫn cài đặt.")
        return 1
    client = Path(path_result.stdout.strip().splitlines()[-1]) if path_result.stdout.strip() else None
    if not client or not client.is_file():
        print(f"Không tìm thấy QyClient.exe tại: {client or '(trống)'}")
        return 1

    start_iqiyi_client(client, proxy)
    return open_manager_when_ready("iQIYI", open_ui=open_ui)


def apply_running_iqiyi_proxy(proxy: str) -> dict:
    """Reconnect only the running player; keep the manager and subtitle workers alive."""
    processes = list_processes()
    client = next((Path(process.path) for process in processes
                   if process.name.lower() == "qyclient.exe" and process.path), None)
    if client is None:
        return {"status": "closed", "message": "iQIYI đang đóng; cấu hình sẽ được dùng khi mở iQIYI."}
    if not client.is_file():
        raise RuntimeError("Không tìm thấy chương trình iQIYI đang chạy.")
    start_iqiyi_client(client, proxy, processes)
    return {"status": "restarted", "message": "iQIYI đã tự mở lại để áp dụng kết nối mới."}


def start_iqiyi_client(client: Path, proxy: str, processes=None) -> None:
    install_root = client.parent
    install_prefix = os.path.normcase(str(install_root).rstrip("\\/")) + os.sep
    qy_processes = [process for process in (list_processes() if processes is None else processes)
                    if Path(process.name).stem.lower() in {"qyclient", "qyplayer", "qykernel", "qyfragment"}
                    and process.path and os.path.normcase(process.path).startswith(install_prefix)]
    if qy_processes:
        print("Đang kết nối lại iQIYI với cấu hình mới...")
        for process in qy_processes:
            if not terminate_process(process.pid) and any(row.pid == process.pid for row in list_processes()):
                raise RuntimeError("Không đóng được iQIYI để đổi kết nối. Đóng iQIYI rồi lưu lại proxy.")
        time.sleep(1)

    webview = webview_runtime()
    env = os.environ.copy()
    browser_args = "--remote-debugging-port=9223 --remote-debugging-address=127.0.0.1"
    if proxy:
        env.update(HTTP_PROXY=proxy, HTTPS_PROXY=proxy, ALL_PROXY=proxy,
                   NO_PROXY="localhost,127.0.0.1,::1,.71edge.com,.ppsimg.com")
        proxy_parts = urlsplit(proxy if "://" in proxy else "http://" + proxy)
        proxy_server = proxy_parts.scheme + "://" + proxy_parts.netloc.rsplit("@", 1)[-1]
        browser_args += f" --proxy-server={proxy_server} --proxy-bypass-list=localhost;127.0.0.1;[::1]"
        print("Đang mở iQIYI qua proxy đã cấu hình trong app phụ đề...")
    else:
        browser_args += " --no-proxy-server"
        for key in tuple(env):
            if key.lower() in ("http_proxy", "https_proxy", "all_proxy"):
                env.pop(key)
        print("Đang mở iQIYI với kết nối trực tiếp (không proxy)...")
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = browser_args
    # The watchdog registers Vietnamese at document-start before resuming each WebView.
    env["WEBVIEW2_WAIT_FOR_SCRIPT_DEBUGGER"] = "1"
    if webview:
        env["WEBVIEW2_BROWSER_EXECUTABLE_FOLDER"] = webview
    try:
        subprocess.Popen([str(client)], cwd=install_root, env=env)
    except OSError as exc:
        raise RuntimeError("Không mở lại được iQIYI sau khi đổi kết nối.") from exc


def open_manager_when_ready(player: str, open_ui: bool = True) -> int:
    from desktop import health, open_window
    for _ in range(20):
        if health():
            if open_ui:
                open_window()
            print(f"Xong. {player} đã mở; app quản lý phụ đề đã sẵn sàng.")
            return 0
        time.sleep(0.5)
    print(f"{player} đã mở nhưng app phụ đề chưa sẵn sàng. Chạy lại launcher để khởi động watcher.")
    return 1


def open_manager() -> int:
    ensure_manager()
    return open_manager_when_ready("Thư viện phụ đề")


def main() -> int:
    parser = argparse.ArgumentParser(description="Khởi chạy công cụ Việt hóa iQIYI")
    parser.add_argument("action", choices=("iqiyi", "manager", "open-manager", "restore"))
    action = parser.parse_args().action
    try:
        if action == "iqiyi":
            return launch_iqiyi()
        if action == "restore":
            return run_apply(restore=True)
        if action == "open-manager":
            return open_manager()
        return subprocess.call([str(python_executable()), str(ROOT / "subtitle_app.py")], cwd=ROOT)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Không chạy được launcher: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
