"""Chunk large novels at chapter/scene boundaries for phased LLM processing.

Provides:
  - chunk_story(): split text at natural boundaries (~30K chars per chunk)
  - build_extraction_chunks(): chapter/window chunks for Phase 1 map/reduce
  - build_chapter_index(): extract 第N章 → text mapping (pure text, no LLM)
  - sample_for_bible(): pick representative chunks for bible extraction
"""

from __future__ import annotations

import re

# ── Chapter/scene break detection ────────────────────────────────────

_CN_NUM = r'[一二三四五六七八九十百千万零〇\d]+'
_CHAPTER_PATTERNS = [
    re.compile(rf'^第{_CN_NUM}[章节卷集幕回]', re.MULTILINE),
    re.compile(r'^Chapter\s+\d+', re.MULTILINE | re.IGNORECASE),
    re.compile(r'^CHAPTER\s+\d+', re.MULTILINE),
    re.compile(r'^\d+\.\s+\S', re.MULTILINE),
]

_SCENE_BREAK = re.compile(
    r'^[\s]*(?:[*]{3,}|[-]{3,}|[—]{3,}|[=]{3,}|[…]{3,}|[·]{3,}|~~~)[\s]*$',
    re.MULTILINE,
)

# Pattern to extract chapter number from a 第N章 marker
_CN_DIGITS = {
    '零': 0, '〇': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9, '十': 10, '百': 100,
    '千': 1000, '万': 10000,
}

_CHAPTER_NUM_PATTERN = re.compile(rf'^第({_CN_NUM})[章节卷集幕回]', re.MULTILINE)


def _cn_to_int(s: str) -> int | None:
    """Convert Chinese numeral string to int. Returns None if unparseable."""
    # Try Arabic numerals first
    try:
        return int(s)
    except ValueError:
        pass

    # Simple Chinese numeral parsing
    if not s:
        return None

    result = 0
    current = 0
    for ch in s:
        if ch in _CN_DIGITS:
            val = _CN_DIGITS[ch]
            if val >= 10:
                if current == 0:
                    current = 1
                current *= val
                result += current
                current = 0
            else:
                current = val
        else:
            return None
    result += current
    return result if result > 0 else None


def find_split_points(text: str) -> list[int]:
    """Find all chapter and scene-break positions in the text."""
    points = set()

    for pat in _CHAPTER_PATTERNS:
        for m in pat.finditer(text):
            points.add(m.start())

    scene_breaks = [m.start() for m in _SCENE_BREAK.finditer(text)]
    if len(scene_breaks) < 500:
        points.update(scene_breaks)

    return sorted(points)


def find_paragraph_breaks(text: str, start: int, end: int) -> list[int]:
    """Find paragraph break positions (double newline) within a range."""
    breaks = []
    pos = start
    while True:
        idx = text.find('\n\n', pos)
        if idx == -1 or idx >= end:
            break
        breaks.append(idx)
        pos = idx + 2
    return breaks


def chunk_story(text: str, max_chars: int = 30000, overlap: int = 2000) -> list[dict]:
    """Split story text into chunks at natural boundaries.

    Returns list of dicts: {index, start, end, char_count, text, context_before, context_after}
    """
    split_points = find_split_points(text)
    text_len = len(text)

    if not split_points or split_points[0] > 0:
        split_points.insert(0, 0)

    # Merge split points that are too close together
    merged = [split_points[0]]
    for pt in split_points[1:]:
        if pt - merged[-1] > 500:
            merged.append(pt)
    split_points = merged

    # Build initial segments from split points
    segments = []
    for i, start in enumerate(split_points):
        end = split_points[i + 1] if i + 1 < len(split_points) else text_len
        segments.append((start, end))

    # Merge small segments and split large ones
    chunks_ranges = []
    current_start = segments[0][0]
    current_end = segments[0][1]

    for i in range(1, len(segments)):
        seg_start, seg_end = segments[i]
        proposed_len = seg_end - current_start

        if proposed_len <= max_chars:
            current_end = seg_end
        else:
            chunks_ranges.append((current_start, current_end))
            current_start = seg_start
            current_end = seg_end

    chunks_ranges.append((current_start, current_end))

    # Split any chunks that are still too large
    final_ranges = []
    for start, end in chunks_ranges:
        if end - start <= max_chars * 1.5:
            final_ranges.append((start, end))
        else:
            para_breaks = find_paragraph_breaks(text, start, end)
            if not para_breaks:
                pos = start
                while pos < end:
                    final_ranges.append((pos, min(pos + max_chars, end)))
                    pos += max_chars
            else:
                sub_start = start
                for pb in para_breaks:
                    if pb - sub_start >= max_chars:
                        final_ranges.append((sub_start, pb))
                        sub_start = pb
                final_ranges.append((sub_start, end))

    # Build chunk objects with overlap context
    chunks = []
    for i, (start, end) in enumerate(final_ranges):
        ctx_before_start = max(0, start - overlap)
        ctx_after_end = min(text_len, end + overlap)

        chunk = {
            'index': i + 1,
            'start': start,
            'end': end,
            'char_count': end - start,
            'text': text[start:end],
            'context_before': text[ctx_before_start:start] if start > 0 else '',
            'context_after': text[end:ctx_after_end] if end < text_len else '',
        }
        chunks.append(chunk)

    return chunks


def build_extraction_chunks(
    text: str,
    chapters: dict[int, str],
    max_chars: int = 8000,
    overlap_chars: int = 600,
) -> list[dict]:
    """Build small Phase 1 map/reduce chunks.

    Prefer chapter windows so extraction logs and highlight chapter IDs remain
    interpretable. If chapters are unavailable, fall back to natural text chunks.
    """
    if chapters:
        ordered = sorted(chapters.items())
        chunks: list[dict] = []
        current: list[tuple[int, str]] = []
        current_len = 0

        def flush() -> None:
            nonlocal current, current_len
            if not current:
                return
            ch_start = current[0][0]
            ch_end = current[-1][0]
            chunk_text = "\n\n".join(t for _, t in current)
            start = _find_chapter_start(text, current[0][1])
            end = _find_chapter_end(text, current[-1][1], start)
            chunks.append({
                "index": len(chunks) + 1,
                "start": start,
                "end": end,
                "char_count": len(chunk_text),
                "text": chunk_text,
                "context_before": text[max(0, start - overlap_chars):start] if start >= 0 else "",
                "context_after": text[end:min(len(text), end + overlap_chars)] if end >= 0 else "",
                "chapter_start": ch_start,
                "chapter_end": ch_end,
                "chapters": [ch for ch, _ in current],
            })
            current = []
            current_len = 0

        for chapter_num, chapter_text in ordered:
            ch_len = len(chapter_text)
            if current and current_len + ch_len > max_chars:
                flush()
            if ch_len > max_chars * 1.5:
                flush()
                for sub in chunk_story(chapter_text, max_chars=max_chars, overlap=overlap_chars):
                    chunks.append({
                        **sub,
                        "index": len(chunks) + 1,
                        "chapter_start": chapter_num,
                        "chapter_end": chapter_num,
                        "chapters": [chapter_num],
                    })
                continue
            current.append((chapter_num, chapter_text))
            current_len += ch_len
        flush()
        return chunks

    chunks = chunk_story(text, max_chars=max_chars, overlap=overlap_chars)
    for chunk in chunks:
        chunk["chapter_start"] = 1
        chunk["chapter_end"] = 1
        chunk["chapters"] = [1]
    return chunks


def _find_chapter_start(text: str, chapter_text: str) -> int:
    needle = chapter_text[:80]
    pos = text.find(needle) if needle else -1
    return pos if pos >= 0 else 0


def _find_chapter_end(text: str, chapter_text: str, start: int) -> int:
    if start < 0:
        return len(text)
    return min(len(text), start + len(chapter_text))


def build_chapter_index(text: str) -> dict[int, str]:
    """Scan raw text for 第N章 markers, extract chapter number → chapter text mapping.

    Pure text processing, no LLM. Returns empty dict if no chapter markers found.
    """
    matches = list(_CHAPTER_NUM_PATTERN.finditer(text))
    if not matches:
        return {}

    chapters: dict[int, str] = {}
    for i, m in enumerate(matches):
        num_str = m.group(1)
        chapter_num = _cn_to_int(num_str)
        if chapter_num is None:
            continue

        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chapters[chapter_num] = text[start:end].strip()

    return chapters


def sample_for_bible(chunks: list[dict], max_chars: int = 80000) -> str:
    """Pick representative chunks for bible extraction.

    Strategy: first 2 + last 2 + evenly spaced middle chunks, up to max_chars.
    This captures the full story arc without exceeding context.
    """
    if not chunks:
        return ""

    n = len(chunks)

    if n <= 4:
        # Small enough — use all chunks
        selected = list(range(n))
    else:
        # First 2 + last 2
        selected = [0, 1, n - 2, n - 1]

        # Fill middle slots evenly
        middle_indices = list(range(2, n - 2))
        remaining_budget = max_chars - sum(chunks[i]['char_count'] for i in selected)

        if remaining_budget > 0 and middle_indices:
            # Pick evenly spaced middle chunks
            step = max(1, len(middle_indices) // 6)  # aim for ~6 middle samples
            for idx in middle_indices[::step]:
                if remaining_budget <= 0:
                    break
                selected.append(idx)
                remaining_budget -= chunks[idx]['char_count']

        selected = sorted(set(selected))

    # Assemble text, truncating if needed
    parts = []
    total = 0
    for idx in selected:
        chunk_text = chunks[idx]['text']
        if total + len(chunk_text) > max_chars:
            # Truncate this chunk to fit
            remaining = max_chars - total
            if remaining > 1000:  # only include if meaningful
                parts.append(f"\n--- Chunk {chunks[idx]['index']} (truncated) ---\n")
                parts.append(chunk_text[:remaining])
            break
        parts.append(f"\n--- Chunk {chunks[idx]['index']} ---\n")
        parts.append(chunk_text)
        total += len(chunk_text)

    return "".join(parts)
