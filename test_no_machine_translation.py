"""UI machine translation stays off while explicit subtitle translation remains available."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parent


class UiMachineTranslationBoundaryTests(unittest.TestCase):
    def test_runtime_sources_have_no_ui_translation_transport(self):
        remote_endpoint = "clients5" + ".google.com/translate_a/t"
        local_endpoint = "api/" + "ui-translate"
        worker_message = "iqiyi-vi-" + "translate"
        files = (
            "ui-engine.js", "lwa-vi.js", "ext/content.js",
            "ext/iqcom-bootstrap.js", "ext/proxy.js",
        )
        for name in files:
            source = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn(remote_endpoint, source, name)
            self.assertNotIn(local_endpoint, source, name)
            self.assertNotIn(worker_message, source, name)

        app = (ROOT / "subtitle_app.py").read_text(encoding="utf-8")
        self.assertNotIn(remote_endpoint, app)
        self.assertNotIn("translate_ui", app)
        self.assertNotIn("/api/ui-translate", app)
        self.assertNotIn("UI_TRANSLATION_DISABLED_MESSAGE", app)

        engine = (ROOT / "ui-engine.js").read_text(encoding="utf-8")
        self.assertNotIn("__iqiyiViAutoStatus", engine)
        self.assertNotIn("__iqiyiViAutoV", engine)
        self.assertNotIn("__iqiyiViDict", engine)
        self.assertNotIn("__iqiyiViTitles", engine)

        # This upstream is retained only for the explicitly requested Youku subtitle overlay.
        hook = (ROOT / "sub-hook.js").read_text(encoding="utf-8")
        extension_hook = (ROOT / "ext" / "sub-hook.js").read_text(encoding="utf-8")
        self.assertIn(remote_endpoint, hook)
        self.assertEqual(extension_hook, hook)

        local_engine = ROOT / ".local" / "lwa-vi.js"
        if local_engine.is_file():
            source = local_engine.read_text(encoding="utf-8")
            self.assertNotIn(remote_endpoint, source, str(local_engine))
            self.assertNotIn(local_endpoint, source, str(local_engine))
            self.assertNotIn(worker_message, source, str(local_engine))
            self.assertNotIn("__iqiyiViAutoStatus", source, str(local_engine))
            self.assertNotIn("__iqiyiViAutoV", source, str(local_engine))
            self.assertNotIn("__iqiyiViDict", source, str(local_engine))
            self.assertNotIn("__iqiyiViTitles", source, str(local_engine))

        self.assertFalse((ROOT / ("ui_" + "translation.py")).exists())
        self.assertFalse((ROOT / "ext" / ("ui-" + "translate.js")).exists())

    def test_generated_sources_match_the_canonical_engine(self):
        canonical = (ROOT / "ui-engine.js").read_text(encoding="utf-8").replace("\r\n", "\n")
        for name in ("lwa-vi.js", "ext/content.js"):
            generated = (ROOT / name).read_text(encoding="utf-8").replace("\r\n", "\n")
            self.assertEqual(generated, canonical, name)

        hook = (ROOT / "sub-hook.js").read_text(encoding="utf-8").replace("\r\n", "\n")
        extension_hook = (ROOT / "ext/sub-hook.js").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertEqual(extension_hook, hook)
        self.assertIn("getItem(CACHE_KEY)", hook)
        self.assertIn("clients5.google.com/translate_a/t", hook)
        self.assertNotIn("removeItem(CACHE_KEY)", hook)

    def test_subtitle_model_translation_remains_available(self):
        source = (ROOT / "subtitle_app.py").read_text(encoding="utf-8")
        ui = source.split("<script>", 1)[1].split("</script>", 1)[0]

        for active in (
            "AI_SETTINGS_PATH", "DEFAULT_AI_BASE_URL", "PROVIDER_KEYS", "compatible_api_request",
            "compatible_chat_completion", "def translate_episode(", "def _translate_episode(",
            "TRANSLATION_SYSTEM", "TRANSLATION_PROGRESS", "TRANSLATION_CANCEL_EVENTS",
            "subtitle_agent as agent", "/api/agent-profile", "/api/stop-translation",
        ):
            self.assertIn(active, source)

        self.assertIn("post('/api/translate'", ui)
        self.assertIn("post('/api/translate-all'", ui)
        self.assertIn("openSettings()", ui)
        self.assertIn('id="settingsDialog"', source)
        self.assertIn("showAgentProfile", ui)
        self.assertIn('if route == "/api/ai/models":', source)
        self.assertIn('if route == "/api/settings":', source)
        self.assertIn('elif route == "/api/translate":', source)
        self.assertIn("def load_translation_state(", source)
        self.assertIn("def translated_cues(", source)
        self.assertTrue((ROOT / "subtitle_agent.py").exists())
        self.assertTrue((ROOT / ".env.example").exists())
        self.assertIn(".ai-settings.json", source)


if __name__ == "__main__":
    unittest.main()
