# -*- coding: utf-8 -*-
"""Kiem tra tu dien/phu de Viet va cac rang buoc timestamp co the kiem chung cuc bo."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
STAMP = re.compile(r"(?:(\d+):)?(\d+):(\d+)[,.](\d+)")


def seconds(value: str) -> float:
    match = STAMP.fullmatch(value.strip())
    if not match:
        raise ValueError(f"timestamp khong hop le: {value}")
    hours, minutes, secs, fraction = match.groups()
    return (int(hours or 0) * 3600 + int(minutes) * 60 + int(secs)
            + int(fraction[:3].ljust(3, "0")) / 1000)


def check_dictionary(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    values = data.get("translations", data) if isinstance(data, dict) else {}
    return [f"{path.name}: {key!r} -> {value!r}"
            for key, value in values.items()
            if isinstance(value, str) and CJK.search(value)]


def check_subtitles(path: Path) -> list[str]:
    raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    errors: list[str] = []
    previous_end = -1.0
    blocks = re.split(r"\n{2,}", raw)
    for number, block in enumerate(blocks, 1):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0:
            continue
        left, right = [part.strip().split(" ", 1)[0] for part in lines[timing_index].split("-->", 1)]
        try:
            start, end = seconds(left), seconds(right)
        except ValueError as exc:
            errors.append(f"{path.name} khoi {number}: {exc}")
            continue
        if end <= start:
            errors.append(f"{path.name} khoi {number}: end <= start")
        if start < previous_end:
            errors.append(f"{path.name} khoi {number}: cue chong len nhau")
        previous_end = max(previous_end, end)
        text = " ".join(lines[timing_index + 1:])
        if CJK.search(text):
            errors.append(f"{path.name} khoi {number}: con ky tu Trung trong phu de")
    return errors


def main() -> int:
    errors: list[str] = []
    for name in ("vi.json", "web-vi.json", "vi-overrides.json"):
        path = ROOT / name
        if path.exists():
            errors.extend(check_dictionary(path))
    subtitle_files = [
        path for path in ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in {".srt", ".vtt", ".ass"}
        and ".venv" not in path.parts and ".git" not in path.parts
    ]
    for path in subtitle_files:
        errors.extend(check_subtitles(path))
    if errors:
        print("Kiem tra that bai:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("OK: khong co ky tu Trung trong cac gia tri dich va khong co loi timestamp cuc bo.")
    if not subtitle_files:
        print("CHUA THE KIEM CHUNG: workspace khong co file SRT/VTT/ASS de doi chieu am thanh/video.")
    else:
        print(f"Da kiem tra {len(subtitle_files)} file phu de ve cau truc timestamp.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
