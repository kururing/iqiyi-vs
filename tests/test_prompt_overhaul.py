"""Offline checks for the modular prompt, compact echo, narrower pronoun review, arbiter and register."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import subtitle_agent as agent  # noqa: E402
import subtitle_app as app  # noqa: E402


def cues(*rows):
    """rows: (start_ms, end_ms, text)"""
    return list(rows)


class ModularPrompt(unittest.TestCase):
    def test_core_is_much_smaller_than_before(self):
        self.assertLess(len(app.TRANSLATION_SYSTEM), 6000)

    def test_modules_follow_the_source(self):
        plain = app.translation_system_for([{"source": "你好吗"}])
        self.assertEqual(plain, app.TRANSLATION_SYSTEM)
        causal = app.translation_system_for([{"source": "这本书是妈妈让我带来的"}])
        self.assertIn("MODULE SAI KHIẾN", causal)
        self.assertNotIn("MODULE TỰ XƯNG", causal)
        self.assertIn("MODULE TỰ XƯNG", app.translation_system_for([{"source": "属下遵命"}]))

    def test_historical_adds_style_module_only_when_confirmed(self):
        profile = {"memory": {"setting": "historical"}}
        self.assertIn("MODULE CỔ TRANG", app.translation_system_for([{"source": "好"}], profile))
        self.assertNotIn("MODULE CỔ TRANG", app.translation_system_for([{"source": "好"}], {"memory": {"setting": "modern"}}))

    def test_literal_newline_example_is_valid_json(self):
        text = app.TRANSLATION_BASE
        example = text[text.index("[{\"id\":12"):].splitlines()[0]
        rows = json.loads(example)
        self.assertEqual(rows[1]["translation"], "- Sao thế?\n- Không có gì.")


class EchoHead(unittest.TestCase):
    def test_accepts_head_or_full_source(self):
        src = "这是一句比较长的台词用来测试"
        self.assertTrue(app.echo_matches(src, src))
        self.assertTrue(app.echo_matches(src[:8], src))
        self.assertTrue(app.echo_matches("这是一句 比较长的", src))      # whitespace is ignored
        self.assertTrue(app.echo_matches("好的", "好的"))               # short sources are echoed whole

    def test_rejects_other_cue_and_too_short_echo(self):
        src = "这是一句比较长的台词用来测试"
        self.assertFalse(app.echo_matches("别的一句话完全不同", src))
        self.assertFalse(app.echo_matches(src[:3], src))
        self.assertFalse(app.echo_matches(None, src))
        self.assertFalse(app.echo_matches("", src))

    def test_valid_translations_uses_it(self):
        source = cues((0, 1000, "这是一句比较长的台词用来测试"), (1000, 2000, "好的"))
        response = [{"id": 1, "source": "这是一句比较长的", "translation": "Một câu khá dài."},
                    {"id": 2, "source": "不对", "translation": "Được."}]
        added, han = app.valid_translations(response, [1, 2], source=source)
        self.assertEqual(added, {"1": "Một câu khá dài."})
        self.assertEqual(han, [])


class PronounGate(unittest.TestCase):
    def test_plain_pronoun_in_flowing_dialogue_is_not_reviewed(self):
        source = cues((0, 1000, "你来了"), (1200, 2200, "我来看看"), (2400, 3400, "你坐吧"))
        self.assertFalse(app.pronoun_needs_review(source, 2))
        self.assertFalse(app.pronoun_needs_review(source, 3))

    def test_ambiguous_cases_are_reviewed(self):
        source = cues((0, 1000, "我信你"), (1100, 2000, "您请坐"), (2100, 3000, "我们走"),
                      (3100, 4000, "好"), (9000, 10000, "我知道了"))
        for cue_id in (1, 2, 3, 5):   # 我…你, 您, 我们, first cue after a long pause
            self.assertTrue(app.pronoun_needs_review(source, cue_id), cue_id)
        self.assertFalse(app.pronoun_needs_review(source, 4))   # no pronoun

    def test_semantic_risk_ids_shrinks_for_ordinary_dialogue(self):
        source = cues(*[(i * 1000, i * 1000 + 800, "我看你累了") if i % 2 else (i * 1000, i * 1000 + 800, "我没事")
                        for i in range(8)])
        ids = app.semantic_risk_ids(source, list(range(1, 9)))
        self.assertLess(len(ids), 8)


class Arbiter(unittest.TestCase):
    def setUp(self):
        self.source = cues((0, 1000, "这本书是妈妈让我带来的"), (1000, 2000, "谢谢你"))
        self.added = {"1": "Cuốn sách này là mẹ ta.", "2": "Cảm ơn nhé."}
        self.reviewed = {"1": "Sách do mẹ bảo ta mang tới.", "2": "Cảm ơn nhé!"}

    def test_cosmetic_difference_is_not_contested(self):
        self.assertEqual(app.contested_ids(self.added, self.reviewed), [1])

    def run_arbiter(self, rows):
        with mock.patch.object(app, "request_translation", return_value=rows) as call, \
                mock.patch.object(app, "check_translation_cancelled"):
            diagnostics = {}
            out = app.arbitrate_review("t", self.source, self.added, self.reviewed, {}, "k", diagnostics=diagnostics)
        return out, diagnostics, call

    def test_keeps_review_when_arbiter_picks_it(self):
        out, diag, call = self.run_arbiter([{"id": 1, "source": "这本书是妈妈让我", "choice": "review", "translation": ""}])
        self.assertEqual(out, self.reviewed)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(diag["arbiter_picks"], {"1": "review"})

    def test_edit_replaces_text(self):
        out, _, _ = self.run_arbiter([{"id": 1, "source": "这本书是妈妈让我", "choice": "edit",
                                       "translation": "Cuốn sách này do mẹ bảo ta mang đến."}])
        self.assertEqual(out["1"], "Cuốn sách này do mẹ bảo ta mang đến.")
        self.assertEqual(out["2"], self.reviewed["2"])

    def test_wrong_echo_or_han_text_falls_back_to_review(self):
        out, _, _ = self.run_arbiter([{"id": 1, "source": "完全不同的句子啊", "choice": "draft", "translation": ""}])
        self.assertEqual(out, self.reviewed)
        out, _, _ = self.run_arbiter([{"id": 1, "source": "这本书是妈妈让我", "choice": "edit", "translation": "书是妈妈"}])
        self.assertEqual(out, self.reviewed)

    def test_picked_draft_that_fails_meaning_checks_is_reverted(self):
        source = cues((0, 1000, "对得起你的信任"), )
        added, reviewed = {"1": "Tôi có lỗi với sự tin tưởng của anh."}, {"1": "Tôi xứng đáng với niềm tin của anh."}
        with mock.patch.object(app, "request_translation",
                               return_value=[{"id": 1, "source": "对得起你的信任", "choice": "draft", "translation": ""}]), \
                mock.patch.object(app, "check_translation_cancelled"):
            out = app.arbitrate_review("t", source, added, reviewed, {}, "k")
        self.assertEqual(out, reviewed)

    def test_api_failure_keeps_review(self):
        with mock.patch.object(app, "request_translation", side_effect=RuntimeError("boom")), \
                mock.patch.object(app, "check_translation_cancelled"):
            diagnostics = {}
            out = app.arbitrate_review("t", self.source, self.added, self.reviewed, {}, "k", diagnostics=diagnostics)
        self.assertEqual(out, self.reviewed)
        self.assertIn("arbiter_skipped", diagnostics)

    def test_disabled_flag_makes_no_call(self):
        with mock.patch.object(app, "AI_ARBITER", False), mock.patch.object(app, "request_translation") as call:
            out = app.arbitrate_review("t", self.source, self.added, self.reviewed, {}, "k")
        self.assertEqual(out, self.reviewed)
        call.assert_not_called()

    def test_skip_ids_are_never_sent(self):
        with mock.patch.object(app, "request_translation") as call:
            out = app.arbitrate_review("t", self.source, self.added, self.reviewed, {}, "k", skip_ids=[1])
        self.assertEqual(out, self.reviewed)
        call.assert_not_called()


class RegisterAndStatus(unittest.TestCase):
    def memory(self, **extra):
        base = {"setting": "historical", "summary": "", "default_register": "", "characters": [],
                "glossary": [], "uncertainties": []}
        base.update(extra)
        return base

    def test_legacy_memory_without_new_fields_still_loads(self):
        legacy = {"setting": "modern", "summary": "x", "characters": [
            {"name": "李明", "translation": "Lý Minh", "role": "chưa rõ", "address": "", "evidence": ""}],
            "glossary": [], "uncertainties": []}
        memory = agent.normalize_memory(legacy)
        self.assertEqual(memory["default_register"], "")
        self.assertEqual(memory["characters"][0]["status"], "")

    def test_model_output_requires_and_validates_new_fields(self):
        good = self.memory(characters=[{"name": "李明", "translation": "Lý Minh", "role": "r", "address": "a",
                                        "evidence": "e", "status": "guess"}])
        agent.normalize_memory(good, repair=False)
        bad = self.memory(characters=[{"name": "李明", "translation": "Lý Minh", "role": "r", "address": "a",
                                       "evidence": "e", "status": "locked"}])
        with self.assertRaises(ValueError):          # the model cannot mint locks
            agent.normalize_memory(bad, repair=False)

    def test_locked_name_gets_locked_status(self):
        previous = agent.normalize_memory(self.memory(characters=[{
            "name": "李明", "translation": "Lý Minh", "role": "r", "address": "a", "evidence": "e", "status": "evidence"}]))
        merged = agent.merge_memory(previous, previous, {"李明": "Lý Minh"})
        self.assertEqual(merged["characters"][0]["status"], "locked")

    def test_default_register_is_stable_unless_explained(self):
        previous = agent.normalize_memory(self.memory(default_register="Công vụ: tự xưng thuộc hạ, gọi đại nhân."))
        silent = agent.normalize_memory(self.memory(default_register="Đổi sang ta/ngươi."))
        self.assertEqual(agent.merge_memory(previous, silent)["default_register"], previous["default_register"])
        empty = agent.normalize_memory(self.memory())
        self.assertEqual(agent.merge_memory(previous, empty)["default_register"], previous["default_register"])
        explained = agent.normalize_memory(self.memory(
            default_register="Đổi sang ta/ngươi.",
            uncertainties=["default_register đổi vì tập 5 cue 12–30 cho thấy khẩu khí đối địch."]))
        self.assertEqual(agent.merge_memory(previous, explained)["default_register"], "Đổi sang ta/ngươi.")

    def test_first_register_is_accepted(self):
        previous = agent.normalize_memory(self.memory())
        incoming = agent.normalize_memory(self.memory(default_register="Gia đình: anh/em."))
        self.assertEqual(agent.merge_memory(previous, incoming)["default_register"], "Gia đình: anh/em.")

    def test_user_lock_wins_in_context(self):
        profile = {"memory": agent.normalize_memory(self.memory(default_register="Model đoán.")),
                   "episodeContext": {}, "confirmedNames": {}, "confirmedRegister": "Người dùng khóa."}
        rendered = agent.memory_context(profile, source_text="你好", max_chars=6000)
        self.assertIn("Người dùng khóa.", rendered)
        self.assertNotIn("Model đoán.", rendered)
        self.assertIn("Người dùng khóa.", agent.memory_context(profile))
        self.assertEqual(app.profile_register(profile), "Người dùng khóa.")

    def test_old_profile_version_is_still_trusted(self):
        self.assertIn("302fddd89d57df118e2f9ea36f735ec7293aa5bdc8add04d5e1d7c15f4ff6ca7",
                      agent.TRUSTED_PROFILE_VERSIONS)
        self.assertIn(agent.PROFILE_VERSION, agent.TRUSTED_PROFILE_VERSIONS)

    def test_profile_prompt_asks_for_the_new_fields(self):
        self.assertIn("default_register", agent.PROFILE_SYSTEM)
        self.assertIn("status = evidence", agent.PROFILE_SYSTEM)
        sample = agent.PROFILE_SYSTEM[agent.PROFILE_SYSTEM.index('{"memory":{"setting"'):].splitlines()[0]
        agent.normalize_profile_result(json.loads(sample))


class TranslationPromptBudget(unittest.TestCase):
    def test_translation_prompt_uses_the_modular_system_for_budget(self):
        source = cues(*[(i * 1000, i * 1000 + 800, "你好吗") for i in range(10)])
        rows = app.translation_rows(source)
        metrics = {}
        item = {"title": "t", "albumTitle": "t", "tvid": "1"}
        with mock.patch.object(app, "official_series_title", return_value=""), \
                mock.patch.object(app, "episode_series_title", return_value=""), \
                mock.patch.object(app, "episode_title_vi", return_value=""):
            app.translation_prompt(item, source, {}, [1, 2], "1", memory="", rows=rows, metrics=metrics,
                                   schema=app.translation_schema([1, 2], echo_source=True))
        self.assertEqual(metrics["system"], app.TRANSLATION_SYSTEM)


if __name__ == "__main__":
    unittest.main()


class EndToEndBatch(unittest.TestCase):
    def test_translate_review_arbitrate_flow(self):
        source = cues((0, 1000, "我信你，真的"), (1100, 2000, "这本书是妈妈让我带来的"))
        calls = []

        def fake_request(tvid, settings, key, prompt, target_count, *, system=None, schema=None, **_):
            calls.append(system)
            data = json.loads(prompt[prompt.index("Dữ liệu lô (JSON): ") + len("Dữ liệu lô (JSON): "):]) \
                if "Dữ liệu lô (JSON): " in prompt else json.loads(prompt)
            if system is app.ARBITER_SYSTEM:
                return [{"id": 2, "source": "这本书是妈妈让我带来的"[:8], "choice": "review", "translation": ""}]
            if system is app.SEMANTIC_REVIEW_SYSTEM:
                return {"meaning": "Người nói tin người nghe; mẹ bảo người nói mang sách.",
                        "results": [{"id": 1, "source": "我信你，真的"[:8], "translation": "Tôi tin anh, thật mà."},
                                    {"id": 2, "source": "这本书是妈妈让我带来的"[:8],
                                     "translation": "Sách này do mẹ bảo tôi mang đến."}]}
            return [{"id": 1, "source": "我信你，真的"[:8], "translation": "Tôi tin anh, thật mà."},
                    {"id": 2, "source": "这本书是妈妈让我带来的"[:8], "translation": "Cuốn sách này là mẹ tôi."}]

        item = {"title": "t", "albumTitle": "t", "tvid": "1"}
        rows = app.translation_rows(source)
        with mock.patch.object(app, "request_translation", side_effect=fake_request), \
                mock.patch.object(app, "interpret_source_units", return_value=["Sách do mẹ bảo tôi mang tới."]), \
                mock.patch.object(app, "check_translation_cancelled"), \
                mock.patch.object(app, "official_series_title", return_value=""), \
                mock.patch.object(app, "episode_series_title", return_value=""), \
                mock.patch.object(app, "episode_title_vi", return_value=""):
            diagnostics = {}
            added, han = app._translate_one_batch("t", 1, [1, 2], source, {}, item, {}, "k", "", rows=rows,
                                                  diagnostics=diagnostics)
        self.assertEqual(han, [])
        self.assertEqual(added["1"], "Tôi tin anh, thật mà.")
        self.assertEqual(added["2"], "Sách này do mẹ bảo tôi mang đến.")        # review beat the identity draft
        self.assertIn("MODULE SAI KHIẾN", calls[0])                             # module reached the translation call
        self.assertEqual(diagnostics.get("unresolved_ids", []), [])
        self.assertIs(calls[-1], app.ARBITER_SYSTEM)
