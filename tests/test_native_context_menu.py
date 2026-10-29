"""Run: python -m unittest discover -s tests -p test_native_context_menu.py"""
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("native_patcher", ROOT / "apply-vi.py")
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)


class NativeContextMenuTest(unittest.TestCase):
    def test_player_menu_and_submenu_are_translated_with_room_for_labels(self):
        labels = ["打开本地文件", "全屏", "小窗模式", "窗口置顶", "画面缩放", "倍速", "截图分享",
                  "定时关机", "快捷键", "在线升级", "反馈与修复", "设置", "铺满(保持比例)", "铺满(拉伸画面)", "原始尺寸"]
        raw = ('<Window><Menu name="menu_root" width="200" minwidht="200" '
               'submenuarrownormalimage="file=\'arrow.svg\' dest=\'166,11,178,23\'">' +
               ''.join(f'<MenuElement text="{label}" width="140" height="40"/>' for label in labels) +
               '</Menu></Window>')
        translated, hits = patcher.patch_text(raw, patcher.load_prepared_ui())
        self.assertEqual(hits, len(labels))
        self.assertFalse(patcher.CJK_RE.search(translated))
        for name in ("right_menu.xml", "right_menu_wine.xml"):
            path = Path("player/menu") / name
            result = patcher.patch_native_context_menu(translated, path)
            self.assertIn('width="240"', result)
            self.assertNotIn('width="140"', result)
            self.assertIn("206,11,218,23", result)
            self.assertEqual(patcher.patch_native_context_menu(result, path), result)
        self.assertEqual(patcher.patch_native_context_menu(raw, Path("other.xml")), raw)


if __name__ == "__main__":
    unittest.main()
