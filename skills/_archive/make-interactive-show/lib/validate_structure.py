#!/usr/bin/env python3
"""Validate a lean interactive show structure.json for consistency.

Lean structure.json format:
  - episodes[]: array of {id, title, thread, chapter_source, summary, beat_type, beat_label, choice}
  - choice: {type, question, options[{text, outcome, next}]}
  - endings[]: array of {id, name, episode, tone, description}
  - stats: {total_episodes, playthrough_episodes, total_forks, ...}

Checks:
  1. DAG integrity — all choice.options[].next targets exist as episode IDs
  2. Fork structure — enough fork/flavor choices per branching spec
  3. Choice quality — no duplicate option text/outcome, type consistency
  4. Option text length — ≤ 8 Chinese characters
  5. Ending reachability — ending episodes exist
  6. Stats consistency — stats block matches actual counts
  7. Episode reachability — all episodes reachable from EP01

Usage:
    python validate_structure.py <project_dir>

Output:
    Prints validation report to stdout.
    Writes $PROJECT_DIR/validation_report.md
"""

import argparse
import json
import os
import sys
from collections import defaultdict


# ── Helpers ──────────────────────────────────────────────────────────

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_choice(ep):
    """Get the choice dict from an episode (lean format: single 'choice' dict)."""
    choice = ep.get("choice")
    if isinstance(choice, dict):
        return choice
    return None


# ── Validators ───────────────────────────────────────────────────────

class ValidationResult:
    def __init__(self):
        self.errors = []    # hard failures
        self.warnings = []  # soft issues
        self.info = []      # informational

    def error(self, category, msg):
        self.errors.append((category, msg))

    def warn(self, category, msg):
        self.warnings.append((category, msg))

    def note(self, category, msg):
        self.info.append((category, msg))

    @property
    def ok(self):
        return len(self.errors) == 0


def validate_dag(structure, result):
    """Check DAG integrity and that every option leads to a DIFFERENT episode."""
    episode_ids = {ep["id"] for ep in structure.get("episodes", [])}

    for ep in structure.get("episodes", []):
        choice = get_choice(ep)
        if not choice:
            # Dead end or ending episodes have no choice — that's OK
            if ep.get("is_dead_end") or ep.get("beat_type") in ("dead_end", "ending"):
                continue
            result.warn("DAG", f"{ep['id']}: no choice defined (not marked as dead end)")
            continue

        options = choice.get("options", [])
        next_targets = []
        for opt in options:
            target = opt.get("next", "")
            if not target:
                result.error("DAG", f"{ep['id']} option '{opt.get('text', '?')}': missing 'next' target")
            elif target not in episode_ids:
                result.error("DAG", f"{ep['id']} option '{opt.get('text', '?')}': next='{target}' not found in episodes")
            else:
                next_targets.append(target)

        # CRITICAL: every option must lead to a DIFFERENT episode
        if len(next_targets) >= 2 and len(set(next_targets)) < len(next_targets):
            dupes = [t for t in next_targets if next_targets.count(t) > 1]
            result.error("DAG", f"{ep['id']}: multiple options lead to same episode '{dupes[0]}' — every option must go to a different episode")

    result.note("DAG", f"Total episodes: {len(episode_ids)}")


def validate_dead_ends(structure, result):
    """Check dead ends are present and scattered throughout."""
    episodes = structure.get("episodes", [])
    total_episodes = len(episodes)

    dead_ends = [ep for ep in episodes if ep.get("is_dead_end") or ep.get("beat_type") == "dead_end"]
    story_eps = [ep for ep in episodes if not (ep.get("is_dead_end") or ep.get("beat_type") == "dead_end")]

    num_dead = len(dead_ends)
    min_dead = max(3, round(total_episodes * 0.15))
    max_dead = round(total_episodes * 0.25) + 1

    if num_dead < min_dead:
        result.error("DEAD_ENDS", f"Need ≥ {min_dead} dead ends for {total_episodes} episodes, got {num_dead}")
    elif num_dead > max_dead:
        result.warn("DEAD_ENDS", f"{num_dead} dead ends may be too many for {total_episodes} episodes (target: {min_dead}-{max_dead})")

    # Check scatter: dead ends should be reachable from different parts of the DAG
    # Simple check: verify dead ends are targeted by different source episodes
    dead_end_ids = {ep["id"] for ep in dead_ends}
    sources = set()
    for ep in episodes:
        choice = get_choice(ep)
        if not choice:
            continue
        for opt in choice.get("options", []):
            if opt.get("next", "") in dead_end_ids:
                sources.add(ep["id"])

    if sources and len(sources) < min(3, num_dead):
        result.warn("DEAD_ENDS", f"Dead ends only reachable from {len(sources)} episode(s) — should be scattered")

    # Check dead end episodes have no choice
    for de in dead_ends:
        if get_choice(de):
            result.error("DEAD_ENDS", f"{de['id']}: dead end should have choice=null")

    result.note("DEAD_ENDS", f"{num_dead} dead end(s), reachable from {len(sources)} source episode(s)")


GENERIC_QUESTIONS = {
    "下一步怎么办", "你的选择是", "接下来怎么办", "怎么办",
    "你想怎么做", "如何选择", "你会怎么做", "做出选择",
}


def validate_choice_quality(structure, result):
    """Check choice quality: unique targets, no duplicate text/outcome, no generic questions."""
    total_choices = 0
    violations = 0

    for ep in structure.get("episodes", []):
        ep_id = ep.get("id", "?")
        choice = get_choice(ep)
        if not choice:
            continue

        total_choices += 1
        options = choice.get("options", [])

        # Check minimum 2 options
        if len(options) < 2:
            result.error("CHOICE_QUALITY",
                f"{ep_id}: only {len(options)} option(s), need ≥ 2")
            violations += 1

        # Check all options lead to DIFFERENT episodes (critical rule)
        next_targets = [opt.get("next", "") for opt in options if opt.get("next")]
        if len(next_targets) >= 2 and len(set(next_targets)) < len(next_targets):
            result.error("CHOICE_QUALITY",
                f"{ep_id}: options share same next target — every option must lead to a different episode")
            violations += 1

        # Check duplicate option text
        seen_texts = set()
        for opt in options:
            t = opt.get("text", "")
            if t and t in seen_texts:
                result.error("CHOICE_QUALITY",
                    f"{ep_id}: duplicate option text '{t}'")
                violations += 1
            seen_texts.add(t)

        # Check duplicate outcome text
        seen_outcomes = set()
        for opt in options:
            o = opt.get("outcome", "")
            if o and o in seen_outcomes:
                result.error("CHOICE_QUALITY",
                    f"{ep_id}: duplicate option outcome '{o[:40]}...'")
                violations += 1
            seen_outcomes.add(o)

        # Check generic question
        question = choice.get("question", "")
        if question in GENERIC_QUESTIONS:
            result.warn("CHOICE_QUALITY",
                f"{ep_id}: generic question '{question}' — should reference episode hook")

    if violations == 0:
        result.note("CHOICE_QUALITY", f"All {total_choices} choices passed quality checks")
    else:
        result.note("CHOICE_QUALITY", f"{violations} violation(s) in {total_choices} choices")


def validate_option_text_length(structure, result):
    """Check that all choice option text fields are ≤ 8 Chinese characters."""
    violations = 0
    for ep in structure.get("episodes", []):
        choice = get_choice(ep)
        if not choice:
            continue
        for opt in choice.get("options", []):
            text = opt.get("text", "")
            char_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
            if char_count == 0:
                char_count = sum(1 for c in text if ord(c) > 127)
            if char_count > 8:
                result.error("OPTION_TEXT",
                    f"{ep['id']} option '{text}': {char_count} chars (max 8)")
                violations += 1

    if violations == 0:
        result.note("OPTION_TEXT", "All option texts ≤ 8 characters")
    else:
        result.note("OPTION_TEXT", f"{violations} option text violation(s) found")


def validate_endings(structure, result):
    """Check that ending episodes exist."""
    episode_ids = {ep["id"] for ep in structure.get("episodes", [])}
    endings = structure.get("endings", [])

    if not endings:
        result.warn("ENDINGS", "No endings defined")
        return

    for ending in endings:
        ep = ending.get("episode", "")
        if ep and ep not in episode_ids:
            result.error("ENDINGS", f"Ending '{ending.get('id', '?')}' references episode '{ep}' which doesn't exist")

    result.note("ENDINGS", f"{len(endings)} ending(s) defined")


def validate_stats(structure, result):
    """Check the stats summary block for consistency."""
    stats = structure.get("stats", {})
    if not stats:
        result.warn("STATS", "No stats block found")
        return

    episodes = structure.get("episodes", [])
    endings = structure.get("endings", [])

    actual_forks = 0
    for ep in episodes:
        choice = get_choice(ep)
        if choice and choice.get("type") == "fork":
            actual_forks += 1

    checks = [
        ("total_episodes", len(episodes), stats.get("total_episodes", 0)),
        ("total_endings", len(endings), stats.get("total_endings", 0)),
        ("total_forks", actual_forks, stats.get("total_forks", 0)),
    ]

    for name, actual, declared in checks:
        if declared and actual != declared:
            result.warn("STATS", f"stats.{name}: declared {declared}, actual {actual}")
        elif declared:
            result.note("STATS", f"stats.{name}: {actual} ✓")


def validate_reachability(structure, result):
    """Check that all episodes are reachable from EP01 via BFS."""
    episodes = structure.get("episodes", [])
    if not episodes:
        return

    episode_ids = {ep["id"] for ep in episodes}
    entry = episodes[0]["id"]

    adj = defaultdict(set)
    for ep in episodes:
        choice = get_choice(ep)
        if not choice:
            continue
        for opt in choice.get("options", []):
            target = opt.get("next", "")
            if target and target in episode_ids:
                adj[ep["id"]].add(target)

    visited = set()
    queue = [entry]
    while queue:
        node = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        for neighbor in adj.get(node, []):
            if neighbor not in visited:
                queue.append(neighbor)

    unreachable = episode_ids - visited
    if unreachable:
        for ep_id in sorted(unreachable):
            result.warn("REACHABILITY", f"Episode '{ep_id}' is unreachable from {entry}")
    else:
        result.note("REACHABILITY", f"All {len(episode_ids)} episodes reachable from {entry}")


# ── Report generation ────────────────────────────────────────────────

def generate_report(result, project_dir):
    """Generate markdown validation report."""
    lines = ["# Structure Validation Report\n"]

    lines.append("## Summary\n")
    lines.append(f"- Errors: **{len(result.errors)}**")
    lines.append(f"- Warnings: **{len(result.warnings)}**")
    lines.append(f"- Info: {len(result.info)}")
    lines.append(f"- Overall: **{'PASS' if result.ok else 'FAIL'}**\n")

    if result.errors:
        lines.append("## Errors (must fix)\n")
        for cat, msg in result.errors:
            lines.append(f"- **[{cat}]** {msg}")
        lines.append("")

    if result.warnings:
        lines.append("## Warnings (should fix)\n")
        for cat, msg in result.warnings:
            lines.append(f"- **[{cat}]** {msg}")
        lines.append("")

    if result.info:
        lines.append("## Details\n")
        current_cat = None
        for cat, msg in result.info:
            if cat != current_cat:
                lines.append(f"\n### {cat}\n")
                current_cat = cat
            lines.append(f"- {msg}")
        lines.append("")

    report = "\n".join(lines)

    report_path = os.path.join(project_dir, "validation_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    return report_path


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Validate lean interactive show structure.json")
    parser.add_argument("project_dir", help="Project directory containing structure.json")
    args = parser.parse_args()

    structure_path = os.path.join(args.project_dir, "structure.json")
    if not os.path.exists(structure_path):
        print(f"ERROR: {structure_path} not found")
        sys.exit(1)

    structure = load_json(structure_path)
    result = ValidationResult()

    print("Running validators...")
    validate_dag(structure, result)
    validate_dead_ends(structure, result)
    validate_choice_quality(structure, result)
    validate_option_text_length(structure, result)
    validate_endings(structure, result)
    validate_reachability(structure, result)
    validate_stats(structure, result)

    report_path = generate_report(result, args.project_dir)

    print(f"\n{'='*60}")
    print(f"  VALIDATION {'PASSED' if result.ok else 'FAILED'}")
    print(f"  Errors: {len(result.errors)}  |  Warnings: {len(result.warnings)}")
    print(f"{'='*60}\n")

    if result.errors:
        print("ERRORS:")
        for cat, msg in result.errors:
            print(f"  ✗ [{cat}] {msg}")
        print()

    if result.warnings:
        print("WARNINGS:")
        for cat, msg in result.warnings:
            print(f"  ⚠ [{cat}] {msg}")
        print()

    print(f"Full report: {report_path}")

    sys.exit(0 if result.ok else 1)


if __name__ == "__main__":
    main()
