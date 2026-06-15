#!/usr/bin/env python3
"""Fix fake choices in state.json: add choice_question + rewrite outcome-style edge labels.

Usage:
    python fix_fake_choices.py <project_dir>

Reads:  <project_dir>/state.json
Writes: <project_dir>/state.json  (in-place)
        <project_dir>/preview.md  (regenerated)
"""

import json
import sys
from pathlib import Path


# ── Choice questions for every branching node ──────────────────────

CHOICE_QUESTIONS = {
    "EP01":  "替嫁初夜，苏锦该何去何从？",
    "EP02":  "面对战王的试探，苏锦该如何回应？",
    "EP03":  "苏锦该如何调查替嫁真相？",
    "EP04":  "面对公开羞辱，苏锦该如何应对？",
    "EP05":  "手握证据，苏锦该如何出手？",
    "EP06":  "下一步该稳扎稳打还是主动出击？",
    "EP07":  "面对太后势力，苏锦该靠谁？",
    "EP08":  "如何对付太后的密谋？",
    "EP09":  "苏锦的终局之路是什么？",
    "EP01A": "守卫逼近，苏锦该怎么办？",
    "EP04A": "暗中追查时，该谨慎还是冒进？",
    "EP04B": "争执升级，苏锦如何收场？",
    "EP05A": "如何让战王相信这份证据？",
    "EP07A": "深入虎穴后，该进还是该退？",
    "EP08A": "如何策反太后心腹？",
    "EP02A": "战王起疑，苏锦如何化解？",
    "EP03A": "调查暴露后，苏锦该如何应对？",
    "EP04C": "被发现后，如何利用这个局面？",
}

# ── Edge label rewrites (keyed by edge ID) ─────────────────────────

EDGE_LABEL_REWRITES = {
    # EP02 forks
    "e02":    "以柔克刚",       # was: 沉着应对
    "e02_de": "主动试探",       # was: 露出破绽

    # EP03 forks
    # "e03": keep "暗中查探"
    "e03_de": "公开追问",       # was: 调查失败

    # EP06 forks
    "e06":    "步步为营",       # was: 继续调查
    "e06_de": "先发制人",       # was: 贸然出手

    # EP01A forks
    "e01a_back": "放弃挣扎",   # was: 被抓回
    "e01a_de":   "拼死翻墙",   # was: 翻墙出逃

    # EP04A forks
    "e04a_05": "谨慎跟踪",     # was: 拿到证据
    "e04a_de": "冒险潜入",     # was: 行踪暴露

    # EP04B forks
    "e04b_05": "以理服人",     # was: 抓住破绽
    "e04b_de": "以势压人",     # was: 落入圈套

    # EP05A forks
    "e05a_06": "坦诚相告",     # was: 战王信任
    "e05a_de": "暗示引导",     # was: 反遭怀疑

    # EP07A forks
    "e07a_08": "见好就收",     # was: 全身而退
    "e07a_de": "深入核心",     # was: 陷入重围

    # EP08A forks
    "e08a_09": "利益拉拢",     # was: 策反成功
    "e08a_de": "威逼施压",     # was: 策反败露

    # EP02A forks
    "e02a_03":   "巧言化解",   # was: (empty)
    "e02a_de05": "矢口否认",   # was: 无法自圆

    # EP03A forks
    "e03a_04":   "转守为攻",   # was: 正面应对
    "e03a_de06": "据守不出",   # was: 两面受敌

    # EP04C forks
    "e04c_05":   "设局反套",   # was: 反转成功
    "e04c_de08": "强行取证",   # was: 计策失败
}


def fix_state(state: dict) -> tuple[int, int]:
    """Apply choice_question and edge label fixes. Returns (questions_added, labels_rewritten)."""
    spine = state["spine"]
    nodes = spine["nodes"]
    edges = spine["edges"]

    # 1. Add choice_question to branching nodes
    questions_added = 0
    for node in nodes:
        nid = node["id"]
        if nid in CHOICE_QUESTIONS:
            node["choice_question"] = CHOICE_QUESTIONS[nid]
            questions_added += 1

    # 2. Rewrite fake-choice edge labels
    labels_rewritten = 0
    for edge in edges:
        eid = edge["id"]
        if eid in EDGE_LABEL_REWRITES:
            old = edge["label"]
            new = EDGE_LABEL_REWRITES[eid]
            edge["label"] = new
            labels_rewritten += 1
            print(f"  {eid}: '{old}' → '{new}'")

    return questions_added, labels_rewritten


def generate_preview(state: dict) -> str:
    """Generate preview.md content from state dict."""
    bible = state.get("bible", {})
    registry = state.get("registry", {})
    spine = state.get("spine", {})
    nodes = spine.get("nodes", [])
    edges = spine.get("edges", [])

    lines = [
        f"# Preview: {bible.get('title', 'Untitled')}\n",
        f"**Genre**: {bible.get('genre', '')} | **Tone**: {bible.get('tone', '')}",
        f"**Dramatic Question**: {bible.get('dramatic_question', '')}\n",
    ]

    # Registry table
    reg_vars = registry.get("vars", [])
    if reg_vars:
        lines.append("## State Registry\n")
        lines.append("| Variable | Type | Default | Description |")
        lines.append("|----------|------|---------|-------------|")
        for v in reg_vars:
            type_str = v["type"]
            if v["type"] == "enum":
                type_str = f"enum({', '.join(v.get('values') or [])})"
            lines.append(f"| `{v['key']}` | {type_str} | `{v.get('default', '')}` | {v.get('description', '')} |")
        lines.append("")

    # Build edge lookup by source
    edges_by_src: dict[str, list[dict]] = {}
    for e in edges:
        edges_by_src.setdefault(e["src"], []).append(e)

    # Spine walkthrough
    lines.append("## Story Spine\n")
    for node in nodes:
        kind = node.get("kind", "scene")
        kind_badge = {"scene": "●", "bottleneck": "◆", "ending": "★"}.get(kind, "○")
        lines.append(f"### {kind_badge} {node['id']}: {node.get('title', '')} ({node.get('duration_min', 0)} min)\n")

        # Entry conditions
        requires = node.get("requires", [])
        if requires:
            req_strs = [f"`{p['key']} {p.get('cmp', 'eq')} {p['value']}`" for p in requires]
            lines.append(f"**入场条件**: {', '.join(req_strs)}\n")

        invariants = node.get("invariants", [])
        if invariants:
            inv_strs = [f"`{p['key']} {p.get('cmp', 'eq')} {p['value']}`" for p in invariants]
            lines.append(f"**不变量 (canon)**: {', '.join(inv_strs)}\n")

        # Story skeleton
        if node.get("summary"):
            lines.append(node["summary"] + "\n")
        if node.get("goal"):
            lines.append(f"**Goal**: {node['goal']}\n")
        beats = node.get("beats", [])
        if beats:
            lines.append("**节拍**:")
            for i, beat in enumerate(beats, 1):
                lines.append(f"{i}. {beat}")
            lines.append("")

        # Player choices
        out_edges = edges_by_src.get(node["id"], [])
        if out_edges:
            cq = node.get("choice_question", "")
            if cq:
                lines.append(f"**选择**: {cq}")
            for edge in out_edges:
                effect_str = ""
                effs = edge.get("effects", [])
                if effs:
                    eff_parts = [f"{e['key']}={e['value']}" for e in effs]
                    effect_str = f" [{', '.join(eff_parts)}]"
                label = edge.get("label") or "→"
                lines.append(f"- → **{edge['dst']}** {label}{effect_str}")
            lines.append("")
        else:
            lines.append("")

    # Endings summary
    endings = [n for n in nodes if n.get("kind") == "ending"]
    if endings:
        lines.append("## Endings\n")
        for e in endings:
            lines.append(f"- **{e['id']}**: {e.get('title', '')} — {e.get('summary', '')}")
        lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("Usage: python fix_fake_choices.py <project_dir>")
        sys.exit(1)

    project_dir = Path(sys.argv[1])
    state_path = project_dir / "state.json"

    if not state_path.exists():
        print(f"Error: {state_path} not found")
        sys.exit(1)

    # Load
    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    print("Fixing fake choices in state.json...")
    questions_added, labels_rewritten = fix_state(state)
    print(f"\nAdded choice_question to {questions_added} nodes")
    print(f"Rewrote {labels_rewritten} edge labels")

    # Save state.json
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    print(f"\nSaved {state_path}")

    # Regenerate preview.md
    preview_path = project_dir / "preview.md"
    preview_content = generate_preview(state)
    with open(preview_path, "w", encoding="utf-8") as f:
        f.write(preview_content)
    print(f"Regenerated {preview_path}")

    # Summary
    print("\n── Verification ──")
    spine = state["spine"]
    edges_by_src: dict[str, list[dict]] = {}
    for e in spine["edges"]:
        edges_by_src.setdefault(e["src"], []).append(e)

    branching = [n for n in spine["nodes"] if len(edges_by_src.get(n["id"], [])) > 1]
    missing_q = [n["id"] for n in branching if not n.get("choice_question")]
    if missing_q:
        print(f"WARNING: {len(missing_q)} branching nodes still missing choice_question: {missing_q}")
    else:
        print(f"All {len(branching)} branching nodes have choice_question ✓")

    # Check for outcome-sounding labels
    outcome_words = ["失败", "成功", "暴露", "破绽", "圈套", "重围", "受敌", "信任", "怀疑"]
    suspect = []
    for e in spine["edges"]:
        if any(w in (e.get("label") or "") for w in outcome_words):
            suspect.append(f"  {e['id']}: {e['label']}")
    if suspect:
        print(f"WARNING: {len(suspect)} edges still sound like outcomes:")
        for s in suspect:
            print(s)
    else:
        print("No outcome-sounding edge labels found ✓")


if __name__ == "__main__":
    main()
