"""Run: python -m unittest test_static_ui_copy"""
import runpy
import unittest


class StaticUiCopyTests(unittest.TestCase):
    def test_player_menu_and_native_escaped_copy(self):
        module = runpy.run_path("apply-vi.py")
        copy = module["load_prepared_ui"]()
        expected = {
            "循环播放": "Phát lặp",
            "隔空手势": "Điều khiển bằng cử chỉ",
            "画面缩放": "Thu phóng hình ảnh",
            "原始尺寸": "Kích thước gốc",
            "常用快捷键": "Phím tắt thường dùng",
            "定时关机": "Hẹn giờ tắt máy",
            "播放问题诊断": "Chẩn đoán lỗi phát",
            "更多设置": "Cài đặt khác",
            "列表透明度": "Độ trong suốt danh sách",
            "歌词时间提前": "Hiển thị lời bài hát sớm hơn",
        }
        for source, translated in expected.items():
            self.assertEqual(copy[source], translated)
        xml = '<Option name="loop" text="循环播放" tooltip="常用快捷键"/>'
        patched, hits = module["patch_text"](xml, copy)
        self.assertEqual(hits, 2)
        self.assertEqual(patched, '<Option name="loop" text="Phát lặp" tooltip="Phím tắt thường dùng"/>')
        source = next(key for key in copy if key.startswith('<c #ffffff>感谢'))
        translated = copy[source]
        self.assertNotRegex(translated, r"[\u4e00-\u9fff]")
        self.assertIn("https://privacy.iqiyi.com/policies", translated)
        self.assertIn("privacy＠qiyi.com", translated)
        self.assertEqual(source.count("<"), translated.count("<"))
        from html import escape
        xml = '<Label text="' + escape(source, quote=True) + '"/>'
        patched, hits = module["patch_text"](xml, copy)
        self.assertEqual(hits, 1)
        self.assertIn(escape(translated, quote=True), patched)


if __name__ == "__main__":
    unittest.main()
