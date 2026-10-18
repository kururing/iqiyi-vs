# -*- coding: utf-8 -*-
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
user32 = ctypes.windll.user32
user32.SetProcessDPIAware()
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def qy_pids():
    raw = subprocess.check_output(
        'powershell -NoProfile -Command "Get-Process QyClient,QyPlayer -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"',
        shell=True, encoding="utf-8", errors="replace",
    )
    return {int(x) for x in raw.split() if x.isdigit()}


def windows(pids):
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
        if w >= 900 and h >= 500:
            found.append((hwnd, cls.value, w, h, rect.left, rect.top, rect.right, rect.bottom))
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
    img.crop((0, int(img.size[1] * 0.5), img.size[0], img.size[1])).save(OUT / "player-caption-band.png")
    print("saved", name, img.size)
    return img


def pick(wins, prefer):
    for w in wins:
        if prefer in w[1]:
            return w
    return max(wins, key=lambda x: x[2] * x[3])


def main():
    pids = qy_pids()
    print("pids", pids)
    wins = windows(pids)
    print("wins", [(w[1], w[2], w[3]) for w in wins])
    player = pick(wins, "QyWindow")
    hwnd, cls, w, h, l, t, r, b = player
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    print("home click")
    click(l + 28, t + 18)
    time.sleep(4)
    wins = windows(pids)
    home = pick(wins, "E7C66FDE")
    hwnd, cls, w, h, l, t, r, b = home
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    grab(hwnd, "home-again.png")
    print("click continue")
    click(l + int(w * 0.22), t + int(h * 0.78))
    time.sleep(8)
    wins = windows(pids)
    player = pick(wins, "QyWindow")
    grab(player[0], "player-now.png")


if __name__ == "__main__":
    main()
