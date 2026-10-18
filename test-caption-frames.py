# -*- coding: utf-8 -*-
import ctypes
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab

OUT = Path(r"D:\dev-cache\iqiyi-vi")
user32 = ctypes.windll.user32
user32.SetProcessDPIAware()
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


def qy_pids():
    raw = subprocess.check_output(
        'powershell -NoProfile -Command "Get-Process QyClient,QyPlayer -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"',
        shell=True, encoding="utf-8", errors="replace",
    )
    return {int(x) for x in raw.split() if x.isdigit()}


def player_hwnd(pids):
    found = []

    def cb(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids or not user32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if "QyWindow" not in cls.value:
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w >= 800 and h >= 400:
            found.append((hwnd, w * h, rect.left, rect.top, rect.right, rect.bottom, w, h))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return max(found, key=lambda x: x[1]) if found else None


def main():
    pids = qy_pids()
    win = player_hwnd(pids)
    print("win", win)
    if not win:
        return
    hwnd, _area, l, t, r, b, w, h = win
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    for i in range(10):
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True)
        band = img.crop((0, int(img.size[1] * 0.55), img.size[0], int(img.size[1] * 0.88)))
        img.save(OUT / f"cap{i:02d}.png")
        band.save(OUT / f"band{i:02d}.png")
        print("saved", i, img.size)
        time.sleep(1.2)


if __name__ == "__main__":
    main()
