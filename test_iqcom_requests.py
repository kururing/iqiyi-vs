"""Run with: python -m unittest test_iqcom_requests"""
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
import gzip
import io
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from iqcom_requests import RequestCache
from iqcom_session import IqcomSession
import subtitle_app as app


class IqcomRequestsTest(unittest.TestCase):
    def test_compressed_metadata_has_same_uncompressed_size_limit(self):
        body = b'{"code":"0","data":{"name":"test"}}'
        for compressed in (False, True):
            response = io.BytesIO(gzip.compress(body) if compressed else body)
            response.headers = {"Content-Encoding":"gzip"} if compressed else {}
            self.assertEqual(app.read_public_metadata(response), body)
        response = io.BytesIO(gzip.compress(b"x" * 4_100_000))
        response.headers = {"Content-Encoding":"gzip"}
        self.assertEqual(len(app.read_public_metadata(response)), 4_000_001)

    def test_known_catalog_still_verifies_identity_without_search(self):
        urls = []
        def fetch(url):
            urls.append(url)
            if "baseinfo" in url:
                return {"code":"A00000", "data":{"albumId":236709101,"name":"招摇","year":"2019","channelId":2}}
            lang = parse_qs(urlsplit(url).query)["langCode"][0]
            return {"code":"0", "data":{"qipuId":249155501,"name":"招摇" if lang == "zh_cn" else "Chiêu Diêu",
                "chnId":2,"publishTime":"20190128","matchedLang":1 if lang == "zh_cn" else 15}}
        with patch.object(app, "INTERNATIONAL_TITLE_CACHE", {}), patch.object(app, "INTERNATIONAL_ALBUM_IDS", {}), \
                patch.object(app, "public_iqiyi_json", side_effect=fetch):
            self.assertEqual(app.international_movie_title("236709101")["title"], "Chiêu Diêu")
        self.assertEqual(len(urls), 3)
        self.assertFalse(any("search2" in url for url in urls))

    def test_overlapping_playback_work_is_shared_but_not_retained(self):
        cache = RequestCache()
        joined, release = threading.Event(), threading.Event()
        count_lock = threading.Lock()
        followers = [0]
        calls = []

        class WaitingFuture(Future):
            def result(self, timeout=None):
                with count_lock:
                    followers[0] += 1
                    if followers[0] == 7:
                        joined.set()
                return super().result(timeout=3)

        def load():
            calls.append(1)
            if len(calls) == 1:
                self.assertTrue(release.wait(3))
            return "signed-result"

        with patch("iqcom_requests.Future", WaitingFuture), ThreadPoolExecutor(max_workers=8) as pool:
            jobs = [pool.submit(cache.run, "playback", load) for _ in range(8)]
            try:
                self.assertTrue(joined.wait(3))
            finally:
                release.set()
            self.assertEqual([job.result(timeout=3) for job in jobs], ["signed-result"] * 8)
        self.assertEqual(len(calls), 1)
        self.assertFalse(cache.cache)
        cache.run("playback", load)
        self.assertEqual(len(calls), 2)

    def test_shared_request_expiry_errors_and_capacity(self):
        cache = RequestCache(capacity=2)
        calls = []
        now = [100.0]
        started, release = threading.Event(), threading.Event()

        def load():
            calls.append(1)
            started.set()
            self.assertTrue(release.wait(3))
            return {"ok": True}

        with patch("iqcom_requests.time.monotonic", side_effect=lambda: now[0]):
            with ThreadPoolExecutor(max_workers=12) as pool:
                jobs = [pool.submit(cache.run, "same", load, ttl=30) for _ in range(12)]
                self.assertTrue(started.wait(3))
                release.set()
                self.assertTrue(all(job.result(timeout=3) == {"ok": True} for job in jobs))
            self.assertEqual(len(calls), 1)
            now[0] = 131
            cache.run("same", load, ttl=30)
            self.assertEqual(len(calls), 2)
            errors = []

            def fail():
                errors.append(1)
                raise OSError("offline")

            for _ in range(2):
                with self.assertRaises(OSError):
                    cache.run("bad", fail, error_ttl=10)
            self.assertEqual(len(errors), 1)
            now[0] += 11
            with self.assertRaises(OSError):
                cache.run("bad", fail, error_ttl=10)
            self.assertEqual(len(errors), 2)
            cache.run("third", lambda: 3, ttl=100)
            self.assertEqual(len(cache.cache), 2)
            self.assertFalse(cache.pending)
            cache.run("signed", lambda: "fresh-url")
            self.assertNotIn("signed", cache.cache)

    def test_public_cache_canonical_keys_language_and_mutation(self):
        base = "https://pcw-api.iq.com/api/epgInfo/249155501?"
        first = base + "langCode=vi_vn&modeCode=intl&platformId=4&deviceId=ew&uid=&pspStatus="
        second = base + "deviceId=ew&platformId=4&modeCode=intl&langCode=vi_vn"
        with patch.object(app, "PUBLIC_METADATA", RequestCache()), patch.object(
                app, "_fetch_public_iqiyi_json", return_value={"code":"0", "data":{"name":"original"}}) as fetch:
            data = app.public_iqiyi_json(first)
            data["data"]["name"] = "mutated"
            self.assertEqual(app.public_iqiyi_json(second)["data"]["name"], "original")
            self.assertEqual(fetch.call_count, 1)
            app.public_iqiyi_json(second.replace("vi_vn", "zh_cn"))
            self.assertEqual(fetch.call_count, 2)
            for _ in range(2):
                app.public_iqiyi_json("https://cache.video.iq.com/dash?tvid=249155501")
            self.assertEqual(fetch.call_count, 4, "Playback URLs must bypass the metadata cache")
            app.public_iqiyi_json(second, refresh=True)
            self.assertEqual(fetch.call_count, 5, "Explicit catalog refresh must bypass a still-valid cache")

    def test_title_cast_and_subtitles_share_album_metadata(self):
        calls = []
        source_cast = {"mainActor":[{"id":111,"n":"甲演员"},{"id":222,"n":"乙演员"}]}
        translated_cast = {"mainActor":[{"id":222,"n":"Actor B"},{"id":111,"n":"Actor A"}]}

        def fetch(url):
            calls.append(url)
            path = urlsplit(url).path
            if "baseinfo" in path:
                return {"code":"A00000", "data":{"albumId":12345678901,"name":"测试片", "year":"2024", "channelId":2}}
            if path == "/api/search2":
                return {"code":"0", "data":{"epg":[{"name":"测试片","type":1,"qipuId":22345678901,
                    "publishTime":"20240101","chnId":2,"cast":source_cast}]}}
            return {"code":"0", "data":{"name":"Phim thử","qipuId":22345678901,"matchedLang":15,
                "defaultTvId":33345678900,"playLocSuffix":"episode-12345678","cast":translated_cast}}

        page = {"props":{"initialState":{"play":{"cachePlayList":{"1":[{
            "tvId":33345678900,"albumId":22345678901,"order":1,"contentType":1}]}}}}}
        with patch.object(app, "PUBLIC_METADATA", RequestCache()), patch.object(app, "INTERNATIONAL_TITLE_CACHE", {}), \
                patch.object(app, "INTERNATIONAL_ACTOR_CACHE", {}), patch.object(app, "INTERNATIONAL_ALBUM_IDS", {}), \
                patch.object(app, "IQCOM_ALBUM_CACHE", {}), patch.object(app, "_fetch_public_iqiyi_json", side_effect=fetch), \
                patch.object(app, "public_iqcom_page", return_value=page) as read_page:
            self.assertEqual(app.international_movie_title("12345678901")["title"], "Phim thử")
            self.assertEqual(len(calls), 3)
            self.assertEqual(app.international_actor_name("甲演员")["name"], "Actor A")
            self.assertEqual(app.international_actor_name("乙演员")["name"], "Actor B")
            album, _, fresh = app.iqcom_album_metadata("22345678901")
            self.assertEqual(str(album["qipuId"]), "22345678901")
            self.assertIsNotNone(fresh)
            self.assertEqual(len(calls), 3, "Cast and subtitle lookup should reuse the title's catalog response")
            self.assertIsNone(app.iqcom_album_metadata("22345678901")[2])
            self.assertEqual(read_page.call_count, 1)
            app.iqcom_album_metadata("22345678901", refresh=True)
            self.assertEqual(read_page.call_count, 2, "New episodes still trigger a fresh playlist read")
            self.assertEqual(len(calls), 4, "An explicit refresh must reload the catalog too")

    def test_actor_verified_in_one_request_and_safe_fallback(self):
        def fetch(url):
            lang = parse_qs(urlsplit(url).query)["langCode"][0]
            return {"code":"0", "data":{"starsInfo": {
                "qipuId":123456789, "name":"Actor A" if lang == "vi_vn" else "甲演员", "nationalityName":"甲演员"}}}
        with patch.object(app, "INTERNATIONAL_ACTOR_CACHE", {}), patch.object(app, "public_iqiyi_json", side_effect=fetch) as request:
            self.assertEqual(app.international_actor_name("甲演员")["name"], "Actor A")
            self.assertEqual(request.call_count, 1)
        rows = [{"code":"0", "data":{"starsInfo":{"qipuId":1,"name":"Wrong person"}}},
                {"code":"0", "data":{"starsInfo":{"qipuId":2,"name":"甲演员"}}}]
        with patch.object(app, "INTERNATIONAL_ACTOR_CACHE", {}), patch.object(app, "public_iqiyi_json", side_effect=rows):
            self.assertEqual(app.international_actor_name("甲演员")["name"], "")

    def test_dash_coalesces_only_within_same_session_and_never_caches(self):
        waiting = threading.Event()
        callers = [0]

        class TrackedFuture(Future):
            def result(self, timeout=None):
                callers[0] += 1
                if callers[0] >= 2:
                    waiting.set()
                return super().result(timeout=min(timeout or 3, 3))

        class Pool:
            def __init__(self):
                self.calls = []
                self.queued = threading.Condition()
            def submit(self, *args):
                future = TrackedFuture()
                with self.queued:
                    self.calls.append((args, future))
                    self.queued.notify_all()
                return future

        with tempfile.TemporaryDirectory() as folder:
            session = IqcomSession(Path(folder))
            original_pool, session.pool = session.pool, Pool()
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    jobs = [pool.submit(session.dash, "episode-12345678", "12345678900") for _ in range(2)]
                    self.assertTrue(waiting.wait(3))
                    self.assertEqual(len(session.pool.calls), 1)
                    session.pool.calls[0][1].set_result({"tvid":"12345678900"})
                    self.assertTrue(all(job.result(timeout=3)["tvid"] == "12345678900" for job in jobs))
                self.assertFalse(session.dash_pending)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(session.dash, "episode-12345678", "12345678900")
                    with session.pool.queued:
                        self.assertTrue(session.pool.queued.wait_for(lambda: len(session.pool.calls) >= 2, timeout=3))
                    with session.lock:
                        session.state["version"] += 1
                    second = pool.submit(session.dash, "episode-12345678", "12345678900")
                    with session.pool.queued:
                        self.assertTrue(session.pool.queued.wait_for(lambda: len(session.pool.calls) >= 3, timeout=3))
                    self.assertEqual(len(session.pool.calls), 3)
                    session.pool.calls[1][1].set_result({"session":0})
                    session.pool.calls[2][1].set_result({"session":1})
                    self.assertEqual(first.result(timeout=3), {"session":0})
                    self.assertEqual(second.result(timeout=3), {"session":1})
            finally:
                for _, future in session.pool.calls:
                    if not future.done():
                        future.set_exception(RuntimeError("test cleanup"))
                session.pool = original_pool
                session.close()

    def test_skip_subtitle_job_for_previous_login(self):
        with patch.object(app, "IQCOM_SESSION") as session, patch.object(app, "fetch_official_subtitle") as fetch, \
                patch.object(app, "OFFICIAL_SUBTITLE_CACHE", {"12345678900":{"sessionVersion":2,"loading":True}}):
            session.version = 2
            app._load_official_subtitle("12345678900", 1)
            fetch.assert_not_called()
            self.assertEqual(app.OFFICIAL_SUBTITLE_CACHE["12345678900"]["sessionVersion"], 2)

    def test_cookie_order_and_bursts_do_not_queue_duplicate_stores(self):
        class Pool:
            def __init__(self):
                self.jobs = []
            def submit(self, function):
                self.jobs.append(function)

        rows = [{"name":"I00001","value":"synthetic-login","domain":".iq.com"},
                {"name":"analytics","value":"1","domain":".iq.com"}]
        with tempfile.TemporaryDirectory() as folder:
            session = IqcomSession(Path(folder))
            original_pool, session.pool = session.pool, Pool()
            try:
                session.update(rows, "synthetic-source-id", select=True)
                signature = session.cookie_signature
                session.update(list(reversed(rows)), "synthetic-source-id")
                self.assertEqual(session.cookie_signature, signature)
                self.assertEqual(len(session.pool.jobs), 1)
                changed = [dict(row) for row in rows]
                changed[1]["value"] = "2"
                session.update(changed, "synthetic-source-id")
                self.assertEqual(len(session.pool.jobs), 1)
                version = session.version
                def store():
                    session.applied_signature = session.cookie_signature
                    return True
                with patch.object(session, "_store_browser_cookies", side_effect=store):
                    session.pool.jobs[0]()
                self.assertFalse(session.cookie_store_pending)
                session.update(list(reversed(changed)), "synthetic-source-id")
                self.assertEqual(len(session.pool.jobs), 1)
                self.assertEqual(session.version, version)
            finally:
                session.pool = original_pool
                session.close()


if __name__ == "__main__":
    unittest.main()
