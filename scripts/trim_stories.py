#!/usr/bin/env python3
"""Trim raw stories to the first N chapters."""

import re
import sys
from pathlib import Path


def find_chapter_breaks(text: str) -> list[int]:
    """Find byte offsets where chapters start."""
    pattern = re.compile(
        r"^[ \t　]*第[零一二三四五六七八九十百千\d]+[章回节]",
        re.MULTILINE,
    )
    return [m.start() for m in pattern.finditer(text)]


def trim_to_chapters(text: str, max_chapters: int) -> str:
    """Return text containing only the first max_chapters chapters."""
    breaks = find_chapter_breaks(text)
    if not breaks:
        # No chapter markers — return first ~30000 chars
        return text[:30000]
    if len(breaks) <= max_chapters:
        return text  # Already short enough
    # Return everything up to the start of chapter max_chapters+1
    return text[:breaks[max_chapters]]


def main():
    max_ch = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    src = Path("/Users/biubiu/Downloads/番茄IP互动剧本/raw_stories")
    dst = Path("/Users/biubiu/Downloads/番茄IP互动剧本/raw_stories_short")
    dst.mkdir(exist_ok=True)

    for f in sorted(src.glob("*.txt")):
        try:
            text = f.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                text = f.read_text(encoding="utf-16")
            except Exception:
                print(f"SKIP {f.name}: encoding error")
                continue
        breaks = find_chapter_breaks(text)
        trimmed = trim_to_chapters(text, max_ch)
        out = dst / f.name
        out.write_text(trimmed, encoding="utf-8")
        print(f"{f.name}: {len(breaks)} chapters total -> trimmed to {len(trimmed):,} chars "
              f"({min(max_ch, len(breaks))} chapters)")


if __name__ == "__main__":
    main()
