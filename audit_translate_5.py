# -*- coding: utf-8 -*-
"""Chạy thử tầng 2 với batch nhỏ (5 cue) để tránh output limit của model nhỏ."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

import subtitle_app as app
import subtitle_agent as agent

SRC = ROOT / "subtitles" / "library" / "6143487417263800" / "source.srt"
EP = ROOT / "subtitles" / "library" / "6143487417263800" / "episode.json"


def main():
    item = json.loads(EP.read_text(encoding="utf-8"))
    source = app.parse_source(SRC.read_text(encoding="utf-8-sig"), "srt")[:5]
    settings = app.load_ai_settings()
    memory = {"setting": "historical", "summary": "Phim cổ trang điền viên.",
              "characters": [{"name": "二伯娘", "translation": "Nhị Bá Nương", "role": "bà thím của cha"}],
              "glossary": [], "uncertainties": []}
    missing = list(range(1, len(source) + 1))
    prompt = agent.memory_context({"memory": memory}, item) + app.translation_prompt(
        item, source, {}, missing)
    raw = app.compatible_chat_completion(settings, prompt, len(missing),
                                         system=app.TRANSLATION_SYSTEM,
                                         schema=app.TRANSLATION_SCHEMA)
    added, han = app.valid_translations(json.loads(raw), missing)
    print(f"dịch được {len(added)}/{len(missing)}; chữ Hán sót: {han}")
    for i, (_s, _e, zh) in enumerate(source, 1):
        print(f"[{i}] {zh!r} -> {added.get(str(i), 'KHONG DICH')!r}")


if __name__ == "__main__":
    main()
