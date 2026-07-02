"""
Structural chunking of docs and source files (pure, no I/O).

Two strategies:
  - Markdown/MDX/RST: split on headings (fence-aware so `#` inside code blocks
    is ignored).
  - Code (.ts/.js/.py/...): split on top-level symbol declarations
    (function/class/const/interface/type/def).

Each chunk: {kind, title, level, start_line, end_line}. Line numbers are
1-indexed and inclusive. These boundaries double as the units we will embed
for semantic search later, so the logic lives in one testable place.
"""

import re

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")

_DOC_EXT = (".md", ".mdx", ".markdown", ".rst", ".txt")

# Ordered so more specific (exported) patterns win the label.
_CODE_PATTERNS = [
    (re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)"), "function"),
    (re.compile(r"^(?:export\s+)?(?:default\s+)?class\s+(\w+)"), "class"),
    (re.compile(r"^(?:export\s+)?(?:abstract\s+)?interface\s+(\w+)"), "interface"),
    (re.compile(r"^(?:export\s+)?type\s+(\w+)\s*="), "type"),
    (re.compile(r"^(?:export\s+)?enum\s+(\w+)"), "enum"),
    (re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)"), "const"),
    (re.compile(r"^\s*def\s+(\w+)"), "def"),
    (re.compile(r"^\s*class\s+(\w+)"), "class"),
]


def is_doc_file(path: str) -> bool:
    return path.lower().endswith(_DOC_EXT)


def chunk_markdown(text: str) -> list:
    """Split markdown into heading-delimited sections (fence-aware)."""
    lines = text.split("\n")
    heads = []  # (line_no, level, title)
    in_fence = False
    for i, line in enumerate(lines, 1):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _MD_HEADING.match(line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))

    if not heads:
        return []

    sections = []
    # Preamble before the first heading (frontmatter / intro), if non-trivial.
    if heads[0][0] > 1:
        sections.append({
            "kind": "preamble", "title": "(preamble)", "level": 0,
            "start_line": 1, "end_line": heads[0][0] - 1,
        })
    for idx, (ln, level, title) in enumerate(heads):
        end = (heads[idx + 1][0] - 1) if idx + 1 < len(heads) else len(lines)
        sections.append({
            "kind": "heading", "title": title, "level": level,
            "start_line": ln, "end_line": end,
        })
    return sections


def _match_symbol(line: str):
    for pat, kind in _CODE_PATTERNS:
        m = pat.match(line)
        if m:
            return kind, m.group(1)
    return None


def chunk_code(text: str) -> list:
    """Split code into top-level symbol-delimited sections (fence not relevant)."""
    lines = text.split("\n")
    anchors = []  # (line_no, kind, name)
    for i, line in enumerate(lines, 1):
        # Top-level only: no leading indentation (avoids nested/method matches),
        # except Python def/class which _CODE_PATTERNS already anchors loosely.
        if line[:1] in (" ", "\t") and not line.lstrip().startswith(("def ", "class ")):
            continue
        hit = _match_symbol(line)
        if hit:
            anchors.append((i, hit[0], hit[1]))

    if not anchors:
        return []

    sections = []
    if anchors[0][0] > 1:
        sections.append({
            "kind": "preamble", "title": "(imports/preamble)", "level": 0,
            "start_line": 1, "end_line": anchors[0][0] - 1,
        })
    for idx, (ln, kind, name) in enumerate(anchors):
        end = (anchors[idx + 1][0] - 1) if idx + 1 < len(anchors) else len(lines)
        sections.append({
            "kind": kind, "title": name, "level": 0,
            "start_line": ln, "end_line": end,
        })
    return sections


def outline(text: str, path: str) -> list:
    """Pick the right strategy by extension and return the chunk list."""
    if is_doc_file(path):
        return chunk_markdown(text)
    return chunk_code(text)
