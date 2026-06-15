"""§3.8–3.10, §3.13 — Graph operations: rank_edges, choose_expansion_type, build_goal, merge."""

from __future__ import annotations

import copy
import os
from .models import (
    VARIES, Choice, Effect, FactDecl, FactId, Feedback, Goal, Graph, Highlight,
    HighlightId, Node, NodeId, Params, Registry, Reject, Requirement, State,
    Violation,
)
from .guaranteed import apply_effects, compute_guaranteed
from .registry import register_facts
from .budget import estimate_minutes, shortest_playthrough

FORK_RECONVERGE_MAX = int(os.environ.get("HARNESS_FORK_RECONVERGE_MAX", "2"))


# ---------- §3.8 rank_edges ----------

def _edges_on_shortest_path(graph: Graph, params: Params) -> set[tuple[NodeId, NodeId]]:
    """Find edges that lie on ANY shortest root→ENDING path."""
    import math
    order = graph.topo_order()

    # Forward: shortest distance from root
    dist_fwd: dict[NodeId, float] = {}
    dist_fwd[graph.root] = estimate_minutes(graph.nodes[graph.root], params)
    pred_on_shortest: dict[NodeId, list[NodeId]] = {graph.root: []}

    for nid in order:
        if nid not in dist_fwd:
            continue
        node = graph.nodes[nid]
        for c in node.choices:
            dest = c.to
            if dest not in graph.nodes:
                continue
            d = dist_fwd[nid] + estimate_minutes(graph.nodes[dest], params)
            if dest not in dist_fwd or d < dist_fwd[dest]:
                dist_fwd[dest] = d
                pred_on_shortest[dest] = [nid]
            elif d == dist_fwd[dest]:
                pred_on_shortest[dest].append(nid)

    # Find ENDING nodes on the overall shortest path
    best_ending = math.inf
    best_ends: list[NodeId] = []
    for nid, node in graph.nodes.items():
        if node.ending == "ENDING" and nid in dist_fwd:
            if dist_fwd[nid] < best_ending:
                best_ending = dist_fwd[nid]
                best_ends = [nid]
            elif dist_fwd[nid] == best_ending:
                best_ends.append(nid)

    # Backtrack to collect all edges on shortest paths
    edges: set[tuple[NodeId, NodeId]] = set()
    visited: set[NodeId] = set()
    stack = list(best_ends)
    while stack:
        nid = stack.pop()
        if nid in visited:
            continue
        visited.add(nid)
        for pid in pred_on_shortest.get(nid, []):
            edges.add((pid, nid))
            stack.append(pid)
    return edges


def rank_edges(
    graph: Graph, highlights: list[Highlight], params: Params
) -> list[tuple[NodeId, Choice]]:
    """§3.8 — Rank edges by expansion priority. Returns (from_node, choice) list, highest first."""
    sp = shortest_playthrough(graph, params)
    shortest_edges = _edges_on_shortest_path(graph, params)

    # Which highlights are already covered?
    covered_highlights: set[HighlightId] = set()
    for node in graph.nodes.values():
        covered_highlights.update(node.covers)

    scored: list[tuple[float, NodeId, Choice]] = []
    for nid, node in graph.nodes.items():
        if "_fallback" in nid:
            continue
        for choice in node.choices:
            if "_fallback" in choice.to:
                continue
            if choice.to in node._non_expandable_edges:
                continue

            dest = choice.to
            if dest not in graph.nodes:
                continue
            if _is_terminal_fanout_node(graph, nid):
                continue
            if _edge_inside_capped_detour(graph, nid, dest):
                continue

            weight = 0.0

            # Length deficit bonus
            if (nid, dest) in shortest_edges and sp < params.target_playthrough_min:
                weight += 10.0

            # Pair-breaking bonus: same-target choice pairs are scaffolding;
            # expanding one edge turns the pair into a real fork that
            # reconverges. Break pairs before anything else — and break them
            # ROOT-FIRST: a fake fork on the player's first choice hurts most.
            siblings_to_dest = sum(1 for c in node.choices if c.to == dest)
            if siblings_to_dest > 1:
                weight += 6.0
                if nid == graph.root:
                    weight += 8.0

            # Unplaced highlight density
            src_node = graph.nodes[nid]
            dst_node = graph.nodes[dest]
            span_start = src_node.chapters[0]
            span_end = dst_node.chapters[1]
            for h in highlights:
                if h.id not in covered_highlights and span_start <= h.chapter <= span_end:
                    weight += h.weight

            scored.append((weight, nid, choice))

    # Sort by weight descending, tie-break by node ID
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [(nid, c) for _, nid, c in scored]


def _is_terminal_fanout_node(graph: Graph, nid: NodeId) -> bool:
    """Do not expand individual edges from the final 3-way ending split.

    D9 permits 3 choices only when every target is terminal. Expanding one of
    those edges creates a mixed 3-choice node (two terminal, one interior), so it
    can never pass the current binary/final-fanout contract.
    """
    node = graph.nodes[nid]
    if len(node.choices) < 3:
        return False
    return all(
        c.to in graph.nodes and graph.nodes[c.to].ending != "NONE"
        for c in node.choices
    )


def _descendants_with_depth(graph: Graph, start: NodeId, max_depth: int) -> dict[NodeId, int]:
    seen: dict[NodeId, int] = {start: 0}
    queue: list[tuple[NodeId, int]] = [(start, 0)]
    while queue:
        nid, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        node = graph.nodes.get(nid)
        if node is None:
            continue
        for choice in node.choices:
            to = choice.to
            if to not in graph.nodes or to in seen:
                continue
            seen[to] = depth + 1
            queue.append((to, depth + 1))
    return seen


def _nodes_on_paths_to(
    graph: Graph, start: NodeId, target: NodeId, max_depth: int,
) -> set[NodeId]:
    """Nodes on any path start→target within max_depth, excluding target."""
    out: set[NodeId] = set()
    queue: list[tuple[NodeId, int, list[NodeId]]] = [(start, 0, [start])]
    while queue:
        nid, depth, path = queue.pop(0)
        if nid == target:
            out.update(path[:-1])
            continue
        if depth >= max_depth:
            continue
        node = graph.nodes.get(nid)
        if node is None:
            continue
        for choice in node.choices:
            to = choice.to
            if to not in graph.nodes or to in path:
                continue
            queue.append((to, depth + 1, path + [to]))
    return out


def _edge_inside_capped_detour(graph: Graph, src: NodeId, dest: NodeId) -> bool:
    """Skip expanding inside an already-maxed live detour.

    The D14 validator rejects overlong cumulative detours after generation; this
    prefilter avoids spending LLM calls on edges that can only lengthen a branch
    already at the configured cap.
    """
    for fork_id, node in graph.nodes.items():
        targets = sorted({
            c.to for c in node.choices
            if c.to in graph.nodes and graph.nodes[c.to].ending == "NONE"
        })
        if len(targets) < 2:
            continue
        reach = {
            target: _descendants_with_depth(graph, target, FORK_RECONVERGE_MAX + 1)
            for target in targets
        }
        common = set.intersection(*(set(r.keys()) for r in reach.values()))
        if not common:
            continue
        meet = min(
            common,
            key=lambda m: max(reach[target][m] for target in targets),
        )
        depth = max(reach[target][meet] for target in targets)
        if depth < FORK_RECONVERGE_MAX:
            continue
        protected: set[NodeId] = set()
        for target in targets:
            protected |= _nodes_on_paths_to(graph, target, meet, depth)
        if ((src in protected) or (src == fork_id and dest in protected)) and dest != meet:
            return True
    return False


# ---------- §3.9 choose_expansion_type ----------

def choose_expansion_type(
    graph: Graph, from_node: NodeId, to_node: NodeId, params: Params
) -> str:
    """§3.9 — always LENGTH_EXTENDING.

    BRANCH_ADDING was unreachable: the binary contract gives every non-ending
    node exactly 2 choices, so the >=2 guard always fired. Forking now comes
    from candidate-menu interiors, dead-end branches, and pair-breaking."""
    return "LENGTH_EXTENDING"


# ---------- §3.10 build_goal ----------

def build_goal(graph: Graph, a_id: NodeId, b_id: NodeId, registry: Registry) -> Goal:
    """§3.10 — Build the goal (frozen outer seams) for expanding edge A→B."""
    from .guaranteed import varying_facts

    a_node = graph.nodes[a_id]
    b_node = graph.nodes[b_id]

    # entryA_state = guaranteed(A)
    entry_state = dict(a_node.guaranteed) if a_node.guaranteed else {}

    # exitB_contract: requirements every downstream-of-B node places on B's output
    exit_contract: list[Requirement] = list(b_node.requires)

    # invariants: all invariant facts in the registry
    invariants = [fid for fid, decl in registry.items() if decl.invariant]

    # varying_state: facts that are VARIES at A — interior MUST NOT reference these
    varying = varying_facts(a_node)

    return Goal(
        entryA_state=entry_state,
        exitB_contract=exit_contract,
        invariants=invariants,
        varying_state=varying,
    )


# ---------- §3.13 merge ----------

def merge(
    graph: Graph,
    subgraph_nodes: dict[NodeId, Node],
    a_id: NodeId,
    b_id: NodeId,
    registry: Registry,
    etype: str,
    new_decls: list[FactDecl] | None = None,
) -> Graph | Reject:
    """§3.13 — Merge a subgraph between A and B into the graph.

    Returns the updated graph or a Reject with reason.
    """
    # 1. register_facts (auto-declare conventional-prefix facts: a good
    # excursion should not die over a missing declaration)
    reason = register_facts(registry, subgraph_nodes, new_decls, auto_declare=True)
    if reason:
        return Reject(reason)

    for nid in subgraph_nodes:
        if nid not in (a_id, b_id) and nid in graph.nodes:
            return Reject(
                f"Interior node id '{nid}' collides with an already accepted graph node. "
                "Rename this new node and update all choices that point to it."
            )

    # 2. Build candidate graph
    candidate = Graph(root=graph.root, nodes={})
    for nid, node in graph.nodes.items():
        candidate.nodes[nid] = copy.deepcopy(node)

    # Add interior nodes
    for nid, node in subgraph_nodes.items():
        if nid not in (a_id, b_id):
            candidate.nodes[nid] = copy.deepcopy(node)

    # Update A's choices from subgraph (the subgraph's version of A has the new connections)
    if a_id in subgraph_nodes:
        sub_a = subgraph_nodes[a_id]
        if etype == "LENGTH_EXTENDING":
            # Replace exactly ONE A→B edge; preserve A's other route — which may
            # itself be a same-target sibling edge to B (stat-write pair).
            preserved: list[Choice] = []
            removed_one = False
            for c in candidate.nodes[a_id].choices:
                if not removed_one and c.to == b_id:
                    removed_one = True
                    continue
                preserved.append(c)
            preserved_dests = {c.to for c in preserved}
            replacement = [
                c for c in sub_a.choices
                if c.to != b_id and c.to not in preserved_dests
            ]
            if not replacement:
                replacement = [
                    c for c in sub_a.choices
                    if c.to not in preserved_dests or c.to == b_id
                ]
            if not replacement:
                # No edge to splice A onto the new interior → A would keep only its
                # old route and the spliced subgraph would be orphaned. Reject cleanly.
                return Reject("Subgraph A has no usable replacement edge to splice onto the interior")
            candidate.nodes[a_id].choices = preserved + copy.deepcopy(replacement[:1])


    # B is an already validated boundary node. The expansion may route into it, but
    # must not rewrite its prose, state contract, ending, or outgoing choices.

    # 3. Check DAG (acyclicity)
    try:
        candidate.topo_order()
    except ValueError:
        return Reject("Subgraph introduces a cycle")

    # 4. Recompute guaranteed
    compute_guaranteed(candidate, registry)

    # 5. Seam check: entryA_state unchanged; exitB_contract satisfied
    b_node = candidate.nodes[b_id]
    if b_node.guaranteed:
        for req in candidate.nodes[b_id].requires:
            val = b_node.guaranteed.get(req.fact)
            if val is VARIES:
                return Reject(
                    f"Reconvergence issue at B ({b_id}): fact '{req.fact}' is VARIES "
                    f"but required to be {req.value}"
                )
            if val != req.value:
                return Reject(
                    f"Seam violation at B ({b_id}): fact '{req.fact}' is {val}, "
                    f"expected {req.value}"
                )

    # 6. Check invariants not flipped
    for nid, node in subgraph_nodes.items():
        for eff in node.produces:
            if eff.fact in registry and registry[eff.fact].invariant:
                if eff.value != registry[eff.fact].initial:
                    return Reject(
                        f"Node '{nid}' flips invariant fact '{eff.fact}' "
                        f"from {registry[eff.fact].initial} to {eff.value}"
                    )

    return candidate
