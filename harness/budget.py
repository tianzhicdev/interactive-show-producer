"""§3.6 — Budget computations: estimate_minutes, shortest_playthrough, total_minutes."""

import math
from .models import Graph, Node, NodeId, Params


def estimate_minutes(node: Node, params: Params) -> float:
    """Word-count proxy for node duration.

    Thin skeleton content is not final runtime prose, so it uses the structural
    placeholder until Phase 4 expands it.
    """
    text = node.get_prose() or ""
    if not text or _looks_like_thin_content(node):
        # Thin (skeleton-only) node: estimate FINISHED minutes. Measured on
        # run_20260611_164014: prose+avg-aftermath ≈ 7.6× skeleton chars
        # (median over 19 nodes). Budgeting planned_duration alone ran 2×
        # under; take the max of declared duration and the measured model.
        import re as _re
        skeleton_chars = len(_re.sub(
            r"\s+", "",
            "".join((el.get("text", "") or "") + (el.get("line", "") or "")
                    for el in (node.skeleton or []) if isinstance(el, dict)),
        ))
        measured = skeleton_chars * 7.5 / max(1.0, params.words_per_min)
        declared = float(getattr(node, "planned_duration_min", 2.0) or 2.0)
        return max(0.5, declared, measured)

    def _cjk_chars(t: str) -> int:
        n = 0
        for ch in t:
            if '\u4e00' <= ch <= '\u9fff':
                n += 1
            elif ch == ' ':
                n += 1  # rough word boundary
        return n

    char_count = _cjk_chars(text)
    # W3: a player sees exactly ONE aftermath \u2014 count the average branch
    aftermath_chars = [
        _cjk_chars("".join(
            (el.get("text", "") or "") + (el.get("line", "") or "")
            for el in c.aftermath if isinstance(el, dict)
        ))
        for c in node.choices if c.aftermath
    ]
    if aftermath_chars:
        char_count += sum(aftermath_chars) // len(aftermath_chars)
    # Chinese reads ~300 chars/min
    return max(0.5, char_count / params.words_per_min)


def _looks_like_thin_content(node: Node) -> bool:
    source = node.content if node.content else node.skeleton
    content = [el for el in (source or []) if isinstance(el, dict)]
    if not content:
        return False
    text_len = sum(
        len((el.get("text", "") or "") + (el.get("line", "") or ""))
        for el in content
    )
    return len(content) <= 10 and text_len < 500


def shortest_playthrough(graph: Graph, params: Params) -> float:
    """Min node-minute sum over all root→ENDING paths. DEAD_END excluded."""
    order = graph.topo_order()

    # dist[nid] = minimum total minutes from root to nid
    dist: dict[NodeId, float] = {}
    dist[graph.root] = estimate_minutes(graph.nodes[graph.root], params)

    for nid in order:
        if nid not in dist:
            continue
        node = graph.nodes[nid]
        for choice in node.choices:
            dest = choice.to
            if dest not in graph.nodes:
                continue
            dest_min = estimate_minutes(graph.nodes[dest], params)
            new_dist = dist[nid] + dest_min
            if dest not in dist or new_dist < dist[dest]:
                dist[dest] = new_dist

    # Find minimum over all ENDING nodes
    min_path = math.inf
    for nid, node in graph.nodes.items():
        if node.ending == "ENDING" and nid in dist:
            min_path = min(min_path, dist[nid])

    return min_path if min_path != math.inf else 0.0


def total_minutes(graph: Graph, params: Params) -> float:
    """Sum of all node minutes across the entire graph."""
    return sum(estimate_minutes(n, params) for n in graph.nodes.values())
