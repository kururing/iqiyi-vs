"""Album translation uses the real job worker with a local, free pipeline fixture."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import subtitle_app as app
from translation_pipeline import TranslationJobs

SRT = "1\n00:00:01,000 --> 00:00:02,000\n你好\n"
MODEL = {"provider": "custom", "base_url": "http://127.0.0.1/v1", "model": "fixture", "api_key": "fixture-secret"}


class AlbumTranslationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.stack = ExitStack()
        self.jobs = TranslationJobs(self.root / "jobs")
        self.started, self.release = threading.Event(), threading.Event()
        self.calls, self.downloads = [], []
        self.block, self.fail = False, False
        episodes = {str(n): {"tvid": str(n), "albumId": "12345601", "albumTitle": "Phim thử", "order": n}
                    for n in (4, 2, 1, 3)}
        self.stack.enter_context(patch.multiple(app, LIBRARY=self.root / "library", EPISODES=episodes,
            LIBRARY_ADMISSIONS={"iqiyi:album:12345601": "accepted"}, ALBUM_LISTS={}, EPISODE_LOCKS={},
            DOWNLOAD_PROGRESS={}, TRANSLATION_JOBS=self.jobs, ALBUM_TRANSLATION={},
            ALBUM_TRANSLATION_LOCK=threading.RLock(), ALBUM_TRANSLATION_CANCEL=threading.Event()))
        self.stack.enter_context(patch.object(app, "official_series_title", return_value="Phim thử"))
        self.stack.enter_context(patch.object(app, "queue_subtitle_downloads", side_effect=self.download))
        self.stack.enter_context(patch("translation_pipeline.pipeline", side_effect=self.pipeline))
        self.data = {"tvid": "2", "context_model": MODEL, "translation_model": MODEL}
        for n, stage in ((1, "complete"), (2, "error")):
            episode = app.episode_dir(str(n))
            episode.mkdir(parents=True)
            (episode / "source.srt").write_text(SRT, encoding="utf-8")
            stat = (episode / "source.srt").stat()
            identifier = str(n) * 32
            folder = self.jobs.folder(identifier)
            folder.mkdir(parents=True)
            (folder / "source.srt").write_text(SRT, encoding="utf-8")
            (folder / "status.json").write_text(json.dumps({"id": identifier, "stage": stage,
                "episode_id": str(n), "episode_label": f"Phim thử · Tập {n}"}), encoding="utf-8")
            (episode / "translation-job.json").write_text(json.dumps({"id": identifier,
                "source_signature": [stat.st_mtime_ns, stat.st_size]}), encoding="utf-8")
        self.addCleanup(self.cleanup)

    def cleanup(self):
        app.stop_album_translation()
        self.release.set()
        deadline = time.monotonic() + 4
        while (self.jobs.busy() or app.album_translation_status().get("stage") == "running") and time.monotonic() < deadline:
            time.sleep(.01)
        self.stack.close()
        self.temp.cleanup()

    def pipeline(self, cues, config, folder, update, cancel):
        self.calls.append(folder.name)
        self.started.set()
        if self.block:
            while not self.release.wait(.01):
                if cancel.is_set():
                    return
        if self.fail:
            raise ValueError("Lỗi provider kiểm tra")
        (folder / "translated.srt").write_text(SRT, encoding="utf-8")
        update(stage="complete", step=5, message="Đã dịch")

    def download(self, ids, retry=False):
        self.assertTrue(retry)
        for tvid in ids:
            self.downloads.append(tvid)
            if tvid == "3":
                folder = app.episode_dir(tvid)
                folder.mkdir(parents=True)
                (folder / "source.srt").write_text(SRT, encoding="utf-8")
            else:
                app.DOWNLOAD_PROGRESS[tvid] = {"stage": "access"}

    def finished(self):
        deadline = time.monotonic() + 4
        while app.album_translation_status().get("stage") == "running" and time.monotonic() < deadline:
            time.sleep(.01)
        state = app.album_translation_status()
        self.assertNotEqual(state.get("stage"), "running", state)
        self.assertNotIn("fixture-secret", json.dumps(state))
        return state

    def test_order_skip_resume_and_download_missing_sources(self):
        app.start_album_translation(self.data)
        state = self.finished()
        self.assertEqual(state["stage"], "complete")
        self.assertEqual((state["processed"], state["translated"], state["skipped"], state["failed"]), (4, 2, 1, 1))
        self.assertEqual(self.calls[0], "2" * 32, "Resume the saved episode instead of starting over")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.downloads, ["3", "4"])
        self.assertEqual(state["episodeIds"], ["1", "2", "3", "4"])

    def test_cancel_stops_remaining_episodes_and_rejects_duplicate_queues(self):
        self.block = True
        app.start_album_translation(self.data)
        self.assertTrue(self.started.wait(2))
        with self.assertRaises(app.EpisodeBusy):
            app.start_album_translation(self.data)
        app.stop_album_translation()
        self.assertEqual(self.finished()["stage"], "cancelled")
        self.assertEqual(self.calls, ["2" * 32])
        self.assertEqual(self.downloads, [])

    def test_provider_failure_stops_queue_with_checkpoint_intact(self):
        self.fail = True
        app.start_album_translation(self.data)
        state = self.finished()
        self.assertEqual(state["stage"], "error")
        self.assertIn("Lỗi provider kiểm tra", state["message"])
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(self.jobs.status("2" * 32)["resumable"])

    def test_cancelling_waiting_queue_does_not_cancel_an_existing_job(self):
        self.block = True
        current = self.jobs.start_episode(self.data, app.episode_dir("1"), "1", "Tập đang dịch riêng")
        self.assertTrue(self.started.wait(2))
        app.start_album_translation(self.data)
        app.stop_album_translation()
        self.assertEqual(self.finished()["stage"], "cancelled")
        self.assertEqual(self.jobs.active_id(), current["id"])
        self.assertFalse(self.jobs.cancel_event.is_set())

    def test_stale_cancel_does_not_cancel_a_separately_resumed_job(self):
        self.fail = True
        app.start_album_translation(self.data)
        self.assertEqual(self.finished()["stage"], "error")
        self.fail, self.block = False, True
        self.started.clear()
        current = self.jobs.resume_episode({**self.data, "id": "2" * 32}, app.episode_dir("2"))
        self.assertTrue(self.started.wait(2))
        app.stop_album_translation()
        self.assertEqual(self.jobs.active_id(), current["id"])
        self.assertFalse(self.jobs.cancel_event.is_set())


if __name__ == "__main__":
    unittest.main()
