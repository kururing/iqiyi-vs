"""Per-user iQIYI integration for normal app launches, with reversible registry edits."""
from __future__ import annotations

import json
from functools import lru_cache
import os
import re
from pathlib import Path
import subprocess

if os.name == "nt":
    import winreg

from iqiyi_common import atomic_write, python_executable
from windows_runtime import command_line_args, run_elevated

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "IQIYI-VI-Watch"
WEBVIEW_KEY = r"Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments"
WEBVIEW_APP = "QyClient.exe"
DEBUG_ARGS = ("--remote-debugging-port=9223", "--remote-debugging-address=127.0.0.1")


def state_path(root: Path) -> Path:
    return root / ".local" / "iqiyi-integration.json"


@lru_cache(maxsize=1)
def current_user_sid() -> str:
    if os.name != "nt":
        raise RuntimeError("Tích hợp iQIYI chỉ hỗ trợ Windows.")
    executable = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "whoami.exe"
    output = subprocess.check_output([str(executable), "/user", "/fo", "csv", "/nh"],
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    match = re.search(r"S-1-(?:\d+-)+\d+", output.decode("ascii", errors="ignore"))
    if not match:
        raise RuntimeError("Không xác nhận được tài khoản Windows đang cài iQIYI.")
    return match[0]


def installer_args(root: Path, restore: bool = False) -> list[str]:
    # Capture the signed-in user's identity before UAC can select another admin account.
    args = [str(root / "apply-vi.py"), *(["--restore"] if restore else []),
            "--user-sid", current_user_sid(), "--defer-watcher"]
    for name in ("APPDATA", "LOCALAPPDATA"):
        if os.environ.get(name):
            args.extend(["--" + name.lower(), os.environ[name]])
    return args


def registry_location(key: str, user_sid: str | None):
    if user_sid and user_sid != current_user_sid():
        return winreg.HKEY_USERS, user_sid + "\\" + key
    return winreg.HKEY_CURRENT_USER, key


def read_value(key: str, name: str, user_sid: str | None = None):
    try:
        hive, path = registry_location(key, user_sid)
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as handle:
            return list(winreg.QueryValueEx(handle, name))
    except FileNotFoundError:
        return None


def write_value(key: str, name: str, value, user_sid: str | None = None) -> None:
    hive, path = registry_location(key, user_sid)
    with winreg.CreateKeyEx(hive, path, 0, winreg.KEY_SET_VALUE) as handle:
        if value is None:
            try:
                winreg.DeleteValue(handle, name)
            except FileNotFoundError:
                pass
        else:
            winreg.SetValueEx(handle, name, 0, value[1], value[0])


def read_state(root: Path) -> dict:
    try:
        state = json.loads(state_path(root).read_text(encoding="utf-8"))
        if state.get("version") == 1 and state.get("root") == str(root.resolve()):
            return state
    except (OSError, ValueError, AttributeError):
        pass
    return {}


def installed(root: Path) -> bool:
    if os.name != "nt" or (root / "watch-iqiyi-vi.disabled").exists():
        return False
    state = read_state(root)
    try:
        user_sid = current_user_sid()
        return (state.get("userSid", user_sid) == user_sid and bool(state.get("entries")) and
                all(read_value(row["key"], row["name"], user_sid) == row["value"] for row in state["entries"]))
    except (OSError, KeyError, TypeError):
        return False


def install(root: Path, user_sid: str | None = None) -> None:
    if os.name != "nt":
        raise RuntimeError("Tích hợp iQIYI chỉ hỗ trợ Windows.")
    root = root.resolve()
    user_sid = user_sid or current_user_sid()
    if not re.fullmatch(r"S-1-(?:\d+-){1,15}\d+", user_sid):
        raise ValueError("Tài khoản Windows cài đặt không hợp lệ.")
    command = subprocess.list2cmdline([str(python_executable(root, background=True)), str(root / "watch-players.py"), "iqiyi"])
    previous = read_state(root)
    if previous.get("userSid", user_sid) != user_sid:
        raise RuntimeError("Thư mục này đã được tích hợp cho tài khoản Windows khác. Dùng một thư mục riêng cho tài khoản hiện tại.")
    entries = []
    for key, name in ((RUN_KEY, RUN_NAME), (WEBVIEW_KEY, WEBVIEW_APP)):
        current = read_value(key, name, user_sid)
        old = next((row for row in previous.get("entries", []) if row["key"] == key and row["name"] == name), None)
        original = old["previous"] if old else current
        if key == RUN_KEY:
            # Older installers already registered this same watcher; uninstall must remove it.
            if original and original[0] == command:
                original = None
            value = command
        else:
            arguments = command_line_args(current[0]) if current and isinstance(current[0], str) else []
            if old and current != old["value"]:
                # A repair adopts unrelated edits made after installation, but
                # restores the user's original debugger/proxy arguments on uninstall.
                prior = command_line_args(original[0]) if original else []
                clean = [arg for arg in arguments if not arg.startswith(("--remote-debugging-port", "--remote-debugging-address", "--proxy-server=", "--proxy-bypass-list="))]
                clean.extend(arg for arg in prior if arg.startswith(("--remote-debugging-port", "--remote-debugging-address", "--proxy-server=", "--proxy-bypass-list=")))
                original = [subprocess.list2cmdline(clean), winreg.REG_SZ] if clean else None
            retained, skip = [], False
            for argument in arguments:
                if skip:
                    skip = False
                elif argument in ("--remote-debugging-port", "--remote-debugging-address"):
                    skip = True
                elif not argument.startswith(("--remote-debugging-port=", "--remote-debugging-address=")) and not (old and argument.startswith(("--proxy-server=", "--proxy-bypass-list="))):
                    retained.append(argument)
            proxy = old.get("proxy", "") if old else ""
            value = subprocess.list2cmdline([*retained, *DEBUG_ARGS, *(["--proxy-server=" + proxy, "--proxy-bypass-list=localhost;127.0.0.1;[::1]"] if proxy else [])])
        entries.append({"key":key,"name":name,"previous":original,"value":[value, winreg.REG_SZ], **({"proxy":proxy} if key == WEBVIEW_KEY else {})})
    # Save the original values before writing, so a partial installation is also reversible.
    atomic_write(state_path(root), json.dumps({"version":1,"root":str(root),"userSid":user_sid,"entries":entries}, ensure_ascii=False))
    for row in entries:
        write_value(row["key"], row["name"], row["value"], user_sid)


def _set_proxy(root: Path, proxy: str, user_sid: str) -> None:
    state = read_state(root)
    if state.get("userSid", user_sid) != user_sid:
        raise RuntimeError("Tích hợp thuộc tài khoản Windows khác; cấu hình hiện tại được giữ lại.")
    row = next((item for item in state.get("entries", []) if item["key"] == WEBVIEW_KEY), None)
    if not row or read_value(WEBVIEW_KEY, WEBVIEW_APP, user_sid) != row["value"]:
        raise RuntimeError("Tích hợp iQIYI đã thay đổi. Bấm Kết nối app iQIYI trước khi đặt proxy.")
    arguments = [arg for arg in command_line_args(row["value"][0])
                 if not arg.startswith(("--proxy-server=", "--proxy-bypass-list="))]
    if proxy:
        arguments.extend(("--proxy-server=" + proxy, "--proxy-bypass-list=localhost;127.0.0.1;[::1]"))
    row["value"] = [subprocess.list2cmdline(arguments), winreg.REG_SZ]
    row["proxy"] = proxy
    write_value(WEBVIEW_KEY, WEBVIEW_APP, row["value"], user_sid)
    atomic_write(state_path(root), json.dumps(state, ensure_ascii=False))


def set_proxy(root: Path, proxy: str) -> None:
    """Update protected WebView2 policy under the original user's identity."""
    user_sid = current_user_sid()
    try:
        _set_proxy(root, proxy, user_sid)
        return
    except PermissionError:
        pass
    # Only the loopback relay URL enters the elevated helper, never credentials.
    result = run_elevated(str(python_executable(root)),
                          [str(root / "app_integration.py"), "--set-proxy", proxy,
                           "--user-sid", user_sid], str(root), timeout=120)
    if result.returncode == 1223:
        raise RuntimeError("Chưa lưu proxy vì yêu cầu quyền Administrator đã bị hủy. Bấm Lưu proxy và chấp thuận cửa sổ Windows.")
    if result.returncode:
        raise RuntimeError("Windows chưa cho phép cập nhật proxy iQIYI. Thử lưu lại và chấp thuận quyền Administrator.")
    row = next((item for item in read_state(root).get("entries", []) if item["key"] == WEBVIEW_KEY), None)
    if not row or row.get("proxy") != proxy or read_value(WEBVIEW_KEY, WEBVIEW_APP, user_sid) != row["value"]:
        raise RuntimeError("Chưa xác nhận được cấu hình proxy iQIYI sau khi xin quyền Administrator. Hãy thử lại.")


def uninstall(root: Path, user_sid: str | None = None) -> None:
    if os.name != "nt":
        return
    state = read_state(root)
    user_sid = user_sid or current_user_sid()
    if not re.fullmatch(r"S-1-(?:\d+-){1,15}\d+", user_sid):
        raise ValueError("Tài khoản Windows cài đặt không hợp lệ.")
    if state.get("userSid", user_sid) != user_sid:
        raise RuntimeError("Tích hợp thuộc tài khoản Windows khác; cấu hình hiện tại được giữ nguyên.")
    for row in state.get("entries", []):
        if read_value(row["key"], row["name"], user_sid) == row["value"]:
            write_value(row["key"], row["name"], row["previous"], user_sid)
    if not state:
        current = read_value(RUN_KEY, RUN_NAME, user_sid)
        args = command_line_args(current[0]) if current else []
        if len(args) > 1 and Path(args[1]).resolve() == (root / "watch-players.py").resolve():
            write_value(RUN_KEY, RUN_NAME, None, user_sid)
    state_path(root).unlink(missing_ok=True)


if __name__ == "__main__":
    import argparse
    from urllib.parse import urlsplit

    parser = argparse.ArgumentParser(description="Cập nhật proxy iQIYI cho tài khoản Windows đã cài tích hợp")
    parser.add_argument("--set-proxy", required=True)
    parser.add_argument("--user-sid", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"S-1-(?:\d+-){1,15}\d+", args.user_sid):
        parser.error("Tài khoản Windows không hợp lệ.")
    if args.set_proxy:
        address = urlsplit(args.set_proxy)
        if (address.scheme != "http" or address.hostname != "127.0.0.1" or not address.port
                or address.username is not None or address.path or address.query or address.fragment):
            parser.error("Chỉ chấp nhận relay proxy nội bộ của app.")
    _set_proxy(Path(__file__).resolve().parent, args.set_proxy, args.user_sid)
