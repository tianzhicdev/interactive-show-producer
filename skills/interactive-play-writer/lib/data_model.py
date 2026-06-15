#!/usr/bin/env python3
"""Shared data model for the interactive-play-writer pipeline.

Three-way split enforced in the type system:

  STATE  — boolean or enum vars in the Registry.  The only thing the
           deterministic validator reads/writes.  Initial values are
           assignments (gun_taken = false); bottleneck invariants are
           predicates checked on every incoming path (father_alive == false).

  GOAL   — free text on each Node.  Generation context for step-2 fork
           proposals ("given this state and this goal, what different
           decisions could the character make?").  Never validated
           deterministically.

  AFFECT — feelings, mood, scenery, interior detail.  Lives in title,
           summary, beats — free text outside the registry.  Validated
           by humans / semantic LLM only.  Must NEVER be quantized into
           state (grief >= 8 is illegal).

Types:
  - Registry (state variables: boolean | enum only)
  - Spine (linear DAG with bottlenecks)
  - Bible (story canon)
  - SpineState (serializable project state)

All types are plain dataclasses with JSON round-trip support.
"""
from __future__ import annotations

import json
import os
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


# ── Registry types ──────────────────────────────────────────────────

@dataclass
class RegistryVar:
    """A declared state variable.

    Type discipline — enforced in the type system, not by convention:
      - boolean: the default.  Binary fact (gun_taken, father_alive).
      - enum: mutually exclusive named values
              (e.g. protagonist_status ∈ {disguised, revealed, dead}).
      - bounded_int: RARE exception.  Only when a threshold is genuinely
              re-checked in multiple places and no boolean captures it.
              Flagged for human review automatically — prefer boolean.

    Never free-form strings or unbounded numbers.
    Feelings / mood / affect are NOT state — they live in free-text
    fields (goal, summary, beats) and are never registry vars.
    """
    key: str
    type: Literal["boolean", "enum", "bounded_int"] = "boolean"
    default: Any = False
    # enum-specific
    values: list[str] | None = None
    # bounded_int-specific (rare — flagged for human review)
    min_val: int | None = None
    max_val: int | None = None
    description: str = ""

    def validate(self) -> list[str]:
        """Return list of error strings (empty = valid)."""
        errors = []
        if self.type == "enum":
            if not self.values or len(self.values) < 2:
                errors.append(f"Enum var '{self.key}' must have ≥2 values")
            if self.default not in (self.values or []):
                errors.append(f"Enum var '{self.key}' default '{self.default}' not in values {self.values}")
        elif self.type == "bounded_int":
            if self.min_val is None or self.max_val is None:
                errors.append(f"Bounded int '{self.key}' must have min_val and max_val")
            elif self.min_val >= self.max_val:
                errors.append(f"Bounded int '{self.key}' min_val >= max_val")
            if not isinstance(self.default, int):
                errors.append(f"Bounded int '{self.key}' default must be int, got {type(self.default).__name__}")
            elif self.min_val is not None and self.max_val is not None:
                if not (self.min_val <= self.default <= self.max_val):
                    errors.append(f"Bounded int '{self.key}' default {self.default} out of range [{self.min_val}, {self.max_val}]")
        elif self.type == "boolean":
            if not isinstance(self.default, bool):
                errors.append(f"Boolean var '{self.key}' default must be bool, got {type(self.default).__name__}")
        else:
            errors.append(f"Unknown type '{self.type}' for var '{self.key}'")
        return errors

    def review_flags(self) -> list[str]:
        """Return advisory flags for human review (not errors)."""
        flags = []
        if self.type == "bounded_int":
            flags.append(
                f"HUMAN REVIEW: '{self.key}' uses bounded_int — "
                f"can this be replaced with a boolean decided at a bottleneck?"
            )
        return flags


@dataclass
class Registry:
    """Collection of declared state variables.  Single source of truth.

    Initial state = the default value on each var (value assignment).
    Bottleneck invariants = predicates checked on incoming paths
    (a separate concept — see Node.invariants).
    """
    vars: list[RegistryVar] = field(default_factory=list)

    def get_var(self, key: str) -> RegistryVar | None:
        for v in self.vars:
            if v.key == key:
                return v
        return None

    def keys(self) -> set[str]:
        return {v.key for v in self.vars}

    def validate(self) -> list[str]:
        errors = []
        seen = set()
        for v in self.vars:
            if v.key in seen:
                errors.append(f"Duplicate registry var '{v.key}'")
            seen.add(v.key)
            errors.extend(v.validate())
        return errors

    def review_flags(self) -> list[str]:
        """Collect all human-review flags from vars."""
        flags = []
        for v in self.vars:
            flags.extend(v.review_flags())
        return flags


# ── Effect & Predicate ──────────────────────────────────────────────

@dataclass
class Effect:
    """State mutation on an edge: { key, op, value }.

    Only touches registry state (boolean/enum/bounded_int).
    Never mutates free-text fields (goal, affect, summary).
    """
    key: str
    op: Literal["set", "add"] = "set"
    value: Any = True

    def validate_against(self, registry: Registry) -> list[str]:
        errors = []
        var = registry.get_var(self.key)
        if not var:
            errors.append(f"Effect references undeclared var '{self.key}'")
            return errors
        if var.type == "boolean":
            if self.op != "set":
                errors.append(f"Boolean var '{self.key}' only supports op='set', got '{self.op}'")
            if not isinstance(self.value, bool):
                errors.append(f"Boolean var '{self.key}' effect value must be bool, got {type(self.value).__name__}")
        elif var.type == "enum":
            if self.op != "set":
                errors.append(f"Enum var '{self.key}' only supports op='set', got '{self.op}'")
            if self.value not in (var.values or []):
                errors.append(f"Enum var '{self.key}' effect value '{self.value}' not in {var.values}")
        elif var.type == "bounded_int":
            if self.op not in ("set", "add"):
                errors.append(f"Bounded int '{self.key}' supports op='set'|'add', got '{self.op}'")
            if not isinstance(self.value, int):
                errors.append(f"Bounded int '{self.key}' effect value must be int, got {type(self.value).__name__}")
        return errors


@dataclass
class Predicate:
    """Condition on state: { key, cmp, value }.

    Used for:
      - Node.requires: entry gate (must hold to enter this episode)
      - Node.invariants: bottleneck canon gate (must hold on every
        incoming path — author's non-negotiable facts as predicates
        over boolean/enum state)

    A predicate CHECKS state; it does not hold or assign state.
    """
    key: str
    cmp: Literal["eq", "ne", "gt", "gte", "lt", "lte"] = "eq"
    value: Any = True

    def validate_against(self, registry: Registry) -> list[str]:
        errors = []
        var = registry.get_var(self.key)
        if not var:
            errors.append(f"Predicate references undeclared var '{self.key}'")
            return errors
        if var.type == "boolean":
            if self.cmp not in ("eq", "ne"):
                errors.append(f"Boolean var '{self.key}' only supports cmp='eq'|'ne', got '{self.cmp}'")
            if not isinstance(self.value, bool):
                errors.append(f"Boolean predicate on '{self.key}' value must be bool")
        elif var.type == "enum":
            if self.cmp not in ("eq", "ne"):
                errors.append(f"Enum var '{self.key}' only supports cmp='eq'|'ne', got '{self.cmp}'")
            if self.value not in (var.values or []):
                errors.append(f"Enum predicate on '{self.key}' value '{self.value}' not in {var.values}")
        elif var.type == "bounded_int":
            if not isinstance(self.value, int):
                errors.append(f"Bounded int predicate on '{self.key}' value must be int")
        return errors

    def validate_as_invariant(self, registry: Registry) -> list[str]:
        """Extra checks for bottleneck invariants specifically.

        Invariants encode canon — author's non-negotiable facts.
        They must be predicates over boolean/enum state.
        Thresholds over bounded_int (grief >= 8) are illegal as
        invariants; use a qualifying boolean instead (e.g. town_trusts_you).
        """
        errors = self.validate_against(registry)
        var = registry.get_var(self.key)
        if var and var.type == "bounded_int":
            errors.append(
                f"Invariant on '{self.key}' uses bounded_int threshold — "
                f"invariants must be boolean/enum canon facts, not meter checks. "
                f"Replace with a qualifying boolean decided at this bottleneck."
            )
        return errors

    def evaluate(self, state: dict[str, Any]) -> bool:
        actual = state.get(self.key)
        if actual is None:
            return False
        ops = {
            "eq": lambda a, b: a == b,
            "ne": lambda a, b: a != b,
            "gt": lambda a, b: a > b,
            "gte": lambda a, b: a >= b,
            "lt": lambda a, b: a < b,
            "lte": lambda a, b: a <= b,
        }
        return ops[self.cmp](actual, self.value)


# ── Node & Edge ─────────────────────────────────────────────────────

@dataclass
class Node:
    """A node in the spine/DAG.  ONE node = ONE episode = ~3 minutes.

    id: EP01, EP02, … — the canonical episode identifier.

    kind:
      - prologue: opening episode — world setup, protagonist intro,
        tutorial-level choices.  Convergent (all paths reach next spine
        node within 0-1 hops), NO dead ends.  Duration ~5 min.
      - scene: regular episode
      - bottleneck: convergence point — gates incoming state, does NOT
        hold its own state.  invariants are predicates checked on every
        incoming path (canon facts the author declares non-negotiable).
      - ending: terminal episode (good/bad/hidden ending)

    Three-way split:
      STATE  → requires (entry gate), invariants (canon gate).
               Only references registry vars (boolean/enum).
      GOAL   → goal field.  Free text.  Generation context for step-2
               fork proposals.  "Given this state + this goal, what
               different decisions could the character make?"
               Never checked by deterministic validator.
      AFFECT → title, summary, beats.  Free text.  Emotion, mood,
               scenery, interior detail.  Semantic/human validation only.
    """
    id: str  # EP01, EP02, ...
    kind: Literal["scene", "bottleneck", "ending", "prologue"] = "scene"
    title: str = ""
    summary: str = ""
    goal: str = ""  # what the character is trying to do in this episode
    duration_min: float = 3.0
    requires: list[Predicate] = field(default_factory=list)
    invariants: list[Predicate] = field(default_factory=list)  # bottleneck only
    beats: list[str] = field(default_factory=list)
    choice_question: str = ""  # protagonist's dilemma, e.g. "苏锦该如何应对战王的试探？"
    chapter_range: str = ""  # source chapter range, e.g. "第1-5章" — used for temporal branching
    entry_context: str = ""  # WHERE/WHEN this scene opens, e.g. "流放第二日·驿站·夜"
    exit_context: str = ""   # WHERE/WHEN this scene ends, e.g. "驿站后院·深夜·颜如玉发现密信"

    @property
    def is_cornerstone(self) -> bool:
        """Cornerstone nodes are structural anchors created by step-1.

        Cornerstones: prologue (entry), bottleneck (convergence), ending (terminal).
        Step-2 MUST NOT rewrite or delete them — only add beats/choices.
        All non-cornerstone nodes are created freely by step-2.
        """
        return self.kind in ("prologue", "bottleneck", "ending")


@dataclass
class Edge:
    """A directed edge in the spine/DAG.

    label: choice text shown to the player (≤8 CJK chars).
    effects: state mutations (registry vars only, never free-text).

    Step-2 fork rule: given (state, goal) at the source node, each
    outgoing edge must represent a DIFFERENT decision the character
    could make.  Reject non-choices, character-impossible actions,
    and pure retreat.
    """
    id: str
    src: str
    dst: str
    label: str = ""
    effects: list[Effect] = field(default_factory=list)
    resolution: list[str] = field(default_factory=list)  # beats showing choice outcome


# ── Spine ───────────────────────────────────────────────────────────

@dataclass
class Spine:
    """The story spine: ordered nodes + edges forming a simplified DAG.

    At step-1, this is linear (one through-line) with marked bottlenecks.
    At step-2, it expands into a branching DAG.
    """
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    entry_node: str = ""

    def get_node(self, node_id: str) -> Node | None:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    def node_ids(self) -> set[str]:
        return {n.id for n in self.nodes}

    def get_successors(self, node_id: str) -> list[str]:
        return [e.dst for e in self.edges if e.src == node_id]

    def get_predecessors(self, node_id: str) -> list[str]:
        return [e.src for e in self.edges if e.dst == node_id]

    def bottleneck_nodes(self) -> list[Node]:
        """Get all bottleneck nodes, ordered by position in the node list."""
        node_order = {n.id: i for i, n in enumerate(self.nodes)}
        return sorted(
            [n for n in self.nodes if n.kind == "bottleneck"],
            key=lambda n: node_order.get(n.id, 0)
        )

    def ending_nodes(self) -> list[Node]:
        return [n for n in self.nodes if n.kind == "ending"]

    def all_paths(self, start: str | None = None, end: str | None = None) -> list[list[str]]:
        """Find all paths from start to end via DFS."""
        start = start or self.entry_node
        if not start:
            return []

        targets = {end} if end else {n.id for n in self.ending_nodes()}
        if not targets:
            has_outgoing = {e.src for e in self.edges}
            targets = self.node_ids() - has_outgoing

        adj: dict[str, list[str]] = {}
        for e in self.edges:
            adj.setdefault(e.src, []).append(e.dst)

        paths: list[list[str]] = []
        stack: list[tuple[str, list[str]]] = [(start, [start])]
        while stack:
            current, path = stack.pop()
            if current in targets:
                paths.append(path)
                continue
            for neighbor in adj.get(current, []):
                if neighbor not in path:
                    stack.append((neighbor, path + [neighbor]))
        return paths

    def reachable_from(self, start: str) -> set[str]:
        """BFS to find all nodes reachable from start."""
        visited: set[str] = set()
        queue = deque([start])
        adj: dict[str, list[str]] = {}
        for e in self.edges:
            adj.setdefault(e.src, []).append(e.dst)
        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            for neighbor in adj.get(node, []):
                if neighbor not in visited:
                    queue.append(neighbor)
        return visited


# ── Bible ───────────────────────────────────────────────────────────

@dataclass
class Bible:
    """Story bible: canon facts extracted from highlights."""
    title: str = ""
    genre: str = ""
    tone: str = ""
    dramatic_question: str = ""
    protagonist: dict[str, Any] = field(default_factory=dict)
    characters: list[dict[str, Any]] = field(default_factory=list)
    world: dict[str, Any] = field(default_factory=dict)
    themes: list[str] = field(default_factory=list)
    canon_facts: list[str] = field(default_factory=list)
    source_chapters: str = ""


# ── SpineState (top-level project state) ────────────────────────────

@dataclass
class SpineState:
    """Top-level project state, serialized to state.json.

    This is the contract between step-1 → step-2 → step-3.
    """
    version: str = "1.0"
    step: Literal["step-1", "step-2", "step-3", "step-4"] = "step-1"
    metadata: dict[str, Any] = field(default_factory=dict)
    bible: Bible = field(default_factory=Bible)
    registry: Registry = field(default_factory=Registry)
    spine: Spine = field(default_factory=Spine)
    highlights: list[dict[str, Any]] = field(default_factory=list)
    budget_report: dict[str, Any] = field(default_factory=dict)
    chapter_index: list[dict[str, Any]] = field(default_factory=list)
    scripts: dict[str, str] = field(default_factory=dict)
    validation_reports: dict[str, Any] = field(default_factory=dict)


# ── Utility functions (step-2) ──────────────────────────────────────

def state_at(spine: Spine, registry: Registry, path: list[str]) -> dict[str, Any]:
    """Simulate state along a path, returning final state dict.

    Starts from registry defaults, applies effects on each edge traversed.
    """
    state: dict[str, Any] = {v.key: v.default for v in registry.vars}
    # Build edge lookup: (src, dst) -> list[Effect]
    edge_map: dict[tuple[str, str], list[Effect]] = {}
    for e in spine.edges:
        edge_map.setdefault((e.src, e.dst), []).extend(e.effects)

    for i in range(len(path) - 1):
        src, dst = path[i], path[i + 1]
        for effect in edge_map.get((src, dst), []):
            var = registry.get_var(effect.key)
            if not var:
                continue
            if effect.op == "set":
                state[effect.key] = effect.value
            elif effect.op == "add" and var.type == "bounded_int":
                val = state.get(effect.key, var.default)
                new_val = val + effect.value
                if var.min_val is not None:
                    new_val = max(var.min_val, new_val)
                if var.max_val is not None:
                    new_val = min(var.max_val, new_val)
                state[effect.key] = new_val
    return state


def path_duration(spine: Spine, path: list[str]) -> float:
    """Sum node durations along a path."""
    total = 0.0
    for node_id in path:
        node = spine.get_node(node_id)
        if node:
            total += node.duration_min
    return total


def segments_between_bottlenecks(spine: Spine) -> list[list[str]]:
    """Slice the spine at bottleneck boundaries.

    Returns a list of segments, where each segment is a list of node IDs.
    Segments run from entry→first bottleneck, bottleneck→bottleneck, etc.
    Bottleneck nodes appear as the LAST element of one segment and the
    FIRST element of the next.
    """
    if not spine.nodes:
        return []

    # Build ordered list from entry via BFS (respecting DAG order)
    visited_order: list[str] = []
    visited_set: set[str] = set()
    queue = deque([spine.entry_node]) if spine.entry_node else deque()
    adj: dict[str, list[str]] = {}
    for e in spine.edges:
        adj.setdefault(e.src, []).append(e.dst)

    while queue:
        nid = queue.popleft()
        if nid in visited_set:
            continue
        visited_set.add(nid)
        visited_order.append(nid)
        for neighbor in adj.get(nid, []):
            if neighbor not in visited_set:
                queue.append(neighbor)

    # Find bottleneck positions
    bn_ids = {n.id for n in spine.bottleneck_nodes()}
    segments: list[list[str]] = []
    current: list[str] = []

    for nid in visited_order:
        current.append(nid)
        if nid in bn_ids and len(current) > 1:
            segments.append(current)
            current = [nid]  # bottleneck starts next segment too

    if current:
        segments.append(current)

    return segments


# ── JSON serialization ──────────────────────────────────────────────

def save_state(state: SpineState, project_dir: str) -> str:
    """Save SpineState to project_dir/state.json. Returns path.

    Validates before writing when step >= "step-2". Raises ValueError
    if blocking validation errors exist — the file is NOT written.
    """
    if state.step in ("step-2", "step-3", "step-4"):
        from validate_spine import validate_spine
        result = validate_spine(state)
        if not result.ok:
            error_lines = [f"  - [{cat}] {msg}" for cat, msg in result.errors]
            raise ValueError(
                f"save_state BLOCKED — {len(result.errors)} validation error(s) "
                f"at step={state.step}:\n" + "\n".join(error_lines)
            )
    data = asdict(state)
    path = os.path.join(project_dir, "state.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def load_state(project_dir: str) -> SpineState:
    """Load SpineState from project_dir/state.json."""
    path = os.path.join(project_dir, "state.json")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return _dict_to_state(data)


def _dict_to_state(data: dict) -> SpineState:
    """Reconstruct SpineState from a dict (JSON round-trip)."""
    reg_data = data.get("registry", {})
    reg_vars = [RegistryVar(**v) for v in reg_data.get("vars", [])]
    registry = Registry(vars=reg_vars)

    spine_data = data.get("spine", {})
    nodes = []
    for nd in spine_data.get("nodes", []):
        requires = [Predicate(**p) for p in nd.pop("requires", [])]
        invariants = [Predicate(**p) for p in nd.pop("invariants", [])]
        nodes.append(Node(**nd, requires=requires, invariants=invariants))
    edges = []
    for ed in spine_data.get("edges", []):
        effects = [Effect(**e) for e in ed.pop("effects", [])]
        resolution = ed.pop("resolution", [])
        edges.append(Edge(**ed, effects=effects, resolution=resolution))
    spine = Spine(
        nodes=nodes, edges=edges,
        entry_node=spine_data.get("entry_node", ""),
    )

    bible_data = data.get("bible", {})
    bible = Bible(**bible_data)
    highlights = data.get("highlights", [])

    return SpineState(
        version=data.get("version", "1.0"),
        step=data.get("step", "step-1"),
        metadata=data.get("metadata", {}),
        bible=bible, registry=registry, spine=spine,
        highlights=highlights,
        budget_report=data.get("budget_report", {}),
        chapter_index=data.get("chapter_index", []),
        scripts=data.get("scripts", {}),
        validation_reports=data.get("validation_reports", {}),
    )


def save_registry_json(registry: Registry, project_dir: str) -> str:
    path = os.path.join(project_dir, "registry.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(registry), f, ensure_ascii=False, indent=2)
    return path


def save_spine_json(spine: Spine, project_dir: str) -> str:
    path = os.path.join(project_dir, "spine.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(spine), f, ensure_ascii=False, indent=2)
    return path


def save_bible_md(bible: Bible, project_dir: str) -> str:
    path = os.path.join(project_dir, "bible.md")
    lines = [
        f"# {bible.title}\n",
        f"**Genre**: {bible.genre}",
        f"**Tone**: {bible.tone}\n",
        f"## Dramatic Question\n",
        f"{bible.dramatic_question}\n",
    ]
    if bible.protagonist:
        lines.append("## Protagonist\n")
        for k, v in bible.protagonist.items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")
    if bible.characters:
        lines.append("## Characters\n")
        for char in bible.characters:
            name = char.get("name", "?")
            role = char.get("role", "")
            lines.append(f"### {name}")
            if role:
                lines.append(f"- **Role**: {role}")
            for k, v in char.items():
                if k not in ("name", "role"):
                    lines.append(f"- **{k}**: {v}")
            lines.append("")
    if bible.world:
        lines.append("## World\n")
        for k, v in bible.world.items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")
    if bible.themes:
        lines.append("## Themes\n")
        for t in bible.themes:
            lines.append(f"- {t}")
        lines.append("")
    if bible.canon_facts:
        lines.append("## Canon Facts\n")
        for fact in bible.canon_facts:
            lines.append(f"- {fact}")
        lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def save_preview_md(state: SpineState, project_dir: str) -> str:
    """Generate a human-readable preview of the spine."""
    path = os.path.join(project_dir, "preview.md")
    bible = state.bible
    spine = state.spine
    registry = state.registry

    lines = [
        f"# Preview: {bible.title}\n",
        f"**Genre**: {bible.genre} | **Tone**: {bible.tone}",
        f"**Dramatic Question**: {bible.dramatic_question}\n",
    ]

    # Registry summary
    if registry.vars:
        lines.append("## State Registry\n")
        lines.append("| Variable | Type | Default | Description |")
        lines.append("|----------|------|---------|-------------|")
        for v in registry.vars:
            type_str = v.type
            if v.type == "enum":
                type_str = f"enum({', '.join(v.values or [])})"
            elif v.type == "bounded_int":
                type_str = f"int[{v.min_val}..{v.max_val}] (REVIEW)"
            lines.append(f"| `{v.key}` | {type_str} | `{v.default}` | {v.description} |")
        lines.append("")

    # Spine walkthrough — one node = one episode (three-part brief)
    lines.append("## Story Spine\n")
    for node in spine.nodes:
        kind_badge = {"prologue": "▶", "scene": "●", "bottleneck": "◆", "ending": "★"}.get(node.kind, "○")
        lines.append(f"### {kind_badge} {node.id}: {node.title} ({node.duration_min} min)\n")

        # Part 1: State — entry conditions + invariants
        if node.requires:
            req_strs = [f"`{p.key} {p.cmp} {p.value}`" for p in node.requires]
            lines.append(f"**入场条件**: {', '.join(req_strs)}\n")
        if node.invariants:
            inv_strs = [f"`{p.key} {p.cmp} {p.value}`" for p in node.invariants]
            lines.append(f"**不变量 (canon)**: {', '.join(inv_strs)}\n")

        # Part 2: Story skeleton — summary + beats
        if node.summary:
            lines.append(node.summary + "\n")
        if node.goal:
            lines.append(f"**Goal**: {node.goal}\n")
        if node.beats:
            lines.append("**节拍**:")
            for i, beat in enumerate(node.beats, 1):
                lines.append(f"{i}. {beat}")
            lines.append("")

        # Part 3: Player options — choice_question + edges with effects
        out_edges = [e for e in spine.edges if e.src == node.id]
        if out_edges:
            if node.choice_question:
                lines.append(f"**选择**: {node.choice_question}")
            for edge in out_edges:
                effect_str = ""
                if edge.effects:
                    eff_parts = [f"{e.key}={e.value}" for e in edge.effects]
                    effect_str = f" [{', '.join(eff_parts)}]"
                label = edge.label or "→"
                lines.append(f"- → **{edge.dst}** {label}{effect_str}")
                if edge.resolution:
                    lines.append(f"  选择结果:")
                    for beat in edge.resolution:
                        lines.append(f"    - {beat}")
            lines.append("")
        else:
            lines.append("")

    # Endings summary
    endings = spine.ending_nodes()
    if endings:
        lines.append("## Endings\n")
        for e in endings:
            lines.append(f"- **{e.id}**: {e.title} — {e.summary}")
        lines.append("")

    # Review flags
    flags = registry.review_flags()
    if flags:
        lines.append("## Human Review Flags\n")
        for f in flags:
            lines.append(f"- {f}")
        lines.append("")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path
