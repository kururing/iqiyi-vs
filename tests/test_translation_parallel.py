"""Parallel name discovery and QC keep source order and resumable checkpoints; no API calls."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import translation_pipeline as tp
from translation_ai import ProviderError, model_config
from translation_srt import parse_srt


BASE_MEMORY = {"genre": "Hiện đại", "characters": [], "pronoun_matrix": {},
               "glossary": {}, "translation_style": "Lời thoại tự nhiên."}


def config():
    model = model_config({"provider": "custom", "base_url": "http://127.0.0.1/v1", "model": "fixture"})
    return {**tp.PIPELINE_DEFAULTS, "batch_size": 1, "concurrency": 2,
            "context_model": model, "translation_model": model}


def source(count):
    return [{"id": i, "start": "00:00:01,000", "end": "00:00:02,000", "text": f"张伟你好{i}"}
            for i in range(1, count + 1)]


def response(payload):
    if "subtitle_srt" in payload:
        return {**BASE_MEMORY, "characters": [], "glossary": {}}
    return [{**row, "text": f"Xin chào {row['id']}." if payload.get("task") == "shorten"
             else "Lời thoại quá dài " * 12} for row in payload["cues"]]


class TranslationParallelTest(unittest.TestCase):
    def test_parallel_stages_keep_source_order_and_resume_without_requests(self):
        barriers = {task: threading.Barrier(2, timeout=3) for task in ("discover_names", "shorten")}
        progressed = {task: threading.Event() for task in barriers}
        calls, active, peak = [], dict.fromkeys(barriers, 0), dict.fromkeys(barriers, 0)
        lock = threading.Lock()

        def update(**values):
            for task, label in (("discover_names", "Đã gom tên"), ("shorten", "Đã kiểm định")):
                if values.get("message", "").startswith(label):
                    progressed[task].set()

        def respond(model, prompt, payload, cancel):
            task = payload.get("task")
            with lock:
                calls.append(payload)
            if task not in barriers:
                return response(payload)
            index = int(payload["subtitle_srt"].splitlines()[0]) if task == "discover_names" else payload["cues"][0]["id"]
            with lock:
                active[task] += 1
                peak[task] = max(peak[task], active[task])
            try:
                barriers[task].wait()
                # Batch 1 finishes after a later batch, for both name discovery and QC.
                if index == 1:
                    self.assertTrue(progressed[task].wait(3))
                if task == "discover_names":
                    self.assertEqual(payload["known_memory"], BASE_MEMORY)
                    return {**response(payload), "characters": [{"name_zh": "张伟",
                            "name_vi": "Trương Vĩ" if index == 1 else "Zhang Wei", "role": "Được nhắc tên."}]}
                self.assertEqual(payload["memory"]["characters"][0]["name_vi"], "Trương Vĩ")
                return response(payload)
            finally:
                with lock:
                    active[task] -= 1

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            tp.pipeline(source(8), config(), folder, update, threading.Event(), respond)
            self.assertEqual(peak, {"discover_names": 2, "shorten": 2})
            self.assertEqual(len(calls), 19)
            memory = json.loads((folder / "memory.json").read_text(encoding="utf-8"))
            self.assertEqual(memory["characters"][0]["name_vi"], "Trương Vĩ")
            output = (folder / "translated.srt").read_text(encoding="utf-8")
            self.assertEqual([row["id"] for row in parse_srt(output)], list(range(1, 9)))
            self.assertEqual(json.loads((folder / "qc.json").read_text(encoding="utf-8"))["shortened_ids"], list(range(1, 9)))
            calls.clear()
            tp.pipeline(source(8), config(), folder, update, threading.Event(), respond)
            self.assertEqual(calls, [])
            self.assertEqual((folder / "translated.srt").read_text(encoding="utf-8"), output)

    def test_failed_stages_keep_late_successes_and_resume_only_missing_work(self):
        for failing_task, prefix in (("discover_names", "names"), ("shorten", "qc")):
            with self.subTest(task=failing_task), tempfile.TemporaryDirectory() as directory:
                folder = Path(directory)
                both_started = threading.Barrier(2, timeout=3)
                calls = []
                count = 12 if failing_task == "discover_names" else 8
                successful_index = 5 if failing_task == "discover_names" else 2

                def fail(model, prompt, payload, cancel):
                    if payload.get("task") == failing_task:
                        index = int(payload["subtitle_srt"].splitlines()[0]) if failing_task == "discover_names" else payload["cues"][0]["id"]
                        calls.append(index)
                        both_started.wait()
                        if index == 1:
                            raise ProviderError("fixture failure")
                        # A successful in-flight response must be saved even after its peer failed.
                        self.assertTrue(cancel.wait(3))
                    return response(payload)

                with self.assertRaisesRegex(ProviderError, "fixture failure"):
                    tp.pipeline(source(count), config(), folder, lambda **_: None, threading.Event(), fail)
                self.assertEqual(sorted(calls), [1, successful_index])
                self.assertTrue((folder / f"{prefix}-{successful_index - 1:04}.json").exists())
                self.assertFalse((folder / "translated.srt").exists())
                calls.clear()

                def resume(model, prompt, payload, cancel):
                    if payload.get("task") == failing_task:
                        calls.append(int(payload["subtitle_srt"].splitlines()[0]) if failing_task == "discover_names"
                                     else payload["cues"][0]["id"])
                    return response(payload)

                tp.pipeline(source(count), config(), folder, lambda **_: None, threading.Event(), resume)
                self.assertEqual(sorted(calls), [1, 9] if failing_task == "discover_names" else [1, 3, 4, 5, 6, 7, 8])
                self.assertEqual(len(list(folder.glob(f"{prefix}-*.json"))), count)
                self.assertEqual(len(parse_srt((folder / "translated.srt").read_text(encoding="utf-8"))), count)


if __name__ == "__main__":
    unittest.main()
