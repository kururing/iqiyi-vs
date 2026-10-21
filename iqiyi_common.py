"""Small shared helpers for the installer, watcher and subtitle manager."""
from contextlib import contextmanager
import json
import hashlib
import hmac
import os
import re
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import time
import urllib.request
from windows_runtime import list_processes


_IQIYI_ROOTS: tuple[Path | None, list[Path]] = (None, [])
_IQIYI_ROOTS_REFRESH = 0.0
LWA_INI_FLAGS = {
    "lwa_disable_checksign_pcafx": "1",
    "lwa_disable_update": "1",
    "lwa_disable_repalce_update": "1",
    "lwa_disable_load_copy": "1",
}


def iqiyi_install_roots(state_dir: Path | None = None) -> list[Path]:
    """Find the native install from its running client, saved location, or Windows defaults."""
    global _IQIYI_ROOTS, _IQIYI_ROOTS_REFRESH
    now = time.monotonic()
    if now >= _IQIYI_ROOTS_REFRESH:
        running = None
        if os.name == "nt":
            for process in list_processes(include_command_line=False):
                if Path(process.name).name.casefold() == "qyclient.exe" and process.path:
                    running = Path(process.path).parent
                    break
        defaults = [
            Path(os.environ[name]) / "IQIYI Video" / "LStyle"
            for name in ("ProgramFiles", "ProgramFiles(x86)")
            if os.environ.get(name)
        ]
        _IQIYI_ROOTS = (running, defaults)
        _IQIYI_ROOTS_REFRESH = now + 10

    running, defaults = _IQIYI_ROOTS
    roots = [running] if running else []
    if state_dir is not None:
        saved = state_dir / ".iqiyi-install-location"
        try:
            value = saved.read_text(encoding="utf-8").strip()
            if value:
                location = Path(value)
                if (location / "skin").is_dir():
                    location = location.parent  # Older installers saved the version directory.
                if location.is_absolute() and location not in roots:
                    roots.append(location)
        except (OSError, ValueError):
            pass
    roots.extend(path for path in defaults if path not in roots)
    return roots


def iqiyi_skin_dir(base: Path) -> Path | None:
    """Return the newest iQIYI version's skin folder under an install root."""
    if not base.exists():
        return None
    if (base / "skin").is_dir():
        return base / "skin"
    versions = sorted(
        (path for path in base.iterdir() if path.is_dir() and (path / "skin").exists()),
        key=lambda path: tuple(int(number) for number in re.findall(r"\d+", path.name)),
        reverse=True,
    )
    return versions[0] / "skin" if versions else None


def atomic_write(path: Path, data: str | bytes) -> None:
    payload = data.encode("utf-8") if isinstance(data, str) else data
    try:
        if path.read_bytes() == payload:
            return
    except FileNotFoundError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def installation_lock(root: Path, name: str = "iqiyi-install.lock"):
    # Windows releases this lock even when an installer or watcher is terminated.
    import msvcrt
    with (root / name).open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def api_token(root: Path) -> str:
    with installation_lock(root, "iqiyi-auth.lock"):
        path = root / ".iqiyi-vi-token"
        if path.exists():
            token = path.read_text(encoding="ascii").strip()
            if len(token) >= 32:
                return token
        token = secrets.token_urlsafe(32)
        atomic_write(path, token)
        return token


def player_token(token: str) -> str:
    """Derive a player-only credential without exposing the manager's admin token."""
    return hmac.new(token.encode("utf-8"), b"subtitle-player-v1", hashlib.sha256).hexdigest()


def browser_proxy_token(token: str) -> str:
    return hmac.new(token.encode("utf-8"), b"browser-proxy-v1", hashlib.sha256).hexdigest()


def browser_session_token(token: str) -> str:
    return hmac.new(token.encode("utf-8"), b"browser-session-v1", hashlib.sha256).hexdigest()


def python_executable(root: Path, background: bool = False) -> Path:
    """Interpreter for helper processes: the checkout's .venv first, then the running Python.

    background=True prefers pythonw.exe so autostart/watchers never open a console window.
    """
    names = ("pythonw.exe", "python.exe") if background else ("python.exe", "pythonw.exe")
    for name in names:
        candidate = root / ".venv" / "Scripts" / name
        if candidate.is_file():
            return candidate
    current = Path(sys.executable)
    if not background and current.name.lower() == "pythonw.exe":
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


def subtitle_manager_alive(port: int = 18766) -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/health", timeout=0.6) as response:
            return response.status == 200
    except (TimeoutError, OSError):
        return False


def update_lwa_ini_flags(raw: str) -> str:
    updated = raw
    for key, value in LWA_INI_FLAGS.items():
        if re.search(rf"(?m)^{re.escape(key)}=.*$", updated):
            updated = re.sub(rf"(?m)^{re.escape(key)}=.*$", f"{key}={value}", updated)
        else:
            updated += f"\n{key}={value}\n"
    return updated


def subtitle_hook(root: Path) -> bytes:
    prefix = ("window.__iqiyiViToken = " + json.dumps(player_token(api_token(root))) + ";\n"
              "window.__iqiyiViTokenPending = false;\n"
              "if (window.__iqiyiViReload) window.__iqiyiViReload();\n")
    return prefix.encode("utf-8") + (root / "sub-hook.js").read_bytes()


def patch_subtitle_tag(text: str, hook: bytes | None) -> str:
    pattern = r'<script\s+src="\./sub-hook\.js(?:\?[^"<>]*)?"\s*></script>'
    tag = ('<script src="./sub-hook.js?v=' + hashlib.sha256(hook).hexdigest()[:12] + '"></script>') if hook is not None else ""
    if tag and text.count(tag) == 1 and len(re.findall(pattern, text)) == 1:
        return text
    text = re.sub(pattern, "", text)
    return re.sub(r"(<head\b[^>]*>)", lambda match: match[0] + tag, text, count=1, flags=re.I)


def lwa_backup_dir(backup: Path, webapp: Path) -> Path:
    if webapp.name == "iqiyi_webapp":
        return backup / "native" / webapp.parents[2].name
    return backup / webapp.name
