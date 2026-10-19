"""Windows launchers for the iQIYI and Youku Việt hóa tools."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

from windows_runtime import list_processes, run_elevated, terminate_process

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except OSError:
            pass

ROOT = Path(__file__).resolve().parent
MANAGER_URL = "http://127.0.0.1:18766/"
MANAGER_HEALTH = MANAGER_URL + "health"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def python_executable(background: bool = False) -> Path:
    names = ("pythonw.exe", "python.exe") if background else ("python.exe", "pythonw.exe")
    for name in names:
        candidate = ROOT / ".venv" / "Scripts" / name
        if candidate.is_file():
            return candidate
    current = Path(sys.executable)
    if current.name.lower() == "pythonw.exe":
        console = current.with_name("python.exe")
        if console.is_file():
            current = console
    if current.is_file():
        return current
    for name in ("pythonw", "python") if background else ("python", "pythonw"):
        found = shutil.which(name)
        if found:
            return Path(found)
    raise RuntimeError("Không tìm thấy Python. Hãy cài Python 3 hoặc tạo môi trường .venv.")


def script_processes(names: set[str], argument: str | None = None):
    targets = {os.path.normcase(str(ROOT / name)).replace("/", "\\") for name in names}
    for process in list_processes():
        command = os.path.normcase(process.command_line).replace("/", "\\")
        if argument is not None and not command.rstrip().endswith(" " + argument):
            continue
        if Path(process.name).name.lower() in {"python.exe", "pythonw.exe"} and any(
            target in command for target in targets
        ):
            # The absolute script path scopes this match to this checkout.
            yield process


def manager_busy() -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(MANAGER_HEALTH, timeout=2) as response:
            health = json.loads(response.read().decode("utf-8"))
        if isinstance(health, dict) and health.get("app") in {"iqiyi-subtitles", "subtitle-manager"} and "busy" in health:
            return bool(health["busy"])
    except (OSError, ValueError, urllib.error.URLError):
        pass
    try:
        with opener.open(MANAGER_URL + "api/episodes", timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
            episodes = payload.get("episodes") if isinstance(payload, dict) else None
        if isinstance(episodes, list):
            return any(isinstance(item, dict) and
                       (item.get("progress") or {}).get("stage") == "translating" for item in episodes)
    except (OSError, ValueError, urllib.error.URLError):
        pass
    return True  # Unknown state is treated as busy to protect an active translation.


def stop_processes(processes) -> None:
    for process in processes:
        terminate_process(process.pid)


def run_apply(restore: bool = False) -> int:
    python = python_executable()
    script = ROOT / "apply-vi.py"
    args = [str(script)] + (["--restore"] if restore else [])
    result = subprocess.run([str(python), *args], cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=1800,
                            creationflags=CREATE_NO_WINDOW)
    if result.returncode == 2:
        print("Đang xin quyền Administrator...")
        result = run_elevated(str(python), args, str(ROOT))
    if result.returncode != 0:
        detail = (result.stdout + "\n" + result.stderr).strip()
        print(detail or f"Thao tác thất bại (mã {result.returncode}).")
    return result.returncode


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


def launch_iqiyi() -> int:
    related = list(script_processes({"watch-players.py"}, "iqiyi"))
    related.extend(script_processes({"watch-iqiyi-vi.py", "inject-cdp.py", "subtitle_app.py"}))
    managers = [process for process in related if "subtitle_app.py" in process.command_line.lower()]
    if managers and manager_busy():
        print("App phụ đề đang dịch hoặc chưa xác nhận được trạng thái. Chờ dịch xong rồi chạy lại launcher.")
        return 1
    stop_processes(related)

    print("Đang cài phụ đề Việt...")
    if run_apply() != 0:
        return 1
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

    install_root = client.parent
    install_prefix = os.path.normcase(str(install_root).rstrip("\\/")) + os.sep
    qy_processes = [process for process in list_processes()
                    if Path(process.name).stem.lower() in {"qyclient", "qyplayer", "qykernel", "qyfragment"}
                    and process.path and os.path.normcase(process.path).startswith(install_prefix)]
    if qy_processes:
        print("Đang khởi động lại iQIYI để nạp hook phụ đề mới...")
        stop_processes(qy_processes)
        time.sleep(1)

    proxy = os.environ.get("IQIYI_PLAYER_PROXY", "").strip()
    webview = webview_runtime()
    env = os.environ.copy()
    browser_args = "--remote-debugging-port=9223 --remote-debugging-address=127.0.0.1"
    if proxy:
        env.update(HTTP_PROXY=proxy, HTTPS_PROXY=proxy, ALL_PROXY=proxy,
                   NO_PROXY="localhost,127.0.0.1,::1")
        browser_args += f" --proxy-server={proxy} --proxy-bypass-list=localhost;127.0.0.1;[::1]"
        print("Đang mở iQIYI qua proxy đã cấu hình (IQIYI_PLAYER_PROXY)...")
    else:
        print("Đang mở iQIYI với kết nối trực tiếp (không proxy)...")
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = browser_args
    if webview:
        env["WEBVIEW2_BROWSER_EXECUTABLE_FOLDER"] = webview
    try:
        subprocess.Popen([str(client)], cwd=install_root, env=env)
    except OSError as exc:
        print(f"Không mở được iQIYI: {exc}")
        return 1
    return open_manager_when_ready("iQIYI")


def find_youku() -> Path | None:
    bases = [Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Youku",
             Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Youku"]
    for base in bases:
        if base.is_dir():
            candidates = [folder / "YOUKU.exe" for folder in base.iterdir()
                          if folder.is_dir() and (folder / "YOUKU.exe").is_file()]
            if candidates:
                return max(candidates, key=lambda path: tuple(
                    int(n) for n in re.findall(r"\d+", path.parent.name.split("-", 1)[0])))
    return None


def launch_youku() -> int:
    client = find_youku()
    if not client:
        print("Không tìm thấy YOUKU.exe trong Program Files.")
        return 1
    managers = list(script_processes({"subtitle_app.py"}))
    if managers and manager_busy():
        print("App phụ đề đang dịch hoặc chưa xác nhận được trạng thái. Chờ dịch xong rồi chạy lại launcher Youku.")
        return 1
    stop_processes(managers)
    stop_processes(script_processes({"watch-youku-vi.py"}))
    try:
        subprocess.Popen([str(client), "--remote-debugging-port=9224"], cwd=client.parent)
        watcher = ROOT / "watch-players.py"
        with (ROOT / "youku-vi.log").open("a", encoding="utf-8") as log:
            subprocess.Popen([str(python_executable(background=True)), str(watcher), "youku"], cwd=ROOT,
                             creationflags=CREATE_NO_WINDOW, stdout=log, stderr=log, close_fds=True)
    except OSError as exc:
        print(f"Không mở được Youku: {exc}")
        return 1
    return open_manager_when_ready("Youku")


def open_manager_when_ready(player: str) -> int:
    for _ in range(20):
        try:
            with urllib.request.urlopen(MANAGER_URL, timeout=1):
                webbrowser.open(MANAGER_URL)
                print(f"Xong. {player} đã mở; app quản lý phụ đề đang chạy trong trình duyệt.")
                return 0
        except (OSError, urllib.error.URLError):
            time.sleep(0.5)
    print(f"{player} đã mở nhưng app phụ đề chưa sẵn sàng. Chạy lại launcher để khởi động watcher.")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Khởi chạy công cụ Việt hóa iQIYI / Youku")
    parser.add_argument("action", choices=("iqiyi", "youku", "manager", "restore"))
    action = parser.parse_args().action
    try:
        if action == "iqiyi":
            return launch_iqiyi()
        if action == "youku":
            return launch_youku()
        if action == "restore":
            return run_apply(restore=True)
        return subprocess.call([str(python_executable()), str(ROOT / "subtitle_app.py")], cwd=ROOT)
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Không chạy được launcher: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
