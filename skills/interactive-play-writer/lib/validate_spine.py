#!/usr/bin/env python3
"""Deterministic validators for the spine format.

AUTHORITATIVE GATE — blocks the build on failure.
Reads only registry state (boolean/enum).  Has no opinion on free-text
fields (goal, title, summary, beats — those are affect/generation context).

Semantic (LLM) checks are ADVISORY — see validate_spine_advisory().
They flag but never block.

Checks (deterministic, blocking):
  1. DAG integrity (all edge targets valid, no self-loops)
  2. Reachability (BFS from entry, all endings reachable)
  3. Registry consistency (effects/predicates reference declared vars)
  4. State discipline (boolean/enum enforced; bounded_int flagged for review)
  5. Bottleneck invariants (canon predicates over boolean/enum only)
  6. Affect guard (no feelings quantized into state)
  7. Duration budget (each episode ~3 min)
  8. Edge labels (≤8 CJK chars, no duplicates per node)

Advisory checks (non-blocking):
  - bounded_int usage → suggests boolean replacement
  - Bottleneck convergence order

Usage:
    python validate_spine.py <project_dir>
"""
import argparse
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from data_model import (
    SpineState, Spine, Registry, Node, Edge, Effect, Predicate,
    load_state, state_at, path_duration,
)
import re


# ── Validation result container ─────────────────────────────────────

class ValidationResult:
    """Three severity levels:

    errors   — deterministic gate failures.  BLOCK the build.
    warnings — deterministic issues that should be fixed but don't block.
    advisory — semantic/human-review flags.  NEVER block.
    info     — informational notes.
    """
    def __init__(self):
        self.errors: list[tuple[str, str]] = []    # blocking
        self.warnings: list[tuple[str, str]] = []  # should fix
        self.advisory: list[tuple[str, str]] = []  # never blocks
        self.info: list[tuple[str, str]] = []

    def error(self, category: str, msg: str):
        self.errors.append((category, msg))

    def warn(self, category: str, msg: str):
        self.warnings.append((category, msg))

    def advise(self, category: str, msg: str):
        """Advisory flag — semantic/human review.  Never blocks."""
        self.advisory.append((category, msg))

    def note(self, category: str, msg: str):
        self.info.append((category, msg))

    @property
    def ok(self) -> bool:
        """Errors AND warnings both block. Advisory items are informational only."""
        return len(self.errors) == 0 and len(self.warnings) == 0


# ── Deterministic validators (blocking) ─────────────────────────────

def validate_dag_integrity(spine: Spine, result: ValidationResult):
    """Check all edge targets exist and no self-loops."""
    node_ids = spine.node_ids()

    for edge in spine.edges:
        if edge.src not in node_ids:
            result.error("DAG", f"Edge '{edge.id}': src '{edge.src}' not in nodes")
        if edge.dst not in node_ids:
            result.error("DAG", f"Edge '{edge.id}': dst '{edge.dst}' not in nodes")
        if edge.src == edge.dst:
            result.error("DAG", f"Edge '{edge.id}': self-loop on '{edge.src}'")

    if spine.entry_node and spine.entry_node not in node_ids:
        result.error("DAG", f"Entry node '{spine.entry_node}' not in nodes")
    elif not spine.entry_node and spine.nodes:
        result.warn("DAG", "No entry_node specified")

    # Duplicate IDs
    edge_ids_seen: set[str] = set()
    for e in spine.edges:
        if e.id in edge_ids_seen:
            result.error("DAG", f"Duplicate edge ID '{e.id}'")
        edge_ids_seen.add(e.id)

    nid_seen: set[str] = set()
    for n in spine.nodes:
        if n.id in nid_seen:
            result.error("DAG", f"Duplicate node ID '{n.id}'")
        nid_seen.add(n.id)

    result.note("DAG", f"Nodes: {len(spine.nodes)}, Edges: {len(spine.edges)}")


def validate_reachability(spine: Spine, result: ValidationResult):
    """BFS from entry: all nodes reachable, all endings reachable."""
    if not spine.entry_node:
        result.warn("REACHABILITY", "No entry node — skipping")
        return

    reachable = spine.reachable_from(spine.entry_node)
    all_ids = spine.node_ids()
    unreachable = all_ids - reachable

    if unreachable:
        for nid in sorted(unreachable):
            result.error("REACHABILITY", f"'{nid}' unreachable from entry '{spine.entry_node}'")
    else:
        result.note("REACHABILITY", f"All {len(all_ids)} nodes reachable from '{spine.entry_node}'")

    endings = spine.ending_nodes()
    if not endings:
        result.warn("REACHABILITY", "No ending nodes defined")
    else:
        for node in endings:
            if node.id not in reachable:
                result.error("REACHABILITY", f"Ending '{node.id}' unreachable from entry")
        result.note("REACHABILITY", f"{len(endings)} ending node(s)")


def validate_registry_consistency(spine: Spine, registry: Registry, result: ValidationResult):
    """Effects/predicates must reference declared vars with correct types."""
    for edge in spine.edges:
        for effect in edge.effects:
            for err in effect.validate_against(registry):
                result.error("REGISTRY", f"Edge '{edge.id}': {err}")

    for node in spine.nodes:
        for pred in node.requires:
            for err in pred.validate_against(registry):
                result.error("REGISTRY", f"Node '{node.id}' requires: {err}")

    reg_errs = registry.validate()
    for err in reg_errs:
        result.error("REGISTRY", err)

    result.note("REGISTRY", f"{len(registry.vars)} var(s): {', '.join(sorted(registry.keys()))}")


def validate_state_discipline(registry: Registry, result: ValidationResult):
    """Enforce: state = boolean | enum.  bounded_int is flagged for human review."""
    for var in registry.vars:
        if var.type == "bounded_int":
            result.advise("STATE_DISCIPLINE",
                f"'{var.key}' uses bounded_int [{var.min_val}..{var.max_val}] — "
                f"can this be a qualifying boolean decided at a bottleneck instead? "
                f"(e.g. '{var.key}_sufficient' = true/false)")
        if var.type not in ("boolean", "enum", "bounded_int"):
            result.error("STATE_DISCIPLINE",
                f"'{var.key}' has illegal type '{var.type}' — "
                f"state vars must be boolean or enum (bounded_int rare exception)")

    bool_count = sum(1 for v in registry.vars if v.type == "boolean")
    enum_count = sum(1 for v in registry.vars if v.type == "enum")
    int_count = sum(1 for v in registry.vars if v.type == "bounded_int")
    result.note("STATE_DISCIPLINE", f"boolean: {bool_count}, enum: {enum_count}, bounded_int: {int_count}")


def validate_bottleneck_invariants(spine: Spine, registry: Registry, result: ValidationResult):
    """Bottleneck invariants must be canon predicates over boolean/enum state.

    A bottleneck gates incoming state — it does NOT hold its own state.
    Invariants are the author's non-negotiable facts restated as predicates.
    Thresholds over bounded_int (grief >= 8) are illegal as invariants.
    """
    for node in spine.nodes:
        if node.kind != "bottleneck" and node.invariants:
            result.warn("INVARIANT",
                f"'{node.id}' (kind={node.kind}) has invariants — only bottlenecks should")

        for pred in node.invariants:
            # Use the stricter invariant-specific validation
            for err in pred.validate_as_invariant(registry):
                result.error("INVARIANT", f"'{node.id}': {err}")

    bn_with_inv = sum(1 for n in spine.nodes if n.kind == "bottleneck" and n.invariants)
    bn_total = sum(1 for n in spine.nodes if n.kind == "bottleneck")
    result.note("INVARIANT", f"{bn_with_inv}/{bn_total} bottleneck(s) have invariants")


def validate_affect_guard(spine: Spine, registry: Registry, result: ValidationResult):
    """Affect-driven content must never be quantized into state.

    Check that no registry var looks like it encodes feelings/mood.
    This is a heuristic — flag for human review, don't hard-block.
    """
    AFFECT_PATTERNS = [
        'grief', 'anger', 'fear', 'joy', 'sadness', 'happiness',
        'mood', 'emotion', 'feeling', 'morale', 'anxiety', 'stress',
        'love', 'hate', 'rage', 'sorrow', 'despair', 'hope',
        '悲', '怒', '恐', '喜', '哀', '情绪', '心情', '感情',
    ]
    for var in registry.vars:
        key_lower = var.key.lower()
        for pat in AFFECT_PATTERNS:
            if pat in key_lower:
                result.advise("AFFECT_GUARD",
                    f"'{var.key}' looks like affect/feeling — "
                    f"affect must not be state. If this is genuinely a "
                    f"plot-boolean (character_grieving = true after death scene), "
                    f"it's fine. If it's a mood meter, remove it.")
                break

    result.note("AFFECT_GUARD", "Affect guard check complete")


def validate_bottleneck_alignment(spine: Spine, result: ValidationResult):
    """Check bottlenecks: convergence points reachable from all prior paths."""
    bottlenecks = spine.bottleneck_nodes()
    if not bottlenecks:
        result.warn("BOTTLENECK", "No bottleneck nodes found")
        return

    bn_ids = [bn.id for bn in bottlenecks]

    if spine.entry_node:
        paths = spine.all_paths()
        for path in paths:
            bn_order = [nid for nid in path if nid in set(bn_ids)]
            expected = [bid for bid in bn_ids if bid in set(path)]
            if bn_order != expected:
                result.warn("BOTTLENECK",
                    f"Path {' → '.join(path[:3])}...{path[-1]} bottlenecks in unexpected order")

    result.note("BOTTLENECK", f"{len(bottlenecks)} bottleneck(s): {', '.join(bn_ids)}")


def validate_duration_budget(spine: Spine, result: ValidationResult):
    """Each node = one episode = ~3 min."""
    if not spine.nodes:
        return

    for node in spine.nodes:
        if node.duration_min <= 0:
            result.warn("DURATION", f"{node.id} has duration_min={node.duration_min}")

    durations = [n.duration_min for n in spine.nodes]
    avg = sum(durations) / len(durations)
    for node in spine.nodes:
        if avg > 0 and node.duration_min > avg * 2:
            result.warn("DURATION", f"{node.id} ({node.duration_min:.1f}min) >2x average ({avg:.1f}min)")

    total = sum(durations)
    result.note("DURATION", f"{len(spine.nodes)} episodes, total {total:.1f} min, avg {avg:.1f} min/ep")


def validate_edge_labels(spine: Spine, result: ValidationResult):
    """Edge labels ≤8 CJK chars, no duplicates per source node."""
    src_labels: dict[str, list[str]] = defaultdict(list)

    for edge in spine.edges:
        label = edge.label
        if not label:
            continue
        cjk_count = sum(1 for c in label if '\u4e00' <= c <= '\u9fff')
        if cjk_count == 0:
            cjk_count = len(label)
        if cjk_count > 8:
            result.error("EDGE_LABEL", f"Edge '{edge.id}' label '{label}' has {cjk_count} chars (max 8)")
        src_labels[edge.src].append(label)

    for src, labels in src_labels.items():
        seen: set[str] = set()
        for lab in labels:
            if lab in seen:
                result.error("EDGE_LABEL", f"Duplicate label '{lab}' from node '{src}'")
            seen.add(lab)

    total_labeled = sum(len(v) for v in src_labels.values())
    result.note("EDGE_LABEL", f"{total_labeled} labeled edge(s)")


# ── Step-2 validators (gated on state.step >= "step-2") ─────────────

def validate_path_budget(state: SpineState, result: ValidationResult):
    """Every entry→ending path ≤ playthrough_target × 1.2."""
    spine = state.spine
    target = state.metadata.get("playthrough_target_min", 50)
    ceiling = target * 1.2

    paths = spine.all_paths()
    if not paths:
        result.warn("PATH_BUDGET", "No paths found")
        return

    for path in paths:
        dur = path_duration(spine, path)
        # Dead-end paths get a pass on being short
        end_node = spine.get_node(path[-1])
        is_dead_end = end_node and end_node.id.startswith("DE")
        if dur > ceiling:
            result.error("PATH_BUDGET",
                f"Path {path[0]}→{path[-1]} is {dur:.1f}min, exceeds ceiling {ceiling:.1f}min")
        elif not is_dead_end and dur < target * 0.5:
            result.warn("PATH_BUDGET",
                f"Path {path[0]}→{path[-1]} is {dur:.1f}min, unusually short vs target {target}min")

    durations = [path_duration(spine, p) for p in paths]
    result.note("PATH_BUDGET",
        f"{len(paths)} paths, range {min(durations):.1f}-{max(durations):.1f}min, target {target}min")


def validate_total_budget(state: SpineState, result: ValidationResult):
    """Sum of all node durations ≤ total_budget."""
    spine = state.spine
    total_budget = state.metadata.get("total_budget_min", 100)
    total = sum(n.duration_min for n in spine.nodes)

    if total > total_budget:
        result.error("TOTAL_BUDGET",
            f"Total node-minutes {total:.1f} exceeds budget {total_budget}")
    else:
        result.note("TOTAL_BUDGET",
            f"Total {total:.1f}min / {total_budget}min budget ({total/total_budget*100:.0f}% used)")


def validate_state_coherence(state: SpineState, result: ValidationResult):
    """Every node.requires satisfied by at least one incoming path."""
    spine = state.spine
    registry = state.registry

    for node in spine.nodes:
        if not node.requires:
            continue
        # Find all paths from entry to this node
        predecessors = spine.get_predecessors(node.id)
        if not predecessors and node.id != spine.entry_node:
            continue  # unreachable — caught by reachability validator

        # Check each requires predicate: at least one incoming path must satisfy it
        paths_to_node = spine.all_paths(end=node.id)
        if not paths_to_node:
            result.warn("STATE_COHERENCE",
                f"No paths reach '{node.id}' — cannot verify requires")
            continue

        for pred in node.requires:
            satisfied = False
            for path in paths_to_node:
                s = state_at(spine, registry, path)
                if pred.evaluate(s):
                    satisfied = True
                    break
            if not satisfied:
                result.error("STATE_COHERENCE",
                    f"'{node.id}' requires `{pred.key} {pred.cmp} {pred.value}` "
                    f"but no incoming path satisfies it")

    result.note("STATE_COHERENCE", "State coherence check complete")


def validate_bottleneck_convergence(state: SpineState, result: ValidationResult):
    """All principal (non-dead-end) paths pass through bottlenecks in order."""
    spine = state.spine
    bn_ids = [n.id for n in spine.bottleneck_nodes()]
    if not bn_ids:
        result.warn("BN_CONVERGENCE", "No bottlenecks — skipping")
        return

    paths = spine.all_paths()
    for path in paths:
        end_node = spine.get_node(path[-1])
        # Dead-end paths don't need to hit all bottlenecks
        if end_node and end_node.id.startswith("DE"):
            continue
        # Principal paths must hit bottlenecks in order
        path_bns = [nid for nid in path if nid in set(bn_ids)]
        expected = [bid for bid in bn_ids if bid in set(path)]
        if path_bns != expected:
            result.error("BN_CONVERGENCE",
                f"Path {path[0]}→{path[-1]} bottleneck order {path_bns} != expected {expected}")

    result.note("BN_CONVERGENCE", f"Checked convergence against {len(bn_ids)} bottleneck(s)")


def validate_branch_id_format(spine: Spine, result: ValidationResult):
    """EP##[A-Z] for branches, DE## for dead ends, END_[A-Z] for endings."""
    ep_pattern = re.compile(r'^EP\d{2}[A-Z]?$')
    de_pattern = re.compile(r'^DE\d{2}$')
    end_pattern = re.compile(r'^END_[A-Z]$')

    for node in spine.nodes:
        nid = node.id
        if nid.startswith("DE"):
            if not de_pattern.match(nid):
                result.error("ID_FORMAT",
                    f"Dead end '{nid}' doesn't match DE## pattern (e.g. DE01)")
        elif nid.startswith("END_"):
            if not end_pattern.match(nid):
                result.error("ID_FORMAT",
                    f"Ending '{nid}' doesn't match END_[A-Z] pattern (e.g. END_A)")
        elif nid.startswith("EP"):
            if not ep_pattern.match(nid):
                result.error("ID_FORMAT",
                    f"Node '{nid}' doesn't match EP## or EP##[A-Z] pattern")
        else:
            result.error("ID_FORMAT",
                f"Node '{nid}' has unrecognized ID prefix (expected EP##, DE##, or END_[A-Z])")

    result.note("ID_FORMAT", "Branch ID format check complete")


def validate_structural_requirements(spine: Spine, result: ValidationResult):
    """Structural checks: ≥1 three-way fork, dead ends 15-25%, ≥1 delayed consequence."""
    # Three-way fork: at least one node with 3+ outgoing edges
    out_degree: dict[str, int] = {}
    for e in spine.edges:
        out_degree[e.src] = out_degree.get(e.src, 0) + 1

    three_way = [nid for nid, deg in out_degree.items() if deg >= 3]
    if not three_way:
        result.error("STRUCTURE", "No three-way forks found (need ≥1 node with 3+ out-edges)")
    else:
        result.note("STRUCTURE", f"Three-way forks: {', '.join(three_way)}")

    # Dead end ratio: 15-25% of total nodes
    total_nodes = len(spine.nodes)
    dead_ends = [n for n in spine.nodes if n.id.startswith("DE")]
    de_count = len(dead_ends)
    if total_nodes > 0:
        de_ratio = de_count / total_nodes
        if de_ratio < 0.15:
            result.warn("STRUCTURE",
                f"Dead ends {de_count}/{total_nodes} ({de_ratio:.0%}) below 15% target")
        elif de_ratio > 0.25:
            result.warn("STRUCTURE",
                f"Dead ends {de_count}/{total_nodes} ({de_ratio:.0%}) above 25% target")
        else:
            result.note("STRUCTURE",
                f"Dead ends {de_count}/{total_nodes} ({de_ratio:.0%}) within 15-25% range")

    # Delayed consequence: at least 1 edge whose effect is read ≥2 nodes downstream
    # (heuristic: effect on edge A→B, read on node C where C is not B)
    delayed = False
    effect_keys_by_edge: dict[str, set[str]] = {}
    for e in spine.edges:
        if e.effects:
            effect_keys_by_edge[e.dst] = {eff.key for eff in e.effects}

    for node in spine.nodes:
        if not node.requires:
            continue
        for pred in node.requires:
            # Check if this predicate's key was set on an edge NOT directly incoming
            preds_of_node = set(spine.get_predecessors(node.id))
            for set_node, keys in effect_keys_by_edge.items():
                if pred.key in keys and set_node not in preds_of_node and set_node != node.id:
                    delayed = True
                    break
        if delayed:
            break

    if not delayed:
        result.warn("STRUCTURE",
            "No delayed consequences detected (an effect set in one segment should be read in a later segment)")
    else:
        result.note("STRUCTURE", "At least 1 delayed consequence found")

    # Build adjacency list for unique-target checks
    adj: dict[str, list[str]] = {}
    for e in spine.edges:
        adj.setdefault(e.src, []).append(e.dst)

    # Universal 2-3 out-degree: every non-leaf node must have 2-3 outgoing edges
    # AND every outgoing edge must go to a UNIQUE target (no flavor choices)
    leaf_kinds = {"ending"}
    for node in spine.nodes:
        if node.kind in leaf_kinds or node.id.startswith("DE"):
            continue  # terminals are exempt
        out = out_degree.get(node.id, 0)
        if out == 0:
            continue  # no outgoing = terminal (caught by other validators)
        if out < 2:
            result.error("STRUCTURE",
                f"'{node.id}' has {out} outgoing edge(s) — every non-leaf node must have 2-3 choices")
        if out > 3:
            result.error("STRUCTURE",
                f"'{node.id}' has {out} outgoing edge(s) — max 3 choices allowed")

        # Check unique targets: no two edges from the same node to the same target
        targets = adj.get(node.id, [])
        unique_targets = set(targets)
        if len(targets) != len(unique_targets):
            dup_targets = [t for t in unique_targets if targets.count(t) > 1]
            result.error("STRUCTURE",
                f"'{node.id}' has multiple edges to same target {dup_targets} — "
                f"every choice must lead to a DIFFERENT node (no flavor choices)")


def validate_beat_choice_coherence(spine: Spine, result: ValidationResult):
    """Advisory: flag when a variant node's content duplicates an action already in the source node's beats.

    Structural rule: spine node beats describe what ALREADY HAPPENS before the choice point.
    If a beat includes an action, that action is a given — it cannot also be offered as a choice.
    Variant branches must offer actions NOT already in the parent node's beats.

    Uses sliding-window substring matching: extracts all 3-4 char CJK substrings
    from beats and checks if any appear in the target node's text.
    """
    # Collect all character names from bible/node data to filter them out
    # (character names appearing in both beats and targets are not action overlaps)
    all_text = " ".join(n.title + " " + n.summary for n in spine.nodes if n.title)
    # Common 3-4 char names: appear in many nodes
    name_candidates: set[str] = set()
    cjk_run_re = re.compile(r'[\u4e00-\u9fff]+')
    for node in spine.nodes:
        # Characters mentioned across many nodes are likely names, not actions
        pass

    variant_re = re.compile(r'^EP\d+[A-Z]$')

    def extract_cjk_ngrams(text: str, min_n: int = 4, max_n: int = 6) -> set[str]:
        """Extract CJK character n-grams from text (min 4 chars to skip short names)."""
        cjk_runs = cjk_run_re.findall(text)
        ngrams: set[str] = set()
        for run in cjk_runs:
            for n in range(min_n, min(max_n + 1, len(run) + 1)):
                for i in range(len(run) - n + 1):
                    ngrams.add(run[i:i + n])
        return ngrams

    for node in spine.nodes:
        if not node.beats:
            continue
        beats_text = "".join(node.beats)
        beat_ngrams = extract_cjk_ngrams(beats_text)
        if not beat_ngrams:
            continue

        for edge in spine.edges:
            if edge.src != node.id:
                continue
            target = spine.get_node(edge.dst)
            if not target or target.id.startswith("DE"):
                continue
            # Only check variant targets (EP##A), not spine continuation (EP##)
            # Spine continuation is expected to share narrative context
            if not variant_re.match(target.id):
                continue

            target_text = " ".join(filter(None, [edge.label, target.title, target.summary]))
            target_ngrams = extract_cjk_ngrams(target_text)

            overlaps = beat_ngrams & target_ngrams
            if overlaps:
                longest = sorted(overlaps, key=len, reverse=True)[:5]
                result.advise("BEAT_CHOICE_COHERENCE",
                    f"'{node.id}' beats share action phrases {longest} "
                    f"with variant '{target.id}' ('{edge.label}'/'{target.title}'). "
                    f"If the beat describes a GIVEN action, it should not also be a CHOICE.")

    result.note("BEAT_CHOICE_COHERENCE", "Beat-choice coherence check complete")


def validate_variant_content_similarity(spine: Spine, result: ValidationResult):
    """Advisory: flag variant pairs sharing a base episode with >30% CJK n-gram Jaccard overlap.

    Groups variant nodes by base episode (EP01A, EP01B → group "01"), computes
    pairwise similarity, and flags pairs that are too similar.
    """
    cjk_run_re = re.compile(r'[\u4e00-\u9fff]+')
    variant_re = re.compile(r'^EP(\d+)([A-Z])$')

    def extract_cjk_ngrams(text: str, min_n: int = 3, max_n: int = 5) -> set[str]:
        ngrams: set[str] = set()
        for run in cjk_run_re.findall(text):
            for n in range(min_n, min(max_n + 1, len(run) + 1)):
                for i in range(len(run) - n + 1):
                    ngrams.add(run[i:i + n])
        return ngrams

    # Group variant nodes by base episode number
    groups: dict[str, list[Node]] = defaultdict(list)
    for node in spine.nodes:
        m = variant_re.match(node.id)
        if m:
            groups[m.group(1)].append(node)

    flagged = 0
    for ep_num, variants in groups.items():
        if len(variants) < 2:
            continue
        # Compute pairwise Jaccard similarity
        ngram_cache: dict[str, set[str]] = {}
        for v in variants:
            text = " ".join(filter(None, [v.title, v.summary, " ".join(v.beats or [])]))
            ngram_cache[v.id] = extract_cjk_ngrams(text)

        for i in range(len(variants)):
            for j in range(i + 1, len(variants)):
                a_id, b_id = variants[i].id, variants[j].id
                a_ng, b_ng = ngram_cache[a_id], ngram_cache[b_id]
                if not a_ng or not b_ng:
                    continue
                intersection = len(a_ng & b_ng)
                union = len(a_ng | b_ng)
                jaccard = intersection / union
                if jaccard > 0.30:
                    flagged += 1
                    result.advise("VARIANT_SIMILARITY",
                        f"'{a_id}' and '{b_id}' have {jaccard:.0%} CJK n-gram overlap "
                        f"(Jaccard). Variants of EP{ep_num} should diverge in content.")

    result.note("VARIANT_SIMILARITY",
        f"Checked {sum(len(v) for v in groups.values())} variant(s) in "
        f"{len(groups)} group(s), {flagged} pair(s) flagged")


def validate_prologue(spine: Spine, result: ValidationResult):
    """Advisory: prologue nodes should be convergent with no dead ends within 1 hop."""
    prologues = [n for n in spine.nodes if n.kind == "prologue"]
    if len(prologues) > 1:
        result.advise("PROLOGUE",
            f"Found {len(prologues)} prologue nodes — expected at most 1")

    for p in prologues:
        # Check no dead ends within 1 hop of prologue
        successors = spine.get_successors(p.id)
        for succ_id in successors:
            succ = spine.get_node(succ_id)
            if succ and succ.id.startswith("DE"):
                result.advise("PROLOGUE",
                    f"Prologue '{p.id}' has direct dead end '{succ_id}' — "
                    f"prologue choices should all be safe (tutorial-level)")

        # Check convergent: all successors reach the same next spine node within 0-1 hops
        # (i.e. all paths from prologue variants converge quickly)
        variant_dests: set[str] = set()
        for succ_id in successors:
            succ = spine.get_node(succ_id)
            if succ and re.match(r'^EP\d+[A-Z]$', succ_id):
                # Variant — check its successors converge
                grand_succs = spine.get_successors(succ_id)
                for gs in grand_succs:
                    gs_node = spine.get_node(gs)
                    if gs_node and not gs.startswith("DE"):
                        variant_dests.add(gs)
            elif succ and not succ_id.startswith("DE"):
                variant_dests.add(succ_id)

        if len(variant_dests) > 1:
            # Check if they all converge to the same spine node
            spine_dests = {d for d in variant_dests if re.match(r'^EP\d+$', d)}
            if len(spine_dests) > 1:
                result.advise("PROLOGUE",
                    f"Prologue '{p.id}' branches don't converge to a single spine node: "
                    f"{sorted(spine_dests)}")

    if prologues:
        result.note("PROLOGUE", f"{len(prologues)} prologue node(s) checked")


def validate_dag_variety(spine: Spine, result: ValidationResult):
    """Advisory: check for pattern variety in the DAG topology."""
    out_degree: dict[str, int] = {}
    for e in spine.edges:
        out_degree[e.src] = out_degree.get(e.src, 0) + 1

    # Pattern detection
    patterns_found: set[str] = set()

    # 1. Standard Diamond: node with 2 out-edges where both targets reach the same next node
    adj: dict[str, list[str]] = {}
    for e in spine.edges:
        adj.setdefault(e.src, []).append(e.dst)

    diamond_count = 0
    for nid, succs in adj.items():
        if len(succs) < 2:
            continue
        # Only count diamonds from spine/bottleneck/prologue nodes, not variants
        if re.match(r'^EP\d+[A-Z]', nid):
            continue
        # 3+ successors = three-way fork, not standard diamond
        if len(succs) >= 3:
            continue
        # Check if variant successors rejoin the same spine node
        for s in succs:
            if re.match(r'^EP\d+[A-Z]$', s):
                s_succs = adj.get(s, [])
                spine_rejoin = [ss for ss in s_succs if re.match(r'^EP\d+$', ss)]
                if spine_rejoin:
                    diamond_count += 1
                    patterns_found.add("diamond")
                    break

    # 2. Sustained parallel: variant with edge to another variant (multi-hop alt track)
    has_sustained = False
    for e in spine.edges:
        if re.match(r'^EP\d+[A-Z]$', e.src) and re.match(r'^EP\d+[A-Z]$', e.dst):
            has_sustained = True
            patterns_found.add("sustained_parallel")
            break

    # 3. Multi-hop doom: dead end reachable via ≥2 hops from nearest spine node
    has_multi_hop_doom = False
    for node in spine.nodes:
        if not node.id.startswith("DE"):
            continue
        preds = spine.get_predecessors(node.id)
        for pred_id in preds:
            if re.match(r'^EP\d+[A-Z]$', pred_id):
                # Check if this variant's parent is also a variant (2+ hops from spine)
                pred_preds = spine.get_predecessors(pred_id)
                for pp in pred_preds:
                    if re.match(r'^EP\d+[A-Z]$', pp):
                        has_multi_hop_doom = True
                        patterns_found.add("multi_hop_doom")
                        break
            if has_multi_hop_doom:
                break
        if has_multi_hop_doom:
            break

    # 4. Three-way fork
    for nid, deg in out_degree.items():
        if deg >= 3:
            patterns_found.add("three_way_fork")
            break

    # 5. Multiple endings
    endings = [n for n in spine.nodes if n.kind == "ending"]
    if len(endings) >= 2:
        patterns_found.add("multiple_endings")

    # Advisory checks
    if diamond_count > 3:
        result.advise("DAG_VARIETY",
            f"Standard diamond pattern used {diamond_count} times (max 3 recommended)")

    if not has_sustained:
        result.advise("DAG_VARIETY",
            "No sustained parallel tracks found (≥1 recommended: variant → variant path)")

    if not has_multi_hop_doom:
        result.advise("DAG_VARIETY",
            "No multi-hop doom paths found (≥1 recommended: ≥2 hops from spine to dead end)")

    if len(patterns_found) < 3:
        result.advise("DAG_VARIETY",
            f"Only {len(patterns_found)} distinct pattern(s) found: {sorted(patterns_found)}. "
            f"Recommend ≥3 for varied topology.")

    result.note("DAG_VARIETY",
        f"Patterns found: {sorted(patterns_found)}, diamonds: {diamond_count}")


def validate_context_fields(spine: Spine, result: ValidationResult):
    """Check entry/exit context fields are present and transitions are plausible."""
    node_map = {n.id: n for n in spine.nodes}

    for node in spine.nodes:
        if node.id.startswith("DE"):
            continue
        if not node.entry_context:
            result.warn("CONTEXT", f"{node.id}: missing entry_context")
        if not node.exit_context and node.kind != "ending":
            result.warn("CONTEXT", f"{node.id}: missing exit_context")

    # Check edge resolution bridges
    for edge in spine.edges:
        src = node_map.get(edge.src)
        dst = node_map.get(edge.dst)
        if not src or not dst:
            continue
        if dst.id.startswith("DE"):
            continue
        if not edge.resolution:
            result.warn("CONTEXT",
                f"Edge {edge.src}→{edge.dst}: no resolution beats to bridge scenes")

    result.note("CONTEXT", "Context field check complete")


def validate_choice_question(spine: Spine, result: ValidationResult):
    """Every non-terminal, non-dead-end node with outgoing edges MUST have choice_question."""
    has_outgoing = {e.src for e in spine.edges}
    missing = []
    for node in spine.nodes:
        if node.kind == "ending" or node.id.startswith("DE"):
            continue
        if node.id not in has_outgoing:
            continue  # leaf node without outgoing edges
        if not node.choice_question:
            missing.append(node.id)

    if missing:
        for nid in missing:
            result.error("CHOICE_QUESTION",
                f"'{nid}' has outgoing edges but no choice_question — "
                f"every non-leaf node needs a protagonist-dilemma question (≤30 chars Chinese)")
    result.note("CHOICE_QUESTION",
        f"{len(missing)} node(s) missing choice_question" if missing
        else "All branching nodes have choice_question")


# ── Report generation ───────────────────────────────────────────────

def generate_report(result: ValidationResult, project_dir: str) -> str:
    lines = ["# Spine Validation Report\n"]

    lines.append("## Summary\n")
    lines.append(f"- Errors (blocking): **{len(result.errors)}**")
    lines.append(f"- Warnings: **{len(result.warnings)}**")
    lines.append(f"- Advisory (non-blocking): **{len(result.advisory)}**")
    lines.append(f"- Overall: **{'PASS' if result.ok else 'FAIL'}**\n")

    if result.errors:
        lines.append("## Errors (BLOCKING — must fix)\n")
        for cat, msg in result.errors:
            lines.append(f"- **[{cat}]** {msg}")
        lines.append("")

    if result.warnings:
        lines.append("## Warnings (should fix)\n")
        for cat, msg in result.warnings:
            lines.append(f"- **[{cat}]** {msg}")
        lines.append("")

    if result.advisory:
        lines.append("## Advisory (NON-BLOCKING — human review)\n")
        for cat, msg in result.advisory:
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


# ── Main: run all validators ────────────────────────────────────────

def validate_spine(state: SpineState) -> ValidationResult:
    """Run all deterministic validators.  Returns result.

    result.ok checks errors AND warnings (both blocking).
    result.advisory is informational only (not blocking).

    Step-2 validators are only run when state.step >= "step-2".
    """
    result = ValidationResult()
    spine = state.spine
    registry = state.registry

    # Deterministic gates (blocking) — always run
    validate_dag_integrity(spine, result)
    validate_reachability(spine, result)
    validate_registry_consistency(spine, registry, result)
    validate_state_discipline(registry, result)
    validate_bottleneck_invariants(spine, registry, result)
    validate_affect_guard(spine, registry, result)
    validate_bottleneck_alignment(spine, result)
    validate_duration_budget(spine, result)
    validate_edge_labels(spine, result)

    # Step-2 validators — only when DAG has been expanded
    if state.step in ("step-2", "step-3"):
        validate_path_budget(state, result)
        validate_total_budget(state, result)
        validate_state_coherence(state, result)
        validate_bottleneck_convergence(state, result)
        validate_branch_id_format(spine, result)
        validate_structural_requirements(spine, result)
        validate_choice_question(spine, result)
        validate_context_fields(spine, result)
        validate_beat_choice_coherence(spine, result)
        validate_variant_content_similarity(spine, result)
        validate_prologue(spine, result)
        validate_dag_variety(spine, result)

    return result


def main():
    parser = argparse.ArgumentParser(description="Validate spine from state.json")
    parser.add_argument("project_dir", help="Project directory containing state.json")
    args = parser.parse_args()

    state_path = os.path.join(args.project_dir, "state.json")
    if not os.path.exists(state_path):
        print(f"ERROR: {state_path} not found")
        sys.exit(1)

    state = load_state(args.project_dir)
    result = validate_spine(state)
    report_path = generate_report(result, args.project_dir)

    print(f"\n{'=' * 60}")
    print(f"  SPINE VALIDATION {'PASSED' if result.ok else 'FAILED'}")
    print(f"  Errors: {len(result.errors)} | Warnings: {len(result.warnings)} | Advisory: {len(result.advisory)}")
    print(f"{'=' * 60}\n")

    if result.errors:
        print("ERRORS (blocking):")
        for cat, msg in result.errors:
            print(f"  ✗ [{cat}] {msg}")
        print()

    if result.warnings:
        print("WARNINGS:")
        for cat, msg in result.warnings:
            print(f"  ⚠ [{cat}] {msg}")
        print()

    if result.advisory:
        print("ADVISORY (non-blocking, human review):")
        for cat, msg in result.advisory:
            print(f"  ℹ [{cat}] {msg}")
        print()

    print(f"Full report: {report_path}")
    sys.exit(0 if result.ok else 1)


if __name__ == "__main__":
    main()
