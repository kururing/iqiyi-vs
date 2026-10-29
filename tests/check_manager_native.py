"""Exercise the real Windows titlebar with an isolated WebView2 test window."""
from pathlib import Path
import base64
import json
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import manager_window
import subtitle_app
import webview

failures = []
done = threading.Event()
page = subtitle_app.PAGE.replace("__IQIYI_TOKEN__", '"fixture-token"')
fixture = """<script>window.fetch=async url=>new Response(JSON.stringify(String(url).includes('app-localization')?
{status:'idle',installed:true}:String(url).includes('/episodes')?{episodes:Array.from({length:12},(_,i)=>({tvid:String(i+1),provider:'iqiyi',albumId:String(i+100),albumTitle:'Thư Quyển Nhất Mộng '+(i+1),order:1,downloaded:false,cues:0}))}:{}),{status:200});</script>"""
page = page.replace("<title>", fixture + "<title>", 1)
window = webview.create_window("Manager titlebar check", html=page,
                               width=1000, height=700, frameless=True, easy_drag=False, shadow=True)
window.events.before_show += manager_window.install_titlebar

def check():
    import ctypes
    from ctypes import wintypes
    from System import Action, Array, Byte, Func, Object
    from System.Drawing import Bitmap, Graphics, Rectangle
    from System.Drawing.Imaging import ImageFormat
    from System.IO import MemoryStream
    from System.Windows.Forms import FormWindowState, Screen

    def run():
        try:
            form = window.native
            bar = form._manager_titlebar
            controls = {control.Name: control for control in bar.Controls if control.Name}
            assert controls["window-minimize"].Left < controls["window-maximize"].Left < controls["window-close"].Left
            title = next(control for control in bar.Controls if control.Text == manager_window.TITLE)
            assert title.Right <= controls["window-minimize"].Left
            assert form.webview.Top >= bar.Bottom, (form.webview.Top, bar.Bottom)
            assert form.webview.Parent == bar.Parent
            assert form.ClientSize.Width == form.Width and form.ClientSize.Height == form.Height
            assert form.Padding.Left == form.Padding.Top == form.Padding.Right == form.Padding.Bottom == 1
            assert bar.Parent.Left == bar.Parent.Top == 1
            assert form.ClientSize.Width - bar.Parent.Right == form.ClientSize.Height - bar.Parent.Bottom == 1
            user32 = ctypes.WinDLL("user32")
            user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.SendMessageW.restype = ctypes.c_ssize_t
            hwnd = form.Handle.ToInt64()
            # Both NCCALCSIZE forms must keep Windows from reserving a native frame.
            rect = wintypes.RECT(0, 0, form.Width, form.Height)
            user32.SendMessageW(hwnd, 0x83, 0, ctypes.addressof(rect))
            actual = (rect.left, rect.top, rect.right, rect.bottom)
            assert actual == (0, 0, form.Width, form.Height), actual
            user32.GetWindowDC.argtypes = [wintypes.HWND]
            user32.GetWindowDC.restype = wintypes.HDC
            user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
            gdi32 = ctypes.WinDLL("gdi32")
            gdi32.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
            gdi32.GetPixel.restype = wintypes.DWORD

            def check_dark_frame():
                for active in (0, 1):
                    user32.SendMessageW(hwnd, 0x86, active, 0)  # Focus change
                    user32.SendMessageW(hwnd, 0x85, 1, 0)  # Explicit frame repaint
                    dc = user32.GetWindowDC(hwnd)
                    try:
                        for y in range(7):
                            color = gdi32.GetPixel(dc, form.Width // 2, y)
                            assert max(color & 255, (color >> 8) & 255, (color >> 16) & 255) < 128, (active, y, hex(color))
                    finally:
                        user32.ReleaseDC(hwnd, dc)

            check_dark_frame()
            bitmap = Bitmap(bar.Width, bar.Height)
            bar.DrawToBitmap(bitmap, Rectangle(0, 0, bar.Width, bar.Height))
            output = manager_window.ROOT / ".local" / "repairs" / "manager-titlebar.png"
            output.parent.mkdir(parents=True, exist_ok=True)
            bitmap.Save(str(output), ImageFormat.Png)
            bitmap.Dispose()
            frame = bar.Parent
            full = Bitmap(form.ClientSize.Width, form.ClientSize.Height)
            form.DrawToBitmap(full, Rectangle(0, 0, form.ClientSize.Width, form.ClientSize.Height))
            graphics = Graphics.FromImage(full)
            stream = MemoryStream(Array[Byte](browser_image))
            browser_bitmap = Bitmap(stream)
            bounds = form.webview.Bounds
            bounds.Offset(frame.Left, frame.Top)
            graphics.DrawImage(browser_bitmap, bounds)
            full.Save(str(output.with_name("manager-window-layout.png")), ImageFormat.Png)
            browser_bitmap.Dispose()
            stream.Dispose()
            graphics.Dispose()
            full.Dispose()
            for width in (800, 1200):
                form.Width = width
                assert form.webview.Top >= bar.Bottom
                assert controls["window-minimize"].Left < controls["window-maximize"].Left < controls["window-close"].Left
            controls["window-maximize"].PerformClick()
            assert form.WindowState == FormWindowState.Maximized
            area = Screen.FromHandle(form.Handle).WorkingArea
            assert form.Bounds == area, (str(form.Bounds), str(area))
            assert form.ClientSize == form.Size, "Maximized content must fill the work area"
            assert form.Padding.Left == form.Padding.Top == form.Padding.Right == form.Padding.Bottom == 0
            check_dark_frame()
            controls["window-maximize"].PerformClick()
            assert form.WindowState == FormWindowState.Normal
            assert form.ClientSize.Width == form.Width and form.ClientSize.Height == form.Height
            assert form.Padding.Left == form.Padding.Top == form.Padding.Right == form.Padding.Bottom == 1
            controls["window-minimize"].PerformClick()
            assert form.WindowState == FormWindowState.Minimized
            form.WindowState = FormWindowState.Normal
            check_dark_frame()
            controls["window-close"].PerformClick()
        except Exception as error:
            failures.append(error)
            window.native.Close()
        finally:
            done.set()

    window.events.loaded.wait(20)
    task = window.native.Invoke(Func[Object](lambda: window.native.browser.webview.CoreWebView2.CallDevToolsProtocolMethodAsync("Page.captureScreenshot", '{"format":"png"}')))
    deadline = time.monotonic() + 15
    while not task.IsCompleted and time.monotonic() < deadline:
        time.sleep(0.02)
    assert task.IsCompleted, "WebView2 screenshot did not finish"
    browser_image = base64.b64decode(json.loads(str(task.Result))["data"])
    window.evaluate_js("document.getElementById('appSettings').showModal()")
    window.native.Invoke(Action(run))

# WebView2 can hold its metrics file briefly after the form has closed.
with tempfile.TemporaryDirectory(prefix="iq-titlebar-check-", ignore_cleanup_errors=True) as profile:
    webview.start(check, gui="edgechromium", storage_path=profile, private_mode=False)
assert done.is_set(), "Native check did not finish"
if failures:
    raise failures[0]
print("PASS: frame stays dark across focus changes, maximize/restore and minimize; taskbar bounds and titlebar controls work")
