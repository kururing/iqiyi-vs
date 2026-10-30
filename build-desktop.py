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
import tempfile
import zipfile
import hashlib

ROOT = Path(__file__).resolve().parent
SOURCES = (
    "desktop.py", "manager_window.py", "launcher.py", "apply-vi.py", "watch-players.py", "subtitle_app.py",
    "iqiyi_common.py", "windows_runtime.py", "cdp.py", "app_integration.py",
    "iqcom_requests.py", "iqcom_session.py", "iqcom_audio.py", "proxy_support.py",
    "translation_ai.py", "translation_srt.py", "translation_pipeline.py", "translation_ui.html",
    "README.md", "requirements.txt",
    "assets/iqiyi-logo.svg", "assets/iqiyi.ico",
)
EXTENSION = ("manifest.json", "content.js", "sub-hook.js", "proxy.js", "https-rules.json",
             "iqcom-bootstrap.js", "iqcom-session.js", "session-bridge.js", "local-api.js", "local-api-worker.js",
             "public-api-worker.js", "audio-worker.js", "audio-player.html", "audio-player.js")


def validate_extension(folder: Path):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    references = [manifest["background"]["service_worker"]]
    for script in manifest.get("content_scripts", []):
        references.extend(script.get("js", []))
        references.extend(script.get("css", []))
    references.extend(manifest.get("icons", {}).values())
    for resource in manifest.get("web_accessible_resources", []):
        references.extend(resource["resources"])
    for rule in manifest.get("declarative_net_request", {}).get("rule_resources", []):
        references.append(rule["path"])
    for name in references:
        if name not in EXTENSION or not (folder / name).is_file():
            raise FileNotFoundError("Tiện ích thiếu tài nguyên được manifest tham chiếu: " + name)
    return manifest


def build(output: Path, installer: bool = False):
    if os.name != "nt" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("Build bằng Python x64 trên Windows.")
    archive = output.parent / (output.name + ".zip")
    setup = output.parent / (output.name + "-Setup.exe")
    if output.exists() or archive.exists() or (installer and setup.exists()):
        raise FileExistsError("Đích đã tồn tại; chọn thư mục mới bằng --output để giữ dữ liệu cũ.")
    compiler = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    if not compiler.is_file():
        raise RuntimeError("Thiếu compiler .NET Framework 4.x (csc.exe).")
    base = Path(sys.base_prefix)
    if not all((base / name).is_file() for name in ("python.exe", "pythonw.exe")):
        raise RuntimeError("Cần bản CPython Windows đầy đủ để đóng gói runtime.")
    missing = [name for name in (*SOURCES, *("ext/" + item for item in EXTENSION)) if not (ROOT / name).is_file()]
    if missing:
        raise FileNotFoundError("Thiếu mã nguồn đóng gói: " + ", ".join(missing))
    manifest = validate_extension(ROOT / "ext")
    output.mkdir(parents=True)
    for name in SOURCES:
        (output / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, output / name)
    (output / "ext").mkdir()
    for name in EXTENSION:
        shutil.copy2(ROOT / "ext" / name, output / "ext" / name)
    validate_extension(output / "ext")
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
                    "--only-binary=:all:", "--no-binary=proxy-tools", "--target", str(runtime / "Lib/site-packages"),
                    "-r", str(ROOT / "requirements.txt")], check=True)
    subprocess.run([str(compiler), "/nologo", "/target:winexe", "/platform:x64", "/optimize+",
                    "/win32icon:" + str(ROOT / "assets/iqiyi.ico"),
                    "/reference:System.Windows.Forms.dll", "/out:" + str(output / "IQIYI-VI.exe"),
                    str(ROOT / "packaging/DesktopLauncher.cs")], check=True)
    subprocess.run([str(runtime / "python.exe"), str(output / "desktop.py"), "--check"],
                   cwd=output, check=True, timeout=90)
    dependencies = subprocess.check_output([
        str(runtime / "python.exe"), "-c",
        "import importlib.metadata,json; print(json.dumps({d.metadata['Name']:d.version for d in importlib.metadata.distributions()}))",
    ], text=True, encoding="utf-8")
    (output / "build-info.json").write_text(json.dumps({
        "version": manifest["version"],
        "python": platform.python_version(), "platform": "Windows x64",
        "dependencies": json.loads(dependencies),
    }, indent=2), encoding="utf-8")
    version = json.loads((output / "build-info.json").read_text(encoding="utf-8"))["version"]
    installer_source = (ROOT / "packaging/AppInstaller.cs").read_text(encoding="utf-8").replace("__VERSION__", version)
    def compile_installer(target: Path, *options):
        with tempfile.TemporaryDirectory(prefix="iqiyi-compiler-") as temporary:
            source = Path(temporary) / "AppInstaller.cs"
            source.write_text(installer_source, encoding="utf-8-sig")
            subprocess.run([str(compiler), "/nologo", "/target:winexe", "/platform:x64", "/optimize+",
                            "/win32icon:" + str(ROOT / "assets/iqiyi.ico"),
                            *["/reference:" + item + ".dll" for item in (
                                "System.Windows.Forms", "System.Drawing", "System.IO.Compression",
                                "System.IO.Compression.FileSystem", "System.Web.Extensions")],
                            "/out:" + str(target), *options, str(source)], check=True)
    if installer:
        compile_installer(output / "Uninstall.exe", "/define:UNINSTALLER")
    # No local library, auth files, backups, browser sessions, tests or audits enter the package.
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in output.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                bundle.write(path, Path(output.name) / path.relative_to(output))
    print(f"APP: {output / 'IQIYI-VI.exe'}")
    print(f"ZIP: {archive} ({archive.stat().st_size / 1024 / 1024:.1f} MB)")
    archive.with_suffix(".zip.sha256").write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n", encoding="ascii")
    if installer:
        compile_installer(setup, "/resource:" + str(archive) + ",app.zip")
        with tempfile.TemporaryDirectory(prefix="iqiyi-package-check-") as temporary:
            report = Path(temporary) / "check.json"
            result = subprocess.run([str(setup), "--check-package", str(report)], timeout=180)
            if result.returncode or not report.is_file() or not json.loads(report.read_text())["ok"]:
                raise RuntimeError("Bộ cài chưa qua kiểm tra giải nén và chạy runtime.")
        checksum = hashlib.sha256(setup.read_bytes()).hexdigest()
        setup.with_suffix(".sha256").write_text(checksum + "  " + setup.name + "\n", encoding="ascii")
        print(f"SETUP: {setup} ({setup.stat().st_size / 1024 / 1024:.1f} MB)")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/IQIYI-VI-Windows-x64")
    parser.add_argument("--installer", action="store_true", help="Tạo thêm bộ cài Windows cho tài khoản hiện tại")
    args = parser.parse_args()
    build(args.output.resolve(), args.installer)


if __name__ == "__main__":
    main()
