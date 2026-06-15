"""Deterministic fake LLM backend — full-pipeline smoke tests in seconds.

`--model fake` routes every LLM call here. Responses are schema-valid,
deterministic, and structurally correct (trunk chain with same-target pairs,
reconverging excursions, prose long enough to pass D9 length floors), so the
whole pipeline — guaranteed-state lattice, D-checks, merge, metrics, export —
runs end-to-end with zero network. It validates MECHANICS, not creativity.
"""

from __future__ import annotations

import json
import re


def _detect(json_schema: dict | None) -> str:
    props = (json_schema or {}).get("properties", {})
    if "sequences" in props and "main_dramatic_question" in props:
        return "outline"
    if "beat_roles" in props:
        return "metadata_fill"
    if "root" in props:
        return "cornerstone"
    if "nodes" in props:
        return "subgraph"
    if "highlights" in props:
        return "highlights"
    if "world" in props or "facts" in props:
        return "bible"
    if "violations" in props:
        return "violations"
    if "content" in props:
        return "prose"
    if "question" in props:
        return "node_fix"
    return "unknown"


def _chapter_bounds(system: str, user: str) -> tuple[int, int]:
    m = re.search(r"bounds are (\d+)-(\d+)", system) or \
        re.search(r"chapters?:?\s*(\d+)-(\d+)", user, re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    return 1, 1

_LOC = "废弃营地"
_CTX = f"{_LOC}·夜"

_PAD = "夜风掠过营地，火光在断壁间摇晃，人影被拉得很长，刀锋上凝着一点寒星。"


def _skeleton(nid: str, n_beats: int = 5) -> list[dict]:
    els: list[dict] = [{
        "type": "scene_header", "location": _LOC, "time": "夜",
        "characters": ["主角", "对手"], "id": "b0",
    }]
    for i in range(1, n_beats):
        els.append({"type": "action", "text": f"{nid}节拍{i}：{_PAD}", "id": f"b{i}"})
    return els


def _prose_elements(min_chars: int = 1200, n_scenes: int = 3) -> list[dict]:
    # covers 5min*220 floor; n_scenes satisfies the 3-5 场 (scene_header) gate
    def _header(idx: int) -> dict:
        return {"type": "scene_header", "location": f"{_LOC}{idx}", "time": "夜",
                "characters": ["主角", "对手"]}
    els: list[dict] = [_header(1)]
    seg = max(1, min_chars // n_scenes)
    total = 0
    i = 0
    next_scene = 2
    while total < min_chars:
        i += 1
        # Cut to a new 场 each segment until we have n_scenes headers.
        if next_scene <= n_scenes and total >= seg * (next_scene - 1):
            els.append(_header(next_scene))
            next_scene += 1
        text = f"第{i}拍：{_PAD}{_PAD}"
        els.append({"type": "action", "text": text})
        total += len(text)
    els.append({"type": "dialogue", "speaker": "主角", "line": "就在今夜，一了百了。",
                "emotion": "压低声音"})
    return els


def _node(nid: str, kind: str, chapters: tuple[int, int], *,
          ending: str = "NONE", question: str | None = None,
          choices: list[dict] | None = None, duration: float = 2.5,
          sequence: str = "", arc_slot: str = "", tension: int = 3,
          charges: tuple[str, str] = ("-", "+")) -> dict:
    return {
        "id": nid, "kind": kind, "planned_duration_min": duration,
        "chapters": list(chapters), "covers": [],
        "skeleton": _skeleton(nid),
        "content": _skeleton(nid),  # thin content mirrors the skeleton
        "entry_context": _CTX, "exit_context": _CTX,
        "produces": [], "requires": [], "entry_invariants": [],
        "ending": ending, "question": question, "choices": choices or [],
        "sequence": sequence, "arc_slot": arc_slot, "tension": tension,
        "value": "生死", "opening_charge": charges[0], "closing_charge": charges[1],
        "turning_type": "action",
        "expectation": f"{nid}：以为能平稳过关", "result": f"{nid}：局势骤变",
    }


def _pair(to: str, fa: str, fb: str) -> list[dict]:
    return [
        {"label": "舍身相护", "to": to, "resolution": ["挡在身前", "硬接一击"],
         "state_delta": [{"fact": fa, "value": True}],
         "cost": "暴露身手，被记恨",
         "goal_impacts": {"守护家人": 1, "隐藏秘密": -1}},
        {"label": "夺信取证", "to": to, "resolution": ["抢下密信", "记下罪证"],
         "state_delta": [{"fact": fb, "value": True}],
         "cost": "放走对手，亲人受辱",
         "goal_impacts": {"守护家人": -1, "查明真相": 1}},
    ]


def _outline(system: str, user: str) -> dict:
    lo, hi = _chapter_bounds(system, user)
    mid = (lo + hi) // 2 or lo
    seqs = [
        ("A", "hook", [0.0, 0.15], "她能否在第一鞭下立住？", lo, lo),
        ("B", "lock_in", [0.15, 0.4], "把柄在手，敢不敢用？", lo, mid),
        ("C", "main_culmination", [0.4, 0.8], "真相揭开后还回得了头吗？", mid, hi),
        ("D", "crisis_finale", [0.8, 1.0], "最后一战：玉碎还是瓦全？", hi, hi),
    ]
    return {
        "main_dramatic_question": "主角能否带全家活着走完流放路并翻案？",
        "sequences": [
            {"id": sid, "function": fn, "span_pct": span,
             "dramatic_question": q, "bottleneck_gloss": f"{sid}段汇合点：{q}",
             "satisfaction_beats": [f"h{i + 1:03d}"],
             "chapters": [c0, c1]}
            for i, (sid, fn, span, q, c0, c1) in enumerate(seqs)
        ],
        "ledger": [
            {"id": "q.main", "kind": "question", "gloss": "全片主问题",
             "plant_sequence": "A", "close_sequence": "D",
             "fact_id": "world.fake_q_main"},
            {"id": "setup.blade", "kind": "setup", "gloss": "藏起的短刃",
             "plant_sequence": "A", "close_sequence": "C",
             "fact_id": "world.fake_blade_planted"},
            {"id": "irony.identity", "kind": "irony", "gloss": "观众先知的身份",
             "plant_sequence": "B", "close_sequence": "C",
             "fact_id": "world.fake_irony_identity"},
            {"id": "dangling.threat", "kind": "dangling_cause", "gloss": "灭门威胁",
             "plant_sequence": "B", "close_sequence": "D",
             "fact_id": "world.fake_threat_planted"},
        ],
        "player_stats": [
            {"id": "player.fake_bold", "gloss": "勇烈", "low_effect": "谨慎线",
             "high_effect": "刚烈线"},
            {"id": "player.fake_wary", "gloss": "隐忍", "low_effect": "直来直往",
             "high_effect": "步步为营"},
        ],
    }


def _cornerstone(system: str, user: str) -> dict:
    lo, hi = _chapter_bounds(system, user)
    mid = (lo + hi) // 2 or lo
    facts = [
        ("player.fake_bold", "勇烈倾向"), ("player.fake_wary", "隐忍倾向"),
        ("player.fake_open", "坦诚倾向"), ("player.fake_guard", "戒备倾向"),
    ]
    nodes = {
        "n1": _node("n1", "prologue", (lo, lo), question="挡下鞭子还是记下罪证？",
                    choices=_pair("t1", "player.fake_bold", "player.fake_wary"),
                    duration=3.0, sequence="A", arc_slot="hook",
                    tension=3, charges=("-", "+")),
        "t1": _node("t1", "bottleneck", (lo, mid), question="坦白底牌还是独自承担？",
                    choices=_pair("t2", "player.fake_open", "player.fake_guard"),
                    duration=3.0, sequence="B", arc_slot="lock_in",
                    tension=4, charges=("+", "-")),
        "t2": _node("t2", "bottleneck", (mid, hi), question="死战到底还是以财赎命？",
                    choices=[
                        {"label": "死战到底", "to": "e1",
                         "resolution": ["拔刀迎敌", "血战城头"], "state_delta": [],
                         "cost": "可能全军覆没",
                         "goal_impacts": {"查明真相": 1, "守护家人": -1}},
                        {"label": "以财赎命", "to": "e2",
                         "resolution": ["散尽千金", "远走他乡"], "state_delta": [],
                         "cost": "正义沉没，仇人逍遥",
                         "goal_impacts": {"守护家人": 1, "查明真相": -1}},
                    ], duration=3.5, sequence="C", arc_slot="crisis",
                    tension=5, charges=("-", "+")),
        "e1": _node("e1", "ending", (hi, hi), ending="ENDING", duration=2.5,
                    sequence="D", arc_slot="resolution", tension=4,
                    charges=("-", "+")),
        "e2": _node("e2", "ending", (hi, hi), ending="ENDING", duration=2.5,
                    sequence="D", arc_slot="resolution", tension=3,
                    charges=("-", "+")),
    }
    return {
        "root": "n1",
        "new_facts": [
            {"id": fid, "kind": "disposition", "gloss": gloss,
             "initial": False, "invariant": False}
            for fid, gloss in facts
        ],
        "nodes": nodes,
    }


def _subgraph(system: str, user: str) -> dict:
    ma = re.search(r"Endpoint A: (\S+)", system)
    mb = re.search(r"Endpoint B: (\S+)", system)
    a_id = ma.group(1) if ma else "a"
    b_id = mb.group(1) if mb else "b"
    lo, hi = _chapter_bounds(system, user)
    x_id = f"x_{a_id}_{b_id}"[:48]
    fa, fb = f"player.fake_{x_id}_l"[:60], f"player.fake_{x_id}_r"[:60]

    a_node = _node(a_id, "scene", (lo, hi), question="只能选一边——救人还是追凶？",
                   choices=[{"label": "转身救人", "to": x_id,
                             "resolution": ["折返回身", "扑向火场"], "state_delta": []}])
    interior = _node(x_id, "scene", (lo, hi), question="火场中央——硬闯还是绕行？",
                     choices=[
                         {"label": "硬闯火线", "to": b_id,
                          "resolution": ["冲入烈焰", "带伤而出"],
                          "state_delta": [{"fact": fa, "value": True}]},
                         {"label": "绕行后巷", "to": b_id,
                          "resolution": ["贴墙疾行", "错失一步"],
                          "state_delta": [{"fact": fb, "value": True}]},
                     ])
    b_stub = _node(b_id, "scene", (lo, hi), question="占位？",
                   choices=[])  # B is an immutable boundary; merge ignores it
    return {
        "nodes": {a_id: a_node, x_id: interior, b_id: b_stub},
        "new_facts": [
            {"id": fa, "kind": "disposition", "gloss": f"{x_id}左径",
             "initial": False, "invariant": False},
            {"id": fb, "kind": "disposition", "gloss": f"{x_id}右径",
             "initial": False, "invariant": False},
        ],
    }


def _bible(system: str, user: str) -> dict:
    lo, hi = _chapter_bounds(system, user)
    chars = [
        {"name": "主角", "role": "protagonist", "description": "身负秘密的流放者"},
        {"name": "对手", "role": "antagonist", "description": "押送官"},
        {"name": "盟友", "role": "ally", "description": "暗中相助的旧识"},
    ]
    facts = [
        {"id": f"world.fake_{key}", "kind": kind, "gloss": gloss,
         "initial": False, "invariant": False}
        for key, kind, gloss in [
            ("secret", "knowledge", "主角身怀随身空间"),
            ("exile", "event", "全家被流放边地"),
            ("plot", "knowledge", "权臣暗中谋反"),
            ("blade", "possession", "主角藏有短刃"),
            ("debt", "relation", "盟友欠主角一命"),
        ]
    ]
    return {
        "world": "架空王朝，权谋与流放交织的边地。",
        "setting": f"覆盖章节{lo}-{hi}的测试设定。",
        "characters": chars,
        "default_license": [],
        "facts": facts,
        "protagonist_goals": [
            {"id": "守护家人", "gloss": "保住流放路上的家人"},
            {"id": "查明真相", "gloss": "查清构陷真相"},
            {"id": "隐藏秘密", "gloss": "不暴露随身空间"},
        ],
    }


def _highlights(system: str, user: str) -> dict:
    lo, hi = _chapter_bounds(system, user)
    return {"highlights": [
        {"id": f"h{i + 1:03d}", "chapter": max(lo, min(hi, lo + i)),
         "weight": round(0.9 - i * 0.1, 2),
         "gloss": f"高光{i + 1}：当众反杀立威，旁观者哗然"}
        for i in range(5)
    ]}


def fake_response(system: str, user: str, json_schema: dict | None) -> str:
    kind = _detect(json_schema)
    if kind == "outline":
        data = _outline(system, user)
        return json.dumps(data, ensure_ascii=False)
    if kind == "metadata_fill":
        try:
            req = json.loads(user)
        except Exception:
            req = {}
        n_beats = len(req.get("beats", []))
        roles = [""] + ["buildup"] * max(0, n_beats - 2)
        if req.get("ending", "NONE") == "NONE" and n_beats >= 2:
            roles.append("decision_trigger")
        elif n_beats >= 2:
            roles.append("aftermath")
        data = {
            "title": f"试炼·{req.get('node_id', 'X')}"[:12],
            "value": "生死", "opening_charge": "-", "closing_charge": "+",
            "turning_type": "action", "tension": 4, "arc_slot": "",
            "beat_roles": roles[:n_beats],
            "choices": [
                {"label": c.get("label", ""), "cost": c.get("cost") or "代价沉重",
                 "goal_impacts": {"守护家人": 1, "查明真相": -1} if i == 0
                                 else {"守护家人": -1, "查明真相": 1}}
                for i, c in enumerate(req.get("choices", []))
            ],
        }
        return json.dumps(data, ensure_ascii=False)
    if kind == "cornerstone":
        data = _cornerstone(system, user)
    elif kind == "subgraph":
        data = _subgraph(system, user)
    elif kind == "bible":
        data = _bible(system, user)
    elif kind == "highlights":
        data = _highlights(system, user)
    elif kind == "violations":
        data = {"violations": []}
    elif kind == "prose":
        labels = re.findall(r'"label":\s*"([^"]{1,16})"', user)
        # Respect the computed first-appearance contract (W4)
        m_first = re.search(r"首次出场（必须加 namecard 并自然引入）: (\[[^\]]*\])", user)
        first_chars = []
        if m_first:
            try:
                first_chars = json.loads(m_first.group(1))
            except Exception:
                first_chars = []
        # Aftermath filler must NOT share bigrams with _PAD (prose filler) —
        # the overlap check would false-positive on identical padding.
        aftermaths = [
            {"label": lb, "elements": [
                {"type": "action", "text": f"选择{lb}之后，尘埃缓缓落定，回声远去。"},
                {"type": "dialogue", "speaker": "主角", "line": "就这么办。", "emotion": "低声"},
                {"type": "action", "text": f"代价与收获皆已写入命运的账册（{lb}）。"},
            ]}
            for lb in dict.fromkeys(labels)
        ]
        content = _prose_elements()
        for ch in first_chars:
            content.insert(1, {"type": "namecard", "name": ch, "title": "测试身份"})
        data = {"content": content, "aftermaths": aftermaths}
    elif kind == "node_fix":
        data = {"fixed_summary": "出场：主角。事件：(1) 修正后的冲突 (2) 反转逼出抉择。",
                "question": "硬闯还是绕行？"}
    else:
        data = {}
    return json.dumps(data, ensure_ascii=False)
