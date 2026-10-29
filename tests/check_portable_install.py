"""Verify one-time installation from the build allowlist in an isolated, fresh folder.

Run: python tests/check_portable_install.py
No Windows registry entries, services or user data are changed by this check.
"""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('portable_builder', ROOT / 'build-desktop.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

CHECK = r'''
import importlib.util, json, os, sys
from pathlib import Path
from unittest.mock import patch
root = Path.cwd()
sys.path.insert(0, str(root))
import app_integration as integration
import launcher
from windows_runtime import command_line_args
assert Path(integration.__file__).resolve().parent == root
assert not (root / '.local').exists(), 'The distributed app must start without developer state'
sid = 'S-1-5-21-444-555-666-1001'
admin_sid = 'S-1-5-21-444-555-666-500'
settings = {}
def read(key, name, user_sid):
    return settings.get((user_sid, key, name))
def write(key, name, value, user_sid):
    if value is None:
        settings.pop((user_sid, key, name), None)
    else:
        settings[user_sid, key, name] = value
def reject_process(*args, **kwargs):
    raise AssertionError('The privileged installation must not start a watcher or manager')
spec = importlib.util.spec_from_file_location('fresh_installer', root / 'apply-vi.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
with patch.object(integration, 'current_user_sid', return_value=sid):
    os.environ['APPDATA'] = str(root / 'User profile' / 'Roaming')
    os.environ['LOCALAPPDATA'] = str(root / 'User profile' / 'Local')
    args = integration.installer_args(root)
os.environ['APPDATA'] = str(root / 'Admin profile' / 'Roaming')
os.environ['LOCALAPPDATA'] = str(root / 'Admin profile' / 'Local')
with patch.object(integration, 'current_user_sid', return_value=admin_sid), \
     patch.object(integration, 'read_value', side_effect=read), \
     patch.object(integration, 'write_value', side_effect=write), \
     patch.object(installer, 'startup_vbs', return_value=root / '.local' / 'legacy.vbs'), \
     patch.object(launcher, 'script_processes', return_value=[]), \
     patch.object(launcher, 'stop_processes'), \
     patch.object(installer.subprocess, 'Popen', side_effect=reject_process), \
     patch.object(sys, 'argv', [args[0], '--install-integration', *args[1:]]):
    assert installer.main() == 0
    assert installer.APPDATA_LWA == root / 'User profile' / 'Roaming' / 'IQIYI Video' / 'localwebapp'
    assert installer.WRAPPER_APP == root / 'User profile' / 'Local' / 'Programs/iQIYI/resources/app'
    assert all(key[0] == sid for key in settings), 'UAC must preserve the original Windows user'
    command = command_line_args(settings[sid, integration.RUN_KEY, integration.RUN_NAME][0])
    assert Path(command[0]) == root / 'runtime' / 'pythonw.exe'
    assert Path(command[1]) == root / 'watch-players.py'
    assert command[2:] == ['iqiyi']
    first = integration.read_state(root)
    assert installer.main() == 0
    assert integration.read_state(root) == first, 'Repeat installation must preserve its backup'
    with patch.object(integration, 'current_user_sid', return_value=sid):
        assert integration.installed(root)
    integration.uninstall(root, sid)
    assert not settings, 'Uninstall must remove only this package integration'
print('Fresh portable install passed: dynamic Unicode path, bundled runtime, original user, UAC handoff, repeat install and uninstall.')
'''


def main():
    with tempfile.TemporaryDirectory(prefix='iq fresh package ') as temporary:
        bundle = Path(temporary) / 'Gói phát hành mới'
        for name in builder.SOURCES:
            destination = bundle / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
        for name in builder.EXTENSION:
            destination = bundle / 'ext' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / 'ext' / name, destination)
        (bundle / 'runtime').mkdir()
        for name in ('python.exe', 'pythonw.exe'):
            (bundle / 'runtime' / name).touch()  # Path selection only; never execute placeholder binaries.
        subprocess.run([sys.executable, '-I', '-B', '-X', 'utf8', '-'], cwd=bundle,
                       input=CHECK, text=True, encoding='utf-8', check=True, timeout=30)


if __name__ == '__main__':
    main()
