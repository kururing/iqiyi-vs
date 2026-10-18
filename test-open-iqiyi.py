# -*- coding: utf-8 -*-
"""Launch China iQIYI (QyClient) and capture the player window."""
from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = Path(r"D:\dev-cache\iqiyi-vi")
OUT.mkdir(parents=True, exist_ok=True)
EXE = Path(r"C:\Program Files\IQIYI Video\LStyle\QyClient.exe")

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def qy_pids() -> set[int]:
    pids = set()
    try:
        raw = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process QyClient,QyPlayer -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }) -join ','"],
            encoding="utf-8", errors="replace",
        )
        pids = {int(x) for x in raw.replace("\r", "").replace("\n", "").split(",") if x.strip().isdigit()}
    except Exception as exc:
        print("pids err", exc)
    return pids


def windows_for(pids: set[int]) -> list[tuple]:
    found = []

    def cb(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pids and pid.value not in pids:
            return True
        vis = bool(user32.IsWindowVisible(hwnd))
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        found.append((hwnd, pid.value, vis, cls.value, buf.value, w, h, rect.left, rect.top, rect.right, rect.bottom))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found


def click(x: int, y: int) -> None:
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def capture(name: str, box: tuple[int, int, int, int] | None = None):
    img = ImageGrab.grab(bbox=box, all_screens=True) if box else ImageGrab.grab(all_screens=True)
    path = OUT / name
    img.save(path)
    print("saved", path, img.size)
    return img


def kill_iqiyi() -> None:
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process QyClient,QyPlayer,QyKernel -ErrorAction SilentlyContinue | Stop-Process -Force"],
        check=False,
    )
    time.sleep(2)


def main() -> int:
    print("kill leftover")
    kill_iqiyi()
    print("start", EXE)
    subprocess.Popen([str(EXE)], cwd=str(EXE.parent))
    last_big = None
    for i in range(40):
        time.sleep(1)
        pids = qy_pids()
        wins = windows_for(pids)
        vis = [w for w in wins if w[2]]
        big = [w for w in vis if w[5] >= 400 and w[6] >= 300]
        print(f"t={i+1}s pids={pids} vis={len(vis)} big={len(big)}")
        for w in vis:
            print(" ", w[3], w[5], w[6], w[4][:60])
        if not big:
            continue
        best = max(big, key=lambda x: x[5] * x[6])
        hwnd, pid, visb, cls, title, w, h, l, t, r, b = best
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        img = capture(f"t{i+1:02d}.png", (l, t, r, b))
        last_big = best
        # Repair dialog: click No. Buttons were near center.
        pixels = img.getpixel((img.size[0] // 2, img.size[1] // 2))
        print(" center pixel", pixels)
        if i in (3, 6, 10, 15):
            # No button ~ a bit right of center, slightly below vertical center of dialog
            nx, ny = l + w // 2 + 40, t + h // 2 + 30
            print("click No at", nx, ny)
            click(nx, ny)
            time.sleep(0.4)
            # also try pressing Escape / N
            user32.PostMessageW(hwnd, 0x0100, 0x1B, 0)  # WM_KEYDOWN VK_ESCAPE
        if title and ("播放" in title or "player" in title.lower() or len(title) > 8) and i >= 12:
            capture("player-now.png", (l, t, r, b))
            img.crop((0, int(h * 0.58), w, h)).save(OUT / "player-caption-band.png")
            print("player captured", title)
            break
    else:
        if last_big:
            hwnd, pid, visb, cls, title, w, h, l, t, r, b = last_big
            img = capture("player-now.png", (l, t, r, b))
            img.crop((0, int(h * 0.58), w, h)).save(OUT / "player-caption-band.png")
    print("done pids", qy_pids())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
