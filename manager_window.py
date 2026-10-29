"""The manager's frameless WebView2 window; closing it leaves the service running."""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TITLE = "iQIYI – Quản lý phụ đề"


def install_titlebar(window):
    # Native controls stay usable while an HTML settings/translation dialog is open.
    import ctypes
    from ctypes import wintypes
    from System.Drawing import ColorTranslator, ContentAlignment, Font, GraphicsUnit, Pen, Size, SolidBrush
    from System.Drawing.Drawing2D import SmoothingMode
    from System.Windows.Forms import (Button, ColumnStyle, DockStyle, FlatStyle, FormWindowState,
                                      Label, MouseButtons, Padding, RowStyle, Screen, SizeType,
                                      TableLayoutPanel, ToolTip)

    form = window.native
    user32 = ctypes.WinDLL("user32")
    user32.ReleaseCapture.argtypes = []
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
    hwnd = form.Handle.ToInt64()
    style = user32.GetWindowLongW(hwnd, -16)
    user32.SetWindowLongW(hwnd, -16, style | 0x40000 | 0x20000 | 0x10000)  # resize/minimize/maximize
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.CallWindowProcW.restype = ctypes.c_ssize_t
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    class MINMAXINFO(ctypes.Structure):
        _fields_ = [(name, wintypes.POINT) for name in
                    ("ptReserved", "ptMaxSize", "ptMaxPosition", "ptMinTrackSize", "ptMaxTrackSize")]

    @callback_type
    def frame_proc(handle, message, wparam, lparam):
        # Own both NCCALCSIZE forms and frame painting; otherwise Windows can
        # reintroduce its light resize frame when the window loses focus.
        if message in (0x83, 0x85):  # WM_NCCALCSIZE / WM_NCPAINT
            return 0
        if message == 0x86 and form.WindowState != FormWindowState.Minimized:  # WM_NCACTIVATE
            return user32.CallWindowProcW(previous_proc, handle, message, wparam, -1)
        result = user32.CallWindowProcW(previous_proc, handle, message, wparam, lparam)
        if message == 0x24:  # WM_GETMINMAXINFO
            # Borderless WinForms otherwise maximizes over the taskbar. Read the
            # current monitor each time, including after moving between screens.
            screen = Screen.FromHandle(form.Handle)
            work, monitor = screen.WorkingArea, screen.Bounds
            limits = MINMAXINFO.from_address(lparam)
            limits.ptMaxPosition.x = work.Left - monitor.Left
            limits.ptMaxPosition.y = work.Top - monitor.Top
            limits.ptMaxSize.x = work.Width
            limits.ptMaxSize.y = work.Height
            return 0
        if message == 0x84 and result == 1 and not user32.IsZoomed(handle):  # WM_NCHITTEST
            rect = wintypes.RECT()
            user32.GetWindowRect(handle, ctypes.byref(rect))
            x, y = ctypes.c_short(lparam & 0xffff).value, ctypes.c_short((lparam >> 16) & 0xffff).value
            grip = max(5, round(6 * form.DeviceDpi / 96))
            column = 0 if x < rect.left + grip else 2 if x >= rect.right - grip else 1
            row = 0 if y < rect.top + grip else 2 if y >= rect.bottom - grip else 1
            return ((13, 12, 14), (10, 1, 11), (16, 15, 17))[row][column]
        return result

    previous_proc = user32.SetWindowLongPtrW(hwnd, -4, ctypes.cast(frame_proc, ctypes.c_void_p))
    form._manager_frameproc = frame_proc  # Keep the native callback alive until the form is destroyed.
    form.BackColor = ColorTranslator.FromHtml("#2b3035")

    def update_border(*_):
        form.Padding = Padding(0 if user32.IsZoomed(hwnd) else 1)

    form.Resize += update_border
    update_border()
    # Keep the resize frame dark even when Windows uses its light app theme.
    dwm = ctypes.WinDLL("dwmapi")
    dwm.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    for attribute, value in ((20, 1), (34, 0x1D1A17), (35, 0x1D1A17)):
        setting = ctypes.c_int(value)
        dwm.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(setting), ctypes.sizeof(setting))
    user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x37)  # refresh the frame, keep bounds/focus
    background = ColorTranslator.FromHtml("#171a1d")
    foreground = ColorTranslator.FromHtml("#c3c8ce")
    height = round(40 * form.DeviceDpi / 96)
    frame = TableLayoutPanel()
    frame.Dock = DockStyle.Fill
    frame.Margin = frame.Padding = Padding(0)
    frame.BackColor = background
    frame.ColumnCount, frame.RowCount = 1, 2
    frame.ColumnStyles.Add(ColumnStyle(SizeType.Percent, 100))
    frame.RowStyles.Add(RowStyle(SizeType.Absolute, height))
    frame.RowStyles.Add(RowStyle(SizeType.Percent, 100))
    bar = TableLayoutPanel()
    bar.AccessibleName = "Thanh tiêu đề"
    bar.BackColor = background
    bar.Dock = DockStyle.Fill
    bar.Margin = bar.Padding = Padding(0)
    bar.ColumnCount, bar.RowCount = 4, 1
    bar.ColumnStyles.Add(ColumnStyle(SizeType.Percent, 100))
    for _ in range(3):
        bar.ColumnStyles.Add(ColumnStyle(SizeType.Absolute, height))
    bar.RowStyles.Add(RowStyle(SizeType.Percent, 100))
    form.SuspendLayout()
    form.Controls.Remove(form.webview)
    form.webview.Margin = Padding(0)
    frame.Controls.Add(bar, 0, 0)
    frame.Controls.Add(form.webview, 0, 1)
    form.Controls.Add(frame)
    form.ResumeLayout(True)

    def toggle_maximize(*_):
        form.WindowState = (FormWindowState.Normal if form.WindowState == FormWindowState.Maximized
                            else FormWindowState.Maximized)

    def drag(_, event):
        if event.Button == MouseButtons.Left:
            user32.ReleaseCapture()
            user32.SendMessageW(hwnd, 0xA1, 2, 0)  # WM_NCLBUTTONDOWN / HTCAPTION

    title = Label()
    title.Text = TITLE
    title.ForeColor = foreground
    title.BackColor = background
    title.Font = Font("Segoe UI", 13, GraphicsUnit.Pixel)
    title.Padding = Padding(16, 0, 0, 0)
    title.TextAlign = ContentAlignment.MiddleLeft
    title.Dock = DockStyle.Fill
    title.Margin = Padding(0)
    title.MouseDown += drag
    title.DoubleClick += toggle_maximize
    bar.Controls.Add(title, 0, 0)
    tips = ToolTip()

    def add_button(action, label, column):
        button = Button()
        button.AccessibleName = label
        button.Name = "window-" + action
        button.TabIndex = {"minimize": 0, "maximize": 1, "close": 2}[action]
        button.Size = Size(height, height)
        button.Dock = DockStyle.Fill
        button.Margin = Padding(0)
        button.FlatStyle = FlatStyle.Flat
        button.FlatAppearance.BorderSize = 0
        button.FlatAppearance.MouseOverBackColor = background
        button.FlatAppearance.MouseDownBackColor = background
        button.BackColor = background
        tips.SetToolTip(button, label)
        hovered = [False]

        def hover(value):
            hovered[0] = value
            button.Invalidate()

        def paint(_, event):
            g = event.Graphics
            g.SmoothingMode = SmoothingMode.AntiAlias
            scale = button.Height / 44
            g.ScaleTransform(scale, scale)
            if action == "close" or hovered[0]:
                color = "#43474b" if hovered[0] else "#2b2e32"
                brush = SolidBrush(ColorTranslator.FromHtml(color))
                g.FillEllipse(brush, 6, 6, 32, 32)
                brush.Dispose()
            pen = Pen(foreground, 1.5)
            if action == "minimize":
                g.DrawLine(pen, 16, 23, 28, 23)
            elif action == "maximize":
                if form.WindowState == FormWindowState.Maximized:
                    g.DrawRectangle(pen, 19, 15, 10, 10)
                    brush = SolidBrush(background)
                    g.FillRectangle(brush, 15, 19, 10, 10)
                    brush.Dispose()
                    g.DrawRectangle(pen, 15, 19, 10, 10)
                else:
                    g.DrawRectangle(pen, 16, 16, 12, 12)
            else:
                g.DrawLine(pen, 17, 17, 27, 27)
                g.DrawLine(pen, 27, 17, 17, 27)
            pen.Dispose()

        button.Paint += paint
        button.MouseEnter += lambda *_: hover(True)
        button.MouseLeave += lambda *_: hover(False)
        if action == "close":
            button.Click += lambda *_: form.Close()
        elif action == "minimize":
            button.Click += lambda *_: setattr(form, "WindowState", FormWindowState.Minimized)
        else:
            button.Click += toggle_maximize
            form.Resize += lambda *_: button.Invalidate()
        bar.Controls.Add(button, column, 0)

    for column, (action, label) in enumerate((("minimize", "Thu nhỏ"), ("maximize", "Phóng to / Khôi phục"), ("close", "Đóng")), 1):
        add_button(action, label, column)
    # Keep the tooltip alive for the lifetime of its native controls.
    form._manager_tooltips = tips
    form._manager_titlebar = bar


def main():
    import webview
    from desktop import URL, ensure_manager
    from windows_runtime import create_named_mutex

    key = hashlib.sha256(str(ROOT).casefold().encode()).hexdigest()[:16]
    instance = create_named_mutex("Local\\IQIYI-VI-ManagerWindow-" + key)
    if instance is None:
        return 0
    ensure_manager()
    window = webview.create_window(
        TITLE, URL, width=1280, height=850, min_size=(760, 520),
        frameless=True, easy_drag=False, shadow=True, background_color="#101214",
    )
    window.events.before_show += install_titlebar
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.start(gui="edgechromium", private_mode=False,
                  storage_path=str(ROOT / ".local" / "manager-webview"),
                  icon=str(ROOT / "assets" / "iqiyi.ico"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
