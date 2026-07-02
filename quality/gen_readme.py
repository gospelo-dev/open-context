#!/usr/bin/env python3
"""
Regenerate the monitored-packages breakdown in README.md / README_ja.md from
quality/baseline.json. Idempotent: replaces the content between the markers

    <!-- BEGIN:monitored ... -->
    <!-- END:monitored -->

Usage:
    python quality/gen_readme.py          # rewrite READMEs in place
    python quality/gen_readme.py --check   # exit 1 if any README is out of date
"""

import json
import os
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BASELINE = os.path.join(HERE, "baseline.json")
BEGIN = "<!-- BEGIN:monitored"
END = "<!-- END:monitored -->"
TARGETS = ["README.md", "README_ja.md"]


def _block(total_label):
    with open(BASELINE, encoding="utf-8") as f:
        pkgs = json.load(f)["packages"]
    counts = Counter(p.get("category", "uncategorized") for p in pkgs)
    # sort by count desc, then category name
    rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    lines = ["| Category | Count |", "|---|---|"]
    lines += [f"| `{cat}` | {n} |" for cat, n in rows]
    lines.append(f"| **{total_label}** | **{len(pkgs)}** |")
    return "\n".join(lines)


def _render(text, block):
    b = text.index(BEGIN)
    b_end = text.index("-->", b) + len("-->")
    e = text.index(END)
    return text[: b_end] + "\n" + block + "\n" + text[e:]


def main():
    check = "--check" in sys.argv
    total_label = "Total"
    stale = []
    for name in TARGETS:
        path = os.path.join(ROOT, name)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if BEGIN not in text or END not in text:
            print(f"{name}: markers not found", file=sys.stderr)
            sys.exit(2)
        new = _render(text, _block(total_label))
        if new != text:
            if check:
                stale.append(name)
            else:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new)
                print(f"updated {name}")
        else:
            print(f"{name}: up to date")
    if check and stale:
        print("stale (run quality/gen_readme.py): " + ", ".join(stale), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
