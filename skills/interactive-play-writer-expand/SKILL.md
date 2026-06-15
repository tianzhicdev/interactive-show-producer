---
name: interactive-play-writer-expand
description: "Step-2: DFS expansion of locked linear spine into a branching DAG with backtracking, state wiring, and deterministic validation."
---

# /interactive-play-writer-expand — Step 2: DFS Expand Spine into DAG

From a **locked step-1 state.json** (bible + registry + **cornerstone-only spine**), fill the segments between cornerstones with a branching DAG using **depth-first traversal with backtracking**. Step-1 provides only cornerstones (prologue, bottlenecks, endings); step-2 creates ALL intermediate nodes, edges, beats, and choices with full creative freedom — as long as all paths respect cornerstone invariants.

## Parameters

Parse from user command:

| Parameter | Required | Default | Example |
|-----------|----------|---------|---------|
| `--state` | Yes | - | `~/Downloads/play_spine_xxx/state.json` |
| `--playthrough-target` | No | `50` | Minutes for a principal playthrough |
| `--total-budget` | No | `100` | Total authored node-minutes |
| `--output` | No | same dir as state.json | `/path/to/output` |

## Language Rule

All output (summaries, edge labels, preview) in **Chinese**, unless story requires foreign language. JSON keys stay English, values Chinese.

## Node ID Convention

- **Linear nodes** (from step-1): `EP01`, `EP02`, ... — unchanged
- **Branch variants**: `EP01A`, `EP01B` — parallel content for the same spine position
- **Dead ends**: `DE01`, `DE02`, ... — terminal nodes that end a path early

## Prologue Rules

EP01 is a **cornerstone** with `kind: "prologue"`:
- **Duration**: 3.0 min (same as regular episodes)
- **Convergent**: all paths from EP01 MUST reach the next cornerstone within 0-2 hops
- **NO dead ends**: EP01 branches must NOT lead to DE## nodes
- **Content**: world setup, protagonist introduction, demonstrate core ability/trait
- **Choice**: tutorial-level (both options are safe, introduce the choice mechanic)
- **Structure example**: EP01 → EP02 + EP01A → EP02 → next_cornerstone (NO EP01A → DE##)
- **Immutable**: EP01's kind/invariants/requires cannot be changed by step-2

## Execution Phases

### Phase 1: LOAD

Load the step-1 state and initialize the DFS expander.

```python
import sys
sys.path.insert(0, "skills/interactive-play-writer/lib")
from data_model import load_state, save_state, segments_between_bottlenecks
from dfs_expander import (
    get_initial_state, apply_effects, check_invariants, check_requires,
    find_next_bottleneck, find_next_cornerstone,
    budget_remaining, path_budget_remaining,
    apply_expansion, undo_expansion, get_expansion_prompt_context,
    validate_expansion_output, dicts_to_nodes, dicts_to_edges, ExpansionLog,
    lookup_chapter_excerpts,
)
from llm_judge import (
    S2_QUESTIONS, filter_questions_for_node,
    build_judge_prompt, build_step2_judge_context,
    parse_judge_response, format_retry_feedback,
)

state = load_state(project_dir)
assert state.step == "step-1", "Input must be a locked step-1 state"

# Verify step-1 spine contains only cornerstones
for node in state.spine.nodes:
    assert node.is_cornerstone, f"Step-1 should only have cornerstones, found scene node: {node.id}"

segments = segments_between_bottlenecks(state.spine)
```

Save expansion parameters to `$PROJECT_DIR/args.json`:
```json
{
  "playthrough_target_min": 50,
  "total_budget_min": 100,
  "input_state": "/path/to/state.json"
}
```

### Phase 2: DFS_EXPAND

**Core algorithm.** Traverse the cornerstone spine depth-first from `entry_node`. At each node, the LLM creates intermediate nodes and branches. DFS recurses into every new node to continue filling until reaching the next cornerstone.

**Key insight:** Step-1 provides only cornerstones (EP01→EP04→EP07→EP10). Step-2 creates ALL intermediate nodes (EP02, EP03, EP02A, DE01, etc.) between them. The DFS algorithm works the same way for cornerstones and for newly-created intermediate nodes — every non-terminal node gets expanded.

```
expansion_log = ExpansionLog()
initial_state = get_initial_state(registry)

DFS_EXPAND(entry_node, initial_state, [entry_node]):
```

#### DFS_EXPAND(node, accumulated_state, path)

```
1. CHECK REQUIRES
   - violations = check_requires(node, accumulated_state)
   - If violations: return REQUIRES_FAIL(violations)

2. IF CORNERSTONE (bottleneck or ending):
   - IF BOTTLENECK:
     - violations = check_invariants(node, accumulated_state)
     - If violations: return BOTTLENECK_FAIL(violations)
     - CHECKPOINT: save_state() (state.json snapshot after passing bottleneck)
     - Log: "✓ Bottleneck {node.id} passed: {invariants}"
   - IF ENDING:
     - Log: "✓ Ending {node.id} reached"
     - return SUCCESS

3. IF DEAD-END:
   - Log: "✓ Dead end {node.id} reached"
   - return SUCCESS

4. CHECK BUDGET
   - If budget_remaining() < 3.0: return SUCCESS (no room to expand)
   - If path_budget_remaining() < 3.0: return SUCCESS (path too long)

5. GET EXPANSION CONTEXT
   - next_cs = find_next_cornerstone(spine, node.id)  # target cornerstone
   - next_bn = find_next_bottleneck(spine, node.id)
   - context = get_expansion_prompt_context(
       node, accumulated_state, ...,
       bible=state.bible, chapter_index=state.chapter_index
     )
   - context includes target_cornerstone: what the expansion must eventually reach

6. EXPAND (with retry loop, max 3 attempts):
   For attempt in 1..3:
     a. LLM CALL: Generate expansion for this node
        - Input: context dict from step 5 (includes target_cornerstone)
        - Output: { parent_beats, parent_exit_context, choice_question,
                    nodes: [...], edges: [...] }
        - New nodes can be:
          * Intermediate scene nodes (EP02, EP03) — leaf-for-now, DFS expands later
          * Branch variants (EP02A, EP03B) — leaf-for-now or with their own choices
          * Dead ends (DE01) — terminal
          * Direct connections to next cornerstone — when close enough to link

     b. VALIDATE FORMAT (IO):
        - errors = validate_expansion_output(expansion, node.id, registry)
        - If errors: log errors, continue to next attempt

     c. LLM JUDGE (semantic validation):
        - questions = filter_questions_for_node(S2_QUESTIONS, node.kind)
        - judge_context = build_step2_judge_context(expansion, context)
        - judge_prompt = build_judge_prompt(questions, judge_context)
        - LLM CALL: run judge prompt → raw response
        - report = parse_judge_response(raw, questions, node.id, "step-2")
        - Log all soft-fail warnings: report.soft_fails
        - If report.retry_needed (any hard-fail):
            feedback = format_retry_feedback(report)
            Append feedback to next attempt's expansion prompt → continue to next attempt

     d. APPLY EXPANSION:
        - Convert dicts to Node/Edge objects
        - Set node.beats from expansion.parent_beats
        - Set node.choice_question from expansion
        - Set node.exit_context from expansion.parent_exit_context
        - apply_expansion(spine, node.id, new_nodes, new_edges, expansion_log)

     e. RECURSE INTO BRANCHES:
        all_ok = True
        For each outgoing edge from node:
          - target = edge.dst
          - new_state = apply_effects(accumulated_state, edge.effects, registry)
          - result = DFS_EXPAND(target, new_state, path + [target])
          - If BOTTLENECK_FAIL:
              - undo_expansion(spine, node.id, expansion_log)
              - all_ok = False
              - break  (retry with new LLM call)

     f. If all_ok: return SUCCESS

   If all 3 attempts exhausted:
     return BOTTLENECK_FAIL (propagate up for grandparent backtracking)
```

#### Cornerstone Immutability

**Cornerstones (prologue, bottleneck, ending) created by step-1 are IMMUTABLE in structure.** Step-2 can:
- ✅ Add beats, choice_question, exit_context to a cornerstone
- ✅ Create outgoing edges and child nodes from a cornerstone
- ❌ Cannot delete, rename, or change kind/invariants/requires of a cornerstone
- ❌ Cannot reorder cornerstones or skip them

**Non-cornerstone nodes created by step-2 have no such restriction.** They can be freely created, shaped, connected — the only constraint is that all non-dead-end paths eventually reach the next cornerstone with invariants satisfied.

#### LLM Expansion Prompt

For each node being expanded, provide this context to the LLM.

**IMPORTANT:** Step-1 provides ONLY cornerstone nodes (prologue, bottleneck, ending) — no regular scene nodes exist yet. Step-2 creates ALL intermediate nodes between cornerstones. When expanding a cornerstone, the LLM creates intermediate nodes that form the story path to the next cornerstone. When expanding an intermediate node (one created by a prior expansion), it adds further branches.

The expansion output can contain "leaf-for-now" nodes with 0 outgoing edges — these will be expanded by the DFS in a subsequent recursion step. This allows building the segment incrementally rather than all at once.

```
You are expanding node {node.id} ("{node.title}") in an interactive story DAG.

## Current Node (SKELETON — you will write the beats)
- Summary: {node.summary}
- Goal: {node.goal}
- Duration: {node.duration_min} min
- NOTE: This node has NO beats yet. You must write them below as parent_beats.

## Episode Arc (iron law)
Every non-terminal episode follows this structure:
  [Previous choice resolution ~30s] → [New conflict/escalation ~60s] → [TENSION PEAK — episode ends here, choice appears]
Beats build TO the choice, never past it.

## Accumulated State (this path only)
{state vars and current values}

## Guaranteed State (same on ALL incoming paths — safe to reference)
{guaranteed_state: vars with single possible value across all paths}

## Varying State (DANGEROUS — differs across paths, DO NOT reference)
{varying_state: vars with multiple possible values}

## Target: Next Cornerstone
{target_cornerstone.id} ({target_cornerstone.kind}): {target_cornerstone.title}
Summary: {target_cornerstone.summary}
Entry context: {target_cornerstone.entry_context}
Invariants that MUST hold when reaching this cornerstone:
{invariants as key cmp value}

All non-dead-end paths from this node must eventually reach this cornerstone.
If close enough (1-2 hops away), connect directly. Otherwise create intermediate
nodes that the DFS will expand further.

## Budget
- Total remaining: {budget.total_remaining} min
- Path remaining: {budget.path_remaining} min

## Registry Variables
{registry vars with types and current values}

## Genre: {genre}
Use genre-appropriate choice archetypes, dead-end flavors, and tension peak styles.
See Genre Profiles table in the SKILL.md for guidance.

## Story Bible (reference — do NOT invent beyond this)
Protagonist: {name} — {role}, abilities: {abilities}
Characters (exhaustive — do NOT introduce unlisted characters):
{for each: "- {name} ({role}): {relationship}"}
World: {world dict}
Canon facts (MUST NOT contradict): {list}

## Story So Far (path to this node)
{for each prior node: "{id}: {title} — {summary}\n  Beats: {beats}"}

## Already-Created Variants (DO NOT duplicate their content)
{for each: "- {id}: {title} — {summary}"}

## Task
1. Write parent_beats for this node (3-5 beats building to tension peak)
2. Write a choice_question (protagonist dilemma at the peak)
3. Design 2-3 branching choices with nodes + edges
   - Nodes can be: intermediate scenes (leaf-for-now, DFS expands later),
     variants, dead ends, or direct connections to the target cornerstone
   - Leaf-for-now nodes: include title/summary/goal/entry_context/exit_context
     but leave beats=[] and choice_question="" (DFS fills these later)
   - Nodes connecting directly to the target cornerstone: just create an edge
     to the existing cornerstone node (do NOT recreate it)

## Beat Richness (CRITICAL)

Each beat is a NARRATIVE PARAGRAPH (2-4 sentences), not a one-line telegram.
A reader should be able to read the beats alone and follow a complete story.

Every beat must include:
  - WHO acts (character names, not pronouns on first mention)
  - WHY they act (motivation, goal, emotional state)
  - WHAT happens (concrete actions and consequences)
  - WHERE/WHEN (setting details, atmosphere, sensory cues)

BAD (telegram):
  "黑衣杀手半夜围攻营地，情势危急"

GOOD (narrative paragraph):
  "午夜时分，十余名黑衣杀手从四面八方无声逼近营地。领头者手持精钢短刀，
   刀身上刻着翼王府的暗纹。霍长鹤第一个察觉异样，低声唤醒众人戒备，
   自己持刀立于篝火前。杀手们毫不停顿，刀光如水银泻地般扑来。"

The same richness applies to:
  - parent_beats (spine node beats)
  - variant node beats
  - dead-end node beats
  - edge resolution beats

Output JSON:
{
  "parent_beats": [
    "设定/铺垫 — 2-4句叙事段落，包含人物、动机、场景",
    "升级/冲突 — 2-4句叙事段落，展示矛盾激化",
    "张力顶点 — 2-4句叙事段落，主角被逼入绝境，选择出现"
  ],
  "parent_exit_context": "WHERE/WHEN the source node scene ends (e.g. 颜府门前·白天·颜如玉握紧拳头)",
  "choice_question": "主角此刻面临的抉择（≤30字）",
  "nodes": [
    {
      "id": "EP03A", "kind": "scene",
      "title": "...", "summary": "...",
      "goal": "...", "duration_min": 3.0,
      "requires": [], "invariants": [],
      "entry_context": "流放第二日·驿站·夜 — 颜如玉假寐中听到异响",
      "exit_context": "驿站后院·深夜 — 颜如玉藏好密信回到原位",
      "beats": ["resolution of this choice", "new escalation", "new tension peak"],
      "choice_question": "variant's own dilemma"
    }
  ],
  "edges": [
    {
      "id": "E_EP03_EP03A", "src": "EP03", "dst": "EP03A",
      "label": "≤8字",
      "effects": [{"key": "has_item", "op": "set", "value": true}],
      "resolution": [
        "选择后立即发生的结果 beat 1",
        "结果的连锁反应 beat 2",
        "过渡到下一场景的桥段 beat 3（如有时间/地点跳转）"
      ]
    }
  ]
}
```

CRITICAL RULES:

```
- TENSION PEAK RULE: The LAST parent_beat MUST be the moment of maximum tension —
  the protagonist is cornered, the threat is immediate, action is required NOW.
  The choice appears at this exact moment. Beats NEVER contain resolution.
  The last beat MUST end with a tension indicator (？ or —— or … or ！).

  BAD:  [..., "颜如玉一脚踹飞颜松"]  ← resolution already happened
  GOOD: [..., "颜如玉握紧拳头——出手，还是忍？"] ← tension peak, choice follows

- RESOLUTION ON EDGES: Every edge MUST have 2-5 resolution beats showing what
  happens immediately after the player's choice. Resolution beats are:
  (a) Shown to the player right after they choose (before the next node starts)
  (b) The direct consequence of THIS specific action
  (c) ~30-60 seconds of content total
  (d) The BRIDGE from this scene to the next — if there's a time/location jump,
      the resolution beats carry the reader across it

  The NEXT node then starts fresh with its own setup/escalation arc.
  This closes the "choice → consequence" loop that makes choices feel meaningful.

  BAD:  edge has no resolution → player chooses "果断出手" and next scene is
        about something completely unrelated
  GOOD: edge resolution shows "颜如玉一脚踹飞颜松，逼他签血书" → THEN next
        node starts its own arc

- TRANSITION CHAINING RULE: The entry_context of a child node MUST be
  reachable from the parent's exit_context + edge resolution in ≤1 scene jump.

  BAD:  Parent exit = "颜府门前·白天", Child entry = "流放第三日·荒野营地"
        (3-day jump, new location, no bridge)
  GOOD: Parent exit = "颜府门前·白天·颜如玉转身走向流放队伍",
        Edge resolution = ["颜如玉大步走向流放队伍", "与押送官兵汇合,踏上流放路"],
        Child entry = "流放路上·第一日黄昏·队伍在山道上艰难前行"

  If the story needs a time skip, it MUST happen in the edge resolution beats.
  The edge resolution is the BRIDGE — it carries the reader from parent scene
  to child scene. Expand edge resolution to 2-5 beats if needed for the bridge.

- EPISODE = SETUP→ESCALATION→PEAK→CHOICE: Every non-terminal episode follows this arc.
  No episode ends mid-action. No episode resolves its own tension.

- NO CONTENT DUPLICATION: Variant nodes MUST NOT restate:
  (a) Parent node's parent_beats (given context)
  (b) Content from existing_variants above
  (c) Plot points from earlier episodes in Story So Far

- CHARACTER CONTINUITY: Only reference characters from the Bible's list or
  characters introduced in prior nodes' beats. No sudden appearances.

- OBJECT/ABILITY CONTINUITY: Items must be plausibly available — mentioned in
  prior beats or indicated by accumulated_state (has_<item> = true).

- NARRATIVE PROGRESSION: Each branch must ADVANCE plot toward/away from
  the next bottleneck. No circular narrative (same situation, different words).

- CANON COMPLIANCE: Do not contradict bible canon_facts or world rules.

- STATE COHERENCE (CRITICAL): You MUST only reference items, events, or facts
  that are GUARANTEED at this node (same value on ALL incoming paths).
  The guaranteed_state dict shows what you can safely reference.
  The varying_state dict shows what you MUST NOT reference — these items
  exist on some paths but not others.

  BAD: EP02A references a letter obtained in EP01A, but EP02A is also reachable
       without going through EP01A → letter may not exist
  GOOD: EP02A only references items/events from EP01 (which ALL paths pass through)

  Rule of thumb: if a variable is in varying_state, any scene/item/dialogue
  gated by that variable MUST NOT appear in beats, summaries, or scripts.

- TEMPORAL BRANCHING (preferred over tactic branching): When designing choices,
  prefer "which event happens" over "how to handle the same event."
  Each branch should pull from DIFFERENT source chapters, giving players
  genuinely different story content — not the same scene with a different approach.

  BAD (tactic branch): "fight the guards" vs "sneak past the guards" (same event)
  GOOD (temporal branch): "rescue the hostage (ch.15-18)" vs "infiltrate the camp (ch.20-23)"

  Use the node's chapter_range to identify what source material each branch draws from.
  Variant nodes should have their OWN chapter_range pointing to different source chapters.

- EDGE LABELS ARE PLAYER ACTIONS, NEVER OUTCOMES: Every edge label must be
  something the player DECIDES TO DO (≤8字). Never an outcome that happens TO them.
  The player should think "both options are plausible" — dead ends result from
  reasonable-sounding actions that lead to failure, not from choosing to fail.

  BAD:  "说理失败" ← outcome, no one chooses to fail
  BAD:  "被巡逻发现" ← happens TO the player, not a decision
  BAD:  "内应叛变" ← consequence, not player action
  GOOD: "继续硬刚" ← player action (pushes too hard → backfires)
  GOOD: "再搬一趟" ← player action (greed → gets caught)
  GOOD: "全权信任" ← player action (trusts too much → betrayed)

  Test: can you put "我选择" in front of the label and it makes sense?
  "我选择继续硬刚" ✓  "我选择说理失败" ✗

- UNIQUE TARGETS (IRON LAW): Every edge from a node MUST go to a DIFFERENT
  target node. No two edges from the same source can share a destination.
  This is validated by validate_expansion_output() and will cause a retry.

  BAD:  EP03 → EP04, EP03 → EP04 (flavor choice — same destination)
  GOOD: EP03 → EP04, EP03 → EP03A (genuine fork — different destinations)

- EVERY non-leaf node must have 2-3 outgoing edges with choices — NO pass-through nodes
- This includes variant nodes (EP##A, EP##B) — they ALSO need their own choices
- Pattern: spine nodes branch to (continue spine + variant). Variants branch to (rejoin spine + dead-end)
- Dead ends (DE##) and endings are the ONLY nodes allowed to have 0 outgoing edges
- Each edge label ≤ 8 Chinese characters
- Each non-leaf node needs a choice_question (protagonist dilemma, ≤30 chars Chinese)
- Dead ends use DE## IDs, branch variants use EP##[A-Z]
- Effects only reference declared registry variables
- At least one branch must be able to reach the next bottleneck with invariants satisfied
- Dead ends should be dramatically satisfying, not arbitrary failures
```

## DAG Pattern Catalog

Use a MIX of these patterns. No single pattern should dominate — variety creates richer topology.

**Pattern 1: Standard Diamond** (default, ≤3 uses per story)
```
EPn ──→ EP(n+1)             (continue spine)
  └──→ EPnA ──→ EP(n+1)     (rejoin spine)
           └──→ DExx         (dead end)
```

**Pattern 2: Sustained Parallel Track** (≥1 required, mid-story forks)
```
EPn ──→ EP(n+1) ──→ ...spine... ──→ bottleneck
  └──→ EPnA ──→ EPnB ──→ bottleneck   (2 eps on alt track)
           └──→ DExx                    (optional dead end)
```
Alt track runs 2+ episodes before rejoining. Creates genuinely different narrative arcs.

**Pattern 3: Multi-Hop Doom** (≥1 required, builds tension)
```
EPn ──→ EP(n+1)                      (safe path)
  └──→ EPnA ──→ doom_node ──→ DExx   (2 hops to death)
           └──→ EP(n+1)              (escape hatch)
```
Player makes one bad choice, gets a second chance, but doubling down = death. 2+ hops from spine to dead end.

**Pattern 4: Three-Way Fork** (≥1 required, key dramatic moments)
```
EPn ──→ EP(n+1)    (path A)
  ├──→ EPnA ──→ ... (path B)
  └──→ EPnB ──→ ... (path C)
```
Three genuinely different directions at a major decision point.

**Pattern 5: Multiple Endings** (final act)
```
EP_last ──→ ENDING_A
  ├──→ ENDING_B
  └──→ EPnA ──→ ENDING_C
```
Final node funnels to 2-3 different endings based on accumulated state.

### Pattern Placement Guide

| Story Phase | Recommended Patterns |
|------------|---------------------|
| Prologue (EP01) | Convergent diamond (NO dead ends) |
| Early (EP02-03) | Standard diamond, introduce first doom |
| Mid (EP04-06) | Sustained parallel, three-way fork |
| Late (EP07-08) | Sustained parallel, multi-hop doom |
| Final (EP09+) | Funnel to multiple endings |

Every node except dead ends and endings MUST have 2-3 outgoing edges.
Every edge from the same node MUST go to a DIFFERENT target (no flavor choices).
```

#### Backtracking Rules

- **Max 2 backtrack attempts per node**: If a node's expansion fails invariant checks after 3 LLM retries, propagate BOTTLENECK_FAIL up to the parent.
- **Undo is clean**: `undo_expansion()` removes all nodes and edges added by that expansion.
- **Checkpoint on bottleneck passage**: After successfully passing a bottleneck, save state.json. If a later expansion fails and backtracks, we don't lose validated progress.

### Phase 3: VALIDATE-FIX LOOP (MANDATORY — repeat until 0 errors AND 0 warnings)

**This phase is a BLOCKING GATE. You MUST run BOTH the IO validator AND the LLM judge. You MUST NOT skip, abbreviate, or defer validation. If you skip this phase, the entire step-2 output is INVALID.**

**The validation is a LOOP, not a one-shot check. You run validation, fix every issue found (errors AND warnings), then re-validate. Repeat until the output is completely clean: 0 IO errors, 0 IO warnings, 0 LLM hard-fails, 0 LLM soft-fails.**

```
VALIDATE-FIX LOOP (step-2):
  round = 0
  REPEAT:
    round += 1
    1. Run IO validator → collect errors + warnings
    2. Run LLM judge on all non-DE nodes → collect hard-fails + soft-fails
    3. If 0 errors + 0 warnings + 0 hard-fails + 0 soft-fails → PASS → exit loop
    4. Otherwise:
       a. Fix ALL issues (errors, warnings, hard-fails, soft-fails)
       b. Re-generate affected nodes/beats/edges with fix feedback
       c. Go to step 1
    5. If round > 5: STOP and report to user (something is structurally wrong)
```

#### 3a. IO Validator (deterministic)

```bash
python skills/interactive-play-writer/lib/validate_spine.py "$PROJECT_DIR"
```

IO checks:
1. **DAG integrity** — all edge targets valid, no self-loops, all nodes reachable
2. **Path budget** — every entry→ending path ≤ playthrough_target × 1.2
3. **Total budget** — sum of all node durations ≤ total_budget
4. **State coherence** — every node.requires satisfied by at least one incoming path
5. **Bottleneck convergence** — all principal paths pass through bottlenecks in order
6. **Branch ID format** — EP##[A-Z] for branches, DE## for dead ends, END_[A-Z] for endings
7. **Structural requirements** — ≥1 three-way fork, dead ends 15-25%, ≥1 delayed consequence
8. **Universal out-degree** — every non-leaf node has 2-3 outgoing edges (no pass-throughs)

**Fix ALL errors AND warnings before proceeding to 3b. Warnings are NOT acceptable — they indicate issues that must be resolved.**

#### 3b. LLM Judge (semantic validation — MANDATORY)

For EVERY non-dead-end node in the expanded spine, run the LLM judge:

```python
from llm_judge import (
    S2_QUESTIONS, filter_questions_for_node,
    build_judge_prompt, build_step2_judge_context,
    parse_judge_response, format_retry_feedback,
)

all_reports = {}
fail_nodes = []  # both hard AND soft fails

for node in spine.nodes:
    if node.id.startswith("DE"):
        continue  # dead ends are too short for semantic review

    questions = filter_questions_for_node(S2_QUESTIONS, node.kind)
    context = build_step2_judge_context(expansion_data, prompt_context)
    prompt = build_judge_prompt(questions, context)

    # LLM CALL: send prompt, get raw JSON response
    raw_response = llm_call(prompt)

    report = parse_judge_response(raw_response, questions, node.id, "step-2")
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

**The LLM judge checks these 15 questions per node (see llm_judge.py for full text):**

| ID | Category | What it catches | Severity |
|----|----------|----------------|----------|
| S2_OBJ_01 | OBJECT | Items appear without prior introduction | HARD |
| S2_OBJ_02 | OBJECT | Items depend on varying state (may not exist) | HARD |
| S2_OBJ_03 | OBJECT | Destroyed items reappear | HARD |
| S2_CHO_01 | CHOICE | Last beat resolves tension (choice becomes cosmetic) | HARD |
| S2_CHO_02 | CHOICE | Choice question contradicts scene state | HARD |
| S2_CHO_03 | CHOICE | Choices are passive events, not player actions | HARD |
| S2_CON_01 | CONTINUITY | Time/location jump without bridge | HARD |
| S2_CON_02 | CONTINUITY | Edge resolution doesn't connect parent→child | HARD |
| S2_CON_03 | CONTINUITY | Child re-narrates resolution content | SOFT |
| S2_CON_04 | CONTINUITY | Characters appear without prior introduction | HARD |
| S2_STA_01 | STATE | Edge effects don't match resolution narrative | HARD |
| S2_STA_02 | STATE | Beats reference varying-state items | HARD |
| S2_STA_03 | STATE | Content contradicts canon facts | HARD |
| S2_DRA_01 | DRAMA | Plot circles instead of advancing | SOFT |
| S2_DRA_02 | DRAMA | Beats lack who/why/what/where | SOFT |

**ALL 15 questions must pass. Both hard-fails AND soft-fails must be fixed.**

**Fix-and-revalidate procedure for each failing node:**
1. Collect ALL feedback (hard + soft): `format_retry_feedback(report)`
2. Rewrite that node's beats/choices/edges with the feedback appended to the LLM prompt
3. Re-run the LLM judge on the rewritten node
4. If still failing: fix again and re-validate (up to 5 rounds total)
5. If still failing after 5 rounds: STOP and report to user

**GATE RULE: Do NOT proceed to Phase 4 until ALL of these are true:**
- IO validator returns 0 errors AND 0 warnings
- LLM judge returns 0 hard-fails AND 0 soft-fails across ALL nodes
- Save all judge reports to `$PROJECT_DIR/validation_report_step2.json`

**There is no concept of "acceptable warnings." Every issue must be fixed.**

### Phase 4: PREVIEW

Generate human-readable artifacts:

1. **preview.md** — full walkthrough with branches, effects, paths

```python
from data_model import load_state, save_preview_md
state = load_state(project_dir)
save_preview_md(state, project_dir)
```

2. **DAG visual** — Graphviz PNG with color-coded nodes

```python
from render_spine_dag import render_spine_dag
render_spine_dag(state, project_dir, fmt='png')
```

Node colors:
- Blue (solid): linear spine nodes (EP##)
- Blue (dashed): branch variants (EP##A/B)
- Orange: bottlenecks
- Green: endings
- Red: dead ends (DE##)

### Phase 5: LOCK

Update state.json to step-2 and save:

```python
from data_model import save_state, save_registry_json, save_spine_json, save_bible_md

state.step = "step-2"
state.budget_report = {
    "total_authored_min": sum(n.duration_min for n in state.spine.nodes),
    "playthrough_target_min": playthrough_target,
    "total_budget_min": total_budget,
    "node_count": len(state.spine.nodes),
    "edge_count": len(state.spine.edges),
    "dead_end_count": len([n for n in state.spine.nodes if n.id.startswith("DE")]),
    "path_count": len(state.spine.all_paths()),
    "per_segment": {seg_id: {"nodes": N, "minutes": M} for ...},
}

save_state(state, project_dir)
save_registry_json(state.registry, project_dir)
save_spine_json(state.spine, project_dir)
save_bible_md(state.bible, project_dir)
```

Report to user:
1. Node count (linear + branches + dead ends)
2. Edge count
3. Path count (entry → each ending/dead end)
4. Budget utilization (total authored vs budget)
5. Registry changes from step-1 (new vars added)
6. Validation result (PASS/FAIL)
7. DAG visual location
8. Backtracking stats (how many retries at each node)

**Final deliverables:**
```
$PROJECT_DIR/
  state.json                      ← Updated to step-2
  bible.md                        ← Unchanged from step-1
  registry.json                   ← May have new vars
  spine.json                      ← Expanded DAG
  preview.md                      ← Updated walkthrough
  dag.png                         ← Color-coded DAG
  validation_report_step2.json    ← IO + LLM judge results
  args.json                       ← Expansion parameters
```

## Definition of Done

**ALL of these must be true before step-2 is complete:**

- [ ] All segments between cornerstones are filled with intermediate nodes
- [ ] IO validator: 0 errors AND 0 warnings
- [ ] LLM judge: 0 hard-fails AND 0 soft-fails across ALL non-dead-end nodes
- [ ] Validation reports saved to `$PROJECT_DIR/validation_report_step2.json`
- [ ] state.json updated to `step: "step-2"`
- [ ] preview.md and dag.png generated

**If ANY validation issue remains (error, warning, hard-fail, or soft-fail), the step is NOT complete. Do NOT advance state.step. Run the validate-fix loop until clean.**

## Data Model Reference

All types in `skills/interactive-play-writer/lib/data_model.py`.
DFS helper in `skills/interactive-play-writer/lib/dfs_expander.py`.

Step-2 additions:
- **`state_at(spine, registry, path)`** — simulate state along a path
- **`path_duration(spine, path)`** — sum node durations
- **`segments_between_bottlenecks(spine)`** — slice at bottleneck boundaries
- **`dfs_expander.*`** — all DFS expansion functions
- **`SpineState.budget_report`** — budget utilization data

## Cornerstone-Based DFS

Step-1 provides only cornerstones (prologue, bottlenecks, endings). Step-2 fills segments between them:

| Step-1 (lock) | Step-2 (fill) |
|---------------|---------------|
| Cornerstones only | ALL intermediate nodes |
| Entry, bottlenecks, endings | Scenes, variants, dead ends |
| Invariants + registry | Beats, choices, edges |
| Structure skeleton | Full branching DAG |

The DFS traverses from entry cornerstone, creating intermediate nodes. When it reaches the next cornerstone, it checks invariants and checkpoints. Each expansion creates some nodes; the DFS recurses into them for further expansion. "Leaf-for-now" nodes (0 outgoing edges) trigger their own expansion on the next DFS step.

## Genre Profiles

Step-1 detects genre and stores it in `bible.genre`. Step-2 uses the genre tag
to shape choice design, dead-end flavor, and tension peak style.

| Genre Tag | Choice Archetypes | Dead-End Flavors | Tension Peak Style |
|-----------|-------------------|------------------|-------------------|
| `heroine_period` | 忍vs刚, 智取vs硬碰, 借力vs独行 | 宅斗失败被陷害, 暴露身份被幽禁, 得罪权贵被赐死 | 被逼到绝境的女性困境 |
| `cultivation` | 突破vs稳固, 硬拼vs智取, 独修vs结盟 | 走火入魔, 宗门覆灭, 渡劫失败 | 修为瓶颈/强敌压境的生死抉择 |
| `urban` | 合作vs对抗, 公开vs隐忍, 商业vs情感 | 公司破产, 身份曝光, 信任崩塌 | 职场/商场的信任危机时刻 |
| `apocalypse` | 救人vs自保, 探索vs固守, 信任vs怀疑 | 感染变异, 物资耗尽被困, 队友背叛 | 资源/生存的极限抉择 |
| `mystery` | 追查vs潜伏, 信任vs怀疑, 公开vs隐瞒 | 被凶手反杀, 错误指控无辜, 关键证据销毁 | 真相即将揭露的危险时刻 |

## Expansion Rules Summary

| Rule | Constraint |
|------|-----------|
| Out-edges per non-leaf node | 2-3 (EVERY non-leaf, including variants) |
| Three-way forks | ≥1 required |
| Dead end ratio | 15-25% of total nodes |
| Delayed consequences | ≥1 required |
| Distinct DAG patterns | ≥3 different patterns from the catalog |
| Standard Diamond | ≤3 uses per story |
| Sustained parallel tracks | ≥1 required (variant → variant path) |
| Multi-hop doom paths | ≥1 required (≥2 hops from spine to dead end) |
| Prologue (if present) | Convergent, NO dead ends, 3 min |
| Cornerstones | Immutable (step-2 adds beats/choices, cannot delete/rewrite) |
| Path duration ceiling | playthrough_target × 1.2 |
| Total budget | sum(node.duration_min) ≤ total_budget |
| Branch merging | All principal paths converge at bottlenecks |
| Backtrack attempts | Max 2 per node before propagating failure |

## Definition of Done (full checklist)

Step-2 is done when:
- [ ] IO validator: 0 errors AND 0 warnings
- [ ] LLM judge: 0 hard-fails AND 0 soft-fails across ALL non-dead-end nodes
- [ ] Validation reports saved to `$PROJECT_DIR/validation_report_step2.json`
- [ ] state.json updated to `step: "step-2"`
- [ ] DAG has ≥1 three-way fork
- [ ] Dead ends are 15-25% of total nodes
- [ ] At least 1 delayed consequence exists
- [ ] All principal paths converge at bottlenecks
- [ ] Budget is within limits
- [ ] Every edge has appropriate state effects
- [ ] Every edge has 2-5 resolution beats
- [ ] Every non-leaf node has 2-3 outgoing edges (no pass-through nodes)
- [ ] Every non-terminal, non-dead-end node has `choice_question`
- [ ] Bottleneck invariants hold on every incoming path
- [ ] preview.md is coherent and complete
- [ ] DAG visual renders with correct colors

**If ANY validation issue remains, the step is NOT complete. Run the validate-fix loop until clean.**
- [ ] state.json round-trips through serialization unchanged
