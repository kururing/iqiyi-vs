import unittest

import subtitle_app as app
from subtitles.benchmarks import tian_geng_ji as bench
from subtitles.benchmarks import run_tian_geng_ji_ab as ab


class TianGengJiBenchmarkTests(unittest.TestCase):
    def test_parent_address_rules_are_in_the_active_prompts(self):
        self.assertIn("đôi vợ chồng cùng nuôi con", app.TRANSLATION_SYSTEM)
        self.assertIn("không mặc định 你/我 thành anh/em", app.TRANSLATION_SYSTEM)
        self.assertIn("không tự chuyển sang “cậu/tớ”", app.TRANSLATION_SYSTEM)
        self.assertIn("“một nghìn lượng vàng”", app.TRANSLATION_SYSTEM)
        self.assertIn("đôi vợ chồng cùng nuôi con, không mặc định 你/我 thành anh/em",
                      app.agent.PROFILE_SYSTEM)
        self.assertIn("Không đoán huynh/đệ/tỷ/muội", app.agent.PROFILE_SYSTEM)

    def test_time_candidates_keep_1_to_n_and_n_to_1_candidates(self):
        source = [(1000, 3000, "甲问乙去哪里"), (3000, 5000, "乙回答回家")]
        reference = [(1450, 2300, "Hỏi đi đâu?"), (2300, 3100, ""), (3400, 5100, "Về nhà.")]
        candidates = bench.temporal_candidate_groups(source, reference, tolerance_ms=1000)
        self.assertIn([1, 2], [row["reference_ids"] for row in candidates[0]["candidates"]])
        self.assertTrue(any(set(a["reference_ids"]) & set(b["reference_ids"])
                            for a in candidates[0]["candidates"] for b in candidates[1]["candidates"]))
        self.assertTrue(all(row["status"] == "candidate_only" for row in candidates))

    def test_same_line_at_different_scenes_uses_time_not_text(self):
        source = [(900, 1400, "同一句"), (99900, 100400, "同一句")]
        reference = [(1000, 1300, "Same"), (100000, 100300, "Same")]
        candidates = bench.temporal_candidate_groups(source, reference, tolerance_ms=500)
        self.assertEqual(candidates[0]["candidates"][0]["reference_ids"], [1])
        self.assertEqual(candidates[1]["candidates"][0]["reference_ids"], [2])

    def test_candidate_window_handles_six_second_source_track_skew(self):
        source = [(9000, 10500, "再加十坛")]
        reference = [(3000, 4500, "Thêm mười vò")]
        row = bench.temporal_candidate_groups(source, reference)[0]
        self.assertEqual(row["status"], "candidate_only")
        self.assertEqual(row["candidates"][0]["reference_ids"], [1])

    def test_ambiguous_and_out_of_window_matches_are_quarantined(self):
        valid = {"source_ids": [1], "reference_ids": [1], "match_status": "ambiguous",
                 "confidence": 0.55, "match_reason": "Hai khả năng."}
        result = bench.validate_alignment_rows([valid], 1, 2, [1], {1})
        self.assertEqual(result["accepted"], [])
        self.assertEqual(result["review"][0]["match_status"], "ambiguous")
        invalid = dict(valid, match_status="matched", confidence=0.99, reference_ids=[2])
        result = bench.validate_alignment_rows([invalid], 1, 2, [1], {1})
        self.assertEqual(result["accepted"], [])
        self.assertEqual(result["review"][0]["review_reason"], "reference_candidate_breach")

    def test_large_many_to_many_groups_are_quarantined(self):
        row = {"source_ids": [1, 2], "reference_ids": [1, 2], "match_status": "matched",
            "confidence": 0.99, "match_reason": "same scene", "category": "agree", "severity": "none"}
        result = bench.validate_alignment_rows([row], 2, 2, [1, 2], {1, 2})
        self.assertEqual(result["accepted"], [])
        self.assertEqual(result["review"][0]["review_reason"], "unsupported_group_shape_or_size")

    def test_nonadjacent_reference_ids_are_review_only(self):
        row = {"source_ids": [1], "reference_ids": [1, 3], "match_status": "matched",
            "confidence": 0.99, "match_reason": "same line", "category": "agree", "severity": "none"}
        result = bench.validate_alignment_rows([row], 1, 3, [1], {1, 2, 3})
        self.assertEqual(result["accepted"], [])
        self.assertIn("unsupported_reference_group", result["review"][0]["review_reason"])

    def test_exact_and_near_duplicates_are_removed_from_both_splits(self):
        episodes = {
            1: {"source": [(0, 1, "“同一句！”"), (2, 3, "今天我们一起回家吃饭") ]},
            5: {"source": [(0, 1, "同一句"), (2, 3, "今天我们一起回家吃饭吧") ]},
        }
        result = bench.find_split_leakage(episodes)
        self.assertEqual(len(result["excluded_training"]), 2)
        self.assertEqual(len(result["excluded_evaluation"]), 2)
        self.assertEqual(len(result["clusters"]), 2)
        self.assertIn("near_duplicate", {r for c in result["clusters"] for r in c["reasons"]})

    def test_generated_prompt_uses_only_chinese_context_and_requested_ids(self):
        context = [{"id": 4, "start_ms": 1000, "end_ms": 1600, "source": "你回来啦"}]
        prompt = ab.render_user_prompt("", {"series_title": "剧名", "episode_title": "第5集"},
                                      context, [4])
        self.assertIn('"source":"你回来啦"', prompt)
        self.assertIn("Các id cần dịch: [4]", prompt)
        self.assertNotIn("international_reference", prompt)
        self.assertNotIn('"webapp_vi"', prompt)
        self.assertNotIn("reference_group_vi", prompt)

    def test_active_prompt_has_a_fingerprint(self):
        self.assertTrue(app.TRANSLATION_SYSTEM.strip())
        self.assertTrue(app.TRANSLATION_PROMPT_VERSION)

    def test_randomized_judge_labels_map_back_to_before_after(self):
        self.assertEqual(ab.map_ab_decision("a_better", False), "before_better")
        self.assertEqual(ab.map_ab_decision("b_better", False), "after_better")
        self.assertEqual(ab.map_ab_decision("a_better", True), "after_better")
        self.assertEqual(ab.map_ab_decision("b_better", True), "before_better")
        self.assertEqual(ab.map_ab_decision("equal", True), "equal")

    def test_translation_ids_are_unique_across_episodes(self):
        merged = {}
        merged.update(ab.qualify_episode_ids(5, {"1": "old"}))
        merged.update(ab.qualify_episode_ids(10, {"1": "new"}))
        self.assertEqual(merged, {"ep05#1": "old", "ep10#1": "new"})

    def test_benchmark_cache_key_isolated_by_prompt_version(self):
        data = {"episode": 999, "batch_number": 1, "source_hash": "source",
            "training_profile_sha256": "profile", "user_prompt": "Chinese source only",
            "target_ids": [1], "context_ids": [1]}
        settings = {"model": "test-model", "baseUrl": "https://api.example", "compatible": False}
        key_before, _, _ = ab._cache_artifacts("cache-test", "system prompt A", "prompt-a", data, settings)
        key_after, _, _ = ab._cache_artifacts("cache-test", "system prompt B", "prompt-b", data, settings)
        self.assertNotEqual(key_before, key_after)


if __name__ == "__main__":
    unittest.main()
