#!/usr/bin/env python3
"""
MDX body safety: escape / check characters that break the MDX 3 build.

Article bodies are plain Markdown (no JSX components), but MDX 3 parses
`{...}` as JS expressions and `<x` as JSX tags, so LLM prose like
"{he sneezed}" or "<5 seconds" fails `next build`.

- escape_mdx_body(text): turns bare `{` `}` into `\\{` `\\}` and `<` followed by a
  non-space into `\\<`, outside the `export const metadata = {...}` block,
  fenced code blocks and inline code. Already-escaped characters stay as is.
- find_mdx_issues(text): line numbers (1-based) that still have such characters.

CLI (used by website_create merge step):
    python3 mdx.py check <dir>    # prints file:line per issue, exit 1 if any
"""

import re
import sys
from pathlib import Path

_INLINE_CODE_RE = re.compile(r"(`+)(.+?)\1")
_BRACE_RE = re.compile(r"(?<!\\)([{}])")
_LT_RE = re.compile(r"(?<!\\)<(?=\S)")


_METADATA_START_RE = re.compile(r"^[ \t]*export const metadata = \{", re.M)


def strip_preamble(text: str) -> str:
    """Drop whatever the model wrote before the `export const metadata = {` line (a note such as
    "the source was a Cloudflare block page…", or an opening ```mdx fence). Must run before
    escape_mdx_body: with text in front, the metadata block is not recognised and its braces
    get escaped to `\\{`. Text without a metadata line is returned unchanged."""
    m = _METADATA_START_RE.search(text or "")
    return text[m.start():].lstrip() if m and m.start() > 0 else text


def _body_start(lines: list) -> int:
    """Line index where the body starts: after the line that closes the
    `export const metadata = {` block (`}` or `};`). None when the block never
    closes, so callers leave the file untouched and report it."""
    if not "\n".join(lines).lstrip().startswith("export const metadata"):
        return 0
    for i, line in enumerate(lines):
        if line.strip() in ("}", "};"):
            return i + 1
    return None


def _map_outside_inline_code(line: str, fn) -> str:
    """Apply fn to the parts of a line that are not inline code."""
    out, pos = [], 0
    for m in _INLINE_CODE_RE.finditer(line):
        out.append(fn(line[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(fn(line[pos:]))
    return "".join(out)


def _escape_segment(s: str) -> str:
    s = _BRACE_RE.sub(r"\\\1", s)
    return _LT_RE.sub(r"\\<", s)


def _has_issue(s: str) -> bool:
    return bool(_BRACE_RE.search(s) or _LT_RE.search(s))


def _body_lines(text: str):
    """Yield (index, line, in_code) for every line; in_code covers fences and metadata."""
    lines = text.split("\n")
    start = _body_start(lines)
    if start is None:
        start = len(lines)
    code = False
    for i, line in enumerate(lines):
        if i < start:
            yield i, line, True
            continue
        if line.lstrip().startswith("```"):
            code = not code
            yield i, line, True
            continue
        yield i, line, code


def escape_mdx_body(text: str) -> str:
    lines = []
    for _, line, in_code in _body_lines(text):
        lines.append(line if in_code else _map_outside_inline_code(line, _escape_segment))
    return "\n".join(lines)


def find_mdx_issues(text: str) -> list:
    if _body_start(text.split("\n")) is None:
        return [1]   # metadata block never closes
    bad = []
    for i, line, in_code in _body_lines(text):
        if not in_code and _has_issue(_INLINE_CODE_RE.sub("", line)):
            bad.append(i + 1)
    return bad


def _cli(argv: list) -> int:
    if len(argv) != 3 or argv[1] != "check":
        print("usage: mdx.py check <dir>", file=sys.stderr)
        return 2
    bad = []
    for f in sorted(Path(argv[2]).glob("**/*.mdx")):
        if not f.is_file():
            continue
        for n in find_mdx_issues(f.read_text(encoding="utf-8")):
            bad.append(f"{f}:{n}")
    for b in bad:
        print(b)
    print(f"MDX 问题: {len(bad)}", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
