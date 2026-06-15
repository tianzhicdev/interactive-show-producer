"""Report card — quantitative quality metrics for a story graph.

Works on plain serialized graph dicts ({root, nodes}) so it can score both live
Graph objects (via checkpoint._serialize_graph) and historical run outputs
(graph_final.json / checkpoint_*.json) that predate newer schema fields.

Gates (HARNESS_V2_IMPLEMENTATION_PLAN M0/M3):
  - convergence_count >= 1 once the graph has >= 8 nodes
  - dead_end_ratio <= 0.25
  - every fork reconverges within FORK_RECONVERGE_MAX nodes or terminates
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

FORK_RECONVERGE_MAX = int(os.environ.get("HARNESS_FORK_RECONVERGE_MAX", "2"))
DEAD_END_RATIO_MAX = 0.25  # D15
CONVERGENCE_MIN_GRAPH_SIZE = 8  # D13 applies only to graphs at least this big


# ---------- graph-dict helpers ----------

def _graph_dict(graph_or_dict) -> dict:
    """Accept a Graph object or a serialized {root, nodes} dict."""
    if isinstance(graph_or_dict, dict):
        return graph_or_dict
    from .checkpoint import _serialize_graph
    return _serialize_graph(graph_or_dict)


def _edges(gd: dict) -> list[tuple[str, str]]:
    out = []
    for nid, nd in gd["nodes"].items():
        for c in nd.get("choices", []):
            to = c.get("to", "")
            if to in gd["nodes"]:
                out.append((nid, to))
    return out


def _parents(gd: dict) -> dict[str, list[str]]:
    """Distinct parent NODES per node. A same-target choice pair contributes one
    parent — stat-write pairs are not narrative convergence."""
    parents: dict[str, set[str]] = defaultdict(set)
    for src, dst in _edges(gd):
        parents[dst].add(src)
    return {k: sorted(v) for k, v in parents.items()}


def _topo(gd: dict) -> list[str]:
    indeg = {nid: 0 for nid in gd["nodes"]}
    for _, dst in _edges(gd):
        indeg[dst] += 1
    queue = sorted([n for n, d in indeg.items() if d == 0])
    order = []
    while queue:
        n = queue.pop(0)
        order.append(n)
        for c in gd["nodes"][n].get("choices", []):
            to = c.get("to", "")
            if to in indeg:
                indeg[to] -= 1
                if indeg[to] == 0:
                    queue.append(to)
        queue.sort()
    return order


def _bigrams(text: str) -> set[str]:
    text = "".join(text.split())
    return {text[i:i + 2] for i in range(len(text) - 1)}


# ---------- metric sections ----------

def _structure_metrics(gd: dict) -> dict:
    nodes = gd["nodes"]
    parents = _parents(gd)
    endings = [n for n, nd in nodes.items() if nd.get("ending") == "ENDING"]
    dead_ends = [n for n, nd in nodes.items() if nd.get("ending") == "DEAD_END"]
    convergence = sorted([n for n, ps in parents.items() if len(ps) > 1])
    parent_hist: dict[int, int] = defaultdict(int)
    for nid in nodes:
        parent_hist[len(parents.get(nid, []))] += 1

    n_total = len(nodes)
    return {
        "node_count": n_total,
        "ending_count": len(endings),
        "dead_end_count": len(dead_ends),
        "dead_end_ratio": round(len(dead_ends) / n_total, 3) if n_total else 0.0,
        "convergence_count": len(convergence),
        "convergence_nodes": convergence,
        "parent_count_histogram": dict(sorted(parent_hist.items())),
    }


def _fork_reconvergence(gd: dict) -> dict:
    """For each true fork (2 distinct in-graph targets), depth until branches
    re-meet at a common descendant. None = never re-meet (time-cave fork)."""
    nodes = gd["nodes"]

    def descend_frontiers(start: str, depth: int) -> list[set[str]]:
        """frontiers[d] = set of nodes reachable in exactly <= d steps."""
        seen = {start}
        frontier = {start}
        layers = [set(seen)]
        for _ in range(depth):
            nxt = set()
            for n in frontier:
                for c in nodes.get(n, {}).get("choices", []):
                    if c.get("to") in nodes and c["to"] not in seen:
                        nxt.add(c["to"])
            seen |= nxt
            frontier = nxt
            layers.append(set(seen))
        return layers

    forks = {}
    for nid, nd in nodes.items():
        targets = list({c.get("to") for c in nd.get("choices", []) if c.get("to") in nodes})
        if len(targets) < 2:
            continue
        # Exempt legitimate fork shapes: ending fan-outs (all terminal) and
        # mediate forks (one branch dies in a DEAD_END/ENDING — it cannot
        # re-merge by definition; that is the designed BE shape).
        nonterminal = [t for t in targets if nodes[t].get("ending") == "NONE"]
        if len(nonterminal) < 2:
            continue
        targets = nonterminal
        la = descend_frontiers(targets[0], FORK_RECONVERGE_MAX + 1)
        lb = descend_frontiers(targets[1], FORK_RECONVERGE_MAX + 1)
        depth = None
        for d in range(FORK_RECONVERGE_MAX + 2):
            ia = la[min(d, len(la) - 1)]
            ib = lb[min(d, len(lb) - 1)]
            if ia & ib:
                depth = d
                break
        # A fork whose branches terminate (ending/dead-end) without re-meeting
        # is acceptable only late-game; report depth=None for visibility.
        forks[nid] = depth

    never = sorted([n for n, d in forks.items() if d is None])
    too_deep = sorted([n for n, d in forks.items() if d is not None and d > FORK_RECONVERGE_MAX])
    return {
        "fork_count": len(forks),
        "reconverge_depths": {k: v for k, v in sorted(forks.items())},
        "forks_never_reconverging": never,
        "forks_reconverging_too_deep": too_deep,
    }


def _pacing_metrics(gd: dict) -> dict:
    nodes = gd["nodes"]
    durations = [float(nd.get("planned_duration_min", 0) or 0) for nd in nodes.values()]
    total = sum(durations)

    # Shortest/longest playthrough minutes over the DAG
    order = _topo(gd)
    shortest: dict[str, float] = {}
    longest: dict[str, float] = {}
    for nid in reversed(order):
        nd = nodes[nid]
        dur = float(nd.get("planned_duration_min", 0) or 0)
        kids = [c.get("to") for c in nd.get("choices", []) if c.get("to") in nodes]
        if not kids:
            shortest[nid] = longest[nid] = dur
        else:
            shortest[nid] = dur + min(shortest.get(k, 0) for k in kids)
            longest[nid] = dur + max(longest.get(k, 0) for k in kids)
    root = gd.get("root", "")
    mean = total / len(durations) if durations else 0
    var = sum((d - mean) ** 2 for d in durations) / len(durations) if durations else 0
    locations = set()
    for nd in nodes.values():
        for el in nd.get("content", []) or nd.get("skeleton", []) or []:
            if isinstance(el, dict) and el.get("type") == "scene_header":
                loc = (el.get("location") or "").strip()
                if loc:
                    locations.add(loc)
    return {
        "distinct_locations": len(locations),
        "total_minutes": round(total, 1),
        "shortest_playthrough_min": round(shortest.get(root, 0), 1),
        "longest_playthrough_min": round(longest.get(root, 0), 1),
        "duration_mean": round(mean, 2),
        "duration_variance": round(var, 3),
    }


def _choice_metrics(gd: dict) -> dict:
    nodes = gd["nodes"]
    questions = [(nid, nd.get("question") or "") for nid, nd in nodes.items()
                 if nd.get("question")]
    n_choices = 0
    same_target_pairs = 0
    state_writing = 0
    label_prefix_dupes = []
    for nid, nd in nodes.items():
        cs = nd.get("choices", [])
        n_choices += len(cs)
        targets = [c.get("to") for c in cs]
        if len(targets) == 2 and targets[0] == targets[1]:
            same_target_pairs += 1
        for c in cs:
            if c.get("state_delta"):
                state_writing += 1
        if len(cs) == 2:
            l0, l1 = cs[0].get("label", ""), cs[1].get("label", "")
            if l0[:2] and l0[:2] == l1[:2]:
                label_prefix_dupes.append(nid)

    # Question similarity clusters: pairwise bigram Jaccard > 0.35
    sim_pairs = []
    for i in range(len(questions)):
        for j in range(i + 1, len(questions)):
            a, b = _bigrams(questions[i][1]), _bigrams(questions[j][1])
            if not a or not b:
                continue
            jac = len(a & b) / len(a | b)
            if jac > 0.35:
                sim_pairs.append((questions[i][0], questions[j][0], round(jac, 2)))

    return {
        "choice_count": n_choices,
        "question_count": len(questions),
        "same_target_pairs": same_target_pairs,
        "state_writing_choices": state_writing,
        "label_prefix_dupes": label_prefix_dupes,
        "similar_question_pairs": sim_pairs[:20],
        "similar_question_pair_count": len(sim_pairs),
    }


def _gates(structure: dict, forks: dict, choices: dict | None = None,
           root_pair: bool = False) -> dict:
    gates = {}
    if choices is not None:
        gates["W2_residual_pairs"] = {
            "pass": not root_pair,
            "value": choices.get("same_target_pairs", 0),
            "threshold": "root pair must be broken (0 at root)",
        }
    n = structure["node_count"]
    if n >= CONVERGENCE_MIN_GRAPH_SIZE:
        gates["D13_convergence_floor"] = {
            "pass": structure["convergence_count"] >= 1,
            "value": structure["convergence_count"],
            "threshold": ">=1",
        }
    gates["D15_dead_end_ratio"] = {
        "pass": structure["dead_end_ratio"] <= DEAD_END_RATIO_MAX,
        "value": structure["dead_end_ratio"],
        "threshold": f"<={DEAD_END_RATIO_MAX}",
    }
    gates["D14_fork_reconvergence"] = {
        "pass": not forks["forks_reconverging_too_deep"],
        "value": len(forks["forks_reconverging_too_deep"]),
        "threshold": f"reconverge within {FORK_RECONVERGE_MAX} nodes",
    }
    return gates


# ---------- public API ----------

def report(graph_or_dict) -> dict:
    gd = _graph_dict(graph_or_dict)
    structure = _structure_metrics(gd)
    forks = _fork_reconvergence(gd)
    choices = _choice_metrics(gd)
    root = gd.get("root", "")
    root_targets = [c.get("to") for c in gd["nodes"].get(root, {}).get("choices", [])]
    root_pair = len(root_targets) == 2 and root_targets[0] == root_targets[1]
    return {
        "structure": structure,
        "forks": forks,
        "pacing": _pacing_metrics(gd),
        "choices": choices,
        "gates": _gates(structure, forks, choices, root_pair),
    }


def render_markdown(rep: dict) -> str:
    s, f, p, c = rep["structure"], rep["forks"], rep["pacing"], rep["choices"]
    lines = ["# Graph Report Card", ""]
    lines.append("## Gates")
    for name, g in rep["gates"].items():
        mark = "PASS" if g["pass"] else "FAIL"
        lines.append(f"- [{mark}] {name}: {g['value']} (need {g['threshold']})")
    lines += [
        "",
        "## Structure",
        f"- nodes: {s['node_count']}  endings: {s['ending_count']}  "
        f"dead_ends: {s['dead_end_count']} (ratio {s['dead_end_ratio']})",
        f"- convergence nodes: {s['convergence_count']} {s['convergence_nodes']}",
        f"- parent histogram: {s['parent_count_histogram']}",
        f"- forks: {f['fork_count']}; never reconverging: "
        f"{len(f['forks_never_reconverging'])} {f['forks_never_reconverging'][:8]}",
        "",
        "## Pacing",
        f"- distinct locations: {p.get('distinct_locations', '?')}",
        f"- total {p['total_minutes']} min; playthrough "
        f"{p['shortest_playthrough_min']}-{p['longest_playthrough_min']} min",
        f"- node duration mean {p['duration_mean']} var {p['duration_variance']}",
        "",
        "## Choices",
        f"- choices: {c['choice_count']}  questions: {c['question_count']}",
        f"- same-target (stat-write) pairs: {c['same_target_pairs']}; "
        f"choices with state_delta: {c['state_writing_choices']}",
        f"- similar question pairs (bigram>0.35): {c['similar_question_pair_count']}",
    ]
    for a, b, j in c["similar_question_pairs"][:10]:
        lines.append(f"  - {a} ~ {b} ({j})")
    if c["label_prefix_dupes"]:
        lines.append(f"- label prefix dupes: {c['label_prefix_dupes']}")
    drama = rep.get("drama")
    if drama:
        lines += ["", "## Drama lint (IR validators, warning-level)"]
        for section, problems in drama.items():
            lines.append(f"- {section}: {len(problems)} issue(s)")
            for p in problems[:6]:
                lines.append(f"  - {p}")
    return "\n".join(lines) + "\n"


def write_report(graph_or_dict, out_dir: str, extra_sections: dict | None = None) -> dict:
    """Compute the report and write report.json + report.md into out_dir."""
    rep = report(graph_or_dict)
    if extra_sections:
        rep.update(extra_sections)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(render_markdown(rep))
    return rep


def report_from_path(path: str) -> dict:
    """Load a run dir (graph_final.json preferred) or a graph JSON file."""
    p = Path(path)
    if p.is_dir():
        candidates = sorted(p.glob("graph_final.json")) or \
            sorted(p.glob("checkpoint_*.json"))
        if not candidates:
            raise FileNotFoundError(f"No graph_final.json or checkpoint in {path}")
        p = candidates[-1]
    with open(p, encoding="utf-8") as fh:
        gd = json.load(fh)
    if "nodes" not in gd:
        raise ValueError(f"{p} does not look like a serialized graph")
    return report(gd)
