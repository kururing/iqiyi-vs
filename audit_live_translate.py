# -*- coding: utf-8 -*-
"""Chạy thử pipeline dịch 2 tầng (profile + translate) trên 20 cue đầu của tập 4 田耕纪."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

import subtitle_app as app
import subtitle_agent as agent

SRC = ROOT / "subtitles" / "library" / "6143487417263800" / "source.srt"
EP = ROOT / "subtitles" / "library" / "6143487417263800" / "episode.json"


def main():
    item = json.loads(EP.read_text(encoding="utf-8"))
    source = app.parse_source(SRC.read_text(encoding="utf-8-sig"), "srt")
    source = source[:20]  # chỉ 20 cue đầu để đo nhanh
    settings = app.load_ai_settings()
    settings["compatible"] = True
    print("model:", settings["model"], "| baseUrl:", settings["baseUrl"])
    print("key loaded:", bool(settings["apiKey"]), "(không in giá trị key)")

    # Tầng 1: profile
    profile = {"memory": {}, "episodes": {}, "updatedAt": 0, "profileVersion": ""}
    prof_prompt = agent.profile_prompt(item, source, profile, max_chars=8000)
    print("\n=== TANG 1: PROFILE ===")
    try:
        raw = app.compatible_chat_completion(
            settings, prof_prompt, 8192, system=agent.PROFILE_SYSTEM,
            schema=agent.MEMORY_SCHEMA)
        memory = agent.normalize_memory(json.loads(raw), repair=False)
        print("setting:", memory["setting"])
        print("summary:", memory["summary"][:200])
        print("characters:", json.dumps(memory["characters"], ensure_ascii=False)[:600])
        print("glossary:", json.dumps(memory["glossary"], ensure_ascii=False)[:400])
        print("uncertainties:", json.dumps(memory["uncertainties"], ensure_ascii=False)[:300])
        prof_ok = True
    except Exception as exc:
        print("PROFILE FAILED:", type(exc).__name__, str(exc)[:300])
        memory = profile.get("memory", {}) or {}
        prof_ok = False

    # Tầng 2: dịch
    print("\n=== TANG 2: TRANSLATE (20 cue) ===")
    translations = {}
    missing = list(range(1, len(source) + 1))
    prompt = agent.memory_context({"memory": memory}, item) + app.translation_prompt(
        item, source, translations, missing)
    try:
        raw = app.compatible_chat_completion(settings, prompt, len(missing),
                                             system=app.TRANSLATION_SYSTEM,
                                             schema=app.TRANSLATION_SCHEMA)
        rows = json.loads(raw)
        added, han = app.valid_translations(rows, missing)
        print(f"dịch được {len(added)}/{len(missing)} cue; chữ Hán sót: {han}")
        for i, (start, end, zh) in enumerate(source, 1):
            print(f"[{i}] {zh!r} -> {added.get(str(i), 'KHONG DICH')!r}")
    except Exception as exc:
        print("TRANSLATE FAILED:", type(exc).__name__, str(exc)[:400])

    print("\n=== KET QUA ===")
    print("profile_ok:", prof_ok)


if __name__ == "__main__":
    main()
