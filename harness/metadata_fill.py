"""P2.5 — Dramatic-metadata backfill pass.

The creative structure calls reliably produce plot but unreliably produce
per-field dramatic metadata (charges, goal_impacts, beat roles): fields that
no validator blocks on decay under load. This pass gives metadata its own
single-responsibility call per node — tiny enum-constrained output, trivially
verifiable, parallel, idempotent (only fills what's missing/invalid).
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from .models import Graph, Node, Params

log = logging.getLogger(__name__)

_ARC_SLOTS = ["hook", "lock_in", "first_attempt", "midpoint", "complication",
              "main_culmination", "crisis", "crisis_finale", "climax", "resolution"]

_META_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string",
                  "description": "章节式标题，≤12字，吸引但不剧透，禁止与 question 相同或同义复述"},
        "value": {"type": "string",
                  "description": "价值轴：2-4字名词，有正负两极（生死/尊严/信任/自由/掌控/亲情…）。"
                                 "禁止剧情概括（如'绝境立威遭弃'是错误示例）"},
        "expectation": {"type": "string",
                        "description": "主角对本场结果的预期（一句话，McKee Gap 的一半）"},
        "result": {"type": "string",
                   "description": "实际发生的事——必须偏离预期（Gap 的另一半）"},
        "opening_charge": {"type": "string", "enum": ["+", "-"]},
        "closing_charge": {"type": "string", "enum": ["+", "-"]},
        "expectation": {"type": "string", "description": "主角对本场结果的预期（McKee Gap 的一半）"},
        "result": {"type": "string", "description": "实际发生的事——必须偏离预期（Gap 的另一半）"},
        "turning_type": {"type": "string", "enum": ["action", "revelation"]},
        "tension": {"type": "integer", "description": "1-5"},
        "arc_slot": {"type": "string", "enum": _ARC_SLOTS + [""]},
        "beat_roles": {
            "type": "array", "items": {"type": "string"},
            "description": "与骨架节拍一一对应的职能数组：buildup|payoff|surprise|decision_trigger|recap|preparation|aftermath。"
                           "非结局节点最后一个非空职能必须是 decision_trigger",
        },
        "choices": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "cost": {"type": "string"},
                    "goal_impacts": {"type": "object",
                                     "description": "整数 -1/0/+1，键必须取自给定的主角目标"},
                },
                "required": ["label", "goal_impacts"],
            },
        },
    },
    "required": ["title", "value", "opening_charge", "closing_charge", "expectation",
                 "result", "turning_type", "tension", "beat_roles", "choices"],
}


def _node_needs_fill(node: Node) -> bool:
    if not node.title:
        return True
    if node.ending != "NONE":
        return not (node.opening_charge and node.closing_charge and node.tension)
    missing_charges = not (node.opening_charge and node.closing_charge
                           and node.opening_charge != node.closing_charge)
    missing_impacts = any(not c.goal_impacts for c in node.choices)
    missing_roles = not any(
        isinstance(el, dict) and el.get("role") for el in node.skeleton
    )
    missing_gap = not (node.expectation and node.result)
    missing_turning = not (node.turning_type and node.turning_type in ("action", "revelation"))
    return (missing_charges or missing_impacts or missing_roles
            or missing_gap or missing_turning or not node.tension)


def _fill_one(node: Node, goals: list[dict], params: Params,
              prev_charges: list[str] | None = None) -> dict | None:
    from .llm import _call_json

    beats = [
        {"i": i, "type": el.get("type"), "text": (el.get("text") or el.get("line") or "")[:80]}
        for i, el in enumerate(node.skeleton) if isinstance(el, dict)
    ]
    system = f"""你是剧作元数据标注员。给定一个剧情节点的骨架与选择，输出它的戏剧元数据。
不创作新剧情，只判断已有内容。

规则：
- title：章节式标题（≤12字），概括本场戏剧核心，不得照搬或复述 question。
- value：**价值轴名词**（2-4字，有正负两极：生死/尊严/信任/自由/掌控…），charges 是主角在此轴上的位置；不是剧情概括。
- expectation/result：主角预期 vs 实际发生（必须偏离——这是场景的 Gap）。
- opening_charge/closing_charge：本场开/收时主角处境的价值极性，必须不同（场要翻转）。
- 节奏交替：若给出了"前节点收尾极性"，本场收尾尽量与其交替（连续三场同极性=单调）。
- turning_type：翻转靠行动(action)还是靠揭示(revelation)。非结尾节点必须是"action"或"revelation"（不能留空）。
- tension：1-5，爽点/危机峰值为4-5。
- beat_roles：与骨架节拍数组一一对应（含scene_header，可填""）。非结局节点
  最后一个有内容的节拍标 decision_trigger（逼出选择问题的事件）；爽点标 payoff。
- choices[].goal_impacts：对下列主角目标的影响，整数 -1/0/+1，省略0项；
  真两难=每个选项至少对一个目标为负。键只能取自目标列表。
- choices[].cost：此选项不可逆的代价（一句话，已有则保留原文）。

主角目标：{json.dumps([g.get('id') for g in goals], ensure_ascii=False)}

只返回 JSON。"""
    user = json.dumps({
        "node_id": node.id,
        "ending": node.ending,
        "前节点收尾极性": prev_charges or [],
        "summary": node.get_summary()[:400],
        "beats": beats,
        "question": node.question,
        "choices": [{"label": c.label, "resolution": c.resolution, "cost": c.cost}
                    for c in node.choices],
    }, ensure_ascii=False, indent=1)

    try:
        return _call_json(
            system, user, params, context=f"metadata_fill_{node.id}",
            schema=_META_SCHEMA, reasoning_effort="none", cacheable=True,
        )
    except Exception:
        log.exception("metadata fill failed for %s (non-fatal)", node.id)
        return None


def _apply(node: Node, data: dict, goal_ids: set[str]) -> None:
    from .web_export import _normalize_title_text
    title = str(data.get("title", "") or "").strip()
    # Reject a title that repeats the question under the SAME normalization the
    # export validator uses — otherwise a near-match (differing only by punctuation)
    # passes here but aborts the whole export later.
    if (title and not node.title
            and _normalize_title_text(title) != _normalize_title_text(node.question or "")):
        node.title = title[:14]
    oc, cc = data.get("opening_charge", ""), data.get("closing_charge", "")
    if oc in ("+", "-") and cc in ("+", "-"):
        node.opening_charge, node.closing_charge = oc, cc
    if data.get("turning_type") in ("action", "revelation"):
        node.turning_type = data["turning_type"]
    try:
        t = int(data.get("tension", 0))
        if 1 <= t <= 5:
            node.tension = t
    except (TypeError, ValueError):
        pass
    val = str(data.get("value", "") or "").strip()
    if val and len(val) <= 6:  # axis noun, not a plot summary
        node.value = val
    if data.get("expectation"):
        node.expectation = str(data["expectation"])[:60]
    if data.get("result"):
        node.result = str(data["result"])[:60]
    if data.get("arc_slot") in _ARC_SLOTS and not node.arc_slot:
        node.arc_slot = data["arc_slot"]

    roles = data.get("beat_roles") or []
    skel = [el for el in node.skeleton if isinstance(el, dict)]
    if roles and abs(len(roles) - len(skel)) <= 2:
        for el, role in zip(skel, roles):
            if role in ("buildup", "payoff", "surprise", "decision_trigger",
                        "recap", "preparation", "aftermath"):
                el["role"] = role

    by_label = {c.get("label", ""): c for c in data.get("choices", [])}
    for choice in node.choices:
        cd = by_label.get(choice.label)
        if not cd:
            continue
        impacts = {}
        for k, v in (cd.get("goal_impacts") or {}).items():
            if k in goal_ids:
                try:
                    f = float(v)
                except (TypeError, ValueError):
                    continue
                if f > 0:
                    impacts[k] = 1
                elif f < 0:
                    impacts[k] = -1
        if impacts and not choice.goal_impacts:
            choice.goal_impacts = impacts
        if cd.get("cost") and not choice.cost:
            choice.cost = str(cd["cost"])[:60]


def backfill_dramatic_metadata(
    graph: Graph, bible: dict, params: Params, max_workers: int = 4,
) -> int:
    """Fill missing dramatic metadata on all nodes. Idempotent, non-fatal.
    Returns the number of nodes updated."""
    goals = bible.get("protagonist_goals", []) or []
    goal_ids = {g.get("id") for g in goals if g.get("id")}
    todo = [n for n in graph.nodes.values() if _node_needs_fill(n)]
    if not todo:
        return 0
    log.info("=== P2.5: Dramatic-metadata backfill (%d nodes) ===", len(todo))
    updated = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for n in todo:
            prev = [graph.nodes[p].closing_charge
                    for p in graph.predecessors(n.id)
                    if graph.nodes[p].closing_charge]
            futures[pool.submit(_fill_one, n, goals, params, prev)] = n
        for f in as_completed(futures):
            node = futures[f]
            data = f.result()
            if data:
                _apply(node, data, goal_ids)
                updated += 1
                log.info("  %s: metadata filled (%s→%s T=%s roles=%s impacts=%s)",
                         node.id, node.opening_charge, node.closing_charge,
                         node.tension,
                         sum(1 for el in node.skeleton
                             if isinstance(el, dict) and el.get("role")),
                         sum(1 for c in node.choices if c.goal_impacts))
    return updated
