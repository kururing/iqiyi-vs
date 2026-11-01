"""JSON contracts, repair feedback and diagnostics without calling an AI provider."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import translation_ai as ai
import translation_pipeline as tp


def model(provider="gemini"):
    return ai.model_config({"provider": provider, "base_url": "http://127.0.0.1/v1",
                            "model": "fixture", "api_key": "fixture-secret"})


def envelope(text):
    return json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": text}}]}).encode()


class TranslationJSONTest(unittest.TestCase):
    def test_gemini_schema_matches_each_task_without_mutating_model(self):
        config = model()
        for payload in ({"cues": [{"id": 1}, {"id": 2}]},
                        {"task": "shorten", "cues": [{"id": 2}]},
                        {"subtitle_srt": "source"},
                        {"task": "discover_names", "subtitle_srt": "source"}):
            requests = []

            def respond(request, cancel):
                requests.append(json.loads(request.data))
                return envelope("[]" if "cues" in payload else "{}")

            with self.subTest(payload=payload), patch.object(ai, "read_api_response", side_effect=respond):
                tp.checked_request(config, "test", payload, lambda value: value, threading.Event())
            schema = requests[0]["response_format"]["json_schema"]["schema"]
            if "cues" in payload:
                self.assertEqual(schema["type"], "array")
                self.assertEqual(schema["minItems"], len(payload["cues"]))
                self.assertEqual(schema["maxItems"], len(payload["cues"]))
                self.assertEqual(schema["items"]["required"], ["id", "time", "text"])
                self.assertFalse(schema["items"]["additionalProperties"])
            else:
                self.assertEqual(set(schema["required"]), {
                    "genre", "characters", "pronoun_matrix", "glossary", "translation_style"})
                self.assertEqual(schema["properties"]["glossary"]["additionalProperties"], {"type": "string"})
            self.assertNotIn("_json_schema", config)
            prompt = requests[0]["messages"][0]["content"]
            self.assertIn(r'"- Chào.\n- Vâng."', prompt)
            self.assertIn(r'"Anh nói \"được\"."', prompt)
            self.assertIn("previous_response", prompt)

    def test_retries_receive_parser_location_and_failed_response(self):
        source = [{"id": 1, "start": "00:00:01,000", "end": "00:00:02,000", "text": "- 你好\n- 再见"}]
        good = tp.model_cues([{**source[0], "text": "- Chào.\n- Tạm biệt."}])
        for bad in ('[{"text":"A\nB"}]', '[{"text":"Anh nói "được"."}]', "Here is the result: []"):
            requests = []

            def respond(request, cancel):
                requests.append(json.loads(request.data))
                return envelope(bad if len(requests) == 1 else json.dumps(good))

            with self.subTest(bad=bad), patch.object(ai, "read_api_response", side_effect=respond):
                result = tp.checked_request(model(), tp.TRANSLATE_PROMPT, {"cues": tp.model_cues(source)},
                    lambda value: tp.validate_model_translation(value, source), threading.Event())
            self.assertEqual(result[0]["text"], good[0]["text"])
            self.assertEqual(len(requests), 2)
            retry = json.loads(requests[1]["messages"][-1]["content"])
            self.assertEqual(retry["previous_response"], bad)
            self.assertIn("dòng", retry["validation_feedback"])
            self.assertIn("cột", retry["validation_feedback"])
            self.assertIn("vị trí", retry["validation_feedback"])
            self.assertEqual(requests[0]["response_format"], requests[1]["response_format"])

    def test_terminal_failure_keeps_bounded_diagnostic_and_success_clears_it(self):
        bad = '[{"text":"' + "a" * 20000
        config = model()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "errors" / "translate-0005.json"
            with patch.object(ai, "read_api_response", return_value=envelope(bad)) as request:
                with self.assertRaisesRegex(ValueError, "sau 3 lần.*dòng"):
                    tp.checked_request(config, "test", {"cues": []}, lambda value: value,
                                       threading.Event(), diagnostic_path=path)
            self.assertEqual(request.call_count, 3)
            raw = path.read_text(encoding="utf-8")
            diagnostic = json.loads(raw)
            self.assertEqual(diagnostic["attempt"], 3)
            self.assertEqual(diagnostic["response"], bad[:16000])
            self.assertTrue(diagnostic["response_truncated"])
            self.assertNotIn("fixture-secret", raw)
            with patch.object(ai, "read_api_response", return_value=envelope("[]")):
                tp.checked_request(config, "test", {"cues": []}, lambda value: value,
                                   threading.Event(), diagnostic_path=path)
            self.assertFalse(path.exists())

    def test_bad_api_envelope_is_not_retried_as_model_output(self):
        for raw in (b"<html>upstream failure</html>", b'{"error":{"message":"upstream failure"}}'):
            with self.subTest(raw=raw), patch.object(ai, "read_api_response", return_value=raw) as request:
                with self.assertRaisesRegex(ai.ProviderError, "API"):
                    tp.checked_request(model(), "test", {"cues": []}, lambda value: value, threading.Event())
                self.assertEqual(request.call_count, 1)

    def test_other_providers_keep_their_existing_response_contract(self):
        for provider in ("openai", "custom", "qwen", "anthropic"):
            requests = []

            def respond(request, cancel):
                requests.append(json.loads(request.data))
                if provider == "anthropic":
                    return b'{"stop_reason":"end_turn","content":[{"type":"text","text":"[]"}]}'
                return envelope("[]")

            with self.subTest(provider=provider), patch.object(ai, "read_api_response", side_effect=respond):
                self.assertEqual(tp.checked_request(model(provider), "test", {"cues": []},
                                 lambda value: value, threading.Event()), [])
            self.assertNotIn("response_format", requests[0])


if __name__ == "__main__":
    unittest.main()
