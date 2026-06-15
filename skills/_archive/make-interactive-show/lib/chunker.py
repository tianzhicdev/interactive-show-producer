#!/usr/bin/env python3
"""Chunk a large story file at chapter/scene boundaries with overlap context.

Usage:
    python chunker.py <story_file> <output_dir> [--max-chars 30000] [--overlap 2000]

Output:
    <output_dir>/chunks/chunk_001.txt
    <output_dir>/chunks/chunk_002.txt
    ...
    <output_dir>/chunks/manifest.json
"""
import argparse
import json
import os
import re
import sys


# ── Chapter/scene break detection ────────────────────────────────────

# Chinese chapter patterns: 第1章, 第一章, 第二十三章, etc.
_CN_NUM = r'[一二三四五六七八九十百千万零〇\d]+'
_CHAPTER_PATTERNS = [
    re.compile(rf'^第{_CN_NUM}[章节卷集幕回]', re.MULTILINE),       # 第N章/节/卷/集/幕/回
    re.compile(r'^Chapter\s+\d+', re.MULTILINE | re.IGNORECASE),     # Chapter N
    re.compile(r'^CHAPTER\s+\d+', re.MULTILINE),                     # CHAPTER N
    re.compile(r'^\d+\.\s+\S', re.MULTILINE),                        # 1. Title
]

# Scene break patterns (standalone separator lines)
_SCENE_BREAK = re.compile(
    r'^[\s]*(?:[*]{3,}|[-]{3,}|[—]{3,}|[=]{3,}|[…]{3,}|[·]{3,}|~~~)[\s]*$',
    re.MULTILINE
)


def find_split_points(text: str) -> list[int]:
    """Find all chapter and scene-break positions in the text."""
    points = set()

    # Chapter markers
    for pat in _CHAPTER_PATTERNS:
        for m in pat.finditer(text):
            points.add(m.start())

    # Scene breaks (only use if fewer than 500 — otherwise too granular)
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

    Returns list of dicts: {index, start, end, text, context_before, context_after}
    """
    split_points = find_split_points(text)
    text_len = len(text)

    if not split_points or split_points[0] > 0:
        split_points.insert(0, 0)

    # Merge split points that are too close together
    merged = [split_points[0]]
    for pt in split_points[1:]:
        if pt - merged[-1] > 500:  # minimum 500 chars between splits
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
            # Merge this segment into current chunk
            current_end = seg_end
        else:
            # Current chunk is big enough, finalize it
            chunks_ranges.append((current_start, current_end))
            current_start = seg_start
            current_end = seg_end

    # Don't forget the last chunk
    chunks_ranges.append((current_start, current_end))

    # Split any chunks that are still too large
    final_ranges = []
    for start, end in chunks_ranges:
        if end - start <= max_chars * 1.5:
            final_ranges.append((start, end))
        else:
            # Split at paragraph breaks
            para_breaks = find_paragraph_breaks(text, start, end)
            if not para_breaks:
                # No paragraph breaks — force split
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


def detect_title(text: str) -> str:
    """Try to extract the story title from the first few lines."""
    lines = text[:2000].strip().split('\n')
    for line in lines[:10]:
        line = line.strip()
        if line and len(line) < 50 and not line.startswith(('本书', '【', '——', 'http')):
            return line
    return 'Untitled'


def main():
    parser = argparse.ArgumentParser(description='Chunk a story file at natural boundaries')
    parser.add_argument('story_file', help='Path to the story text file')
    parser.add_argument('output_dir', help='Output directory for chunks')
    parser.add_argument('--max-chars', type=int, default=30000, help='Max chars per chunk (default: 30000)')
    parser.add_argument('--overlap', type=int, default=2000, help='Overlap chars for context (default: 2000)')
    args = parser.parse_args()

    # Read story
    with open(args.story_file, 'r', encoding='utf-8') as f:
        text = f.read()

    print(f'Story file: {args.story_file}')
    print(f'Total chars: {len(text):,}')
    print(f'Total lines: {text.count(chr(10)):,}')

    # Detect title
    title = detect_title(text)
    print(f'Detected title: {title}')

    # Chunk
    chunks = chunk_story(text, max_chars=args.max_chars, overlap=args.overlap)
    print(f'Chunks: {len(chunks)}')

    # Write chunks
    chunks_dir = os.path.join(args.output_dir, 'chunks')
    os.makedirs(chunks_dir, exist_ok=True)

    manifest_entries = []
    for chunk in chunks:
        filename = f'chunk_{chunk["index"]:03d}.txt'
        filepath = os.path.join(chunks_dir, filename)

        # Write chunk with context markers
        with open(filepath, 'w', encoding='utf-8') as f:
            if chunk['context_before']:
                f.write('=== CONTEXT FROM PREVIOUS SECTION ===\n')
                f.write(chunk['context_before'])
                f.write('\n=== END CONTEXT ===\n\n')
            f.write(chunk['text'])
            if chunk['context_after']:
                f.write('\n\n=== CONTEXT FROM NEXT SECTION ===\n')
                f.write(chunk['context_after'])
                f.write('\n=== END CONTEXT ===\n')

        manifest_entries.append({
            'index': chunk['index'],
            'filename': filename,
            'char_count': chunk['char_count'],
            'start': chunk['start'],
            'end': chunk['end'],
            'has_context_before': bool(chunk['context_before']),
            'has_context_after': bool(chunk['context_after']),
        })

        size_bar = '#' * (chunk['char_count'] // 1000)
        print(f'  chunk_{chunk["index"]:03d}.txt  {chunk["char_count"]:>6,} chars  {size_bar}')

    # Write manifest
    manifest = {
        'title': title,
        'source_file': os.path.abspath(args.story_file),
        'total_chars': len(text),
        'total_chunks': len(chunks),
        'max_chars': args.max_chars,
        'overlap': args.overlap,
        'chunks': manifest_entries,
    }
    manifest_path = os.path.join(args.output_dir, 'chunks', 'manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f'\nManifest: {manifest_path}')
    print('Done.')


if __name__ == '__main__':
    main()
