"""Regression checks for model evidence, subtitle integrity and resumable QC; no API calls."""
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import translation_pipeline as tp
from translation_ai import model_config, request_json
from translation_srt import format_lines, validate_translation


def cue(index=1, text="张伟说你好"):
    return {"id": index, "start": "00:00:01,000", "end": "00:00:02,000", "text": text}


def memory():
    return {"genre": "Hiện đại", "characters": [
        {"name_zh": "张伟", "name_vi": "Zhang Wei", "role": "Được nhắc trong câu 1."},
        {"name_zh": "李明", "name_vi": "Li Ming", "role": "Được nhắc trong câu 2."}],
        "pronoun_matrix": {"张伟 to 李明": "tôi / anh"}, "glossary": {},
        "translation_style": "Lời thoại hiện đại, quan hệ chưa rõ."}


def model():
    return model_config({"provider": "custom", "base_url": "http://127.0.0.1/v1",
                         "model": "fixture", "api_key": "fixture-secret"})


class TranslationValidationTest(unittest.TestCase):
    def test_memory_rejects_hallucinations_placeholders_and_pronoun_menus(self):
        source = [cue(), cue(2, "李明拿着项目报告")]
        self.assertEqual(tp.validate_memory(memory(), source), memory())
        bad = []
        for key, value in (("陌生人 to 李明", "tôi / anh"), ("张伟 to 张伟", "tôi / anh"),
                           ("张伟 to 李明", "em / con / ngươi"), ("张伟 to 李明", "tôi / anh hoặc chị")):
            candidate = memory()
            candidate["pronoun_matrix"] = {key: value}
            bad.append(candidate)
        for field, value in (("name_zh", "王强"), ("name_vi", "Tên Việt thống nhất"), ("name_vi", "张伟")):
            candidate = memory()
            candidate["characters"][0][field] = value
            bad.append(candidate)
        candidate = memory()
        candidate["glossary"] = {"凭空发明": "bịa đặt"}
        bad.append(candidate)
        candidate = memory()
        candidate["glossary"] = {"张伟": "Trương Vĩ"}
        bad.append(candidate)
        candidate = memory()
        candidate["characters"].append(candidate["characters"][0])
        bad.append(candidate)
        candidate = memory()
        candidate["characters"] *= 21
        bad.append(candidate)
        candidate = memory()
        candidate["glossary"] = {f"项目{i}": "dự án" for i in range(81)}
        bad.append(candidate)
        candidate = memory()
        candidate["glossary"] = {f"项目{i}": "a" * 500 for i in range(30)}
        bad.append(candidate)
        for candidate in bad:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                tp.validate_memory(candidate, source)

    def test_retry_receives_evidence_feedback(self):
        bad = memory()
        good = {**bad, "characters": [], "pronoun_matrix": {}}
        payloads = []

        def respond(config, prompt, payload, cancel):
            payloads.append(payload)
            return bad if len(payloads) == 1 else good

        result = tp.checked_request({}, tp.CONTEXT_PROMPT, {}, lambda v: tp.validate_memory(v, [cue(text="你好")]),
                                    threading.Event(), respond)
        self.assertEqual(result, good)
        self.assertIn("không xuất hiện", payloads[1]["validation_feedback"])

    def test_speaker_lines_songs_cjk_and_notes(self):
        self.assertEqual(format_lines("- A\n- B", 40), "- A\n- B")
        self.assertEqual(format_lines("– Xin chào.\n— Chào anh.", 40), "– Xin chào.\n— Chào anh.")
        self.assertIsNone(format_lines("- " + "rất dài " * 8 + "\n- Vâng.", 40))
        self.assertEqual(format_lines("…\n…", 40), "…\n…")
        source = [cue(text="- 你好\n- 再见")]
        with self.assertRaises(ValueError):
            validate_translation({"cues": [cue(text="- Chào - Tạm biệt")]}, source)
        for text in ("你好", "Zhang Wei 张伟", "(Translator's note: a name)", "[ND: tên riêng]", "\ufffd"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                validate_translation({"cues": [cue(text=text)]}, [cue()])
        self.assertEqual(validate_translation({"cues": [cue(text="中")]}, [cue()], cjk_whitelist="中")[0]["text"], "中")
        for source_text, target in (("♪ 你好 ♪", "Chào"), ("…", "Im lặng")):
            with self.assertRaises(ValueError):
                validate_translation({"cues": [cue(text=target)]}, [cue(text=source_text)])
        for text in ("♪ Chào ♪", "…"):
            self.assertEqual(validate_translation({"cues": [cue(text=text)]}, [cue(text=text)])[0]["text"], text)

    def test_sample_spans_file_and_ignores_marked_opening_song(self):
        source = [cue(i, "♪ 片头曲 ♪" if i < 100 else "对白") for i in range(1000)]
        sample = tp.context_sample(source, 120)
        self.assertEqual(len(sample), 120)
        self.assertEqual([c["id"] for c in sample[:80]], list(range(100, 180)))
        self.assertEqual(sample[-1]["id"], 999)
        self.assertTrue(any(400 < c["id"] < 700 for c in sample))
        self.assertEqual(sample, tp.context_sample(source, 120))
        self.assertEqual(tp.context_sample([cue(text="♪ 歌 ♪")], 120), [])

    def test_consistency_warnings_respect_line_breaks_and_include_glossary(self):
        self.assertEqual(tp.consistency_warnings([cue()], [cue(text="Zhang\nWei nói chào.")], memory()), [])
        glossary = {**memory(), "glossary": {"项目": "dự án"}}
        self.assertEqual(tp.consistency_warnings([cue(text="项目")], [cue(text="kế hoạch")], glossary), [
            {"id": 1, "kind": "canonical_term", "source": "项目", "expected": "dự án"}])
        self.assertEqual(tp.consistency_warnings([cue(text="Hello")], [cue(text="Hello")], memory()), [
            {"id": 1, "kind": "unchanged_source"}])

    def test_pipeline_discovers_names_warns_and_resumes_without_api(self):
        source = [cue(1, "张伟你好"), cue(2, "李明你好")]
        base = {**memory(), "characters": [], "pronoun_matrix": {}}
        calls = []
        draft_name = {"first": "Trương Vĩ, chào."}

        def respond(config, prompt, payload, cancel):
            calls.append(payload)
            if payload.get("task") == "discover_names":
                return {**copy.deepcopy(base), "characters": [c for c in memory()["characters"]
                        if c["name_zh"] in payload["subtitle_srt"]]}
            if "subtitle_srt" in payload:
                return copy.deepcopy(base)
            return [{**row, "text": draft_name["first"] if row["id"] == 1 else "Li Ming, chào."}
                    for row in payload["cues"]]

        config = {**tp.PIPELINE_DEFAULTS, "batch_size": 1, "concurrency": 1,
                  "context_model": model(), "translation_model": model()}
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            updates = []
            tp.pipeline(source, config, folder, lambda **v: updates.append(v), threading.Event(), respond)
            canonical = json.loads((folder / "memory.json").read_text(encoding="utf-8"))
            self.assertEqual([c["name_vi"] for c in canonical["characters"]], ["Zhang Wei", "Li Ming"])
            self.assertEqual(updates[-1]["qc"]["warnings"], [
                {"id": 1, "kind": "canonical_term", "source": "张伟", "expected": "Zhang Wei"}])
            plan_text = (folder / "plan.json").read_text()
            self.assertNotIn("fixture-secret", plan_text)
            self.assertIn("prompt_hash", plan_text)
            second_batch = next(p for p in calls if p.get("cues", [{}])[0].get("id") == 2)
            self.assertEqual(second_batch["translated_context"][0]["text"], "Trương Vĩ, chào.")
            first = (folder / "translated.srt").read_bytes()
            calls.clear()
            tp.pipeline(source, config, folder, lambda **_: None, threading.Event(), respond)
            self.assertEqual(calls, [])
            self.assertEqual((folder / "translated.srt").read_bytes(), first)
            # A repaired batch invalidates its name review and QC even when IDs/times match.
            (folder / "batch-0000.json").write_text(json.dumps({"cues": [cue(text="张伟")]}), encoding="utf-8")
            draft_name["first"] = "Zhang Wei, chào."
            tp.pipeline(source, config, folder, lambda **_: None, threading.Event(), respond)
            self.assertEqual(len(calls), 2)
            self.assertNotIn("task", calls[0])
            self.assertEqual(calls[1]["task"], "discover_names")
            self.assertIn("Zhang Wei, chào.", (folder / "translated.srt").read_text(encoding="utf-8"))
            calls.clear()
            changed = copy.deepcopy(config)
            changed["translation_model"]["model"] = "other"
            with self.assertRaisesRegex(ValueError, "prompt, model"):
                tp.pipeline(source, changed, folder, lambda **_: None, threading.Event(), respond)
            with patch.object(tp, "TRANSLATE_PROMPT", tp.TRANSLATE_PROMPT + " changed"):
                with self.assertRaisesRegex(ValueError, "prompt, model"):
                    tp.pipeline(source, config, folder, lambda **_: None, threading.Event(), respond)
            plan = json.loads(plan_text)
            plan["version"] = 1
            (folder / "plan.json").write_text(json.dumps(plan))
            with self.assertRaises(ValueError):
                tp.pipeline(source, config, folder, lambda **_: None, threading.Event(), respond)

    def test_temperature_falls_back_only_for_explicit_unsupported_parameter(self):
        requests = []

        def respond(request, cancel):
            body = json.loads(request.data)
            requests.append(body)
            if len(requests) == 1:
                error = {"error": {"param": "temperature", "code": "unsupported_value"}}
                raise urllib.error.HTTPError(request.full_url, 400, "Bad request", {},
                                             io.BytesIO(json.dumps(error).encode()))
            return b'{"choices":[{"finish_reason":"stop","message":{"content":"{}"}}]}'

        with patch("translation_ai.read_api_response", side_effect=respond):
            self.assertEqual(request_json(model(), "test", {}, threading.Event()), {})
        self.assertEqual(requests[0]["temperature"], 0.2)
        self.assertNotIn("temperature", requests[1])


if __name__ == "__main__":
    unittest.main()
