"""Run: python -m unittest test_no_legacy_dict"""
import json
from pathlib import Path
import runpy
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent

class NoLegacyDictionaryTests(unittest.TestCase):
    def test_installer_cannot_rebundle_legacy_files(self):
        module = runpy.run_path(str(ROOT / "apply-vi.py"))
        source = (ROOT / "ui-engine.js").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            for name in ("vi.json", "web-vi.json", "vi-overrides.json", "titles-vi.json"):
                (folder / name).write_text(json.dumps({"旧标签": "Nhãn cũ"}), encoding="utf-8")
            engine = folder / "ui-engine.js"
            engine.write_text(source, encoding="utf-8")
            for name in ("load_prepared_ui", "build_lwa_js"):
                module[name].__globals__.update(ROOT=folder, LWA_ENGINE=engine)
            copy = module["load_prepared_ui"]()
            self.assertEqual(copy["正片"], "Tập chính")
            self.assertNotIn("旧标签", copy)
            self.assertEqual(module["build_lwa_js"](), source)

    def test_native_popup_attributes_and_html_copy(self):
        module = runpy.run_path(str(ROOT / "apply-vi.py"))
        copy = module["load_prepared_ui"]()
        xml = '<Button text="关闭" tooltip="下一集" title="播放设置" data-title="关闭"/>'
        result, hits = module["patch_text"](xml, copy)
        self.assertEqual(hits, 3)
        self.assertIn('text="Đóng"', result)
        self.assertIn('data-title="关闭"', result)
        html = '<script>关闭</script><style>关闭</style><textarea>关闭</textarea><button>关闭</button>'
        result, hits = module["patch_text_nodes"](html, copy)
        self.assertEqual(hits, 1)
        self.assertEqual(result, '<script>关闭</script><style>关闭</style><textarea>关闭</textarea><button>Đóng</button>')
        result, _ = module["patch_text"]('<button title="未知提示"/>', {"未知提示": 'Dấu " & < >'})
        self.assertIn('&quot; &amp; &lt; &gt;', result)

    def test_extension_keeps_api_bootstrap_without_dictionary(self):
        manifest = json.loads((ROOT / "ext/manifest.json").read_text(encoding="utf-8"))
        scripts = [script for item in manifest["content_scripts"] for script in item["js"]]
        self.assertNotIn("vi-dict.js", scripts)
        self.assertIn("iqcom-bootstrap.js", scripts)
        for script in scripts:
            self.assertTrue((ROOT / "ext" / script).is_file(), script)
        bootstrap = (ROOT / "ext/iqcom-bootstrap.js").read_text(encoding="utf-8")
        self.assertIn("api/extension-token", bootstrap)
        self.assertNotIn("__iqiyiViDict", bootstrap)

if __name__ == "__main__":
    unittest.main()
