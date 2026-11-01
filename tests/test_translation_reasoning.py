"""Check reasoning levels in serialized API requests without calling a provider."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from translation_ai import model_config
from translation_pipeline import PIPELINE_DEFAULTS, pipeline


class TranslationReasoningTest(unittest.TestCase):
    def test_context_translation_and_qc_effort(self):
        for provider, name, expected in (
                ("gemini", "gemini-3.5-flash-lite", ("high", "medium", "high", "medium")),
                ("gemini", "models/gemini-3.8-flash", ("high", "medium", "high", "medium")),
                ("gemini", "gemini-3-flash-preview", ("high", "medium", "high", "medium")),
                ("gemini", "gemini-2.5-flash-lite", (None, None, None, None)),
                ("custom", "fixture-reasoning", ("high", "high", "high", "high")),
                ("custom", "gemini-3.8-flash", (None, None, None, None))):
            requests = []

            def respond(request, cancel):
                body = json.loads(request.data)
                requests.append(body)
                payload = json.loads(body["messages"][-1]["content"])
                if "subtitle_srt" in payload:
                    result = {"genre": "Chua ro", "characters": [], "pronoun_matrix": {},
                              "glossary": {}, "translation_style": "Tu nhien"}
                else:
                    result = [{**cue, "text": "Xin chao." if payload.get("task") == "shorten"
                               else "rat dai " * 20} for cue in payload["cues"]]
                return json.dumps({"choices": [{"finish_reason": "stop", "message": {
                    "content": json.dumps(result)}}]}).encode()

            with self.subTest(provider=provider, model=name), tempfile.TemporaryDirectory() as directory:
                model = model_config({"provider": provider, "model": name,
                                      "base_url": "http://127.0.0.1/v1", "api_key": "",
                                      "reasoning_effort": "high" if name == "fixture-reasoning" else "auto"})
                config = {**PIPELINE_DEFAULTS, "context_model": model, "translation_model": model}
                cues = [{"id": 1, "start": "00:00:01,000", "end": "00:00:02,000", "text": "你好"}]
                with patch("translation_ai.read_api_response", side_effect=respond):
                    pipeline(cues, config, Path(directory), lambda **_: None, threading.Event())
                self.assertEqual(tuple(body.get("reasoning_effort") for body in requests), expected)
                self.assertEqual([body["max_tokens"] for body in requests], [12288, 8192, 12288, 8192])
                expected_temperature = 0.2 if name == "gemini-2.5-flash-lite" else None
                self.assertEqual([body.get("temperature") for body in requests], [expected_temperature] * 4)
                self.assertEqual(json.loads(requests[-1]["messages"][-1]["content"])["task"], "shorten")
                self.assertNotIn("_reasoning_effort", model)
                self.assertTrue((Path(directory) / "translated.srt").exists())


if __name__ == "__main__":
    unittest.main()
