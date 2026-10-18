# -*- coding: utf-8 -*-
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
user32 = ctypes.windll.user32
user32.SetProcessDPIAware()
EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
BM_CLICK = 0x00F5
WM_COMMAND = 0x0111
IDNO = 7
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


def pids() -> set[int]:
    raw = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command",
         "(Get-Process QyClient,QyPlayer -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }) -join ','"],
        encoding="utf-8", errors="replace",
    )
    return {int(x) for x in raw.replace("\r", "").replace("\n", "").split(",") if x.strip().isdigit()}


def enum_windows(pidset: set[int] | None = None):
    found = []

    def cb(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pidset is not None and pid.value not in pidset:
            return True
        vis = bool(user32.IsWindowVisible(hwnd))
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        found.append({
            "hwnd": hwnd, "pid": pid.value, "vis": vis, "cls": cls.value, "title": buf.value,
            "w": rect.right - rect.left, "h": rect.bottom - rect.top,
            "l": rect.left, "t": rect.top, "r": rect.right, "b": rect.bottom,
        })
        return True

    user32.EnumWindows(EnumWindowsProc(cb), 0)
    return found


def children(hwnd):
    out = []

    def cb(ch, _):
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(ch, cls, 256)
        n = user32.GetWindowTextLengthW(ch)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(ch, buf, n + 1)
        out.append((ch, cls.value, buf.value))
        return True

    user32.EnumChildWindows(hwnd, EnumWindowsProc(cb), 0)
    return out


def click_xy(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def grab(win, name):
    user32.ShowWindow(win["hwnd"], 9)
    user32.SetForegroundWindow(win["hwnd"])
    time.sleep(0.25)
    img = ImageGrab.grab(bbox=(win["l"], win["t"], win["r"], win["b"]), all_screens=True)
    img.save(OUT / name)
    print("saved", name, img.size, win["cls"], win["title"][:40])
    return img


def dismiss_dialogs(wins):
    for w in wins:
        if not w["vis"]:
            continue
        if w["cls"] == "#32770":
            print("dialog", w["title"], children(w["hwnd"]))
            for ch, cls, text in children(w["hwnd"]):
                if text.strip() in ("No", "否", "&No", "取消", "Cancel"):
                    print("click child", text)
                    user32.SetForegroundWindow(w["hwnd"])
                    user32.SendMessageW(ch, BM_CLICK, 0, 0)
                    return True
            user32.SetForegroundWindow(w["hwnd"])
            user32.SendMessageW(w["hwnd"], WM_COMMAND, IDNO, 0)
            return True
        if w["cls"] == "UIUpdateDlgx":
            print("update dlg", children(w["hwnd"]))
            for ch, cls, text in children(w["hwnd"]):
                if text.strip() in ("关闭", "Close", "取消"):
                    print("click", text)
                    user32.SendMessageW(ch, BM_CLICK, 0, 0)
                    return True
            # close button near top-right of dialog
            click_xy(w["l"] + w["w"] - 24, w["t"] + 18)
            return True
    return False


def main():
    pidset = pids()
    print("pids", pidset)
    for i in range(35):
        wins = enum_windows(pidset)
        vis = [w for w in wins if w["vis"]]
        print(f"--- {i}s vis={len(vis)}")
        for w in vis:
            print(f"  {w['cls'][:40]:40} {w['w']:4}x{w['h']:<4} {w['title'][:50]}")
        if dismiss_dialogs(vis):
            time.sleep(0.6)
            continue
        content = [w for w in vis if w["w"] >= 900 and w["h"] >= 600 and "Splash" not in w["cls"] and "Shadow" not in w["cls"] and "Loadind" not in w["cls"]]
        splash = [w for w in vis if "Splash" in w["cls"] or "Loadind" in w["cls"]]
        target = content[0] if content else (max(vis, key=lambda w: w["w"] * w["h"]) if vis else None)
        if target:
            img = grab(target, f"ui{i:02d}.png")
            cx, cy = img.size[0] // 2, img.size[1] // 2
            print("center", img.getpixel((cx, cy)))
            # homepage usually has more than splash green logo
            if content and i >= 4:
                img.save(OUT / "player-now.png")
                img.crop((0, int(img.size[1] * 0.55), img.size[0], img.size[1])).save(OUT / "player-caption-band.png")
                # click likely continue-watching area: left-mid content
                click_xy(target["l"] + 280, target["t"] + 260)
                time.sleep(2)
                img2 = grab(target, "after-click.png")
                img2.save(OUT / "player-now.png")
                img2.crop((0, int(img2.size[1] * 0.55), img2.size[0], img2.size[1])).save(OUT / "player-caption-band.png")
                print("clicked continue-ish")
                if i >= 8:
                    break
        time.sleep(1.2)
    print("done")


if __name__ == "__main__":
    main()
