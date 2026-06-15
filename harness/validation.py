"""§3.14 — Validation: deterministic (hard) + semantic (soft)."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field

from .models import (
    VARIES, Feedback, Graph, Node, NodeId, Params, Registry, Violation,
)
from .guaranteed import apply_effects

_SEMANTIC_CACHE: dict[str, list[Violation]] = {}
_ALLOWED_KINDS = {"prologue", "scene", "bottleneck", "ending"}
FORK_RECONVERGE_MAX = int(os.environ.get("HARNESS_FORK_RECONVERGE_MAX", "2"))


# ---------- Per-node memory for DFS semantic validation ----------

@dataclass
class NodeMemory:
    ancestor_summaries: list[tuple[str, str]] = field(default_factory=list)
    ancestor_skeleton_beats: list[tuple[str, list[str]]] = field(default_factory=list)  # [(nid, [beat_texts])]
    established_facts: dict[str, str] = field(default_factory=dict)
    known_characters: set[str] = field(default_factory=set)
    last_exit_context: str = ""
    is_convergence: bool = False
    parent_count: int = 0


def _extract_characters_from_content(node: Node) -> set[str]:
    chars: set[str] = set()
    for source in (node.content, node.skeleton):
        for el in source:
            if not isinstance(el, dict):
                continue
            if el.get("type") == "dialogue" and el.get("speaker"):
                chars.add(el["speaker"])
            elif el.get("type") == "namecard" and el.get("name"):
                chars.add(el["name"])
            elif el.get("type") == "scene_header":
                for c in el.get("characters", []):
                    if c:
                        chars.add(c)
    return chars


def _skeleton_beat_texts(node: Node) -> list[str]:
    beat_texts = []
    for el in (node.skeleton or []):
        if not isinstance(el, dict):
            continue
        t = el.get("type", "")
        if t in ("scene_header", "namecard"):
            continue
        text = el.get("text", "") or el.get("line", "")
        if text:
            beat_texts.append(text)
    return beat_texts


def _post_memory(mem: NodeMemory, node: Node, registry: Registry) -> NodeMemory:
    new = NodeMemory(
        ancestor_summaries=list(mem.ancestor_summaries),
        ancestor_skeleton_beats=list(mem.ancestor_skeleton_beats),
        established_facts=dict(mem.established_facts),
        known_characters=set(mem.known_characters),
        last_exit_context=node.exit_context or "",
        is_convergence=False,
        parent_count=0,
    )
    summary = node.get_summary()
    if summary:
        new.ancestor_summaries.append((node.id, summary))
    beat_texts = _skeleton_beat_texts(node)
    if beat_texts:
        new.ancestor_skeleton_beats.append((node.id, beat_texts))
    for eff in node.produces:
        gloss = registry[eff.fact].gloss if eff.fact in registry else eff.fact
        new.established_facts[eff.fact] = gloss
    new.known_characters |= _extract_characters_from_content(node)
    return new


def _intersect_memories(memories: list[NodeMemory]) -> NodeMemory:
    if not memories:
        return NodeMemory()
    if len(memories) == 1:
        return NodeMemory(
            ancestor_summaries=list(memories[0].ancestor_summaries),
            ancestor_skeleton_beats=list(memories[0].ancestor_skeleton_beats),
            established_facts=dict(memories[0].established_facts),
            known_characters=set(memories[0].known_characters),
            last_exit_context=memories[0].last_exit_context,
            is_convergence=True,
            parent_count=1,
        )
    nid_sets = [set(nid for nid, _ in m.ancestor_summaries) for m in memories]
    common_nids = nid_sets[0]
    for s in nid_sets[1:]:
        common_nids &= s
    summaries = [(nid, summ) for nid, summ in memories[0].ancestor_summaries
                 if nid in common_nids]
    beats = [(nid, bts) for nid, bts in memories[0].ancestor_skeleton_beats
             if nid in common_nids]
    common_facts = set(memories[0].established_facts.keys())
    for m in memories[1:]:
        common_facts &= set(m.established_facts.keys())
    facts = {k: memories[0].established_facts[k] for k in common_facts}
    common_chars = set(memories[0].known_characters)
    for m in memories[1:]:
        common_chars &= m.known_characters

    return NodeMemory(
        ancestor_summaries=summaries,
        ancestor_skeleton_beats=beats,
        established_facts=facts,
        known_characters=common_chars,
        last_exit_context="",
        is_convergence=True,
        parent_count=len(memories),
    )


def compute_node_memories(
    graph: Graph, registry: Registry,
) -> dict[str, NodeMemory]:
    """Compute per-node reader memory in one topological pass. O(V+E)."""
    order = graph.topo_order()
    # post_mem[nid] = what the reader knows AFTER reading nid
    post_mem: dict[str, NodeMemory] = {}
    # entry_mem[nid] = what the reader knows BEFORE reading nid
    entry_mem: dict[str, NodeMemory] = {}

    for nid in order:
        node = graph.nodes[nid]
        preds = graph.predecessors(nid)

        if not preds:
            # Root: empty memory
            mem = NodeMemory()
        else:
            parent_posts = [post_mem[pid] for pid in preds if pid in post_mem]
            if len(parent_posts) <= 1:
                mem = NodeMemory(
                    ancestor_summaries=list(parent_posts[0].ancestor_summaries) if parent_posts else [],
                    ancestor_skeleton_beats=list(parent_posts[0].ancestor_skeleton_beats) if parent_posts else [],
                    established_facts=dict(parent_posts[0].established_facts) if parent_posts else {},
                    known_characters=set(parent_posts[0].known_characters) if parent_posts else set(),
                    last_exit_context=parent_posts[0].last_exit_context if parent_posts else "",
                    is_convergence=False,
                    parent_count=len(preds),
                )
            else:
                mem = _intersect_memories(parent_posts)

        entry_mem[nid] = mem
        post_mem[nid] = _post_memory(mem, node, registry)

    return entry_mem


_BANNED_Q_PATTERNS = ["如何应对", "如何回应", "怎么办", "你的选择是", "如何处理", "怎么应对"]


def validate_deterministic(
    graph: Graph,
    registry: Registry,
    region: list[NodeId] | None = None,
    *,
    require_content: bool = True,
    min_ending_count: int = 1,
) -> list[Violation]:
    """§3.14 deterministic — D1–D12 checks. Authoritative."""
    violations: list[Violation] = []
    nodes_to_check = region if region else list(graph.nodes.keys())

    for nid in nodes_to_check:
        if nid not in graph.nodes:
            continue
        node = graph.nodes[nid]
        g = node.guaranteed or {}

        if not require_content:
            violations.extend(_validate_skeleton_contract(node))
        elif require_content and not node.content:
            violations.append(Violation(
                node=nid, check="D9",
                problem="Node has no content elements",
                suggested_fix="Generate content for this node from the source text",
            ))
        elif require_content:
            violations.extend(_validate_node_output_contract(node))

        # D1: requires ⊆ guaranteed (by value)
        for req in node.requires:
            val = g.get(req.fact)
            if val is VARIES:
                violations.append(Violation(
                    node=nid, check="D4",
                    problem=f"Required fact '{req.fact}' is VARIES (paths disagree)",
                    suggested_fix=(
                        f"Remove '{req.fact}' from requires if it is only introduced in this node, "
                        f"or establish '{req.fact}' on every incoming path before '{nid}'"
                    ),
                ))
            elif val != req.value:
                violations.append(Violation(
                    node=nid, check="D1",
                    problem=f"Requires '{req.fact}'={req.value} but guaranteed={val}",
                    suggested_fix=(
                        f"Remove '{req.fact}' from requires if the node can introduce it locally, "
                        f"or establish '{req.fact}'={req.value} on all paths to '{nid}'"
                    ),
                ))

        # D2: choice.label_requires at choosing state
        if node.guaranteed is not None:
            choosing_state = apply_effects(g, node)
            for ci, choice in enumerate(node.choices):
                for req in choice.label_requires:
                    val = choosing_state.get(req.fact)
                    if val is VARIES:
                        violations.append(Violation(
                            node=nid, check="D2",
                            problem=(
                                f"Choice '{choice.label}' label_requires '{req.fact}' "
                                f"but it's VARIES at choosing time"
                            ),
                        ))
                    elif val != req.value:
                        violations.append(Violation(
                            node=nid, check="D2",
                            problem=(
                                f"Choice '{choice.label}' label_requires "
                                f"'{req.fact}'={req.value} but choosing_state={val}"
                            ),
                        ))

        # D3: entry_invariants
        for req in node.entry_invariants:
            val = g.get(req.fact)
            if val is VARIES:
                violations.append(Violation(
                    node=nid, check="D3",
                    problem=f"Entry invariant '{req.fact}' is VARIES",
                ))
            elif val != req.value:
                violations.append(Violation(
                    node=nid, check="D3",
                    problem=(
                        f"Entry invariant '{req.fact}'={req.value} violated, "
                        f"guaranteed={val}"
                    ),
                ))

        # D5: registry closure — every FactId must be registered
        all_facts = set()
        for eff in node.produces:
            all_facts.add(eff.fact)
        for req in node.requires:
            all_facts.add(req.fact)
        for req in node.entry_invariants:
            all_facts.add(req.fact)
        for choice in node.choices:
            for req in choice.label_requires:
                all_facts.add(req.fact)
            for eff in choice.state_delta:
                all_facts.add(eff.fact)
        for fid in all_facts:
            if fid not in registry:
                violations.append(Violation(
                    node=nid, check="D5",
                    problem=f"Fact '{fid}' not in registry",
                    suggested_fix=f"Register '{fid}' via register_facts",
                ))

        # D7: invariant facts not flipped (produces and per-choice state_delta)
        d7_effects = list(node.produces) + [
            eff for c in node.choices for eff in c.state_delta
        ]
        for eff in d7_effects:
            if eff.fact in registry and registry[eff.fact].invariant:
                if eff.value != registry[eff.fact].initial:
                    violations.append(Violation(
                        node=nid, check="D7",
                        problem=(
                            f"Flips invariant fact '{eff.fact}' from "
                            f"{registry[eff.fact].initial} to {eff.value}"
                        ),
                    ))

        # D9: schema — every playable node is binary; terminals have no choices.
        if node.ending == "NONE":
            if not node.question:
                violations.append(Violation(
                    node=nid, check="D9",
                    problem="Non-ending node missing 'question'",
                ))
            elif _cjk_len(node.question) > 30:
                violations.append(Violation(
                    node=nid, check="D9",
                    problem=f"Question is {_cjk_len(node.question)} Chinese chars; max is 30",
                    suggested_fix="Rewrite question to a concise protagonist dilemma ≤30 Chinese chars",
                ))
            # Binary mid-graph; a final fan-out node (every choice targets a
            # terminal node) may carry 3 choices for a 3-way ending split.
            all_terminal = bool(node.choices) and all(
                c.to in graph.nodes and graph.nodes[c.to].ending != "NONE"
                for c in node.choices
            )
            allowed_counts = (2, 3) if all_terminal else (2,)
            if len(node.choices) not in allowed_counts:
                violations.append(Violation(
                    node=nid, check="D9",
                    problem=(
                        f"Non-ending node has {len(node.choices)} choices "
                        "(must have exactly 2; 3 allowed only when every choice "
                        "targets an ENDING/DEAD_END node)"
                    ),
                ))
            targets = [c.to for c in node.choices]
            if len(targets) != len(set(targets)):
                # Same-target choices are legal ONLY when their state_delta differ:
                # the choice writes divergent state instead of forking the graph.
                delta_keys = [c.delta_key() for c in node.choices]
                if len(delta_keys) != len(set(delta_keys)):
                    violations.append(Violation(
                        node=nid, check="D9",
                        problem=(
                            "Non-ending node has multiple choices to the same target "
                            "with identical state_delta (pure flavor choice)"
                        ),
                        suggested_fix=(
                            "Either point the choices at different nodes, or give each "
                            "a different state_delta so the choice leaves a trace"
                        ),
                    ))
            for ci, choice in enumerate(node.choices):
                if _cjk_len(choice.label) > 8:
                    violations.append(Violation(
                        node=nid, check="D9",
                        problem=(
                            f"Choice {ci} label '{choice.label}' is "
                            f"{_cjk_len(choice.label)} Chinese chars; max is 8"
                        ),
                        suggested_fix="Rewrite the label as a short player action, not an outcome",
                    ))
                if len(choice.resolution) != 2:
                    violations.append(Violation(
                        node=nid, check="D9",
                        problem=(
                            f"Choice '{choice.label}' has {len(choice.resolution)} "
                            "resolution beats; must have exactly 2"
                        ),
                        suggested_fix="Add exactly 2 short resolution beats showing the choice outcome",
                    ))
            # D9: question blocklist — ban generic question patterns
            if node.question:
                for pat in _BANNED_Q_PATTERNS:
                    if pat in node.question:
                        violations.append(Violation(
                            node=nid, check="D9",
                            problem=f"Question uses generic pattern '{pat}'",
                            suggested_fix="Rewrite as character's inner dilemma, e.g. '救他还是追凶？'",
                        ))
                        break
            # CHOICE_DESIGN R6/R14 deterministic slice:
            # bare opt-out labels (retreat with no object/benefit) and
            # question lacking an explicit contrast structure.
            _OPT_OUT_BARE = {
                "冷眼退避", "退避", "转身离开", "离开", "不予理会", "不理",
                "旁观", "袖手旁观", "无视", "沉默", "默不作声", "走开",
                "置之不理", "避而不答", "退缩",
            }
            # Negative-framed attitude labels: read as capitulation / the loser
            # option even when mechanically balanced. A label must lead with an
            # action verb toward a named good, not name a posture of yielding.
            _NEGATIVE_ATTITUDE = (
                "吞声", "蛰伏", "隐忍", "忍气", "忍让", "认命", "作罢", "退让",
                "按兵不动", "委曲求全", "逆来顺受", "忍辱负重", "忍下", "咽下",
                "默默承受", "不动声色",
            )
            for ci, choice in enumerate(node.choices):
                if choice.label in _OPT_OUT_BARE:
                    violations.append(Violation(
                        node=nid, check="D9",
                        problem=(
                            f"Choice label '{choice.label}' is a bare opt-out "
                            "(retreat with no stated benefit) — no player picks it"
                        ),
                        suggested_fix=(
                            "Give the retreat a purchase: 退而保X / 忍辱套话 — "
                            "every option needs a visible gain (CHOICE_DESIGN R2/R6)"
                        ),
                    ))
                elif any(tok in choice.label for tok in _NEGATIVE_ATTITUDE):
                    violations.append(Violation(
                        node=nid, check="D9",
                        problem=(
                            f"Choice label '{choice.label}' is a negative-attitude "
                            "label (yielding/enduring) — reads as the loser option; "
                            "approach-avoidance, not competing goods"
                        ),
                        suggested_fix=(
                            "Name the POSITIVE good this option buys (情报/时机/盟友/"
                            "避免暴露) and lead with an action verb toward it, e.g. "
                            "吞声蛰伏 → 暗记仇敌探虚实 (CHOICE_DESIGN: two goods)"
                        ),
                    ))
            if node.question and "还是" not in node.question and "或" not in node.question:
                violations.append(Violation(
                    node=nid, check="D9",
                    problem="Question lacks an explicit contrast (还是/或) — stakes of both sides must be visible",
                    suggested_fix="Rewrite as 「为了A冒X的险，还是保B放弃Y？」compressed (CHOICE_DESIGN R7)",
                ))
            if len(node.choices) >= 2:
                lens = [_cjk_len(c.label) for c in node.choices]
                if max(lens) - min(lens) > 3:
                    violations.append(Violation(
                        node=nid, check="D9",
                        problem=f"Choice label lengths differ by {max(lens)-min(lens)} (>3) — parallel form required",
                        suggested_fix="Rewrite labels to parallel grammar and similar length (CHOICE_DESIGN R14)",
                    ))

            # D9: choice label prefix distinctness (pairwise; supports 3-way fans)
            labels = [c.label for c in node.choices]
            for i in range(len(labels)):
                for j in range(i + 1, len(labels)):
                    li, lj = labels[i], labels[j]
                    if li and lj and len(li) >= 2 and len(lj) >= 2 and li[:2] == lj[:2]:
                        violations.append(Violation(
                            node=nid, check="D9",
                            problem=f"Choice labels share prefix '{li[:2]}' — labels must use different verbs",
                            suggested_fix="Make each choice a distinct action",
                        ))
        else:
            if node.choices:
                violations.append(Violation(
                    node=nid, check="D9",
                    problem="Ending/dead-end node should have no choices",
                ))

        # D11 RETIRED: continuity is about PLOT, not coordinates. A scene cut
        # to a new location is normal film grammar; what must hold is causal/
        # temporal coherence, which the per-node semantic judge checks using
        # last_exit_context. Location diversity follows the source story.

    # D6: acyclicity (graph-wide)
    try:
        graph.topo_order()
    except ValueError:
        violations.append(Violation(
            node=graph.root, check="D6",
            problem="Graph contains a cycle",
        ))

    # D10: reachability
    if not region:
        reachable = set()
        stack = [graph.root]
        while stack:
            n = stack.pop()
            if n in reachable:
                continue
            reachable.add(n)
            if n in graph.nodes:
                for c in graph.nodes[n].choices:
                    if c.to in graph.nodes:
                        stack.append(c.to)

        for nid in graph.nodes:
            if nid not in reachable:
                violations.append(Violation(
                    node=nid, check="D10",
                    problem=f"Node '{nid}' not reachable from root",
                ))

        # Check every non-DEAD_END node can reach an ENDING
        for nid in graph.nodes:
            node = graph.nodes[nid]
            if node.ending != "NONE":
                continue
            # BFS forward to find an ENDING
            visited = set()
            queue = [nid]
            found_ending = False
            while queue:
                curr = queue.pop(0)
                if curr in visited:
                    continue
                visited.add(curr)
                if curr in graph.nodes and graph.nodes[curr].ending == "ENDING":
                    found_ending = True
                    break
                if curr in graph.nodes:
                    for c in graph.nodes[curr].choices:
                        queue.append(c.to)
            if not found_ending:
                violations.append(Violation(
                    node=nid, check="D10",
                    problem=f"No ENDING reachable from '{nid}'",
                ))

        # D12: minimum ENDING count
        ending_count = sum(1 for n in graph.nodes.values() if n.ending == "ENDING")
        if ending_count < min_ending_count:
            violations.append(Violation(
                node="(global)", check="D12",
                problem=f"Graph has {ending_count} ENDING node(s), need at least {min_ending_count}",
                suggested_fix=f"Add more ENDING nodes (ending=\"ENDING\") to reach minimum of {min_ending_count}",
            ))

        violations.extend(_validate_fork_reconvergence(graph))

    return violations


def _validate_fork_reconvergence(graph: Graph) -> list[Violation]:
    """D14: true forks must rejoin quickly.

    This is deliberately graph-wide and cumulative. If an expansion later
    lengthens an already accepted excursion, the full candidate graph fails here
    even when the local splice shape looks valid.
    """
    violations: list[Violation] = []

    def descendants_with_depth(start: NodeId, max_depth: int) -> dict[NodeId, int]:
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

    for nid, node in graph.nodes.items():
        targets = sorted({
            c.to for c in node.choices
            if c.to in graph.nodes and graph.nodes[c.to].ending == "NONE"
        })
        if len(targets) < 2:
            # Ending fan-outs and one-live-branch mediation forks are exempt.
            continue

        reach = {
            target: descendants_with_depth(target, FORK_RECONVERGE_MAX + 1)
            for target in targets
        }
        best_depth: int | None = None
        best_meet: NodeId | None = None
        for meet in set.intersection(*(set(r.keys()) for r in reach.values())):
            depth = max(reach[target][meet] for target in targets)
            if best_depth is None or depth < best_depth:
                best_depth = depth
                best_meet = meet

        if best_depth is None:
            violations.append(Violation(
                node=nid,
                check="D14",
                problem=(
                    f"Fork branches {targets} never reconverge within "
                    f"{FORK_RECONVERGE_MAX} node(s)"
                ),
                suggested_fix=(
                    "Route every live branch back to the same convergence node "
                    f"within {FORK_RECONVERGE_MAX} step(s), or make one branch a DEAD_END"
                ),
            ))
        elif best_depth > FORK_RECONVERGE_MAX:
            violations.append(Violation(
                node=nid,
                check="D14",
                problem=(
                    f"Fork branches {targets} reconverge at '{best_meet}' after "
                    f"{best_depth} node(s); max is {FORK_RECONVERGE_MAX}"
                ),
                suggested_fix=(
                    f"Shorten the detour so it reaches '{best_meet}' within "
                    f"{FORK_RECONVERGE_MAX} step(s)"
                ),
            ))

    return violations


def choice_quality_defects(choices, question: str | None = None) -> list[tuple[str, str]]:
    """Detect dominated / no-pull / method-framed choices (CHOICE_DESIGN gate).

    A good 2-way choice is competing goods: each option buys a distinct positive
    good and forfeits the other, so neither dominates. Returns (kind, detail) for:
    - 'no_pull': an option with no positive goal_impact — no good it buys.
    - 'dominated': one option weakly dominates the other on every goal_impact.
    - 'method_question': question is "how do you X?" — both options serve one goal
      (method variation), not competing goods.
    Empty list = passes the structural test.
    """
    defects: list[tuple[str, str]] = []
    if question and any(t in question for t in ("如何", "怎样", "怎么")):
        defects.append(("method_question",
                        f"question「{question}」是「如何/怎样」式方法问句——两个选项服务同一目标，"
                        "不是竞争性收益"))
    cs = list(choices or [])
    if len(cs) != 2:
        return defects
    impacts = [dict(getattr(c, "goal_impacts", None) or {}) for c in cs]
    for c, gi in zip(cs, impacts):
        if not any(v > 0 for v in gi.values()):
            defects.append(("no_pull",
                            f"选项「{c.label}」没有任何正向 goal_impact——没有它争取到的收获"))
    keys = set(impacts[0]) | set(impacts[1])
    if keys:
        a = {k: impacts[0].get(k, 0) for k in keys}
        b = {k: impacts[1].get(k, 0) for k in keys}

        def _dominates(x, y):
            return all(x[k] >= y[k] for k in keys) and any(x[k] > y[k] for k in keys)

        if _dominates(a, b):
            defects.append(("dominated",
                            f"选项「{cs[0].label}」在 goal_impacts 上弱支配「{cs[1].label}」"))
        elif _dominates(b, a):
            defects.append(("dominated",
                            f"选项「{cs[1].label}」在 goal_impacts 上弱支配「{cs[0].label}」"))
    return defects


def _cjk_len(text: str | None) -> int:
    """Count visible Chinese chars; fall back to non-space length for mixed text."""
    if not text:
        return 0
    cjk = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text)
    return len(cjk) if cjk else len(re.sub(r"\s+", "", text))


def _content_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def _validate_skeleton_contract(node: Node) -> list[Violation]:
    violations: list[Violation] = []
    content = [el for el in (node.skeleton or []) if isinstance(el, dict)]
    if not content:
        violations.append(Violation(
            node=node.id,
            check="D9",
            problem="Skeleton node missing skeleton beats",
            suggested_fix="Add 5+ skeleton beats covering core plot events",
        ))
        return violations
    if not any(el.get("type") == "scene_header" for el in content):
        violations.append(Violation(
            node=node.id,
            check="D9",
            problem="Skeleton has no scene_header",
            suggested_fix="Add a scene_header with location, time, and characters",
        ))
    min_beats = 3 if node.ending in ("ENDING", "DEAD_END") else 5
    if len(content) < min_beats:
        violations.append(Violation(
            node=node.id,
            check="D9",
            problem=f"Skeleton has {len(content)} beats; minimum is {min_beats}",
            suggested_fix="Add core action/dialogue/narration beats",
        ))
    # Beat-fact grounding: every produces entry with a beat ref must exist
    for eff in node.produces:
        if eff.beat:
            beat = node.get_beat_by_id(eff.beat)
            if beat is None:
                violations.append(Violation(
                    node=node.id,
                    check="D9",
                    problem=f"produces {eff.fact} references beat '{eff.beat}' but no skeleton beat has that id",
                    suggested_fix=f"Add id='{eff.beat}' to the skeleton beat that establishes {eff.fact}",
                ))
    duration = float(getattr(node, "planned_duration_min", 0) or 0)
    min_duration, max_duration = (0.5, 1.5) if node.ending == "DEAD_END" else (2.0, 5.0)
    if not (min_duration <= duration <= max_duration):
        violations.append(Violation(
            node=node.id,
            check="D9",
            problem=(
                f"planned_duration_min={getattr(node, 'planned_duration_min', None)} "
                f"out of range for ending={node.ending}"
            ),
            suggested_fix=(
                "Set planned_duration_min to 2-5 minutes for non-DEAD_END nodes, "
                "or 1-1.5 minutes for DEAD_END nodes"
            ),
        ))
    return violations


def _validate_node_output_contract(node: Node) -> list[Violation]:
    violations: list[Violation] = []
    content = [el for el in (node.content or []) if isinstance(el, dict)]

    if node.kind not in _ALLOWED_KINDS:
        violations.append(Violation(
            node=node.id, check="D9",
            problem=f"Node kind '{node.kind}' is invalid",
            suggested_fix='Use one of "prologue", "scene", "bottleneck", "ending"',
        ))
    if not (node.entry_context or "").strip():
        violations.append(Violation(
            node=node.id, check="D9",
            problem="Node missing entry_context WHERE/WHEN",
            suggested_fix="Set entry_context to the opening place and time",
        ))
    if not (node.exit_context or "").strip():
        violations.append(Violation(
            node=node.id, check="D9",
            problem="Node missing exit_context WHERE/WHEN",
            suggested_fix="Set exit_context to the ending place and time",
        ))

    # Content structure checks
    scene_headers = [el for el in content if el.get("type") == "scene_header"]
    if not scene_headers:
        violations.append(Violation(
            node=node.id, check="D9",
            problem="Content has no scene_header element",
            suggested_fix="Add a scene_header element with location, time, and characters",
        ))
    elif content[0].get("type") != "scene_header":
        violations.append(Violation(
            node=node.id, check="D9",
            problem="Content must start with a scene_header element",
            suggested_fix="Move the first scene_header element to the beginning of content",
        ))
    else:
        first_h = scene_headers[0]
        if not first_h.get("location", "").strip():
            violations.append(Violation(
                node=node.id, check="D9",
                problem="First scene_header missing location",
                suggested_fix="Set location on the first scene_header element",
            ))

    # Scene-count band: every node EXCEPT DEAD_END must have 3-5 场 (scene_headers).
    # DEAD_END scenes are intentionally short and exempt.
    if node.ending != "DEAD_END" and scene_headers:
        n_scenes = len(scene_headers)
        if n_scenes < 3 or n_scenes > 5:
            violations.append(Violation(
                node=node.id, check="D9",
                problem=f"Node has {n_scenes} 场 (scene_headers); must have 3-5",
                suggested_fix=(
                    "Split or merge scenes so the node has 3-5 scene_header elements, "
                    "each a distinct location/time cut, without inventing new plot events"
                ),
            ))

    # Content length check. These are lower bounds only; prose guidance asks for
    # richer scenes, but the deterministic gate should leave room for short beats.
    text_len = node.get_content_text_length()
    duration = float(getattr(node, "planned_duration_min", 0) or 0)
    if node.ending == "DEAD_END":
        min_len = max(120, int(duration * 150))
        if text_len < min_len:
            violations.append(Violation(
                node=node.id, check="D9",
                problem=f"Content text length is {text_len} chars; DEAD_END minimum is {min_len}",
                suggested_fix="Add more action/dialogue/narration elements for this dead-end scene",
            ))
    else:
        min_len = max(420, int(duration * 220))
        if text_len < min_len:
            violations.append(Violation(
                node=node.id, check="D9",
                problem=f"Content text length is {text_len} chars; minimum is {min_len}",
                suggested_fix="Add fuller scenery, action, dialogue, and narration while preserving the skeleton",
            ))

    # Terminal markers
    if node.ending == "DEAD_END" and content:
        last = content[-1]
        last_text = last.get("text", "") if isinstance(last, dict) else ""
        if "BE" not in last_text:
            violations.append(Violation(
                node=node.id, check="D9",
                problem='DEAD_END content must end with {"type":"action","text":"BE"}',
                suggested_fix='Add final element: {"type":"action","text":"BE"}',
            ))
    if node.ending == "ENDING" and content:
        last = content[-1]
        last_text = last.get("text", "") if isinstance(last, dict) else ""
        if "结局：" not in last_text:
            violations.append(Violation(
                node=node.id, check="D9",
                problem='ENDING content must end with {"type":"narration","text":"结局：结局名称"}',
                suggested_fix='Add final element with "结局：结局名称"',
            ))
    return violations


def validate_trunk_shape(graph: Graph, min_ending_count: int = 1) -> list[Violation]:
    """D13 trunk-shape check for the cornerstone phase.

    The trunk must be a convergent chain: prologue and every non-final
    bottleneck use a same-target choice pair (both choices to the next trunk
    node, different state_delta). Expansion later replaces one edge of a pair
    with an excursion, creating branch-and-bottleneck convergence for free.
    """
    violations: list[Violation] = []
    non_ending = [n for n in graph.nodes.values() if n.ending == "NONE"]
    k = len(non_ending)
    pair_nodes = []
    for node in non_ending:
        targets = [c.to for c in node.choices]
        if len(targets) == 2 and targets[0] == targets[1]:
            delta_keys = {c.delta_key() for c in node.choices}
            if len(delta_keys) == 2:
                pair_nodes.append(node.id)
    needed = max(1, k - 1)
    if len(pair_nodes) < needed:
        violations.append(Violation(
            node="(global)", check="D13",
            problem=(
                f"Trunk has {len(pair_nodes)} same-target choice pair(s); needs >= {needed} "
                f"(every non-final trunk node: BOTH choices to the same next node "
                f"with different state_delta)"
            ),
            suggested_fix=(
                "Rewire the trunk chain: prologue and each non-final bottleneck get "
                "2 choices to the SAME next trunk node with different state_delta; "
                "only the final bottleneck forks to different ENDING nodes"
            ),
        ))
    dead_ends = [n.id for n in graph.nodes.values() if n.ending == "DEAD_END"]
    if dead_ends:
        violations.append(Violation(
            node="(global)", check="D13",
            problem=f"Trunk stage must not contain DEAD_END nodes; found {dead_ends}",
            suggested_fix="Remove DEAD_END nodes from the trunk; dead ends belong to expansion",
        ))
    return violations


def validate(
    graph: Graph,
    registry: Registry,
    region: list[NodeId] | None = None,
    params: Params | None = None,
    *,
    require_content: bool = True,
) -> Feedback:
    """§3.14 — Run deterministic validation first; semantic only if det passes."""
    min_endings = params.min_ending_count if params else 1
    det_violations = validate_deterministic(
        graph, registry, region, require_content=require_content,
        min_ending_count=min_endings,
    )
    if det_violations:
        return Feedback(violations=det_violations)
    if params is None:
        return Feedback(violations=[])

    from .llm import validate_semantic

    cache_key = _semantic_cache_key(graph, region)
    if cache_key in _SEMANTIC_CACHE:
        return Feedback(violations=list(_SEMANTIC_CACHE[cache_key]))

    sem_violations = validate_semantic(graph, region, params)
    _SEMANTIC_CACHE[cache_key] = list(sem_violations)
    return Feedback(violations=sem_violations)


def _semantic_cache_key(graph: Graph, region: list[NodeId] | None) -> str:
    node_ids = region if region else sorted(graph.nodes)
    payload = {
        "validator": "semantic-v3-local-introduction",
        "root": graph.root,
        "region": list(node_ids),
        "nodes": {},
    }
    for nid in node_ids:
        if nid not in graph.nodes:
            continue
        node = graph.nodes[nid]
        payload["nodes"][nid] = {
            "kind": node.kind,
            "content": node.content,
            "chapters": list(node.chapters),
            "covers": list(node.covers),
            "produces": [{"fact": e.fact, "value": e.value} for e in node.produces],
            "requires": [{"fact": r.fact, "value": r.value} for r in node.requires],
            "entry_invariants": [
                {"fact": r.fact, "value": r.value} for r in node.entry_invariants
            ],
            "ending": node.ending,
            "question": node.question,
            "entry_context": node.entry_context,
            "exit_context": node.exit_context,
            "choices": [
                {
                    "label": c.label,
                    "to": c.to,
                    "resolution": list(c.resolution),
                    "label_requires": [
                        {"fact": r.fact, "value": r.value} for r in c.label_requires
                    ],
                }
                for c in node.choices
            ],
        }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
