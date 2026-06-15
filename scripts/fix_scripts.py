#!/usr/bin/env python3
"""Fix script files: add choice questions, clean up option labels, improve branch format."""

import json
import os
import re
import sys
from typing import Optional


def load_questions(structure_path: str) -> dict:
    """Load choice questions from structure.json keyed by episode ID."""
    with open(structure_path, "r", encoding="utf-8") as f:
        structure = json.load(f)
    questions = {}
    for ep in structure["episodes"]:
        if ep.get("choice"):
            questions[ep["id"]] = ep["choice"]["question"]
    return questions


def fix_script(filepath: str, question: Optional[str]) -> bool:
    """Fix a single script file. Returns True if modified."""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    original = content

    # 1. Remove （≤8字） from option labels
    content = re.sub(r'（≤8字）', '', content)

    # 2. Add question line after "选择 NNN" if not already present
    if question:
        def add_question(match):
            choice_line = match.group(0)
            # Check if next non-empty line already starts with "问题：" or "▲画面定格"
            return f"{choice_line}\n问题：{question}"

        # Match "选择 NNN" that is NOT already followed by "问题："
        content = re.sub(
            r'^(选择 \d{3})$(?!\n问题：)',
            add_question,
            content,
            count=1,
            flags=re.MULTILINE,
        )

    # 3. Convert --- NNNA: xxx --- parallel format to table-style
    # Replace "--- NNNA：xxx ---          --- NNNB：xxx ---" header pairs
    # with cleaner boxed headers
    content = re.sub(
        r'^--- (\d{3}[A-C])：(.+?) ---\s+--- (\d{3}[A-C])：(.+?) ---\s*$',
        r'┌──────────────────────────────────┬──────────────────────────────────┐\n'
        r'│ \1：\2\n'
        r'├──────────────────────────────────┤\n',
        content,
        flags=re.MULTILINE,
    )

    # Actually, let's use a simpler, more readable approach:
    # Just add a clear section header with box drawing
    content = re.sub(
        r'^--- (\d{3}[A-C])：(.+?) ---$',
        r'━━━━━━━━━━ \1：\2 ━━━━━━━━━━',
        content,
        flags=re.MULTILINE,
    )

    if content != original:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    return False


def main():
    if len(sys.argv) < 2:
        print("Usage: python fix_scripts.py <project_dir>")
        sys.exit(1)

    project_dir = sys.argv[1]
    scripts_dir = os.path.join(project_dir, "scripts")
    structure_path = os.path.join(project_dir, "structure.json")

    questions = load_questions(structure_path)

    modified = 0
    for filename in sorted(os.listdir(scripts_dir)):
        if not filename.endswith(".txt"):
            continue
        ep_id = filename.replace(".txt", "")
        question = questions.get(ep_id)
        filepath = os.path.join(scripts_dir, filename)
        if fix_script(filepath, question):
            modified += 1
            print(f"  Fixed: {filename}" + (f" (added question)" if question else ""))

    print(f"\nModified {modified} files")


if __name__ == "__main__":
    main()
