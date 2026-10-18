# -*- coding: utf-8 -*-
import ctypes
import time
import sys
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import subprocess

OUT = Path(r"D:\dev-cache\iqiyi-vi")
user32 = ctypes.windll.user32
user32.SetProcessDPIAware()
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def qy_pids():
    raw = subprocess.check_output(
        "powershell -NoProfile -Command \"Get-Process QyClient,QyPlayer -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id\"",
        shell=True, encoding="utf-8", errors="replace",
    )
    return {int(x) for x in raw.split() if x.isdigit()}


def content_window(pids):
    found = []

    def cb(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids or not user32.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        name = cls.value
        if w >= 900 and h >= 600 and "Shadow" not in name and "Splash" not in name and "Loadind" not in name:
            found.append((hwnd, name, w, h, rect.left, rect.top, rect.right, rect.bottom))
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found


def click(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.08)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def grab(hwnd, name):
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True)
    img.save(OUT / name)
    img.crop((0, int(img.size[1] * 0.52), img.size[0], img.size[1])).save(OUT / "player-caption-band.png")
    print("saved", name, img.size)
    return img, rect


def main():
    pids = qy_pids()
    print("pids", pids)
    wins = content_window(pids)
    print("wins", wins)
    hwnd, name, w, h, l, t, r, b = wins[0]
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.4)
    grab(hwnd, "before-play.png")
    # Continue-watching first card (Dinh Phong Ba)
    x, y = l + int(w * 0.22), t + int(h * 0.78)
    print("click continue", x, y)
    click(x, y)
    time.sleep(10)
    grab(hwnd, "player-now.png")
    # if still homepage, try Chen Xuan card
    time.sleep(1)
    wins = content_window(pids)
    hwnd, name, w, h, l, t, r, b = wins[0]
    x2, y2 = l + int(w * 0.40), t + int(h * 0.78)
    print("click chen xuan", x2, y2)
    click(x2, y2)
    time.sleep(10)
    grab(hwnd, "player-now.png")


if __name__ == "__main__":
    main()
