"""Deterministic DFS expansion helper for step-2.

No LLM calls — pure Python logic for state simulation, invariant checking,
expansion application/undo, and prompt context generation.

Used by the step-2 SKILL.md DFS algorithm:
  1. Traverse the spine DFS from entry_node
  2. At each node, LLM proposes expansion (forks/dead-ends)
  3. This module validates the expansion deterministically
  4. Apply expansion, recurse into children
  5. At bottlenecks, check invariants — backtrack on failure
"""
from __future__ import annotations

import copy
import re
from dataclasses import asdict
from typing import Any

try:
    from .data_model import (
        Bible, Edge, Effect, Node, Predicate, Registry, Spine, SpineState, state_at,
    )
except ImportError:
    from data_model import (  # type: ignore[no-redef]
        Bible, Edge, Effect, Node, Predicate, Registry, Spine, SpineState, state_at,
    )


# ── State simulation ─────────────────────────────────────────────────

def get_initial_state(registry: Registry) -> dict[str, Any]:
    """Return the default state dict from registry defaults."""
    return {v.key: v.default for v in registry.vars}


def apply_effects(
    state: dict[str, Any],
    effects: list[Effect],
    registry: Registry,
) -> dict[str, Any]:
    """Apply a list of effects to a state, returning a NEW state dict (pure, no mutation)."""
    new_state = dict(state)
    for effect in effects:
        var = registry.get_var(effect.key)
        if not var:
            continue
        if effect.op == "set":
            new_state[effect.key] = effect.value
        elif effect.op == "add" and var.type == "bounded_int":
            val = new_state.get(effect.key, var.default)
            new_val = val + effect.value
            if var.min_val is not None:
                new_val = max(var.min_val, new_val)
            if var.max_val is not None:
                new_val = min(var.max_val, new_val)
            new_state[effect.key] = new_val
    return new_state


# ── Invariant / requires checking ────────────────────────────────────

def check_invariants(node: Node, state: dict[str, Any]) -> list[str]:
    """Check bottleneck invariants against state. Returns list of violations (empty = OK)."""
    violations = []
    for inv in node.invariants:
        if not inv.evaluate(state):
            violations.append(
                f"Invariant failed at {node.id}: "
                f"{inv.key} {inv.cmp} {inv.value} "
                f"(actual: {state.get(inv.key, '<missing>')})"
            )
    return violations


def check_requires(node: Node, state: dict[str, Any]) -> list[str]:
    """Check entry requirements against state. Returns list of unsatisfied predicates."""
    unsatisfied = []
    for req in node.requires:
        if not req.evaluate(state):
            unsatisfied.append(
                f"Requires failed at {node.id}: "
                f"{req.key} {req.cmp} {req.value} "
                f"(actual: {state.get(req.key, '<missing>')})"
            )
    return unsatisfied


# ── Spine navigation ─────────────────────────────────────────────────

def find_next_bottleneck(spine: Spine, node_id: str) -> Node | None:
    """Find the next bottleneck reachable from node_id via BFS. Returns None if none found."""
    from collections import deque

    visited: set[str] = set()
    queue = deque(spine.get_successors(node_id))

    while queue:
        nid = queue.popleft()
        if nid in visited:
            continue
        visited.add(nid)
        node = spine.get_node(nid)
        if node and node.kind == "bottleneck":
            return node
        for succ in spine.get_successors(nid):
            if succ not in visited:
                queue.append(succ)
    return None


def find_next_cornerstone(spine: Spine, node_id: str) -> Node | None:
    """Find the next cornerstone (bottleneck or ending) reachable from node_id via BFS.

    Cornerstones are the structural anchors created by step-1.
    Step-2 fills segments between them.
    """
    from collections import deque

    visited: set[str] = set()
    queue = deque(spine.get_successors(node_id))

    while queue:
        nid = queue.popleft()
        if nid in visited:
            continue
        visited.add(nid)
        node = spine.get_node(nid)
        if node and node.is_cornerstone:
            return node
        for succ in spine.get_successors(nid):
            if succ not in visited:
                queue.append(succ)
    return None


def budget_remaining(
    spine: Spine,
    path: list[str],
    total_budget: float,
) -> float:
    """Return remaining budget = total_budget - sum(duration of all nodes in spine) + sum(duration of nodes NOT on path)."""
    # Simpler: remaining = total_budget - sum of ALL authored node durations
    total_authored = sum(n.duration_min for n in spine.nodes)
    return total_budget - total_authored


def path_budget_remaining(
    spine: Spine,
    path: list[str],
    playthrough_target: float,
) -> float:
    """Return remaining playthrough budget for the current path."""
    path_total = sum(
        (spine.get_node(nid).duration_min if spine.get_node(nid) else 0.0)
        for nid in path
    )
    return playthrough_target * 1.2 - path_total


# ── Expansion log (apply / undo) ─────────────────────────────────────

class ExpansionLog:
    """Tracks expansions for undo support.

    Each expansion is keyed by the source node_id and records what
    nodes and edges were added.
    """

    def __init__(self) -> None:
        self._log: dict[str, list[dict[str, Any]]] = {}

    def record(self, source_node_id: str, new_node_ids: list[str], new_edge_ids: list[str]) -> None:
        """Record an expansion from source_node_id."""
        self._log.setdefault(source_node_id, []).append({
            "new_node_ids": new_node_ids,
            "new_edge_ids": new_edge_ids,
        })

    def last_expansion(self, source_node_id: str) -> dict[str, Any] | None:
        """Get the most recent expansion for a source node."""
        entries = self._log.get(source_node_id, [])
        return entries[-1] if entries else None

    def pop_last(self, source_node_id: str) -> dict[str, Any] | None:
        """Pop and return the most recent expansion for undo."""
        entries = self._log.get(source_node_id, [])
        return entries.pop() if entries else None


def apply_expansion(
    spine: Spine,
    source_node_id: str,
    new_nodes: list[Node],
    new_edges: list[Edge],
    log: ExpansionLog,
) -> None:
    """Add new nodes and edges to the spine. Records in the expansion log for undo."""
    # Remove existing outgoing edges from source (replace with new ones)
    old_edge_ids = [e.id for e in spine.edges if e.src == source_node_id]
    spine.edges = [e for e in spine.edges if e.src != source_node_id]

    # Add new nodes and edges
    for node in new_nodes:
        if not spine.get_node(node.id):
            spine.nodes.append(node)
    for edge in new_edges:
        spine.edges.append(edge)

    # Record for undo
    log.record(
        source_node_id,
        new_node_ids=[n.id for n in new_nodes],
        new_edge_ids=[e.id for e in new_edges],
    )


def undo_expansion(
    spine: Spine,
    source_node_id: str,
    log: ExpansionLog,
) -> bool:
    """Remove the last expansion from source_node_id. Returns True if undo was performed."""
    entry = log.pop_last(source_node_id)
    if not entry:
        return False

    # Remove added edges
    edge_ids_to_remove = set(entry["new_edge_ids"])
    spine.edges = [e for e in spine.edges if e.id not in edge_ids_to_remove]

    # Remove added nodes (but only if they were actually added by this expansion)
    node_ids_to_remove = set(entry["new_node_ids"])
    spine.nodes = [n for n in spine.nodes if n.id not in node_ids_to_remove]

    return True


# ── Chapter index lookup ──────────────────────────────────────────────

def lookup_chapter_excerpts(
    chapter_index: list[dict[str, Any]],
    chapter_range: str,
) -> list[str]:
    """Parse '第5-8章' or '第5章' → matching excerpts from chapter index.

    Returns a flat list of highlight excerpts for the matching chapters.
    """
    if not chapter_range or not chapter_index:
        return []

    # Parse chapter range: "第5-8章", "第5章", "第5-8回"
    m = re.match(r'第(\d+)[-–—~～]?(\d+)?[章回]', chapter_range)
    if not m:
        return []
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else start

    excerpts: list[str] = []
    for entry in chapter_index:
        ch_num = entry.get("chapter_num", 0)
        if start <= ch_num <= end:
            for exc in entry.get("highlight_excerpts", []):
                if exc and exc not in excerpts:
                    excerpts.append(exc)
    return excerpts


# ── Prompt context generation ─────────────────────────────────────────

def get_expansion_prompt_context(
    node: Node,
    state: dict[str, Any],
    spine: Spine,
    registry: Registry,
    playthrough_target: float,
    total_budget: float,
    path: list[str],
    bible: Bible | None = None,
    chapter_index: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build context dict for the LLM expansion prompt.

    Includes: current node info, accumulated state, next bottleneck goal,
    budget constraints, registry vars, path history, narrative context
    (path content, bible, existing variants).
    """
    next_bn = find_next_bottleneck(spine, node.id)
    next_cs = find_next_cornerstone(spine, node.id)

    # A) Path narrative content — what happened before this node
    path_content = []
    for pid in path:
        if pid == node.id:
            continue
        pnode = spine.get_node(pid)
        if pnode:
            path_content.append({
                "id": pnode.id,
                "title": pnode.title,
                "summary": pnode.summary,
                "beats": pnode.beats,
            })

    # B) Compact bible reference
    bible_compact = None
    if bible:
        bible_compact = {
            "protagonist": {
                "name": bible.protagonist.get("name", ""),
                "role": bible.protagonist.get("role", ""),
                "abilities": bible.protagonist.get("abilities", ""),
                "core_conflict": bible.protagonist.get("core_conflict", ""),
            },
            "characters": [
                {"name": c.get("name", ""), "role": c.get("role", ""), "relationship": c.get("relationship", "")}
                for c in bible.characters
            ],
            "world": bible.world,
            "canon_facts": bible.canon_facts,
        }

    # C) Already-created variants (to avoid duplication)
    existing_variants = []
    for sn in spine.nodes:
        if sn.id == node.id:
            continue
        if re.match(r'^(EP\d+[A-Z]|DE\d+)$', sn.id):
            existing_variants.append({
                "id": sn.id, "title": sn.title, "summary": sn.summary,
            })

    # Compute guaranteed vs varying state at this node
    guaranteed = compute_guaranteed_state(spine, registry, node.id)
    varying = compute_varying_state(spine, registry, node.id)

    # Parent exit contexts for transition chaining
    parent_edges = [e for e in spine.edges if e.dst == node.id]
    parent_contexts = []
    for pe in parent_edges:
        pnode = spine.get_node(pe.src)
        if pnode and pnode.exit_context:
            parent_contexts.append({
                "parent_id": pe.src,
                "exit_context": pnode.exit_context,
                "edge_label": pe.label,
                "edge_resolution": pe.resolution,
            })

    ctx = {
        "node": {
            "id": node.id,
            "kind": node.kind,
            "title": node.title,
            "summary": node.summary,
            "goal": node.goal,
            "beats": node.beats,
            "duration_min": node.duration_min,
            "chapter_range": node.chapter_range,
            "entry_context": node.entry_context,
            "exit_context": node.exit_context,
        },
        "accumulated_state": state,
        "guaranteed_state": guaranteed,
        "varying_state": varying,
        "next_bottleneck": {
            "id": next_bn.id,
            "title": next_bn.title,
            "invariants": [asdict(inv) for inv in next_bn.invariants],
        } if next_bn else None,
        "target_cornerstone": {
            "id": next_cs.id,
            "kind": next_cs.kind,
            "title": next_cs.title,
            "summary": next_cs.summary,
            "invariants": [asdict(inv) for inv in next_cs.invariants],
            "entry_context": next_cs.entry_context,
        } if next_cs else None,
        "budget": {
            "total_remaining": budget_remaining(spine, path, total_budget),
            "path_remaining": path_budget_remaining(spine, path, playthrough_target),
            "playthrough_target": playthrough_target,
            "total_budget": total_budget,
        },
        "registry_vars": [
            {"key": v.key, "type": v.type, "current_value": state.get(v.key, v.default)}
            for v in registry.vars
        ],
        "path_so_far": path,
        "path_content": path_content,
    }
    if bible_compact:
        ctx["bible"] = bible_compact
    if bible and bible.genre:
        ctx["genre"] = bible.genre
    if existing_variants:
        ctx["existing_variants"] = existing_variants
    if parent_contexts:
        ctx["parent_exit_contexts"] = parent_contexts
    # Chapter excerpts from source material
    if chapter_index and node.chapter_range:
        excerpts = lookup_chapter_excerpts(chapter_index, node.chapter_range)
        if excerpts:
            ctx["chapter_excerpts"] = excerpts
    return ctx


# ── Expansion output validation ──────────────────────────────────────

def validate_expansion_output(
    expansion: dict[str, Any],
    source_node_id: str,
    registry: Registry,
    source_node: Node | None = None,
) -> list[str]:
    """Validate the format of an LLM expansion output. Returns list of errors (empty = valid).

    Expected expansion format:
    {
      "parent_beats": ["setup", "escalation", "tension peak"],
      "nodes": [{ "id", "kind", "title", "summary", "goal", "duration_min", "requires", "beats", "choice_question" }],
      "edges": [{ "id", "src", "dst", "label", "effects" }],
      "choice_question": "..."  // for the source node
    }
    """
    errors = []

    # Check top-level keys
    if "nodes" not in expansion:
        errors.append("Missing 'nodes' in expansion output")
    if "edges" not in expansion:
        errors.append("Missing 'edges' in expansion output")

    if errors:
        return errors

    # ── parent_beats validation (step-2 writes beats, not step-1) ──
    # Structural checks only. Tension peak quality is verified by LLM, not regex.
    parent_beats = expansion.get("parent_beats", [])
    if not parent_beats:
        errors.append("Missing or empty 'parent_beats' — step-2 must write beats for the source node")
    elif len(parent_beats) < 2:
        errors.append(f"parent_beats has {len(parent_beats)} items, need ≥2")

    # Tension peak quality is now validated by LLM judge (S2_CHO_01),
    # not by fragile punctuation regex.

    # parent_exit_context: source node must get exit_context if it didn't have one
    parent_exit = expansion.get("parent_exit_context", "")
    if not parent_exit and source_node and not source_node.exit_context:
        errors.append(f"Source {source_node_id}: missing parent_exit_context")

    nodes = expansion.get("nodes", [])
    edges = expansion.get("edges", [])

    if not isinstance(nodes, list):
        errors.append("'nodes' must be a list")
        return errors
    if not isinstance(edges, list):
        errors.append("'edges' must be a list")
        return errors

    # Validate nodes
    node_ids = set()
    for i, n in enumerate(nodes):
        if not isinstance(n, dict):
            errors.append(f"nodes[{i}] must be a dict")
            continue
        nid = n.get("id", "")
        if not nid:
            errors.append(f"nodes[{i}] missing 'id'")
            continue
        if nid in node_ids:
            errors.append(f"Duplicate node id: {nid}")
        node_ids.add(nid)

        kind = n.get("kind", "scene")
        if kind not in ("scene", "bottleneck", "ending", "prologue"):
            errors.append(f"Node {nid}: invalid kind '{kind}'")

        # Branch variant IDs: EP##[A-Z] or DE##
        if not re.match(r"^(EP\d+[A-Z]?|DE\d+)$", nid):
            errors.append(f"Node {nid}: invalid ID format (expected EP##[A-Z] or DE##)")

        dur = n.get("duration_min", 3.0)
        if not isinstance(dur, (int, float)) or dur <= 0:
            errors.append(f"Node {nid}: duration_min must be positive number")

        # Validate requires predicates
        for j, req in enumerate(n.get("requires", [])):
            if not isinstance(req, dict):
                errors.append(f"Node {nid} requires[{j}]: must be a dict")
                continue
            if "key" not in req:
                errors.append(f"Node {nid} requires[{j}]: missing 'key'")
            elif not registry.get_var(req["key"]):
                errors.append(f"Node {nid} requires[{j}]: unknown var '{req['key']}'")

        # entry_context required on non-DE nodes
        entry_ctx = n.get("entry_context", "")
        if not entry_ctx and not nid.startswith("DE"):
            errors.append(f"Node {nid}: missing entry_context (WHERE/WHEN does this scene open?)")

        exit_ctx = n.get("exit_context", "")
        if not exit_ctx and kind != "ending" and not nid.startswith("DE"):
            errors.append(f"Node {nid}: missing exit_context (WHERE/WHEN does this scene end?)")

    # Validate edges
    for i, e in enumerate(edges):
        if not isinstance(e, dict):
            errors.append(f"edges[{i}] must be a dict")
            continue
        eid = e.get("id", "")
        src = e.get("src", "")
        dst = e.get("dst", "")
        if not eid:
            errors.append(f"edges[{i}] missing 'id'")
        if not src:
            errors.append(f"edges[{i}] missing 'src'")
        if not dst:
            errors.append(f"edges[{i}] missing 'dst'")

        # Source must be the expanding node or one of the new nodes
        valid_sources = {source_node_id} | node_ids
        if src and src not in valid_sources:
            errors.append(f"Edge {eid}: src '{src}' is neither source node nor new node")

        label = e.get("label", "")
        if label and len(label) > 8:
            errors.append(f"Edge {eid}: label '{label}' exceeds 8 chars")

        # Validate effects
        for j, eff in enumerate(e.get("effects", [])):
            if not isinstance(eff, dict):
                errors.append(f"Edge {eid} effects[{j}]: must be a dict")
                continue
            eff_key = eff.get("key", "")
            if not eff_key:
                errors.append(f"Edge {eid} effects[{j}]: missing 'key'")
            elif not registry.get_var(eff_key):
                errors.append(f"Edge {eid} effects[{j}]: unknown var '{eff_key}'")
            op = eff.get("op", "set")
            if op not in ("set", "add"):
                errors.append(f"Edge {eid} effects[{j}]: invalid op '{op}'")

    # Check edge count from source node (2-3 outgoing)
    source_edges = [e for e in edges if e.get("src") == source_node_id]
    if len(source_edges) < 2:
        errors.append(f"Source node {source_node_id}: needs at least 2 outgoing edges, got {len(source_edges)}")
    if len(source_edges) > 3:
        errors.append(f"Source node {source_node_id}: at most 3 outgoing edges, got {len(source_edges)}")

    # Check unique targets: every edge from same source must go to a DIFFERENT node
    from collections import Counter
    src_dst_map: dict[str, list[str]] = {}
    for e in edges:
        src = e.get("src", "")
        dst = e.get("dst", "")
        if src and dst:
            src_dst_map.setdefault(src, []).append(dst)
    for src, dsts in src_dst_map.items():
        dup_dsts = [d for d, count in Counter(dsts).items() if count > 1]
        if dup_dsts:
            errors.append(
                f"Node {src}: multiple edges to same target {dup_dsts} — "
                f"every choice MUST lead to a DIFFERENT node (no flavor choices)"
            )

    # Check choice_question on source
    choice_q = expansion.get("choice_question", "")
    if not choice_q:
        errors.append(f"Missing choice_question for source node {source_node_id}")

    # Validate edge resolution
    for e in edges:
        eid = e.get("id", "?")
        resolution = e.get("resolution", [])
        if not resolution:
            errors.append(f"Edge {eid} missing resolution beats — "
                          f"every edge must show what happens after the choice")
        elif len(resolution) > 5:
            errors.append(f"Edge {eid} has {len(resolution)} resolution beats, max 5")

    # Check new node outgoing edges.
    # Three valid states for non-terminal nodes:
    #   0 edges = "leaf-for-now" — DFS will expand this node in a later recursion step
    #   1 edge  = pass-through — no choice, just forwarding → error
    #   2-3 edges = has choices → OK (needs choice_question)
    #   4+ edges = too many → error
    for n in nodes:
        nid = n.get("id", "")
        kind = n.get("kind", "scene")
        if kind == "ending" or nid.startswith("DE"):
            continue  # terminals exempt
        child_edges = [e for e in edges if e.get("src") == nid]
        if len(child_edges) == 0:
            # Leaf-for-now: DFS will expand this node later. OK.
            pass
        elif len(child_edges) == 1:
            errors.append(
                f"Node {nid}: has exactly 1 outgoing edge (pass-through). "
                f"Either add choices (2-3 edges) or leave as leaf (0 edges, DFS expands later)."
            )
        elif len(child_edges) > 3:
            errors.append(f"Node {nid}: max 3 outgoing edges, got {len(child_edges)}")
        # choice_question required only if node has outgoing edges in this expansion
        if len(child_edges) >= 2 and not n.get("choice_question"):
            errors.append(f"Node {nid}: missing choice_question (every node with choices needs one)")

    # Beat-choice coherence: variant content must not duplicate source node's beats
    if source_node and source_node.beats:
        beats_text = "".join(source_node.beats)
        # Extract 4-6 char CJK n-grams (min 4 to skip character names)
        beat_ngrams: set[str] = set()
        for run in re.findall(r'[\u4e00-\u9fff]+', beats_text):
            for n in range(4, min(7, len(run) + 1)):
                for i in range(len(run) - n + 1):
                    beat_ngrams.add(run[i:i + n])

        for nd in nodes:
            nid = nd.get("id", "")
            if nid.startswith("DE"):
                continue
            # Only check variant nodes (EP##A), not spine continuation
            if not re.match(r'^EP\d+[A-Z]$', nid):
                continue
            target_text = " ".join(filter(None, [nd.get("title", ""), nd.get("summary", "")]))
            for e in edges:
                if e.get("dst") == nid:
                    target_text += " " + e.get("label", "")
            target_ngrams: set[str] = set()
            for run in re.findall(r'[\u4e00-\u9fff]+', target_text):
                for ngn in range(4, min(7, len(run) + 1)):
                    for i in range(len(run) - ngn + 1):
                        target_ngrams.add(run[i:i + ngn])

            overlaps = beat_ngrams & target_ngrams
            if overlaps:
                longest = sorted(overlaps, key=len, reverse=True)[:5]
                errors.append(
                    f"Node {nid} content overlaps with {source_node_id} beats: "
                    f"{longest}. Beats describe GIVEN actions — choices must offer NEW actions."
                )

    return errors


# ── Conversion helpers ───────────────────────────────────────────────

def dicts_to_nodes(node_dicts: list[dict[str, Any]]) -> list[Node]:
    """Convert a list of node dicts (from LLM output) to Node objects."""
    nodes = []
    for nd in node_dicts:
        requires = [Predicate(**p) for p in nd.pop("requires", [])]
        invariants = [Predicate(**p) for p in nd.pop("invariants", [])]
        nodes.append(Node(**nd, requires=requires, invariants=invariants))
    return nodes


def dicts_to_edges(edge_dicts: list[dict[str, Any]]) -> list[Edge]:
    """Convert a list of edge dicts (from LLM output) to Edge objects."""
    edges = []
    for ed in edge_dicts:
        effects = [Effect(**e) for e in ed.pop("effects", [])]
        resolution = ed.pop("resolution", [])
        edges.append(Edge(**ed, effects=effects, resolution=resolution))
    return edges


# ── Computed states (for DB import) ──────────────────────────────────

def compute_guaranteed_state(
    spine: Spine,
    registry: Registry,
    node_id: str,
) -> dict[str, Any]:
    """Compute state that is GUARANTEED at a node (same value on ALL paths).

    Returns {var_key: guaranteed_value} for vars with single possible value.
    Vars with multiple possible values are excluded.
    """
    possible = compute_possible_states(spine, registry, node_id)
    return {
        key: vals[0] for key, vals in possible.items()
        if len(vals) == 1
    }


def compute_varying_state(
    spine: Spine,
    registry: Registry,
    node_id: str,
) -> dict[str, list[Any]]:
    """Compute state that VARIES at a node (different values on different paths).

    Returns {var_key: [possible_val_1, ...]} for vars with 2+ possible values.
    Scripts MUST NOT reference items/events gated by varying state.
    """
    possible = compute_possible_states(spine, registry, node_id)
    return {
        key: vals for key, vals in possible.items()
        if len(vals) > 1
    }


def compute_possible_states(
    spine: Spine,
    registry: Registry,
    node_id: str,
) -> dict[str, list[Any]]:
    """Compute all possible state values at a node across all paths from entry.

    Returns { var_key: [possible_val_1, possible_val_2, ...] } for each
    registry variable.
    """
    paths = spine.all_paths(end=node_id)
    if not paths:
        # Node might be on a path but not an ending — find paths THROUGH it
        all_paths = spine.all_paths()
        paths = [p[:p.index(node_id) + 1] for p in all_paths if node_id in p]

    if not paths:
        # Unreachable node — return defaults
        return {v.key: [v.default] for v in registry.vars}

    # Collect all possible states at this node
    possible: dict[str, set] = {v.key: set() for v in registry.vars}
    for path in paths:
        s = state_at(spine, registry, path)
        for key, val in s.items():
            if key in possible:
                # Convert to hashable for set storage
                possible[key].add(_hashable(val))

    return {
        key: sorted(_unhashable(v) for v in vals)
        for key, vals in possible.items()
    }


def _hashable(val: Any) -> Any:
    """Make a value hashable for set storage."""
    if isinstance(val, list):
        return tuple(val)
    return val


def _unhashable(val: Any) -> Any:
    """Reverse _hashable."""
    if isinstance(val, tuple):
        return list(val)
    return val
