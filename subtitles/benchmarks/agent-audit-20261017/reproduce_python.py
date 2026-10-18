"""Offline audit probes. Uses temporary data and never contacts an API."""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
import subtitle_app as app


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        settings_path = root / "settings.json"
        settings_path.write_text(json.dumps({
            "apiKey": "", "keyOverride": True, "compatible": True,
            "baseUrl": "http://localhost:1234/v1", "model": "offline",
        }), encoding="utf-8")
        (root / ".env").write_text("GEMINI_API_KEY=fake-gemini-key-for-audit\n", encoding="utf-8")
        with patch.object(app, "ROOT", root), patch.object(app, "AI_SETTINGS_PATH", settings_path):
            settings = app.load_ai_settings()
        assert settings["apiKey"] == "fake-gemini-key-for-audit"
        with patch.object(app, "compatible_api_request", return_value={
            "choices": [{"finish_reason": "stop", "message": {"content": "[]"}}],
        }) as request:
            app.compatible_chat_completion(settings, "offline probe", 1024)
        assert request.call_args.args[1] == "fake-gemini-key-for-audit"
        key_probe = {"explicitEmptyOverrideIgnored": True,
                     "destination": settings["baseUrl"], "keyForwardedToProvider": True,
                     "realCredentialsUsed": False}

        source = [(1000, 2000, "别走")]
        text = "Không.\n\nĐừng đi."
        translations = app.valid_translations([{"id": 1, "translation": text}], [1])
        review = [{"id": 1, "source": source[0][2], "translation": text,
                   "reason": "Đã đối chiếu nội dung."}]
        assert app.agent.validate_review(review, source, translations, [1]) == {}
        serialized = app.to_srt([(1000, 2000, text)])
        parsed = app.parse_source(serialized, "srt")
        assert parsed[0][2] == "Không."
        srt_probe = {"draftAccepted": True, "reviewAccepted": True,
                     "expectedText": text, "roundTripText": parsed[0][2]}

    print(json.dumps({"keyOverride": key_probe, "srtParagraphLoss": srt_probe},
                     ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
