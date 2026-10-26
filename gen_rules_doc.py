"""Regenerate the prompt section of TRANSLATION-RULES.md from the code, so the two cannot drift.

Usage: python gen_rules_doc.py          (rewrites the block between the GENERATED markers)
       python gen_rules_doc.py --check  (exit 1 when the document is out of date)
"""
import re
import sys
from pathlib import Path

import subtitle_agent as agent
import subtitle_app as app

DOC = Path(__file__).with_name("TRANSLATION-RULES.md")
BEGIN, END = "<!-- BEGIN GENERATED: prompts -->", "<!-- END GENERATED: prompts -->"


def render() -> str:
    parts = [BEGIN,
             "<!-- Do not edit by hand: run `python gen_rules_doc.py`. -->", "",
             "## Prompt thực tế (sinh từ code)", "",
             "| Thành phần | Số ký tự |", "|---|---|",
             f"| Dịch: lõi (`TRANSLATION_SYSTEM`) | {len(app.TRANSLATION_SYSTEM):,} |"]
    for name, _, rule in agent.TRANSLATION_MODULES:
        parts.append(f"| Dịch: module `{name}` (chèn khi nguồn trúng) | {len(rule):,} |")
    parts += [f"| Dịch: module cổ trang (khi setting=historical) | {len(agent.HISTORICAL_STYLE_RULE):,} |",
              f"| Rà nghĩa (`SEMANTIC_REVIEW_SYSTEM`) | {len(app.SEMANTIC_REVIEW_SYSTEM):,} |",
              f"| Trọng tài (`ARBITER_SYSTEM`) | {len(app.ARBITER_SYSTEM):,} |",
              f"| Đọc cú pháp (`SYNTAX_UNIT_SYSTEM`) | {len(app.SYNTAX_UNIT_SYSTEM):,} |",
              f"| Lập hồ sơ (`PROFILE_SYSTEM`) | {len(agent.PROFILE_SYSTEM):,} |", ""]
    sections = (("Dịch (lõi, luôn gửi)", app.TRANSLATION_SYSTEM),
                ("Dịch: module theo cấu trúc", "\n\n".join(rule for _, _, rule in agent.TRANSLATION_MODULES)
                 + "\n\n" + agent.HISTORICAL_STYLE_RULE),
                ("Rà nghĩa độc lập", app.SEMANTIC_REVIEW_SYSTEM),
                ("Trọng tài", app.ARBITER_SYSTEM),
                ("Đọc cú pháp", app.SYNTAX_UNIT_SYSTEM),
                ("Lập hồ sơ", agent.PROFILE_SYSTEM))
    for title, text in sections:
        parts += [f"### {title}", "", "```text", text.strip("\n"), "```", ""]
    parts.append(END)
    return "\n".join(parts)


def main() -> int:
    text = DOC.read_text(encoding="utf-8")
    block = render()
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)
    if not pattern.search(text):
        print("Thiếu cặp marker GENERATED trong TRANSLATION-RULES.md", file=sys.stderr)
        return 2
    updated = pattern.sub(lambda _: block, text)
    if "--check" in sys.argv:
        return 0 if updated == text else 1
    DOC.write_text(updated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
