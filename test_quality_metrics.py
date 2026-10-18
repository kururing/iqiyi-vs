# -*- coding: utf-8 -*-
import unittest

import quality_metrics as q


class QualityMetricsTests(unittest.TestCase):
    def test_cjk_leftover_flags_han_in_translation(self):
        rows = [(1, "你好", "xin chào"), (2, "谢谢", "多谢你在")]
        ratio, ids = q.cjk_leftover(rows)
        self.assertEqual(ratio, 0.5)
        self.assertEqual(ids, [2])

    def test_negation_mismatch_flags_lost_negation(self):
        rows = [(1, "我不去", "tôi đi"), (2, "我去", "Tôi không đi")]
        ratio, ids = q.negation_mismatch(rows)
        self.assertEqual(ids, [1])  # source có 不, dịch không có từ phủ định

    def test_number_mismatch_flags_lost_number(self):
        rows = [(1, "三块", "đồng"), (2, "一块", "một đồng")]
        ratio, ids = q.number_mismatch(rows)
        self.assertEqual(ids, [1])

    def test_empty_translations(self):
        rows = [(1, "你好", ""), (2, "你好", "chào")]
        ratio, ids = q.empty_translations(rows)
        self.assertEqual(ids, [1])

    def test_missing_diacritics_detects_untoned_vietnamese(self):
        rows = [(1, "你好", "xin chao"), (2, "你好", "xin chào")]
        ratio, ids = q.missing_diacritics(rows)
        self.assertEqual(ids, [1])

    def test_duplicate_translations(self):
        rows = [(1, "甲", "chào"), (2, "乙", "chào"), (3, "丙", "khác")]
        ratio, ids = q.duplicate_translations(rows)
        self.assertEqual(set(ids), {1, 2})

    def test_length_ratio_outliers(self):
        rows = [(1, "很长很长的一句话很长很长的一句话", "c"), (2, "abc", "một câu rất dài")]
        avg, ids = q.length_ratio(rows)
        self.assertTrue(avg > 0)
        self.assertEqual(set(ids), {1, 2})


if __name__ == "__main__":
    unittest.main()
