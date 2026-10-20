"""Run: python test-p2.py. No installed clients, registry or live APIs are changed."""
from contextlib import ExitStack
import http.client
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

import iqiyi_common as common
import subtitle_app as app


def check_installation(root):
    spec = importlib.util.spec_from_file_location("apply_p2", Path(__file__).with_name("apply-vi.py"))
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    bundle = Path(__file__).with_name("lwa-vi.js").read_bytes()
    with ExitStack() as stack:
        for name, value in {"ROOT": root, "DICT_PATH": root / "vi.json", "WEB_DICT": root / "web-vi.json",
                            "OVERRIDE_DICT": root / "vi-overrides.json", "LWA_JS": root / "lwa-vi.js",
                            "BACKUP": root / "backup", "SKIN_CANDIDATES": []}.items():
            stack.enter_context(patch.object(installer, name, value))
        installer.LWA_JS.write_bytes(bundle)
        mapping = installer.load_dict()
        assert mapping["关闭"] == "Đóng" and len(mapping) > 1000
        skin = root / "CustomInstall" / "1.2.3" / "skin"
        skin.mkdir(parents=True)
        resource = skin / "example.xml"
        original = '<Window text="关闭" />'
        resource.write_text(original, encoding="utf-8")
        assert installer.apply_skin(skin, mapping)[:2] == (1, 1)
        assert 'text="Đóng"' in resource.read_text(encoding="utf-8")
        assert installer.restore_tree(installer.skin_backup_dir(skin), skin) == 1
        assert resource.read_text(encoding="utf-8") == original
        installer.DICT_PATH.write_text(json.dumps({"关闭": "Đóng thử"}), encoding="utf-8")
        assert installer.load_dict()["关闭"] == "Đóng thử"
        installer.DICT_PATH.unlink()

        newer = skin.parents[1] / "1.10.0" / "skin"
        newer.mkdir(parents=True)
        assert common.iqiyi_skin_dir(skin.parent) == skin
        assert common.iqiyi_skin_dir(skin.parents[1]) == newer
        saved = root / ".iqiyi-install-location"
        saved.write_text(str(skin.parent), encoding="utf-8")
        with patch.object(common, "_IQIYI_ROOTS", (None, [])), \
                patch.object(common, "_IQIYI_ROOTS_REFRESH", float("inf")):
            assert common.iqiyi_install_roots(root) == [skin.parents[1]]
            assert installer.find_skin() == newer
            # Exercise the installer's persistence without writing client resources or starting it.
            with ExitStack() as safe:
                safe.enter_context(patch.object(installer.sys, "argv", ["apply-vi.py"]))
                safe.enter_context(patch("builtins.print"))
                for name, value in {"build_lwa_js": "/* test */", "sync_extension_sources": None,
                                    "disable_lwa_sign": None, "patch_wrapper_app": False,
                                    "find_lwa_dirs": [], "install_autostart": None,
                                    "apply_skin": (0, 0, 0)}.items():
                    safe.enter_context(patch.object(installer, name, return_value=value))
                written = safe.enter_context(patch.object(installer, "atomic_write"))
                assert installer._main() == 0
                written.assert_any_call(saved, str(newer.parent.parent) + "\n")
        installer.LWA_JS.unlink()
        with patch.object(installer.sys, "argv", ["apply-vi.py"]), \
                patch.object(installer, "disable_lwa_sign") as modify_client, patch("builtins.print"):
            assert installer._main() == 1
            modify_client.assert_not_called()


def check_cancellation(root):
    item = {"tvid": "101", "albumId": "123", "title": "Audit"}
    gate, waiting, cancelled = threading.Lock(), threading.Event(), threading.Event()
    gate.acquire()

    class ObservedLock:
        def acquire(self, **kwargs):
            waiting.set()
            return gate.acquire(**kwargs)

        def release(self):
            gate.release()

    result = []
    settings = {"baseUrl": "https://audit.invalid/v1", "apiKey": "test", "model": "test"}

    def run():
        try:
            app.ensure_agent_profile("101", [(0, 1000, "source")], settings)
            result.append("unexpected success")
        except app.TranslationCancelled:
            result.append("cancelled")
        except Exception as error:
            result.append(error)

    key = str(app.agent.profile_path(root, item))
    with patch.object(app, "LIBRARY", root), patch.object(app, "EPISODES", {"101": item}), \
            patch.object(app, "AGENT_PROFILE_LOCKS", {key: ObservedLock()}), \
            patch.object(app, "TRANSLATION_CANCEL_EVENTS", {"101": cancelled}), \
            patch.object(app, "request_translation") as api:
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        try:
            assert waiting.wait(2)
            cancelled.set()
            worker.join(2)
            assert not worker.is_alive() and result == ["cancelled"]
            assert gate.locked(), "Cancellation must not release another episode's lock"
            api.assert_not_called()
        finally:
            if gate.locked():
                gate.release()
            worker.join(3)
        # Also cancel just after acquiring: the acquired lock must be released.
        cancelled.clear()
        result.clear()
        with patch.object(app, "AGENT_PROFILE_LOCKS", {key: gate}), \
                patch.object(app.agent, "load_episode_profile", side_effect=app.TranslationCancelled):
            run()
            assert result == ["cancelled"] and not gate.locked()


def check_album_deletion(root):
    with ExitStack() as stack:
        for name, value in {"LIBRARY": root, "EPISODES": {}, "ALBUM_LISTS": {}, "EPISODE_LOCKS": {},
                            "DOWNLOAD_PROGRESS": {}, "TRANSLATION_PROGRESS": {}}.items():
            stack.enter_context(patch.object(app, name, value))
        app.save_episode("101", {"tvid": "101", "albumId": "123", "albumTitle": "Audit"})
        pending, resume = threading.Event(), threading.Event()
        payload = {"code": "A00000", "data": {"albumId": "123", "hasMore": False, "total": 2,
            "epsodelist": [{"tvId": str(i), "order": n, "name": f"Audit ep{n}"}
                           for n, i in enumerate((101, 102), 1)]}}

        def opened(*args, **kwargs):
            pending.set()
            if not resume.wait(5):
                raise TimeoutError("Test did not release metadata request")
            return io.BytesIO(json.dumps(payload).encode())

        stack.enter_context(patch.object(app, "iqiyi_open", side_effect=opened))
        syncing = threading.Thread(target=app.sync_album_list, args=("123", "Audit"), daemon=True)
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        server.api_token = "test-admin"
        serving = threading.Thread(target=server.serve_forever, daemon=True)
        serving.start()

        def delete(album_id):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            try:
                conn.request("POST", "/api/delete-album", json.dumps({"provider": "iqiyi",
                    "albumId": album_id, "seriesTitle": "Audit"}),
                    {"Content-Type": "application/json", "X-Iqiyi-Token": server.api_token})
                response = conn.getresponse()
                response.read()
                return response.status
            finally:
                conn.close()

        try:
            syncing.start()
            assert pending.wait(2)
            assert delete("123") == 409 and delete("") == 409
            assert (root / "101" / "episode.json").exists()
            resume.set()
            syncing.join(3)
            assert not syncing.is_alive() and app.ALBUM_LISTS["123"]["stage"] == "ready"
            assert set(app.EPISODES) == {"101", "102"}
            assert delete("123") == 200 and not app.EPISODES
            assert not (root / "101").exists() and not (root / "102").exists()
            with patch.object(app.threading, "Thread") as background:
                app.refresh_album_lists()
                background.assert_not_called()
        finally:
            resume.set()
            syncing.join(3)
            server.shutdown()
            server.server_close()
            serving.join(3)


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        check_installation(root)
        check_cancellation(root)
        check_album_deletion(root / "library")
    print("PASS: bundled native dictionary, legacy/custom install discovery, cancellable profile lock, sync/delete exclusion")
