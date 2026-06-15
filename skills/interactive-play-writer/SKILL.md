---
name: interactive-play-writer
description: "Produce an interactive play spine from a raw story + guideline. Step-1: locks bible + registry + linear spine. Outputs preview.md + DAG visual."
---

# /interactive-play-writer — Step 1: Lock the World

From a **guideline + raw story**, extract highlights, author a story bible, declare a state registry, and produce a **linear story spine** with marked bottlenecks. Nothing branches yet — that's step-2.

## Parameters

Parse from user command:

| Parameter | Required | Default | Example |
|-----------|----------|---------|---------|
| `--story` | Yes | - | `~/novels/替嫁战王后.txt` |
| `--guideline` | Yes | - | `~/Downloads/替嫁战王后_guideline.docx` |
| `--episodes` | No | `10` | `8`, `10`, `12` |
| `--note` | No | `""` | `"三路线替嫁古言剧"` |
| `--output` | No | `~/Downloads` | `/path/to/output` |

## Language Rule

All output (bible, preview, spine summaries, DAG labels) in **Chinese**, unless story requires foreign language. JSON keys stay English, values Chinese.

## Execution Phases

### Phase 1: INIT

```bash
SKILL_DIR="skills/interactive-play-writer"
PROJECT_DIR="$OUTPUT_DIR/play_spine_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$PROJECT_DIR"
```

Save parameters to `$PROJECT_DIR/args.json`.

### Phase 2: CHUNK

Split the raw story at chapter boundaries using the existing chunker:

```bash
python skills/_archive/make-interactive-show/lib/chunker.py "$STORY_FILE" "$PROJECT_DIR" --max-chars 30000
```

This produces `$PROJECT_DIR/chunks/chunk_NNN.txt` + `manifest.json`.

### Phase 3: GUIDELINE + CHAPTER RANGE

Parse the guideline .docx to extract:
- Which chapters/sections to draw from
- Target tone/genre
- Route descriptions (if any)
- Episode count (if specified, overrides `--episodes`)
- Any authoring directions

```python
from docx import Document
doc = Document(guideline_path)
guideline_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
```

Save to `$PROJECT_DIR/guideline.txt`.

**Auto-detect chapter range**: Scan the guideline for chapter references (e.g., "第1-80章", "前80章", "chapter 1-80"). Cross-reference with the chunk manifest to identify which chunks cover those chapters. Only those chunks proceed to Phase 4 — chunks outside the guideline range are skipped.

If the guideline doesn't specify a chapter range, use all chunks.

### Phase 3.5: GENRE DETECTION

Before mining, auto-detect the story's genre from the guideline + first chunk content.

| Detection Keywords | Genre | Tag |
|-------------------|-------|-----|
| 穿越/重生/替嫁/空间/流放/宅斗/宫斗/嫡庶/世子/王妃/侯府 | 大女主古言 | `heroine_period` |
| 修仙/修炼/灵根/丹药/飞升/宗门/筑基/金丹/元婴 | 修仙 | `cultivation` |
| 总裁/豪门/商战/职场/霸道/首席/少爷/千金 | 都市 | `urban` |
| 末日/丧尸/异能/废土/避难所/基地 | 末世 | `apocalypse` |
| 悬疑/推理/密室/凶手/线索/真相 | 悬疑 | `mystery` |

Use the genre-specific 爽点/钩子 type tables for Phase 4 mining. Fall back to universal types if no genre matches.

Save detected genre to `$PROJECT_DIR/genre.json`: `{"genre": "大女主古言", "tag": "heroine_period"}`.

#### Universal Payoff Types (爽点, default)

| Type | Tag | Description | Required Setup |
|------|-----|-------------|----------------|
| 打脸 | `face_slap` | Mockers slapped by facts | Prior mockery/contempt |
| 扮猪吃虎 | `hidden_power` | Hidden power revealed | Prior underestimation |
| 升级突破 | `breakthrough` | Qualitative power change | Prior bottleneck/crisis |
| 碾压 | `domination` | Overwhelming victory | Prior enemy strength shown |
| 获宝 | `treasure` | Acquire rare resource | Prior value established |
| 揭秘 | `revelation` | Key truth revealed | Prior suspense/foreshadowing |
| 复仇 | `revenge` | Grudge settled | Prior harm/oppression |
| 逆袭 | `comeback` | Comeback from desperation | Prior despair |
| 智斗 | `outwit` | Strategic defeat | Prior info asymmetry |
| 团队高光 | `team_moment` | Team coordination miracle | Prior discord |

#### Universal Hook Types (钩子, default)

| Type | Tag | Description |
|------|-----|-------------|
| 悬念钩 | `suspense` | Unanswered key question |
| 反转钩 | `twist` | Unexpected twist |
| 情绪钩 | `emotional` | Cut at emotional peak |
| 信息钩 | `info_gap` | Partial reveal, key missing |
| 危机钩 | `crisis` | New threat approaching |
| 身份钩 | `identity` | Identity about to be exposed |

#### Genre: 大女主古言 (`heroine_period`) — Payoff Types

| Type | Tag | Description | Immersion Trigger |
|------|-----|-------------|-------------------|
| 怼人打脸 | `verbal_slap` | One sentence silences the mocker | "这话我也想说！" |
| 零元购/搬空 | `loot_sweep` | Clean out the enemy's assets | "搬！全搬走！" |
| 揭马甲 | `identity_reveal` | Hidden identity publicly exposed | "看看你们瞧不起的人是谁" |
| 护短 | `fierce_protection` | Protect family/weak ones fiercely | "我罩的人你敢碰？" |
| 断亲宣言 | `cutting_ties` | Publicly cut ties with toxic family | "不是你不要我，是我不要你" |
| 虐渣 | `punish_villain` | Make villains pay the price | "活该！报应！" |
| 白莲花翻车 | `expose_schemer` | Publicly tear off the hypocrite's mask | "我早看穿你了" |
| 囤货炫富 | `resource_flex` | While others starve, I feast | "羡慕吧？活该！" |
| 降维打击 | `dimensional_crush` | Modern knowledge crushes ancient problems | "小意思" |
| 男主折服 | `male_lead_awe` | Male lead awed by female lead | "服不服？" |

#### Genre: 大女主古言 (`heroine_period`) — Hook Types

| Type | Tag | Description |
|------|-----|-------------|
| 暗中注视 | `secret_observer` | Mysterious person watches in shadows |
| 身份猜疑 | `identity_suspicion` | Someone suspects the truth |
| 阴谋逼近 | `approaching_scheme` | Enemy's next scheme about to strike |
| 情感试探 | `emotional_probe` | Leads test each other, tension+attraction |
| 真相一角 | `partial_truth` | One corner revealed, bigger secret emerges |
| 危机预兆 | `crisis_omen` | Greater threat on the horizon |

### Phase 4: HIGHLIGHTS — Payoff & Hook Mining (Parallel)

**For each chunk within the guideline chapter range**, launch a parallel Task agent to mine payoff moments (爽点) and hooks (钩子).

```
Task agent prompt:
  "你是一位爽文节奏分析师。请从以下章节原文中挖掘所有"爽点时刻"和"钩子"。

   爽点 = 读者积累了期待/压抑后，获得满足感释放的瞬间。
   钩子 = 紧接爽点后的悬念/危机/反转，让读者"不看下一段会死"。

   识别标准：
   1. 有明确的"先抑后扬"：前面有压力/困境/挑衅/被低估，后面有反转/释放/胜利
   2. 读者会忍不住说"爽！""好看！""打得好！"的时刻
   3. 情感强度 >= 5（10分制）
   4. 对每个爽点找到最自然的钩子

   题材: {genre_label} — 使用以下爽点/钩子类型表:
   {genre_specific_type_tables}

   ## 大纲上下文
   {guideline_summary}

   ## 原文
   {chunk_text}

   请输出 JSON:
   {
     \"chunk_index\": N,
     \"chapter_range\": \"第X-Y章\",
     \"characters\": [{\"name\": \"\", \"role\": \"\", \"key_traits\": [], \"first_appearance\": \"\"}],
     \"beats\": [
       {
         \"rank\": 1,
         \"chapter\": \"第X章\",
         \"chapter_position\": \"前段|中段|后段\",
         \"satisfaction_type\": \"tag\",
         \"satisfaction_label\": \"中文类型名\",
         \"setup_summary\": \"铺垫描述（100字内）\",
         \"satisfaction_summary\": \"爽点描述（100字内）\",
         \"hook_type\": \"tag\",
         \"hook_label\": \"中文钩子名\",
         \"hook_summary\": \"钩子描述（100字内）\",
         \"branch_potential\": \"high|medium|low\",
         \"branch_idea\": \"分支创意描述\",
         \"emotional_intensity\": 8,
         \"key_characters\": [\"角色1\", \"角色2\"],
         \"original_text_excerpt\": \"原文关键段落摘录（200字内）\"
       }
     ],
     \"objects\": [{\"name\": \"\", \"significance\": \"\"}],
     \"relationships\": [{\"char1\": \"\", \"char2\": \"\", \"dynamic\": \"\"}]
   }

   宁可多挖不要漏，后续会筛选。"
```

**After all agents return**, filter and rank beats:
1. Sort all beats by `emotional_intensity` descending
2. Select top N beats (where N = `--episodes` count)
3. Ensure narrative continuity — don't skip beats that break the story chain
4. Type diversity — avoid 3+ consecutive beats of same satisfaction_type
5. Branch priority — prefer `branch_potential = high` at equal intensity
6. Rhythm curve — ensure intensity has ups and downs, not monotonic

Collect all highlight JSONs into `$PROJECT_DIR/highlights/`.
Save filtered beats to `$PROJECT_DIR/highlights/selected_beats.json`.

### Phase 4.5: CHAPTER INDEX

After highlights mining, build a chapter-to-chunk mapping so step-2/step-3 can look up source material by chapter range.

1. Parse `$PROJECT_DIR/chunks/manifest.json` for chunk boundaries (start/end chapter numbers per chunk)
2. Scan each chunk file for `第N章` / `第N回` patterns → build chapter→chunk mapping
3. Link highlight excerpts to their source chapters (using `chapter` field from highlight beats)
4. Save to `state.chapter_index` and `$PROJECT_DIR/chapter_index.json`

Entry format:
```json
[
  {
    "chapter_num": 5,
    "chapter_title": "第五章 夜半惊变",
    "chunk_indices": [2],
    "highlight_excerpts": ["原文关键段落摘录..."]
  }
]
```

This index enables step-2 to inject relevant source material when expanding nodes with `chapter_range` references (e.g., "第5-8章").

### Phase 5: BIBLE

Synthesize highlights + guideline into a story bible. **This is an LLM call in the main conversation.**

Compose `bible.md` covering:
- **Title** and genre/tone
- **Dramatic question** — the core tension driving the whole story
- **Protagonist** — name, arc, starting state, core conflict
- **Key characters** — name, role, motivation, relationship to protagonist
- **World** — setting, rules, key locations
- **Themes** — what the story is about thematically
- **Canon facts** — things that are TRUE and must not be contradicted
- **Source chapters** — which parts of the raw story were drawn from

Save as both `$PROJECT_DIR/bible.md` (human-readable) and embedded in `state.json`.

### Phase 6: REGISTRY

From the bible + guideline routes, declare the **state registry** — every variable that can exist.

**Type discipline** (critical):
- **boolean** by default — binary flags (`has_sword`, `met_advisor`, `ally_alive`)
- **enum** when values are mutually exclusive — `protagonist_status ∈ {disguised, revealed, exposed}`
- **bounded_int** ONLY for accumulation mechanics — `trust: 0..10`
- **NEVER** free-form strings or unbounded numbers

For each variable, declare:
- `key`: snake_case identifier
- `type`: boolean | enum | bounded_int
- `default`: initial value
- `description`: what this tracks (Chinese)
- For enum: `values` list
- For bounded_int: `min_val`, `max_val`

#### Registry Category Checklist

**Target: 15-25 variables** for a 10-12 episode story. Every category below must be represented:

| Category | Pattern | Min Vars | Examples |
|----------|---------|----------|---------|
| **Objects/Artifacts** | `has_<item>` (bool) | 2-4 | `has_sword`, `has_poison_evidence`, `has_royal_seal` |
| **Character States** | `<char>_alive` (bool), `<char>_allegiance` (enum) | 3-5 | `father_alive`, `advisor_allegiance ∈ {loyal, betrayed, dead}` |
| **Knowledge/Secrets** | `knows_<secret>` (bool) | 2-3 | `knows_true_identity`, `knows_betrayal_plan` |
| **Location/Progression** | `visited_<place>` or `<place>_destroyed` (bool) | 1-2 | `vault_looted`, `temple_destroyed`, `visited_forbidden_chamber` |
| **Relationship Flags** | `allied_with_<char>` or `<group>_trusts_player` (bool) | 2-3 | `allied_with_advisor`, `town_trusts_player`, `enemy_respects_player` |

#### Causal Chain Rule

Every variable must form at least one causal chain:
- **SET**: The var is written (via Effect) on at least one edge
- **READ**: The var is read (via `requires` or `invariant`) on at least one downstream node

Vars that are set-but-never-read or read-but-never-set are dead weight — remove them. If a var is set once and read once on the immediately next node, reconsider: it's likely just a gate that should be absorbed into the edge structure instead.

#### Anti-patterns (reject these)

- **Mood meters**: `grief_level: 0..10` — affect is not state, use free-text beats
- **Generic counters**: `choice_count`, `exploration_score` — too vague, not causally meaningful
- **Set-once-read-once**: A var that fires once and is checked once on the very next node — just use the edge directly
- **Unbounded accumulators**: `gold`, `experience` — no open-ended resources; use boolean thresholds (`has_enough_gold`)

Save as `$PROJECT_DIR/registry.json`.

### Phase 7: SPINE (Cornerstones Only)

Author the **cornerstone spine** — structural anchors only. Step-2 has complete freedom to create all intermediate nodes between cornerstones.

**CRITICAL: Step-1 produces CORNERSTONE nodes only.** Cornerstones are:
- **Prologue** (EP01): entry point, world setup
- **Bottlenecks**: convergence points where all paths must pass, with invariants
- **Endings**: terminal episodes

Everything else — regular scene episodes, branches, dead ends, beats, choices — is created by step-2. Step-1 locks the WHAT (canon, invariants, structure); step-2 creates the HOW (episodes, choices, narrative flow).

**Cornerstone IDs:** Space IDs to leave room for step-2 to fill intermediate nodes. For a 10-episode story with 2 bottlenecks:
```
EP01(prologue) → EP04(bottleneck) → EP07(bottleneck) → EP10(ending)
```
Step-2 fills EP02, EP03 between EP01→EP04; EP05, EP06 between EP04→EP07; etc.

For each cornerstone node:
- `id`: `EP01`, `EP04`, `EP07`, `EP10` — spaced to leave room — **populated**
- `kind`: `prologue` | `bottleneck` | `ending` — **populated** (NO `scene` nodes at step-1)
- `title`: short title (Chinese, ≤15 chars) — **populated**
- `summary`: what this cornerstone achieves (Chinese, ≤50 chars) — **populated**
- `goal`: narrative goal of this structural anchor — **populated**
- `duration_min`: ~3 minutes (default) — **populated**
- `requires`: entry predicates — **populated**
- `invariants`: bottleneck canon gates — **populated** (bottleneck only)
- `chapter_range`: source chapter range — **populated** (guides step-2 content)
- `entry_context`: WHERE/WHEN this cornerstone scene opens — **populated**
- `beats`: **EMPTY** (step-2 fills these)
- `choice_question`: **EMPTY** (step-2 fills this)

**Edges at step-1:** Direct connections between consecutive cornerstones:
```
EP01 →edge→ EP04 →edge→ EP07 →edge→ EP10
```
These are placeholder edges. Step-2 replaces them with the actual node chain.

**Bottleneck rules:**
- Bottleneck episodes are convergence points — all step-2 branches must pass through them
- They double as budget firewalls in step-2
- Each bottleneck gets **invariants** — predicates that must hold when any branch reaches it
- Invariants reference only declared registry vars

**What step-1 does NOT create:**
- ❌ Regular scene nodes (EP02, EP03, EP05, ...) — step-2 creates these
- ❌ Branch variant nodes (EP02A, EP03B) — step-2 creates these
- ❌ Dead end nodes (DE01, DE02) — step-2 creates these
- ❌ Beats or choices on any node — step-2 writes these
- ❌ Non-cornerstone edges — step-2 creates these

Save as `$PROJECT_DIR/spine.json`.

### Phase 8: VALIDATE

Run the deterministic validator:

```bash
python "$SKILL_DIR/lib/validate_spine.py" "$PROJECT_DIR"
```

Checks:
1. DAG integrity (all edge targets valid, no self-loops)
2. Reachability (BFS from entry, all endings reachable)
3. Registry consistency (effects/predicates reference declared vars, correct types)
4. Bottleneck alignment (convergence points reachable from all prior paths)
5. Duration budget (each episode ~3 min, no outliers)
6. Edge labels ≤ 8 CJK chars
7. Invariants reference declared vars

**If validation fails:** fix the spine/registry in the main conversation and re-run.

Output: `$PROJECT_DIR/validation_report.md`

### Phase 9: PREVIEW

Generate human-readable artifacts:

1. **preview.md** — walkthrough of the spine showing each episode's nodes, edges, registry vars, and invariants

```python
from data_model import load_state, save_preview_md
state = load_state(project_dir)
save_preview_md(state, project_dir)
```

2. **DAG visual** — Graphviz PNG of the spine

```python
from render_spine_dag import render_spine_dag
render_spine_dag(state, project_dir, fmt='png')
```

### Phase 10: OUTLINE (.docx)

Generate a polished outline document (Word) from bible + spine. This is the main
human-readable deliverable of step-1 — a shareable document for stakeholders.
No step-2 data needed; everything comes from bible + spine.

#### 10.1 Character bios

Use the `interactive-play-writer-characters-intro` skill (or Task agents) to
generate ~300-char Chinese bios for each character in the bible. Save to
`$PROJECT_DIR/characters.json`:

```json
{
  "characters": [
    {"name": "角色名", "identity": "一句话身份", "bio": "~300字小传", "group": "主角|家族|反派|盟友|中立"}
  ]
}
```

#### 10.2 Outline DOCX

Generate `$PROJECT_DIR/outline.docx` with these sections:

1. **封面**：作品名 + 互动影游制作大纲 + 章节范围·集数（不含日期）
2. **一、项目概述**：改编范围、集数规划、单次通关（~60分钟）、总内容量（~100分钟）、
   目标受众、核心类型、原著综述、本季弧线、核心看点
3. **二、世界观设定**：时代背景、核心设定（from `bible.world`）
4. **三、角色设定**：按阵营分组，每人附 ~300 字小传（from `characters.json`）
5. **四、分集大纲**：每集含章节来源、概要、**主要情节**（3个 beat）、
   玩家抉择（2-3 选项 + 后果）、变体说明、死胡同说明
6. **五、结局**：所有结局的基调和描述

**术语规范**：
- 使用「主要情节」（不是「叙事节拍」）
- 核心类型使用中文原生网文术语（如「古代言情·女强·穿越空间」）
- 不包含下一季/S2 内容，不显示生成日期
- 单次通关 ~60 分钟，总内容量 ~100 分钟

### Phase 11: LOCK

Assemble final `state.json`:

```python
from data_model import save_state, save_registry_json, save_spine_json, save_bible_md

save_state(state, project_dir)
save_registry_json(state.registry, project_dir)
save_spine_json(state.spine, project_dir)
save_bible_md(state.bible, project_dir)
```

Report to user:
1. Output file locations
2. Bible summary (protagonist, dramatic question)
3. Registry summary (N variables, types breakdown)
4. Spine summary (N nodes, N episodes, N bottlenecks, N endings)
5. Validation result (PASS/FAIL)
6. Outline docx location

**Final deliverables:**
```
$PROJECT_DIR/
  state.json          ← Full state (contract for step-2)
  bible.md            ← Human-readable canon
  registry.json       ← Standalone registry
  spine.json          ← Standalone spine
  preview.md          ← Human-readable walkthrough
  outline.docx        ← Outline document (shareable)
  characters.json     ← Character bios
  dag.png             ← Visual DAG
  validation_report.md
  args.json
  guideline.txt
  chunks/
  highlights/
```

## Data Model Reference

All types defined in `$SKILL_DIR/lib/data_model.py`:

- **RegistryVar**: `{key, type, default, values?, min_val?, max_val?, description}`
- **Predicate**: `{key, cmp, value}` — cmp ∈ {eq, ne, gt, gte, lt, lte}
- **Effect**: `{key, op, value}` — op ∈ {set, add}
- **Node**: `{id (EP01...), kind, title, summary, duration_min (~3), requires, invariants, beats}`
- **Edge**: `{id, src, dst, label, effects}`
- **Spine**: `{nodes, edges, entry_node}`
- **Registry**: `{vars}`
- **Bible**: `{title, genre, tone, dramatic_question, protagonist, characters, world, themes, canon_facts}`
- **SpineState**: `{version, step, metadata, bible, registry, spine, highlights}`

## Verification (at step-1)

**Deterministic (code):**
- Registry well-formed (unique vars, valid types/initial values)
- Spine well-formed (cornerstones only at step-1, bottlenecks in order, edges connect consecutive cornerstones)
- Every invariant references only declared vars
- All cornerstone nodes have kind ∈ {prologue, bottleneck, ending}

**Semantic (separate LLM call, light check):**
- Are the cornerstone placement and invariants dramatically coherent?
- Do bottleneck invariants capture meaningful narrative turning points?
- Are extracted highlights faithful to the source?

## Definition of Done

Step-1 is done when:
- [ ] Sample guideline + raw story produces locked registry + cornerstone spine + bible
- [ ] Spine contains ONLY cornerstone nodes (prologue, bottleneck, ending) — no scene nodes
- [ ] preview.md is human-readable and coherent
- [ ] DAG visual renders correctly
- [ ] Deterministic validator passes
- [ ] state.json round-trips through serialization unchanged
- [ ] All registry vars have correct types + defaults
- [ ] Bottleneck IDs are spaced to leave room for step-2 intermediate nodes
- [ ] Invariants reference only declared vars
