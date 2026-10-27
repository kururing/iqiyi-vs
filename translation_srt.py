"""Strict SRT parsing, context batches, readable line breaks and lossless export."""
from __future__ import annotations

import re
import unicodedata

STAMP = r"\d{2,}:\d{2}:\d{2},\d{3}"
TIMING = re.compile(rf"({STAMP}) --> ({STAMP})")


def milliseconds(stamp: str) -> int:
    hours, minutes, seconds, millis = map(int, re.split(r"[:,]", stamp))
    if minutes > 59 or seconds > 59:
        raise ValueError("Timestamp SRT không hợp lệ.")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def parse_srt(source: str) -> list[dict]:
    if not isinstance(source, str) or not source.strip() or len(source) > 2_000_000:
        raise ValueError("Chọn SRT UTF-8 không rỗng, tối đa 2 triệu ký tự.")
    source = source.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
    cues, previous_id = [], -1
    for block in re.split(r"\n[ \t]*\n", source):
        lines = block.splitlines()
        if len(lines) < 3 or not re.fullmatch(r"[0-9]+", lines[0].strip()):
            raise ValueError(f"Khối SRT {len(cues) + 1} thiếu ID, timestamp hoặc câu thoại.")
        cue_id = int(lines[0].strip())
        match = TIMING.fullmatch(lines[1].strip())
        if not match or cue_id <= previous_id:
            raise ValueError(f"Khối SRT {len(cues) + 1}: ID phải tăng và timestamp phải đúng chuẩn SRT.")
        start, end = match.groups()
        if milliseconds(start) >= milliseconds(end):
            raise ValueError(f"Câu {cue_id}: thời gian kết thúc phải lớn hơn bắt đầu.")
        text = "\n".join(lines[2:]).strip()
        if not text or len(text) > 4000 or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]", text):
            raise ValueError(f"Câu {cue_id}: nội dung trống, quá dài hoặc không phải UTF-8 hợp lệ.")
        cues.append(dict(id=cue_id, start=start, end=end, text=text))
        previous_id = cue_id
    if len(cues) > 10000:
        raise ValueError("Mỗi file hỗ trợ tối đa 10.000 câu.")
    return cues


def batches(cues: list[dict], size: int, overlap: int) -> list[dict]:
    return [{"context": cues[max(0, offset - overlap):offset], "cues": cues[offset:offset + size]}
            for offset in range(0, len(cues), size)]


def format_lines(text: str, limit: int) -> str | None:
    """Return <=2 lines without cutting words, or request semantic shortening."""
    words = unicodedata.normalize("NFC", text).split()
    flat = " ".join(words)
    if len(flat) <= limit:
        return flat
    candidates = []
    for index in range(1, len(words)):
        left, right = " ".join(words[:index]), " ".join(words[index:])
        if max(len(left), len(right)) <= limit:
            boundary = left[-1] in ",.;:!?…" or words[index].lower() in ("nhưng", "và", "mà", "nên", "vì")
            score = abs(len(left) - len(right)) - (limit // 2 if boundary else 0)
            candidates.append((score, left + "\n" + right))
    return min(candidates)[1] if candidates else None


def validate_translation(value: object, source: list[dict]) -> list[dict]:
    rows = value.get("cues") if isinstance(value, dict) else None
    if not isinstance(rows, list) or len(rows) != len(source):
        raise ValueError("Model trả thiếu hoặc thừa câu phụ đề.")
    by_id = {}
    for row in rows:
        if not isinstance(row, dict) or type(row.get("id")) is not int or row["id"] in by_id:
            raise ValueError("Model trả ID không hợp lệ hoặc trùng ID.")
        text = row.get("text")
        if (not isinstance(text, str) or not text.strip() or len(text) > 4000
                or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text)):
            raise ValueError("Model trả nội dung phụ đề không hợp lệ.")
        by_id[row["id"]] = row
    result = []
    for cue in source:
        row = by_id.get(cue["id"], {})
        if row.get("start") != cue["start"] or row.get("end") != cue["end"]:
            raise ValueError(f"Model đổi ID hoặc timestamp ở câu {cue['id']}.")
        result.append({**cue, "text": row["text"].strip()})
    return result


def export_srt(cues: list[dict]) -> str:
    return "\n\n".join(f"{c['id']}\n{c['start']} --> {c['end']}\n{c['text']}" for c in cues) + "\n"
