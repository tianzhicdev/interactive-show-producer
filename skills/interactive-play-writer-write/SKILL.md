---
name: interactive-play-writer-write
description: "Step-3: Write production-ready scripts per node from validated DAG, with state coherence enforcement."
---

# /interactive-play-writer-write — Step 3: Write Scripts

From a **locked step-2 state.json** (bible + registry + branching DAG with beats), write production-ready scripts for every node. No structural changes, no new state variables.

## Parameters

| Parameter | Required | Default | Example |
|-----------|----------|---------|---------|
| `--state` | Yes | - | `~/Downloads/play_spine_xxx/state.json` |
| `--output` | No | same dir | `/path/to/output` |
| `--parallelism` | No | `5` | Max concurrent script-writing agents |

## Language Rule

All scripts in **Chinese**. JSON keys English, values Chinese.

## Script Format (《天坑追匪》 reference)

Every script follows this format:

```
场：NNN    景：地点名
时：时段    人：角色1、角色2、角色3

▲（镜头指示）场景描述和动作。用▲开头的段落是舞台指示/镜头语言。

角色名：（表情/动作）台词内容。
角色名：台词内容。

▲（镜头切换）下一段动作描述。

选择 NNN
问题：主角此刻面临的抉择？
NNN-A：选项A文字 → NNNA
NNN-B：选项B文字 → EP(N+1)

━━━━━━━━━━ NNNA：选项A标题 → NNNA ━━━━━━━━━━

▲分支A的内容……

━━━━━━━━━━ NNNB：选项B标题 → EP(N+1) ━━━━━━━━━━

▲分支B的内容……

【属性变化】（如有）
```

### Format Rules

1. **场/景 header**: `场：` + node ID number, `景：` + location from beats
2. **时/人 header**: `时：` + time of day, `人：` + all characters in scene
3. **Stage directions**: Start with `▲`, include camera hints in `（）` — `特写`, `中景`, `全景`, `手持`, `俯拍`, `平行剪辑` etc.
4. **Dialogue**: `角色名：` + speech. Parenthetical `（动作/表情）` before speech when needed.
5. **Choice block**: `选择 NNN` + newline + `问题：` + newline + options `NNN-A：选项文字 → TARGET_NODE_ID` / `NNN-B：选项文字 → TARGET_NODE_ID`. Each option MUST end with `→ TARGET_NODE_ID` matching the DAG edge destination exactly.
6. **Branch sections**: `━━━━━━━━━━ NNNA：选项标题 → TARGET_NODE_ID ━━━━━━━━━━`
7. **Dead ends**: End with `BE` on its own line
8. **Endings**: End with `结局：结局名称`
9. **No template artifacts**: Never include `（≤8字）` or similar placeholders
10. **Choice table** (for parallel choices): When both options lead to genuinely parallel content (not a dead end), present choices in a comparison table format:
```
┌─────────────────────────┬─────────────────────────┐
│ NNN-A：选项A → NNNA     │ NNN-B：选项B → EP(N+1)  │
├─────────────────────────┼─────────────────────────┤
│ 选项A的简要后果描述      │ 选项B的简要后果描述      │
│ （1-2句，概述走向）      │ （1-2句，概述走向）      │
└─────────────────────────┴─────────────────────────┘
```
Use the table format when BOTH options are valid story paths (not dead ends). If one option leads to a dead end, use the regular list format instead.

11. **Character name card**: When an important character appears for the FIRST TIME in the story, insert a name card immediately after their first mention:
```
【人物卡】角色名
身份：与主角的关系 / 身份定位
特征：一句话外貌或性格标签
```
Example:
```
【人物卡】霍长鹤
身份：镇南王·颜如玉之夫
特征：冷面银甲，自创剑法，外冷内热
```
Only show the name card ONCE per character across all episodes. Characters from the story bible's character list should get name cards; minor unnamed characters (路人、侍女) do not need them.

## Scene Opening Rule

Every script's opening shot (first ▲ direction) MUST match the node's `entry_context`:

- Location in 景 header = location from entry_context
- Time in 时 header = time from entry_context
- Opening action = logical continuation from parent's exit + edge resolution

If the node has incoming edges with resolution beats, the script picks up
AFTER those resolution beats — do not re-narrate the resolution.

BAD:
  entry_context = "流放路上·第一日黄昏"
  Script opens: "场：002  景：流放第三日·营地"  ← wrong day, wrong place

GOOD:
  entry_context = "流放路上·第一日黄昏·队伍在山道上艰难前行"
  Script opens: "场：002  景：流放路上·山道"
  Script starts: "▲（全景）黄昏的山道上，流放队伍蜿蜒前行……"

## Choice Placement Rule

The choice block appears at the TENSION PEAK — the moment of maximum
unresolved pressure. The content BEFORE the choice must NOT resolve the tension.

Self-check: read the script up to `选择 NNN`. Is there still unresolved tension?
If the conflict is already settled, the choice is cosmetic.

BAD: Script narrates "颜如玉当众断亲, 写下血书" then choice asks "断亲出走 vs 隐忍"
     ← 断亲 already happened, the choice is meaningless
GOOD: Script builds to "颜松伸手要夺玉镯——" then choice asks "以血断亲 vs 隐忍退让"
     ← tension is at peak, player decides the action

## Prologue Script Guidelines

When `node.kind == "prologue"` (typically EP01):
- **Length**: ~900 characters (3 minutes of content)
- **Structure**: First ~2 min = world/character setup, then action + tutorial choice
- **Opening**: **MUST open with 旁白** to establish the world before any dialogue or action
- **Choice**: Tutorial-level — both options are safe, introduce the interactive mechanic
- **Tone**: Set the genre atmosphere; the audience should understand "what kind of story this is"
- **NO dead ends**: The choice block must NOT include paths to DE## nodes
- **Convergent**: All branches quickly rejoin the main spine (within 0-1 hops)

### EP01 旁白 Opening Rule (MANDATORY for prologue)

EP01 (prologue) MUST open with `旁白：` before any dialogue or character action:

```
场：001    景：[起始地点]
时：[时段]    人：[主角]

旁白：（全景）[世界观叙述2-3句，建立时代背景、社会规则、故事基调……]

▲（中景）[主角首次出场，展示外貌/状态/处境……]
```

The transition from 旁白 to scene action must be seamless — 旁白 paints the world,
then the camera naturally lands on the protagonist.

This is validated by LLM judge question S3_SCN_02 (hard-fail if missing).

Example structure for a prologue script:
```
场：001    景：[故事起始地点]
时：[时段]    人：[主角]

旁白：（全景）[世界观叙述……]

▲（中景）主角首次出场，展示性格和核心能力……

选择 001
问题：[轻量级抉择，两个都是安全选项]
001-A：[选项A] → EP01A
001-B：[选项B] → EP02

━━━━━━━━━━ 001A：[选项A标题] → EP01A ━━━━━━━━━━
▲分支A内容（安全路线）……

━━━━━━━━━━ 001B：[选项B标题] → EP02 ━━━━━━━━━━
▲分支B内容（安全路线）……
```

## State Coherence (CRITICAL)

Before writing each script, compute guaranteed vs varying state:

```python
from dfs_expander import compute_guaranteed_state, compute_varying_state

guaranteed = compute_guaranteed_state(spine, registry, node_id)
varying = compute_varying_state(spine, registry, node_id)
```

### Hard Constraints for Script Writers

Pass to each script-writing agent:

```
## State Coherence Constraints

GUARANTEED at this node (safe to reference):
{guaranteed_state}

VARYING at this node (DO NOT reference):
{varying_state}

IRON RULE: You MUST NOT mention, reference, or assume any item, event,
or fact that depends on a VARYING state variable. The player may or may
not have that item/event depending on their path.

Examples of violations:
- Referencing a letter that only exists if player went through EP01A
- Mentioning silver that was only looted on one path
- Assuming an enemy was defeated when that only happens on some paths
```

## Execution

### Phase 1: LOAD

```python
state = load_state(project_dir)
assert state.step == "step-2"
```

### Phase 2: TOPO SORT

Topologically sort nodes. Write scripts in dependency order — parent nodes before children.

```python
from collections import deque

# Build in-degree map
in_degree = {n.id: 0 for n in spine.nodes}
adj = {}
for e in spine.edges:
    adj.setdefault(e.src, []).append(e.dst)
    in_degree[e.dst] = in_degree.get(e.dst, 0) + 1

# Kahn's algorithm
queue = deque([n for n in in_degree if in_degree[n] == 0])
topo_order = []
while queue:
    node = queue.popleft()
    topo_order.append(node)
    for child in adj.get(node, []):
        in_degree[child] -= 1
        if in_degree[child] == 0:
            queue.append(child)
```

### Phase 3: WRITE (parallel by topo level)

Group nodes by topo level. Write all nodes at the same level in parallel (up to `--parallelism` concurrent agents).

For each node, the script-writing agent receives:

1. **Node data**: id, kind, title, summary, goal, beats, chapter_range
2. **Outgoing edges**: label, dst, effects, resolution
3. **Incoming edges**: from which nodes, with what resolution
4. **Bible context**: protagonist, characters, world, canon_facts
5. **State coherence**: guaranteed_state + varying_state
6. **Prior scripts**: scripts from parent nodes (for continuity)
7. **Format spec**: the script format above
8. **Transition context**: entry_context (WHERE/WHEN this scene opens), parent's exit_context + edge resolution (what just happened before this scene)
9. **Chapter excerpts**: source material from chapter_index matching node.chapter_range (if available)

### Phase 4: VALIDATE-FIX LOOP (MANDATORY — repeat until 0 errors AND 0 warnings)

**This phase is a BLOCKING GATE. You MUST run BOTH the IO checks AND the LLM judge on EVERY script. You MUST NOT skip, abbreviate, or defer validation. If you skip this phase, the entire step-3 output is INVALID and the scripts CANNOT be imported.**

**The validation is a LOOP, not a one-shot check. You run validation on all scripts, fix every issue found (errors AND warnings), then re-validate the fixed scripts. Repeat until the output is completely clean: 0 IO errors, 0 IO warnings, 0 LLM hard-fails, 0 LLM soft-fails.**

```
VALIDATE-FIX LOOP (step-3):
  round = 0
  REPEAT:
    round += 1
    1. Run IO checks on ALL scripts → collect errors + warnings
    2. Run LLM judge on ALL scripts → collect hard-fails + soft-fails
    3. If 0 errors + 0 warnings + 0 hard-fails + 0 soft-fails → PASS → exit loop
    4. Otherwise:
       a. For each failing script:
          - Collect ALL feedback (IO errors/warnings + LLM hard/soft fails)
          - Re-invoke the script writer with feedback appended to prompt
          - Replace the old script with the rewritten version
       b. Go to step 1 (re-validate ALL scripts, not just the fixed ones)
    5. If round > 5: STOP and report to user (something is structurally wrong)
```

#### 4a. IO Checks (deterministic, per script)

For EVERY generated script, verify:

1. **Format compliance**: 场/景 header present, 选择 NNN + 问题：format, ▲ directions present, ━━━ branch format
2. **No template artifacts**: regex scan for `（≤.字）`, `[待填写]`, `xxx`, `TODO` etc.
3. **Character count**: 300 chars/min × duration_min ± 50% (too short = missing content, too long = over-written)
4. **State coherence**: No references to varying-state items (keyword scan)
5. **Character compliance**: Only bible characters appear
6. **Dead end format**: DE## scripts end with `BE` on its own line
7. **Ending format**: END_* scripts end with `结局：结局名称`
8. **Choice target matching**: Every `→ TARGET` in choice options matches an actual DAG edge destination

**Fix ALL errors AND warnings. Warnings are NOT acceptable — they indicate issues that must be resolved.**

#### 4b. LLM Judge (semantic validation — MANDATORY)

For EVERY script (including dead ends and endings), run the LLM judge:

```python
from llm_judge import (
    S3_QUESTIONS, filter_questions_for_node,
    build_judge_prompt, build_step3_judge_context,
    parse_judge_response, format_retry_feedback,
)

all_reports = {}
fail_nodes = []  # both hard AND soft fails

for node_id, script_text in generated_scripts.items():
    node = get_node(spine, node_id)
    outgoing_edges = get_outgoing_edges(spine, node_id)

    questions = filter_questions_for_node(S3_QUESTIONS, node.kind)
    judge_ctx = build_step3_judge_context(
        script=script_text,
        node={"id": node.id, "kind": node.kind, "beats": node.beats,
              "entry_context": node.entry_context, "exit_context": node.exit_context,
              "choice_question": node.choice_question},
        edges=[{"id": e.id, "src": e.src, "dst": e.dst, "label": e.label,
                "resolution": e.resolution} for e in outgoing_edges],
        bible=bible_compact,
        guaranteed_state=guaranteed,
        varying_state=varying,
        parent_scripts=parent_scripts_dict,
        chapter_excerpts=chapter_excerpts,
    )
    judge_prompt = build_judge_prompt(questions, judge_ctx)

    # LLM CALL: send prompt, get raw JSON response
    raw_response = llm_call(judge_prompt)

    report = parse_judge_response(raw_response, questions, node.id, "step-3")
    all_reports[node.id] = report.to_dict()

    if report.hard_fails or report.soft_fails:
        fail_nodes.append(node.id)
        for v in report.verdicts:
            if not v.answer:
                severity = "🔴 HARD" if v.severity == "hard" else "🟡 SOFT"
                print(f"   {severity} {node.id}/{v.question_id}: {v.reasoning}")
    else:
        print(f"✅ {node.id} PASS")
```

**The LLM judge checks these 15 questions per script (see llm_judge.py for full text):**

| ID | Category | What it catches | Severity |
|----|----------|----------------|----------|
| S3_ALI_01 | ALIGNMENT | Script doesn't dramatize all beats in order | HARD |
| S3_ALI_02 | ALIGNMENT | Script adds events beyond the beats | HARD |
| S3_ALI_03 | ALIGNMENT | Choice block doesn't match DAG edges | HARD |
| S3_TEN_01 | TENSION | No unresolved tension at choice point | HARD |
| S3_TEN_02 | TENSION | Choice question contradicts script state (e.g. says "X被制服" but branch shows X still in control) | HARD |
| S3_NAM_01 | NAMING | Names/places/terms don't match bible | HARD |
| S3_NAM_02 | NAMING | Inconsistent terminology for same concept | SOFT |
| S3_CHR_01 | CHARACTER | Active characters not listed in 人：header | SOFT |
| S3_CHR_02 | CHARACTER | First-appearance character missing 【人物卡】 | SOFT |
| S3_CHR_03 | CHARACTER | Character has impossible knowledge/items | HARD |
| S3_SCN_01 | SCENE | Opening doesn't match entry_context | HARD |
| S3_SCN_02 | SCENE | EP01 (prologue) missing 旁白 opening | HARD |
| S3_FMT_01 | FORMAT | Choice block format incorrect | HARD |
| S3_FMT_02 | FORMAT | Template artifacts remain in script | HARD |
| S3_SCN_03 | SCENE | Stage directions lack cinematic quality | SOFT |

**ALL 15 questions must pass. Both hard-fails AND soft-fails must be fixed.**

**Fix-and-revalidate procedure for each failing script:**
1. Collect ALL feedback (hard + soft): `format_retry_feedback(report)`
2. Combine with any IO check failures for the same script
3. Re-invoke the script writer with ALL feedback appended to the prompt
4. Re-run BOTH IO checks AND LLM judge on the rewritten script
5. If still failing: fix again and re-validate (up to 5 rounds total)
6. If still failing after 5 rounds: STOP and report to user

**GATE RULE: Do NOT proceed to Phase 5 until ALL of these are true:**
- ALL scripts pass IO checks with 0 errors AND 0 warnings
- ALL scripts pass LLM judge with 0 hard-fails AND 0 soft-fails
- Save all judge reports to `$PROJECT_DIR/validation_report_step3.json`

**There is no concept of "acceptable warnings." Every issue must be fixed.**

### Phase 5: SAVE

Save scripts to state.json and individual files:

```python
state.step = "step-3"
# Scripts stored per node ID
scripts = {}
for node_id, script_text in generated_scripts.items():
    scripts[node_id] = script_text
    # Also save individual file
    with open(f"{project_dir}/scripts/{node_id}.txt", "w") as f:
        f.write(script_text)

# Save to state
state_dict = asdict(state)
state_dict["scripts"] = scripts
```

## Output Contract

```json
{
  "version": "1.0",
  "step": "step-3",
  "bible": { "..." },
  "registry": { "..." },
  "spine": { "..." },
  "scripts": {
    "EP01": "场：001    景：镇南王府·地库\n时：夜内    人：颜如玉\n\n▲...",
    "EP02": "...",
    "DE01": "...\nBE"
  }
}
```

## Definition of Done

**ALL of these must be true before step-3 is complete:**

- [ ] All nodes have scripts saved to `$PROJECT_DIR/scripts/`
- [ ] IO validation: 0 errors AND 0 warnings across ALL scripts
- [ ] LLM judge: 0 hard-fails AND 0 soft-fails across ALL scripts
- [ ] Validation reports saved to `$PROJECT_DIR/validation_report_step3.json`
- [ ] state.json updated to `step: "step-3"` with scripts embedded

**If ANY validation issue remains (error, warning, hard-fail, or soft-fail), the step is NOT complete. Do NOT advance state.step. Run the validate-fix loop until clean.**
