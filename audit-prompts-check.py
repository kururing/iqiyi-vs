r"""Offline regression checks: .venv\Scripts\python.exe audit-prompts-check.py"""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import random
import tempfile
from unittest.mock import patch

import subtitle_agent as agent
import subtitle_app as app


def memory():
    return {"setting": "historical", "summary": "Bối cảnh đã xác nhận.",
            "characters": [{"name": "夏侯", "translation": "Hạ Hầu", "role": "quan",
                            "address": "chưa rõ", "evidence": "tập 1, #1: tự giới thiệu."}],
            "glossary": [{"source": "夏侯", "translation": "Hạ Hầu"}], "uncertainties": []}


def empty_result():
    return {"memory": {"setting": "unknown", "summary": "", "characters": [],
                       "glossary": [], "uncertainties": []},
            "episode_context": {"summary": "", "characters": [], "glossary": [], "uncertainties": []}}


def rejected(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("Expected invalid input to be rejected")


def check_profile_contract():
    bad = [{"memory": {"summary": "Tập mới."}, "episode_context": {}}]
    for key, value in (("characters", {}), ("summary", 1), ("setting", "other"), ("extra", "unexpected")):
        reply = empty_result()
        reply["memory"][key] = value
        bad.append(reply)
    reply = empty_result()
    reply["memory"] = memory()
    del reply["memory"]["characters"][0]["evidence"]
    bad.append(reply)
    for reply in bad:
        for repair in (False, True):
            rejected(lambda: agent.normalize_profile_result(reply, repair=repair))
    assert agent.normalize_profile_result(empty_result(), repair=False)["memory"]["characters"] == []
    print("PASS: required fields, types and extra keys checked on every attempt")


def run_profile(prior, reply):
    load_episode = agent.load_episode_profile
    load_profile = agent.load_profile
    with tempfile.TemporaryDirectory(prefix="iqiyi-prompt-test-") as temp, ExitStack() as stack:
        root = Path(temp)
        folder = root / "102"
        folder.mkdir()
        item = {"tvid": "102", "albumId": "audit", "albumTitle": "Audit"}
        for name, value in {"LIBRARY": root, "EPISODES": {"102": item},
                            "AGENT_PROFILE_LOCKS": {}, "TRANSLATION_CANCEL_EVENTS": {}}.items():
            stack.enter_context(patch.object(app, name, value))
        stack.enter_context(patch.object(app, "official_series_title", return_value=""))
        stack.enter_context(patch.object(agent, "load_profile", return_value=deepcopy(prior)))
        stack.enter_context(patch.object(agent, "load_episode_profile", return_value=None))
        request = stack.enter_context(patch.object(app, "request_translation", return_value=reply))
        settings = {"baseUrl": "https://audit.invalid/v1", "apiKey": "fake", "model": "fake"}
        source = [(0, 1000, "你好")]
        result = app.ensure_agent_profile("102", source, settings)
        path = agent.profile_path(root, item)
        saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if saved:
            loaded = load_episode(folder, app.source_fingerprint(source))
            assert loaded and loaded["memory"] == result["memory"]
            stored = load_profile(root, item)
            assert stored["memory"] == result["memory"]
            assert agent.confirmed_names(stored) == agent.confirmed_names(prior)
        return result, saved, request.call_count


def check_profile_preservation():
    prior = {"memory": memory(), "episodes": {"101": "old"}, "profileVersion": agent.PROFILE_VERSION}
    result, saved, count = run_profile(prior, {"memory": {"summary": "Tập mới."}, "episode_context": {}})
    assert result["memory"] == prior["memory"] and saved is None and count == 3
    full = deepcopy(prior)
    full["memory"]["characters"] += [
        {**full["memory"]["characters"][0], "name": f"name-{i}", "translation": f"Tên {i}"}
        for i in range(65)]
    result, saved, count = run_profile(full, empty_result())
    assert len(result["memory"]["characters"]) == 66
    assert saved["memory"]["characters"] == full["memory"]["characters"] and count == 1
    changed = empty_result()
    changed["memory"] = memory()
    changed["memory"]["characters"][0]["translation"] = "Tên khác"
    result, saved, count = run_profile(prior, changed)
    assert result["memory"] == prior["memory"] and saved is None and count == 3
    legacy = deepcopy(prior)
    legacy["profileVersion"] = "500c3f66691ee40ef0ce28291d5765e81726efcd23985d1e6b0194ade9ff2b14"
    result, saved, count = run_profile(legacy, empty_result())
    assert saved["profileVersion"] == agent.PROFILE_VERSION
    assert result["memory"]["characters"] == prior["memory"]["characters"]
    print("PASS: omitted facts/v13 memory retained; failed candidates never saved")


def check_no_destructive_repair():
    value = memory()
    value["characters"][0]["translation"] = "夏侯"
    for repair in (False, True):
        rejected(lambda: agent.normalize_memory(value, repair=repair))
    value["characters"][0]["translation"] = ""
    rejected(lambda: agent.normalize_memory(value))
    value = empty_result()
    value["memory"] = memory()
    value["memory"]["characters"][0]["translation"] = "夏侯"
    prior = {"memory": memory(), "episodes": {}, "profileVersion": agent.PROFILE_VERSION}
    result, saved, count = run_profile(prior, value)
    assert count == 3 and saved is None and result["memory"] == prior["memory"]
    with tempfile.TemporaryDirectory(prefix="iqiyi-bad-profile-") as temp:
        root, item = Path(temp), {"albumId": "audit"}
        path = agent.profile_path(root, item)
        path.parent.mkdir()
        raw = json.dumps({"memory": value["memory"], "confirmedNames": {"夏侯": "Hạ Hầu"}})
        path.write_text(raw, encoding="utf-8")
        rejected(lambda: agent.load_profile(root, item))
        assert path.read_text(encoding="utf-8") == raw
    print("PASS: untranslated/empty names rejected without stripping content")


def check_name_locks():
    prior = {"memory": memory(), "episodes": {}, "profileVersion": agent.PROFILE_VERSION,
             "confirmedNames": {"夏侯": "Hạ Hầu đã chốt"}}
    reply = empty_result()
    reply["memory"] = memory()
    reply["memory"]["characters"][0]["translation"] = "Tên model tự đổi"
    reply["episode_context"]["characters"] = deepcopy(reply["memory"]["characters"])
    reply["episode_context"]["glossary"] = deepcopy(reply["memory"]["glossary"])
    result, saved, count = run_profile(prior, reply)
    for layer in (result["memory"], result["episodeContext"]):
        assert layer["characters"][0]["translation"] == "Hạ Hầu đã chốt"
        assert layer["glossary"][0]["translation"] == "Hạ Hầu đã chốt"
    assert saved["confirmedNames"] == prior["confirmedNames"]
    prior.pop("confirmedNames")
    reply["memory"]["characters"][0]["evidence"] = "tập 2, #3: đối chiếu chữ nguồn, tên tạm sai âm."
    reply["memory"]["uncertainties"] = ["Hạ Hầu → Tên model tự đổi: tên tạm sai âm."]
    result, saved, count = run_profile(prior, reply)
    assert result["memory"]["characters"][0]["translation"] == "Tên model tự đổi"
    assert result["memory"]["glossary"][0]["translation"] == "Tên model tự đổi"
    print("PASS: user locks in both layers; provisional corrections need new evidence")


def check_explicit_ids():
    for value in (["Câu 102", "Câu 101"], [{"translation": "Một"}, {"translation": "Hai"}]):
        assert app.valid_translations(value, [101, 102]) == ({}, [])
    added, han = app.valid_translations([
        {"id": "#102", "translation": "Hai"}, {"id": 101, "translation": "Một"},
        {"id": 999, "translation": "Ngoài yêu cầu"}], [101, 102])
    assert added == {"102": "Hai", "101": "Một"} and not han
    assert app.valid_translations([
        {"id": 101, "translation": "Một"}, {"id": 101, "translation": "Khác"}], [101]) == ({}, [])
    assert app.valid_translations([{"id": 101, "translation": "中文"}], [101]) == ({}, [101])
    print("PASS: explicit/sparse IDs, reordered results and conflicting duplicates")


def encoded_size(rows):
    return len(json.dumps(rows, ensure_ascii=False, separators=(",", ":")))


def check_context_budget():
    rng = random.Random(42)
    for _ in range(40):
        rows = [{"id": i + 1, "source": "甲\n\"" * rng.randint(1, 500)} for i in range(80)]
        limit = rng.randint(200, 4000)
        try:
            fitted = agent._fit_episode(rows, limit)
        except ValueError:
            assert all(encoded_size([row]) > limit for row in rows)
            continue
        assert fitted and encoded_size(fitted) <= limit
        assert fitted == sorted(fitted, key=lambda row: row["id"])
        assert all(row == rows[row["id"] - 1] for row in fitted)
    rows = [{"id": i, "source": "甲" * 500} for i in range(1, 81)]
    assert encoded_size(agent._fit_episode(rows, 1000)) <= 1000
    rejected(lambda: app.context_window(rows, 1, 40, 1000))
    assert encoded_size(app.context_window(rows, 40, 40, 1000)) <= 1000
    source = [(i * 1000, (i + 1) * 1000, "你好" * 8) for i in range(1000)]
    sample = json.loads(agent.profile_prompt({"tvid": "102"}, source, {"memory": {}}, max_chars=8000))
    assert encoded_size(sample["episode"]) <= 8000
    assert sample["episode_coverage"] == {"included": len(sample["episode"]), "total": 1000}
    assert sample["episode_id"] == "102"
    print("PASS: exact JSON budgets, complete source cues and explicit profile coverage")


def check_split_and_resume():
    source = [(i * 1000, (i + 1) * 1000, "甲" * 1800) for i in range(25)]
    item = {"tvid": "102", "albumTitle": "Audit", "title": "Audit ep1"}
    sent = []

    def request(tvid, settings, key, prompt, count, **kwargs):
        line = next(line for line in prompt.splitlines() if "theo thứ tự thời gian (dữ liệu phim, JSON): " in line)
        rows = json.loads(line.split("(dữ liệu phim, JSON): ", 1)[1])
        ids = json.loads(prompt.split("Các id cần dịch: ")[-1])
        assert len(ids) == count and encoded_size(rows) <= 8000
        assert all(row["source"] == source[row["id"] - 1][2] for row in rows)
        assert all(row["duration"] == 1.0 for row in rows)
        sent.append(ids)
        return [{"id": i, "translation": f"Câu {i}"} for i in reversed(ids)]

    with tempfile.TemporaryDirectory(prefix="iqiyi-prompt-split-") as temp, ExitStack() as stack:
        root = Path(temp)
        folder = root / "102"
        folder.mkdir()
        (folder / "source.srt").write_text(app.to_srt(source), encoding="utf-8")
        for name, value in {"LIBRARY": root, "EPISODES": {"102": item},
                            "TRANSLATION_PROGRESS": {}, "TRANSLATION_CANCEL_EVENTS": {},
                            "CONTEXT_CHAR_LIMIT": 8000, "TRANSLATION_BATCH_SIZE": 10,
                            "TRANSLATION_PARALLEL": 2}.items():
            stack.enter_context(patch.object(app, name, value))
        settings = {"baseUrl": "https://audit.invalid/v1", "apiKey": "fake", "model": "fake"}
        stack.enter_context(patch.object(app, "load_ai_settings", return_value=settings))
        stack.enter_context(patch.object(app, "ensure_agent_profile", return_value={"memory": memory()}))
        api = stack.enter_context(patch.object(app, "request_translation", side_effect=request))
        state = {"sourceHash": app.source_fingerprint(source), "translations": {"2": "Đã lưu"}}
        (folder / "translations.json").write_text(json.dumps(state), encoding="utf-8")
        result = app._translate_episode("102")
        assert result["status"] == "translated" and len(sent) > 3
        ids = [i for group in sent for i in group]
        assert len(ids) == len(set(ids)) == 24 and 2 not in ids
        assert app.load_translation_state(folder, source)["translations"]["2"] == "Đã lưu"
        assert (folder / "translated.srt").exists()
        api.reset_mock()
        assert app._translate_episode("102")["status"] == "translated"
        api.assert_not_called()
        huge = [(0, 1000, "甲" * 9000)]
        rejected(lambda: app._translate_one_batch("102", 1, [1], huge, {}, item, settings, "fake", ""))
        api.assert_not_called()
        app.EPISODES["103"] = {**item, "tvid": "103"}
        other = root / "103"
        other.mkdir()
        (other / "source.srt").write_text(app.to_srt(huge), encoding="utf-8")
        assert app._translate_episode("103")["status"] == "partial"
        assert "AI_CONTEXT_CHARS" in app.load_translation_state(other, huge)["lastError"]
        api.assert_not_called()
    print("PASS: split/parallel/save/resume preserves IDs, saved translations and full source")


def check_metadata_and_prompts():
    item = {"albumTitle": "未收录影片", "title": "特别篇", "provider": "iqiyi"}
    with patch.object(app, "vietnamese_series_title", return_value=""), \
            patch.object(app, "official_series_title", return_value=""):
        prompt = app.translation_prompt(item, [(0, 1000, "你好")], {}, [1])
    line = next(line for line in prompt.splitlines() if line.startswith("Thông tin phim"))
    metadata = json.loads(line.split(": ", 1)[1])
    assert metadata["series_title"] == metadata["episode_title"] == ""
    assert metadata["series_title_original"] == "未收录影片"
    assert metadata["episode_title_original"] == "特别篇"
    assert metadata["series_title_status"] == "unconfirmed"
    with patch.object(app, "vietnamese_series_title", return_value="Tên Việt"), \
            patch.object(app, "official_series_title", return_value="Tên Việt"):
        prompt = app.translation_prompt(item, [(0, 1000, "你好")], {}, [1])
    assert '"series_title_status":"confirmed"' in prompt
    line = next(line for line in agent.PROFILE_SYSTEM.splitlines() if line.startswith('{"memory":'))
    example = json.loads(line)["memory"]["characters"][0]
    assert "Mạn Nhi gọi Thanh Lan là tỷ" in example["evidence"] and "em họ" not in example["role"]
    assert "uncertainties" not in app.TRANSLATION_SYSTEM
    assert agent.PROFILE_NAME_RULES not in app.TRANSLATION_SYSTEM
    assert agent.TRANSLATION_NAME_RULES not in agent.PROFILE_SYSTEM
    for mode in app.RESPONSE_MODES:
        caps = {"mode": mode, "tokens_param": "max_tokens", "temperature": True}
        wrapped = {"type": "object", "properties": {"results": app.TRANSLATION_SCHEMA},
                   "required": ["results"], "additionalProperties": False}
        payload = app._chat_payload({"model": "fake"}, app.TRANSLATION_SYSTEM, prompt, wrapped, True, caps, 1024)
        assert '"results"' in payload["messages"][0]["content"]
    print("PASS: metadata language, address example, stage rules and all response modes")


if __name__ == "__main__":
    with patch("urllib.request.urlopen", side_effect=AssertionError("Network disabled during tests")):
        check_profile_contract()
        check_profile_preservation()
        check_no_destructive_repair()
        check_name_locks()
        check_explicit_ids()
        check_context_budget()
        check_split_and_resume()
        check_metadata_and_prompts()
