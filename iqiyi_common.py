"""Small shared helpers for the installer, watcher and subtitle manager."""
from contextlib import contextmanager
import json
import hashlib
import os
import re
from pathlib import Path
import secrets
import subprocess
import tempfile
import time


_IQIYI_ROOTS: tuple[Path | None, list[Path]] = (None, [])
_IQIYI_ROOTS_REFRESH = 0.0


def iqiyi_install_roots(state_dir: Path | None = None) -> list[Path]:
    """Find the native install from its running client, saved location, or Windows defaults."""
    global _IQIYI_ROOTS, _IQIYI_ROOTS_REFRESH
    now = time.monotonic()
    if now >= _IQIYI_ROOTS_REFRESH:
        running = None
        if os.name == "nt":
            try:
                result = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                     "Get-CimInstance Win32_Process -Filter \"Name='QyClient.exe'\" "
                     "-ErrorAction SilentlyContinue | ForEach-Object { $_.ExecutablePath }"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                    encoding="utf-8", errors="replace", timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                for line in result.stdout.splitlines():
                    client = Path(line.strip().strip('"'))
                    if client.name.casefold() == "qyclient.exe":
                        running = client.parent
                        break
            except (OSError, subprocess.SubprocessError):
                pass
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
                if location.is_absolute() and location not in roots:
                    roots.append(location)
        except (OSError, ValueError):
            pass
    roots.extend(path for path in defaults if path not in roots)
    return roots


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


def subtitle_hook(root: Path) -> bytes:
    prefix = "window.__iqiyiViToken = " + json.dumps(api_token(root)) + ";\n"
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
