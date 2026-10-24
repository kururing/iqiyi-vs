"""Build a clean Windows x64 portable webapp from an explicit source allowlist."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parent
SOURCES = (
    "desktop.py", "launcher.py", "apply-vi.py", "watch-players.py", "subtitle_app.py",
    "subtitle_agent.py", "iqiyi_common.py", "windows_runtime.py", "cdp.py",
    "iqcom_requests.py", "iqcom_session.py", "proxy_support.py",
    "ui-engine.js", "lwa-vi.js", "sub-hook.js", "README.md", ".env.example", "requirements.txt",
)
EXTENSION = ("manifest.json", "content.js", "sub-hook.js", "proxy.js", "https-rules.json",
             "iqcom-bootstrap.js", "iqcom-session.js", "session-bridge.js", "local-api.js", "local-api-worker.js")


def build(output: Path):
    if os.name != "nt" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("Build bằng Python x64 trên Windows.")
    if output.exists() or output.with_suffix(".zip").exists():
        raise FileExistsError("Đích đã tồn tại; chọn thư mục mới bằng --output để giữ dữ liệu cũ.")
    compiler = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not compiler.is_file():
        raise RuntimeError("Thiếu compiler .NET Framework 4.x (csc.exe).")
    base = Path(sys.base_prefix)
    if not all((base / name).is_file() for name in ("python.exe", "pythonw.exe")):
        raise RuntimeError("Cần bản CPython Windows đầy đủ để đóng gói runtime.")
    output.mkdir(parents=True)
    for name in SOURCES:
        shutil.copy2(ROOT / name, output / name)
    (output / "ext").mkdir()
    for name in EXTENSION:
        shutil.copy2(ROOT / "ext" / name, output / "ext" / name)
    runtime = output / "runtime"
    runtime.mkdir()
    for name in ("python.exe", "pythonw.exe", "LICENSE.txt"):
        shutil.copy2(base / name, runtime / name)
    for path in base.glob("*.dll"):
        shutil.copy2(path, runtime / path.name)
    ignored = shutil.ignore_patterns("__pycache__", "*.pyc", "site-packages", "test", "tests")
    for name in ("Lib", "DLLs"):
        shutil.copytree(base / name, runtime / name, ignore=ignored)
    # Isolate the portable interpreter from installed Python and user site packages.
    version = f"python{sys.version_info.major}{sys.version_info.minor}"
    (runtime / (version + "._pth")).write_text(
        "Lib\nDLLs\nLib/site-packages\n..\nimport site\n", encoding="utf-8")
    subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-compile",
                    "--only-binary=:all:", "--target", str(runtime / "Lib/site-packages"),
                    "-r", str(ROOT / "requirements.txt")], check=True)
    subprocess.run([str(compiler), "/nologo", "/target:winexe", "/platform:x64", "/optimize+",
                    "/reference:System.Windows.Forms.dll", "/out:" + str(output / "IQIYI-VI.exe"),
                    str(ROOT / "packaging/DesktopLauncher.cs")], check=True)
    subprocess.run([str(runtime / "python.exe"), str(output / "desktop.py"), "--check"],
                   cwd=output, check=True, timeout=90)
    dependencies = subprocess.check_output([
        str(runtime / "python.exe"), "-c",
        "import importlib.metadata,json; print(json.dumps({d.metadata['Name']:d.version for d in importlib.metadata.distributions()}))",
    ], text=True, encoding="utf-8")
    (output / "build-info.json").write_text(json.dumps({
        "python": platform.python_version(), "platform": "Windows x64",
        "dependencies": json.loads(dependencies),
    }, indent=2), encoding="utf-8")
    # No local library, auth files, backups, browser sessions, tests or audits enter the package.
    archive = output.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in output.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                bundle.write(path, Path(output.name) / path.relative_to(output))
    print(f"APP: {output / 'IQIYI-VI.exe'}")
    print(f"ZIP: {archive} ({archive.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/IQIYI-VI-Windows-x64")
    build(parser.parse_args().output.resolve())
