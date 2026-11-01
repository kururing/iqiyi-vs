"""Native caption writes stay within iQIYI and reject stale episode results."""
import ctypes
import unittest
from unittest.mock import Mock, patch

import windows_runtime as runtime


class WindowTitleTests(unittest.TestCase):
    def test_ownership_races_and_unrelated_windows(self):
        windows = {
            1: [10, '爱奇艺', 'main'],
            2: [10, '宁安如梦 第15集', 'QyWindow.GroupClass.BasicWindow'],
            3: [99, '爱奇艺', 'main'],  # Another process must never be changed.
            4: [10, '中文设置', 'dialog'],
            5: [10, '宁安如梦 第16集', 'QyWindow.GroupClass.BasicWindow'],
            6: [10, '宁安如梦 第17集', 'QyWindow.GroupClass.BasicWindow'],
            7: [10, '未知 第1集', 'QyWindow.GroupClass.BasicWindow'],
        }
        writes = []
        def owner(hwnd, output):
            output._obj.value = windows[hwnd][0]
        def text(hwnd, output, size):
            output.value = windows[hwnd][1]
        def kind(hwnd, output, size):
            output.value = windows[hwnd][2]
        def write(hwnd, message, wp, lp, flags, timeout, result):
            self.assertEqual((message, flags, timeout), (0x000C, 3, 250))
            writes.append((hwnd, ctypes.wstring_at(lp)))
            result._obj.value = 1
            return 1
        api = Mock()
        api.EnumWindows.side_effect = lambda visit, _: [visit(hwnd, 0) for hwnd in windows]
        api.GetWindowThreadProcessId.side_effect = owner
        api.GetWindowTextW.side_effect = text
        api.GetClassNameW.side_effect = kind
        api.SendMessageTimeoutW.side_effect = write
        def translate(titles):
            self.assertEqual(len(titles), 5)
            windows[5][1] = '宁安如梦 第18集'  # Native app changed episodes during lookup.
            windows[6][0] = 99  # Windows reused a handle for another process.
            return ['iQIYI', 'Ninh An Như Mộng · Tập 15', 'Tập 16', 'Tập 17', '未知']
        with patch.object(runtime, 'list_processes', return_value=[runtime.Process(10, 'QyClient.exe', '', '')]), \
             patch.object(ctypes, 'WinDLL', return_value=api):
            self.assertEqual(runtime.localize_iqiyi_window_titles(translate), 2)
        self.assertEqual(writes, [(1, 'iQIYI'), (2, 'Ninh An Như Mộng · Tập 15')])


if __name__ == '__main__':
    unittest.main()
