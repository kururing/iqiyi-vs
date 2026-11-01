"""Exercise the installer's actual file operations, entirely inside a temporary folder."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
with tempfile.TemporaryDirectory(prefix="iqiyi-installer-test-") as folder:
    output = Path(folder) / "check.exe"
    subprocess.run([str(compiler), "/nologo", "/target:exe", "/platform:x64", "/main:InstallerFiles",
                    *["/reference:" + name + ".dll" for name in (
                        "System.Windows.Forms", "System.Drawing", "System.IO.Compression",
                        "System.IO.Compression.FileSystem", "System.Web.Extensions")],
                    "/out:" + str(output), str(ROOT / "packaging/AppInstaller.cs"),
                    str(ROOT / "tests/InstallerFiles.cs")], check=True)
    subprocess.run([str(output), folder], check=True, timeout=30)
