# -*- coding: utf-8 -*-
"""Các metric định lượng cho bản dịch phụ đề Trung -> Việt.

Bổ sung cho verify-vietnamese.py (chỉ kiểm tra chữ Hán + timestamp) và cho judge LLM
(run_tian_geng_ji_ab.py, chưa được con người xác minh). Các metric ở đây chạy nội bộ,
không gọi API, miễn phí và tái lập được; dùng để phát hiện nhanh các lỗi cơ học:

- chữ Hán còn sót (cjk)
- mất phủ định (negation)
- thay đổi số liệu (number)
- bản dịch rỗng (empty)
- trùng lặp bất thường (duplicate)
- độ dài bất thường (length)
- mất dấu tiếng Việt (diacritics) - gợi ý bản dịch chưa hoàn thiện

Mỗi metric trả về tỷ lệ trong [0, 1] và danh sách id cue vi phạm, để ghép vào báo cáo
audit hoặc chạy như một smoke test trong CI.
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
# Dấu phủ định tiếng Trung phổ biến. 没/不/别/无/未/非/莫/勿/甭.
NEG_CN = re.compile(r"没|不|别|无|未|非|莫|勿|甭|否|休")
# Từ phủ định tiếng Việt tương ứng.
NEG_VI = re.compile(r"không|chẳng|chưa|đừng|chớ|chả|đâu|cấm|khỏi|vô|bất|phi|vị|đừng")
# Chữ số Trung và Ả Rập.
NUM_CN = re.compile(r"[零〇一二三四五六七八九十百千万亿兩两]|\d+(?:\.\d+)?")
NUM_VI = re.compile(r"\d+(?:\.\d+)?|một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|trăm|nghìn|ngàn|triệu|tỷ|vạn|ức")
# Dấu tiếng Việt (các nguyên âm có dấu + Đ/đ/Ơ...).
DIACRITIC_RE = re.compile(r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]")


def _parse_srt_pair(source_path: Path, translated_path: Path):
    """Trả về danh sách (idx, zh, vi) khớp theo thứ tự cue; khác số cue thì trả None."""
    from subtitle_app import parse_source
    src = parse_source(source_path.read_text(encoding="utf-8-sig"), source_path.suffix.lstrip("."))
    trg = parse_source(translated_path.read_text(encoding="utf-8-sig"), translated_path.suffix.lstrip("."))
    if len(src) != len(trg):
        return None
    return [(i + 1, s[2], t[2]) for i, (s, t) in enumerate(zip(src, trg))]


def _ratio(bad: int, total: int) -> float:
    return round(bad / total, 4) if total else 0.0


def cjk_leftover(rows) -> tuple[float, list[int]]:
    """Tỷ lệ cue có chữ Hán còn sót trong bản dịch."""
    bad = [idx for idx, _zh, vi in rows if CJK_RE.search(vi)]
    return _ratio(len(bad), len(rows)), bad


def negation_mismatch(rows) -> tuple[float, list[int]]:
    """Cue mà source có phủ định nhưng bản dịch không có (có thể mất nghĩa phủ định)."""
    bad = [idx for idx, zh, vi in rows if NEG_CN.search(zh) and not NEG_VI.search(vi)]
    return _ratio(len(bad), len(rows)), bad


def number_mismatch(rows) -> tuple[float, list[int]]:
    """Cue mà source chứa số nhưng bản dịch dường như không giữ số (mất/gộp số liệu)."""
    bad = [idx for idx, zh, vi in rows if NUM_CN.search(zh) and not NUM_VI.search(vi)]
    return _ratio(len(bad), len(rows)), bad


def empty_translations(rows) -> tuple[float, list[int]]:
    bad = [idx for idx, _zh, vi in rows if not vi.strip()]
    return _ratio(len(bad), len(rows)), bad


def missing_diacritics(rows) -> tuple[float, list[int]]:
    """Cue bản dịch có ít nhất một chữ cái tiếng Việt nhưng không có dấu -> nghi bản dịch chưa hoàn thiện."""
    bad = [idx for idx, _zh, vi in rows
           if re.search(r"[a-z]", vi, re.I) and not DIACRITIC_RE.search(vi)]
    return _ratio(len(bad), len(rows)), bad


def duplicate_translations(rows) -> tuple[float, list[int]]:
    """Tỷ lệ cue có bản dịch trùng nguyên văn với một cue khác (cảnh báo copy nhầm)."""
    counts = Counter(vi.strip() for _idx, _zh, vi in rows if vi.strip())
    bad = [idx for idx, _zh, vi in rows if counts[vi.strip()] > 1]
    return _ratio(len(bad), len(rows)), bad


def length_ratio(rows) -> tuple[float, list[int]]:
    """Trung bình len(vi)/len(zh); cue quá ngắn (<0.4) hoặc quá dài (>3.0) được đánh dấu."""
    ratios, bad = [], []
    for idx, zh, vi in rows:
        if not zh.strip():
            continue
        r = len(vi.strip()) / len(zh.strip())
        ratios.append(r)
        if r < 0.4 or r > 3.0:
            bad.append(idx)
    avg = round(sum(ratios) / len(ratios), 3) if ratios else 0.0
    return avg, bad


def audit_files(source_path: Path, translated_path: Path) -> dict:
    """Chạy toàn bộ metric và trả báo cáo dạng dict."""
    rows = _parse_srt_pair(source_path, translated_path)
    if rows is None:
        return {"error": "source và bản dịch khác số lượng cue", "source": str(source_path),
                "translated": str(translated_path)}
    cjk_ratio, cjk_bad = cjk_leftover(rows)
    neg_ratio, neg_bad = negation_mismatch(rows)
    num_ratio, num_bad = number_mismatch(rows)
    empty_ratio, empty_bad = empty_translations(rows)
    dia_ratio, dia_bad = missing_diacritics(rows)
    dup_ratio, dup_bad = duplicate_translations(rows)
    len_avg, len_bad = length_ratio(rows)
    return {
        "source": str(source_path),
        "translated": str(translated_path),
        "cues": len(rows),
        "cjk_leftover_ratio": cjk_ratio,
        "cjk_leftover_ids": cjk_bad[:50],
        "negation_mismatch_ratio": neg_ratio,
        "negation_mismatch_ids": neg_bad[:50],
        "number_mismatch_ratio": num_ratio,
        "number_mismatch_ids": num_bad[:50],
        "empty_ratio": empty_ratio,
        "empty_ids": empty_bad[:50],
        "missing_diacritics_ratio": dia_ratio,
        "missing_diacritics_ids": dia_bad[:50],
        "duplicate_ratio": dup_ratio,
        "duplicate_ids": dup_bad[:50],
        "avg_length_ratio": len_avg,
        "length_outlier_ids": len_bad[:50],
        # Ngưỡng gợi ý "đạt" để in nhanh:
        "pass": (cjk_ratio == 0 and empty_ratio == 0 and neg_ratio < 0.05 and num_ratio < 0.05),
    }
