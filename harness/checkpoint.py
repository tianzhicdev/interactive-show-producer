"""§3.15 — Checkpoint and write: crash-recovery and final output."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from datetime import datetime

from .models import Choice, Effect, Graph, Highlight, Node, Requirement

log = logging.getLogger(__name__)

# ── Per-run output directory ──────────────────────────────────────────

_run_dir: str | None = None


def init_run_dir(base: str = "harness_output") -> str:
    """Create a timestamped run directory. Called once at the start of each run."""
    global _run_dir
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    _run_dir = os.path.join(base, f"run_{ts}")
    Path(_run_dir).mkdir(parents=True, exist_ok=True)
    return _run_dir


def set_run_dir(path: str) -> str:
    """Set run directory to an existing path (for resume)."""
    global _run_dir
    _run_dir = path
    return _run_dir


def get_run_dir() -> str:
    """Get current run directory, creating one if needed."""
    if _run_dir is None:
        return init_run_dir()
    return _run_dir


# ── Phase 1 checkpoints ──────────────────────────────────────────────

def checkpoint_phase1(
    stage: str,
    *,
    bible: dict | None = None,
    chapters: dict[int, str] | None = None,
    highlights: list[Highlight] | None = None,
) -> str:
    """Save Phase 1 intermediate data to the run directory.

    stage: "bible", "chapters", "highlights", or "phase1_complete"
    """
    run_dir = get_run_dir()
    path = os.path.join(run_dir, f"{stage}.json")

    data: dict = {"_stage": stage, "_time": datetime.now().isoformat()}

    if bible is not None:
        data["bible"] = bible
    if chapters is not None:
        data["chapters"] = {str(k): v for k, v in chapters.items()}
    if highlights is not None:
        data["highlights"] = [
            {"id": h.id, "chapter": h.chapter, "weight": h.weight, "gloss": h.gloss,
             "satisfaction_type": h.satisfaction_type, "hook_type": h.hook_type}
            for h in highlights
        ]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def load_phase1(stage: str, run_dir: str | None = None) -> dict | None:
    """Load a Phase 1 checkpoint. Returns None if not found."""
    d = run_dir or get_run_dir()
    path = os.path.join(d, f"{stage}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Graph serialization ──────────────────────────────────────────────

def _serialize_graph(graph: Graph) -> dict:
    nodes = {}
    for nid, node in graph.nodes.items():
        nodes[nid] = {
            "id": nid,
            "skeleton": node.skeleton,
            "content": node.content,
            "planned_duration_min": node.planned_duration_min,
            "chapters": list(node.chapters),
            "covers": node.covers,
            "kind": node.kind,
            "produces": [{"fact": e.fact, "value": e.value, "beat": e.beat} for e in node.produces],
            "requires": [{"fact": r.fact, "value": r.value} for r in node.requires],
            "entry_invariants": [{"fact": r.fact, "value": r.value} for r in node.entry_invariants],
            "ending": node.ending,
            "question": node.question,
            "title": node.title,
            "entry_context": node.entry_context,
            "exit_context": node.exit_context,
            "sequence": node.sequence,
            "arc_slot": node.arc_slot,
            "tension": node.tension,
            "value": node.value,
            "opening_charge": node.opening_charge,
            "closing_charge": node.closing_charge,
            "turning_type": node.turning_type,
            "expectation": node.expectation,
            "result": node.result,
            "choices": [
                {
                    "label": c.label,
                    "label_requires": [{"fact": r.fact, "value": r.value} for r in c.label_requires],
                    "to": c.to,
                    "resolution": c.resolution,
                    "state_delta": [
                        {"fact": e.fact, "value": e.value, "beat": e.beat}
                        for e in c.state_delta
                    ],
                    "cost": c.cost,
                    "goal_impacts": c.goal_impacts,
                    "aftermath": c.aftermath,
                }
                for c in node.choices
            ],
        }
    return {"root": graph.root, "nodes": nodes}


def checkpoint(graph: Graph, output_dir: str | None = None, tag: str | None = None) -> str:
    """Save a crash-recovery checkpoint. Optional tag is appended to the filename."""
    d = output_dir or get_run_dir()
    Path(d).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{tag}" if tag else ""
    path = os.path.join(d, f"checkpoint_{ts}{suffix}.json")
    data = _serialize_graph(graph)
    data["_checkpoint_time"] = ts
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def write(graph: Graph, prose: bool, output_dir: str | None = None) -> str:
    """Final emit of the graph."""
    d = output_dir or get_run_dir()
    Path(d).mkdir(parents=True, exist_ok=True)
    suffix = "final" if prose else "structure"
    path = os.path.join(d, f"graph_{suffix}.json")
    data = _serialize_graph(graph)
    data["_has_prose"] = prose

    # Also emit a human-readable summary
    summary_lines = [f"Interactive Story Graph — {len(graph.nodes)} nodes"]
    summary_lines.append(f"Root: {graph.root}")

    endings = [n for n in graph.nodes.values() if n.ending == "ENDING"]
    dead_ends = [n for n in graph.nodes.values() if n.ending == "DEAD_END"]
    summary_lines.append(f"Endings: {len(endings)}, Dead ends: {len(dead_ends)}")
    summary_lines.append("")

    for nid in graph.topo_order():
        node = graph.nodes[nid]
        tag = f" [{node.ending}]" if node.ending != "NONE" else ""
        summary_lines.append(
            f"[{nid}]{tag} ch{node.chapters[0]}-{node.chapters[1]} "
            f"planned={node.planned_duration_min:.1f}m"
        )
        if node.content:
            preview = node.get_prose()[:80].replace("\n", " ")
            summary_lines.append(f"  \"{preview}...\"")
        if node.question:
            summary_lines.append(f"  Q: {node.question}")
        for c in node.choices:
            summary_lines.append(f"    → {c.label} → {c.to}")
        summary_lines.append("")

    data["_summary"] = "\n".join(summary_lines)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Also write summary as text
    summary_path = os.path.join(d, f"summary_{suffix}.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines))

    return path


# ── Resume from checkpoint ──────────────────────────────────────────

def find_latest_checkpoint(run_dir: str) -> str | None:
    """Find the most recently WRITTEN checkpoint_*.json in a run directory.

    Sort by mtime, not filename: a tagged checkpoint (e.g. ..._phase3_done.json)
    can share a second-granular timestamp with the later untagged post-prose
    checkpoint and would win a lexical sort, loading stale pre-prose state and
    needlessly re-running Phase 4. mtime reflects true write order.
    """
    checkpoints = list(Path(run_dir).glob("checkpoint_*.json"))
    if not checkpoints:
        return None
    # Sort by (mtime, untagged?). At an identical second-granular mtime, prefer the
    # UNtagged checkpoint: tagged milestones (e.g. ..._phase3_done.json) are written
    # at a phase boundary, while untagged checkpoints are written later during prose,
    # so the untagged one is the more-progressed state to resume from.
    def _untagged(p: Path) -> int:
        # checkpoint_YYYYMMDD_HHMMSS.json (no trailing _<tag>) → untagged.
        return 1 if re.match(r"^checkpoint_\d{8}_\d{6}\.json$", p.name) else 0
    checkpoints.sort(key=lambda p: (p.stat().st_mtime, _untagged(p), p.name))
    return str(checkpoints[-1])


def load_graph(checkpoint_path: str) -> Graph:
    with open(checkpoint_path, encoding="utf-8") as f:
        data = json.load(f)

    root = data["root"]
    nodes: dict[str, Node] = {}
    for nid, ndata in data["nodes"].items():
        skeleton = ndata.get("skeleton", [])
        content = ndata.get("content", [])
        summary = ndata.get("summary", "")

        # Migration: old checkpoints have content but no skeleton
        if not skeleton and content:
            skeleton = list(content) if isinstance(content, list) else []
        if not skeleton and summary:
            skeleton = _migrate_summary_to_skeleton(summary, ndata)

        produces_raw = ndata.get("produces", [])
        produces = [
            Effect(fact=e["fact"], value=e["value"], beat=e.get("beat", ""))
            for e in produces_raw
        ]

        node = Node(
            id=nid,
            kind=ndata.get("kind", "scene"),
            skeleton=skeleton,
            content=content if content else [],
            planned_duration_min=float(ndata.get("planned_duration_min", 2.0)),
            scene_location=ndata.get("scene_location", ""),
            scene_time=ndata.get("scene_time", ""),
            scene_characters=ndata.get("scene_characters", []),
            prose=ndata.get("prose", ""),
            chapters=tuple(ndata.get("chapters", [0, 0])),
            covers=ndata.get("covers", []),
            produces=produces,
            requires=[Requirement(fact=r["fact"], value=r.get("value", True))
                      for r in ndata.get("requires", [])],
            entry_invariants=[Requirement(fact=r["fact"], value=r.get("value", True))
                              for r in ndata.get("entry_invariants", [])],
            ending=ndata.get("ending", "NONE"),
            question=ndata.get("question"),
            title=ndata.get("title", ""),
            entry_context=ndata.get("entry_context", ""),
            exit_context=ndata.get("exit_context", ""),
            sequence=ndata.get("sequence", ""),
            arc_slot=ndata.get("arc_slot", ""),
            tension=int(ndata.get("tension", 0) or 0),
            value=ndata.get("value", ""),
            opening_charge=ndata.get("opening_charge", ""),
            closing_charge=ndata.get("closing_charge", ""),
            turning_type=ndata.get("turning_type", ""),
            expectation=ndata.get("expectation", ""),
            result=ndata.get("result", ""),
            choices=[
                Choice(
                    label=c["label"],
                    label_requires=[Requirement(fact=r["fact"], value=r.get("value", True))
                                    for r in c.get("label_requires", [])],
                    to=c["to"],
                    resolution=c.get("resolution", []),
                    state_delta=[
                        Effect(fact=e["fact"], value=e.get("value", True),
                               beat=e.get("beat", ""))
                        for e in c.get("state_delta", [])
                    ],
                    cost=c.get("cost", ""),
                    goal_impacts=c.get("goal_impacts", {}) or {},
                    aftermath=c.get("aftermath", []) or [],
                )
                for c in ndata.get("choices", [])
            ],
        )
        if node.ending == "DEAD_END":
            node.planned_duration_min = max(0.5, min(1.5, node.planned_duration_min))
        else:
            node.planned_duration_min = max(2.0, min(5.0, node.planned_duration_min))
        nodes[nid] = node
    graph = Graph(root=root, nodes=nodes)
    log.info(f"Loaded graph from {checkpoint_path}: {len(nodes)} nodes, root={root}")
    return graph


def _migrate_summary_to_skeleton(summary: str, ndata: dict) -> list[ContentElement]:
    from .models import _parse_prose_to_elements, make_scene_header
    elements = []
    loc = ndata.get("entry_context", "").split("·")[0] if ndata.get("entry_context") else ""
    time = ""
    chars = []
    if loc:
        elements.append(make_scene_header(loc, time, chars))
    elements.extend(_parse_prose_to_elements(summary))
    return elements


def detect_resume_phase(run_dir: str) -> str:
    """Detect what phase a previous run completed.

    Returns: "none", "phase1", "cornerstone", "expansion", or "phase3_done"
    """
    has_phase1 = os.path.exists(os.path.join(run_dir, "phase1_complete.json"))
    # phase3_done checkpoints are written as checkpoint_<timestamp>_phase3_done.json,
    # so match by glob — a fixed "checkpoint_phase3_done.json" never exists and
    # would force every crashed run to needlessly re-run the expansion loop.
    has_phase3_done = bool(
        list(Path(run_dir).glob("checkpoint_*_phase3_done.json"))
        or list(Path(run_dir).glob("checkpoint_phase3_done.json"))
    )
    has_checkpoint = find_latest_checkpoint(run_dir) is not None

    if has_phase3_done:
        return "phase3_done"
    if has_checkpoint:
        # Retroactive detection: if the latest checkpoint already meets the
        # total budget, the expansion loop must have completed and the run
        # likely crashed in Phase 3.5 or later.  Treat as phase3_done so we
        # skip re-running the expansion loop.
        cp_path = find_latest_checkpoint(run_dir)
        if _checkpoint_budget_met(cp_path):
            return "phase3_done"
        return "expansion"
    if has_phase1:
        return "phase1"
    return "none"


def _checkpoint_budget_met(cp_path: str | None, threshold: float = 95.0) -> bool:
    """Heuristic: if the checkpoint's total planned_duration >= threshold% of
    the default budget (100 min), the expansion loop likely completed.
    """
    if cp_path is None:
        return False
    try:
        with open(cp_path, encoding="utf-8") as f:
            data = json.load(f)
        nodes = data.get("nodes", {})
        total = sum(
            n.get("planned_duration_min", 0) for n in nodes.values()
        )
        return total >= threshold
    except Exception:
        return False
