"""Run: python -m unittest discover -s tests -p test_native_context_menu.py"""
import importlib.util
import hashlib
import struct
import tempfile
from unittest.mock import patch
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("native_patcher", ROOT / "apply-vi.py")
patcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patcher)


class NativeContextMenuTest(unittest.TestCase):
    def native_fixture(self):
        raw = bytearray(8452480)
        struct.pack_into('<I', raw, 60, 0x100)
        struct.pack_into('<I', raw, 624, 2503042)
        for reference, original, zh, _ in patcher.NATIVE_MENU_STRINGS:
            raw[original:original + len(zh.encode()) + 1] = zh.encode() + b'\0'
            raw[reference:reference + 3] = b'\x48\x8d\x15'
            target = 5074944 + original - 5068800
            struct.pack_into('<i', raw, reference + 3, target - (4096 + reference - 1024 + 7))
        return bytes(raw)

    def test_dynamic_native_labels_patch_only_verified_references_and_empty_padding(self):
        raw = self.native_fixture()
        self.assertIsNone(patcher.native_menu_bytes(raw), 'Unknown DLL builds must remain untouched')
        with patch.object(patcher, 'NATIVE_MENU_SOURCE_SHA256', hashlib.sha256(raw).hexdigest()):
            result = patcher.native_menu_bytes(raw)
        self.assertEqual(len(raw), len(result))
        allowed = set(range(624, 628)) | set(range(0x158, 0x15c))
        allowed.update(range(5068800 + 2503048, 5068800 + 2503168))
        for reference, _, _, vi in patcher.NATIVE_MENU_STRINGS:
            allowed.update(range(reference + 3, reference + 7))
            target = 4096 + reference - 1024 + 7 + struct.unpack_from('<i', result, reference + 3)[0]
            offset = 5068800 + target - 5074944
            self.assertEqual(result[offset:offset + len(vi.encode()) + 1], vi.encode() + b'\0')
        self.assertTrue(all(i in allowed for i, (old, new) in enumerate(zip(raw, result)) if old != new))
        with patch.object(patcher, 'NATIVE_MENU_PATCHED_SHA256', hashlib.sha256(result).hexdigest()):
            self.assertEqual(patcher.native_menu_bytes(result), result)
        damaged = bytearray(raw)
        damaged[5068800 + 2503048] = 1
        with patch.object(patcher, 'NATIVE_MENU_SOURCE_SHA256', hashlib.sha256(damaged).hexdigest()):
            with self.assertRaises(ValueError):
                patcher.native_menu_bytes(bytes(damaged))

    def test_native_menu_backup_restore_and_app_updates(self):
        raw = self.native_fixture()
        with patch.object(patcher, 'NATIVE_MENU_SOURCE_SHA256', hashlib.sha256(raw).hexdigest()):
            localized = patcher.native_menu_bytes(raw)
            with (tempfile.TemporaryDirectory() as temp,
                  patch.object(patcher, 'NATIVE_MENU_PATCHED_SHA256', hashlib.sha256(localized).hexdigest()),
                  patch.object(patcher, 'BACKUP', Path(temp) / 'backup')):
                install = Path(temp) / 'version'; install.mkdir()
                path = install / 'player.dll'; path.write_bytes(raw)
                self.assertTrue(patcher.patch_native_menu_labels(install))
                self.assertEqual(path.read_bytes(), localized)
                self.assertFalse(patcher.patch_native_menu_labels(install))
                self.assertTrue(patcher.patch_native_menu_labels(install, restore=True))
                self.assertEqual(path.read_bytes(), raw)
                path.write_bytes(b'new app version')
                self.assertFalse(patcher.patch_native_menu_labels(install, restore=True))
                self.assertEqual(path.read_bytes(), b'new app version')

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
