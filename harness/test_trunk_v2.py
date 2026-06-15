"""Tests for v2 trunk mechanics: same-target choices, per-choice state_delta,
edge-wise guaranteed computation, trunk-shape validation, and the report card."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harness.checkpoint import _serialize_graph
from harness.graph_ops import merge
from harness.guaranteed import compute_guaranteed
from harness.metrics import report
from harness.models import (
    VARIES, Choice, Effect, FactDecl, Graph, Node, Registry,
)
from harness.validation import validate_deterministic, validate_trunk_shape


def _registry() -> Registry:
    return {
        "player.bold": FactDecl("player.bold", "disposition", "勇", False),
        "player.kind": FactDecl("player.kind", "disposition", "仁", False),
        "world.secret": FactDecl("world.secret", "knowledge", "秘密", False),
    }


def _skel(nid: str):
    return [
        {"type": "scene_header", "location": "营地", "time": "夜", "characters": ["主角"]},
        {"type": "action", "text": f"{nid} 动作1"},
        {"type": "action", "text": f"{nid} 动作2"},
        {"type": "dialogue", "speaker": "主角", "line": "……"},
        {"type": "narration", "text": "转折"},
    ]


def _node(nid: str, choices: list[Choice], ending: str = "NONE", kind: str = "scene") -> Node:
    return Node(
        id=nid, kind=kind if ending == "NONE" else "ending",
        skeleton=_skel(nid),
        planned_duration_min=2.5 if ending != "DEAD_END" else 1.0,
        chapters=(1, 2),
        ending=ending,
        question=None if ending != "NONE" else "走还是留？",
        choices=choices,
        entry_context="营地·夜", exit_context="营地·夜",
    )


def _pair(to: str, fa: str, fb: str) -> list[Choice]:
    return [
        Choice(label="冒险救人", to=to, resolution=["r1", "r2"],
               state_delta=[Effect(fact=fa, value=True)]),
        Choice(label="稳妥撤离", to=to, resolution=["r1", "r2"],
               state_delta=[Effect(fact=fb, value=True)]),
    ]


def _trunk_graph() -> Graph:
    """prologue → t1 → t2 →(fork) e1/e2, trunk uses same-target pairs."""
    g = Graph(root="p")
    g.nodes = {
        "p": _node("p", _pair("t1", "player.bold", "player.kind"), kind="prologue"),
        "t1": _node("t1", _pair("t2", "player.bold", "player.kind"), kind="bottleneck"),
        "t2": _node("t2", [
            Choice(label="决一死战", to="e1", resolution=["r1", "r2"]),
            Choice(label="远走高飞", to="e2", resolution=["r1", "r2"]),
        ], kind="bottleneck"),
        "e1": _node("e1", [], ending="ENDING"),
        "e2": _node("e2", [], ending="ENDING"),
    }
    return g


# ---------- same-target D9 semantics ----------

def test_same_target_with_distinct_deltas_is_legal():
    g = _trunk_graph()
    reg = _registry()
    compute_guaranteed(g, reg)
    violations = validate_deterministic(g, reg, require_content=False)
    same_target_v = [v for v in violations if "same target" in v.problem]
    assert not same_target_v, same_target_v


def test_same_target_with_identical_deltas_is_violation():
    g = _trunk_graph()
    reg = _registry()
    # Make t1's two choices identical in delta
    for c in g.nodes["t1"].choices:
        c.state_delta = [Effect(fact="player.bold", value=True)]
    compute_guaranteed(g, reg)
    violations = validate_deterministic(g, reg, require_content=False)
    assert any("identical state_delta" in v.problem for v in violations)


# ---------- edge-wise guaranteed ----------

def test_guaranteed_meets_over_choice_deltas():
    g = _trunk_graph()
    reg = _registry()
    compute_guaranteed(g, reg)
    # At t1, the two inbound edges from p disagree on bold/kind → VARIES
    assert g.nodes["t1"].guaranteed["player.bold"] is VARIES
    assert g.nodes["t1"].guaranteed["player.kind"] is VARIES


def test_guaranteed_agreeing_deltas_stay_concrete():
    g = _trunk_graph()
    reg = _registry()
    # Both p-choices also set world.secret=True → guaranteed at t1
    for c in g.nodes["p"].choices:
        c.state_delta.append(Effect(fact="world.secret", value=True))
    compute_guaranteed(g, reg)
    assert g.nodes["t1"].guaranteed["world.secret"] is True


# ---------- trunk shape (D13) ----------

def test_trunk_shape_passes_on_convergent_trunk():
    g = _trunk_graph()
    assert validate_trunk_shape(g) == []


def test_trunk_shape_fails_on_time_cave():
    """Old-style cornerstone: first fork never converges."""
    g = Graph(root="p")
    g.nodes = {
        "p": _node("p", [
            Choice(label="冒险救人", to="a", resolution=["r1", "r2"]),
            Choice(label="稳妥撤离", to="b", resolution=["r1", "r2"]),
        ], kind="prologue"),
        "a": _node("a", [
            Choice(label="决一死战", to="e1", resolution=["r1", "r2"]),
            Choice(label="远走高飞", to="e2", resolution=["r1", "r2"]),
        ]),
        "b": _node("b", [
            Choice(label="进城寻仇", to="e3", resolution=["r1", "r2"]),
            Choice(label="归隐山林", to="e4", resolution=["r1", "r2"]),
        ]),
        "e1": _node("e1", [], ending="ENDING"),
        "e2": _node("e2", [], ending="ENDING"),
        "e3": _node("e3", [], ending="ENDING"),
        "e4": _node("e4", [], ending="ENDING"),
    }
    violations = validate_trunk_shape(g)
    assert any(v.check == "D13" for v in violations)


def test_trunk_shape_rejects_dead_ends_at_trunk_stage():
    g = _trunk_graph()
    g.nodes["de"] = _node("de", [], ending="DEAD_END")
    violations = validate_trunk_shape(g)
    assert any("DEAD_END" in v.problem for v in violations)


# ---------- 3-way ending fan ----------

def test_three_choice_ending_fan_is_legal():
    g = _trunk_graph()
    reg = _registry()
    g.nodes["e3"] = _node("e3", [], ending="ENDING")
    g.nodes["t2"].choices.append(
        Choice(label="远遁江湖", to="e3", resolution=["r1", "r2"]))
    compute_guaranteed(g, reg)
    violations = validate_deterministic(g, reg, require_content=False)
    count_v = [v for v in violations if "choices" in v.problem and "must have exactly" in v.problem]
    assert not count_v, count_v


def test_three_choices_mid_graph_is_violation():
    g = _trunk_graph()
    reg = _registry()
    # t1 targets t2 (non-terminal) — 3 choices must be rejected here
    g.nodes["t1"].choices.append(
        Choice(label="另寻他路", to="t2", resolution=["r1", "r2"],
               state_delta=[Effect(fact="world.secret", value=True)]))
    compute_guaranteed(g, reg)
    violations = validate_deterministic(g, reg, require_content=False)
    assert any("must have exactly 2" in v.problem for v in violations)


# ---------- merge: expanding one edge of a same-target pair ----------

def test_merge_length_extending_preserves_sibling_pair_edge():
    g = _trunk_graph()
    reg = _registry()
    compute_guaranteed(g, reg)

    interior = _node("x1", [
        Choice(label="搏命突围", to="t1", resolution=["r1", "r2"],
               state_delta=[Effect(fact="player.bold", value=True)]),
        Choice(label="智取脱身", to="t1", resolution=["r1", "r2"],
               state_delta=[Effect(fact="player.kind", value=True)]),
    ])
    sub_a = _node("p", [Choice(label="冒险救人", to="x1", resolution=["r1", "r2"])],
                  kind="prologue")
    sub = {"p": sub_a, "x1": interior, "t1": g.nodes["t1"]}

    merged = merge(g, sub, "p", "t1", reg, "LENGTH_EXTENDING")
    assert isinstance(merged, Graph), getattr(merged, "reason", None)

    p_choices = merged.nodes["p"].choices
    assert len(p_choices) == 2
    targets = sorted(c.to for c in p_choices)
    assert targets == ["t1", "x1"]  # one pair edge preserved, one replaced

    # t1 now has 2 parents → convergence
    assert sorted(merged.predecessors("t1")) == ["p", "x1"]

    compute_guaranteed(merged, reg)
    violations = validate_deterministic(merged, reg, require_content=False)
    hard = [v for v in violations if v.check in ("D1", "D4", "D6", "D7")]
    assert not hard, hard


# ---------- report card ----------

def test_report_card_gates_on_convergent_graph():
    g = _trunk_graph()
    rep = report(_serialize_graph(g))
    # Stat-write pairs are NOT narrative convergence: distinct parents only
    assert rep["structure"]["convergence_count"] == 0
    assert rep["structure"]["dead_end_ratio"] == 0.0
    assert rep["gates"]["D15_dead_end_ratio"]["pass"]
    assert rep["choices"]["same_target_pairs"] == 2
    assert rep["choices"]["state_writing_choices"] == 4


def test_report_card_counts_real_convergence_after_excursion():
    g = _trunk_graph()
    reg = _registry()
    compute_guaranteed(g, reg)
    interior = _node("x1", [
        Choice(label="搏命突围", to="t1", resolution=["r1", "r2"],
               state_delta=[Effect(fact="player.bold", value=True)]),
        Choice(label="智取脱身", to="t1", resolution=["r1", "r2"],
               state_delta=[Effect(fact="player.kind", value=True)]),
    ])
    sub_a = _node("p", [Choice(label="冒险救人", to="x1", resolution=["r1", "r2"])],
                  kind="prologue")
    merged = merge(g, {"p": sub_a, "x1": interior, "t1": g.nodes["t1"]},
                   "p", "t1", reg, "LENGTH_EXTENDING")
    assert isinstance(merged, Graph)
    rep = report(_serialize_graph(merged))
    assert rep["structure"]["convergence_count"] == 1
    assert rep["structure"]["convergence_nodes"] == ["t1"]


def test_report_card_fails_time_cave():
    # The documented bad run shape: no convergence, heavy dead ends
    g = Graph(root="p")
    g.nodes = {
        "p": _node("p", [
            Choice(label="冒险救人", to="a", resolution=["r1", "r2"]),
            Choice(label="稳妥撤离", to="b", resolution=["r1", "r2"]),
        ], kind="prologue"),
        "a": _node("a", [
            Choice(label="决一死战", to="e1", resolution=["r1", "r2"]),
            Choice(label="远走高飞", to="d1", resolution=["r1", "r2"]),
        ]),
        "b": _node("b", [
            Choice(label="进城寻仇", to="e2", resolution=["r1", "r2"]),
            Choice(label="归隐山林", to="d2", resolution=["r1", "r2"]),
        ]),
        "e1": _node("e1", [], ending="ENDING"),
        "e2": _node("e2", [], ending="ENDING"),
        "d1": _node("d1", [], ending="DEAD_END"),
        "d2": _node("d2", [], ending="DEAD_END"),
    }
    rep = report(_serialize_graph(g))
    assert rep["structure"]["convergence_count"] == 0
    assert not rep["gates"]["D15_dead_end_ratio"]["pass"]


# ---------- registry recovery on resume ----------

def test_recover_registry_includes_state_delta_facts():
    """Resume path must re-register facts that live only in choice.state_delta
    (regression: D5 rejections of every expansion after resume)."""
    from harness.harness import _recover_registry_from_graph

    g = _trunk_graph()
    registry: dict = {}  # simulate resume: bible registry lost the trunk's new_facts
    _recover_registry_from_graph(g, registry)
    assert "player.bold" in registry
    assert "player.kind" in registry
    assert registry["player.bold"].kind == "disposition"


# ---------- fake-backend end-to-end smoke ----------

def test_fake_pipeline_end_to_end(tmp_path):
    """Whole pipeline (phase 1 → export) on the fake backend, ~0.1s.
    Validates wiring + structural gates, not creativity."""
    import json
    import subprocess

    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "test_3ch.txt")
    # --total leaves room for BOTH batch excursions to commit: commits are
    # as-completed (race-ordered), and only the n1→t1 one creates convergence.
    proc = subprocess.run(
        [sys.executable, "-m", "harness", fixture, "--model", "fake",
         "--playthrough", "8", "--total", "20", "--min-endings", "2",
         "--no-upload"],
        capture_output=True, text=True, timeout=120,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]

    # Find the run dir from the output and check the report card gates
    import re
    m = re.search(r"Report card written to (\S+)/report\.md", proc.stdout + proc.stderr)
    assert m, "no report card line in output"
    with open(os.path.join(m.group(1), "report.json"), encoding="utf-8") as fh:
        rep = json.load(fh)
    assert all(g["pass"] for g in rep["gates"].values()), rep["gates"]
    assert rep["structure"]["convergence_count"] >= 1
    assert rep["structure"]["dead_end_count"] == 0


# ---------- checkpoint round-trip ----------

def test_checkpoint_roundtrip_preserves_state_delta(tmp_path):
    import json

    from harness.checkpoint import load_graph

    g = _trunk_graph()
    data = _serialize_graph(g)
    path = tmp_path / "checkpoint_test.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    g2 = load_graph(str(path))
    c0 = g2.nodes["p"].choices[0]
    assert c0.state_delta and c0.state_delta[0].fact == "player.bold"
    assert g2.nodes["p"].choices[0].delta_key() != g2.nodes["p"].choices[1].delta_key()
