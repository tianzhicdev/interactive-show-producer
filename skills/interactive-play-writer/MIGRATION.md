# Migration Audit: make-interactive-show → interactive-play-writer

> Sorted every rule from the old `make-interactive-show` skills into one of three homes.

## Classification Key

| Home | Code | Lives in | Description |
|------|------|----------|-------------|
| **Generation Prompt** | A | step-2/step-3 SKILL.md prompts | Tells the model *how to write* (voice, structure, dialogue, format) |
| **Semantic Validator** | B | Separate LLM call (not the writer) | Asks "is this good / coherent / in-voice / meaningful?" |
| **Deterministic Check** | C | Pure Python code | Asks "is this established / does this count / within budget / in the registry?" |

---

## A. 角色设计 (Character Design)

### A1. 人物与角色关系设定

| Rule | Home | Target Step | Notes |
|------|------|-------------|-------|
| 主角有≥3个通过行为体现的性格特征 | B | step-3 semantic | Needs reading prose to judge |
| 反派有合理动机 | B | step-3 semantic | |
| 配角有≥1个"意外行为" | A → step-3 | step-3 prompt | Instruct writer to include surprises |
| 角色关系图存在≥1组三角关系 | C | step-1 bible | Check bible's relationship graph |
| 原作角色核心特质保留 | B | step-3 semantic | Requires source comparison |

### A2. 人物一致性

| Rule | Home | Target Step | Notes |
|------|------|-------------|-------|
| 同一角色在不同集/分支中称谓一致 | C | step-3 post-check | String match across scripts |
| 角色知识水平一致（不突然知道不该知道的事） | B | step-3 semantic | Needs understanding of scene context |
| 角色能力水平一致 | **C** | step-2 registry | **HIGH VALUE MIGRATION**: track abilities in registry as booleans; deterministic check that ability used → ability acquired |
| 角色语言风格一致 | B | step-3 semantic | |
| 分支中角色性格基底相同 | B | step-3 semantic | |
| 角色使用的能力/武器必须在获取后才使用 | **C** | step-2 registry | **HIGH VALUE**: registry var `has_<ability>` must be set before use |
| 已死亡角色不得在死亡集后出场 | **C** | step-2 registry | `<char>_alive = false` after death scene → deterministic |
| 新角色首次出场必须有介绍场景 | C | step-3 post-check | Check for character intro pattern in prose |

### A3. 人物成长弧光

| Rule | Home | Target Step | Notes |
|------|------|-------------|-------|
| 主角EP01 vs 最终集面对相似情境反应不同 | B | step-3 semantic | |
| 成长转折点有具体场景承载 | A → step-2 | step-2 prompt | Instruct beat design to include growth beats |
| 成长是渐进的 | B | step-3 semantic | |
| 不同结局反映不同成长方向 | A → step-2 | step-2 prompt | Structural concern — endings differ |

---

## B. 台词质量 (Dialogue Quality)

### B1. 台词内容质量

| Rule | Home | Target Step | Notes |
|------|------|-------------|-------|
| ≥3个角色遮住名字仍可区分 | B | step-3 semantic | |
| 关键场景对白有足够信息量 | A → step-3 | step-3 prompt | |
| 不存在"为解释而解释"的工具人台词 | B | step-3 semantic | |
| 旁白/独白不过度使用 | A → step-3 | step-3 prompt | |
| 台词契合时代/世界观背景 | B | step-3 semantic | |

### B2. 台词情感表达

| Rule | Home | Target Step | Notes |
|------|------|-------------|-------|
| 每集≥1个明确情绪节拍高点 | A → step-2 | step-2 prompt | Structural: beats must have emotional peak |
| 幽默元素不破坏整体氛围 | B | step-3 semantic | |
| 紧张场景用短句 | A → step-3 | step-3 prompt | |
| 角色情绪状态在舞台指示中标注 | A → step-3 | step-3 prompt | Format rule |

---

## C. 剧情与叙事 (Plot & Narrative)

### C1. 分支剧情丰富度

| Rule | Home | Target Step | Notes |
|------|------|-------------|-------|
| 每个决策点的不同选项至少有1个独立场景（≥300字差异化内容） | C | step-3 post-check | Word count diff between branches |
| 存在≥1条延时分岔 | **C** | step-2 | Check edge predicates span >1 episode |
| 分支非简单好/坏对立 | B | step-2 semantic | |
| 分支质量一致性（偏差≤30%） | **C** | step-3 post-check | Word count ratio between parallel branches |
| 延迟后果在后续集中有实际兑现 | **C** | step-2 | Effect set in EP X → predicate read in EP Y where Y>X+1 |

### C2. 情节完整性与钩子密度

| Rule | Home | Target Step | Notes |
|------|------|-------------|-------|
| EP01前2场景建立核心悬念 | A → step-3 | step-3 prompt | |
| 每集最后场景包含悬念/反转/决策压力 | A → step-2 | step-2 prompt | Structural beat requirement |
| 全剧≥1条贯穿线 | B | step-1 semantic | Bible should have dramatic question |
| 集间时间/空间跳跃有过渡 | A → step-3 | step-3 prompt | |
| 钩子密度：每8-10min至少1个小钩子 | C | step-2 | duration_min arithmetic |

### C3. 矛盾冲突与情节反转

| Rule | Home | Target Step | Notes |
|------|------|-------------|-------|
| ≥2层矛盾（外部+内心） | A → step-1 | step-1 bible | Bible should define both |
| 至少1个反转有≥2处伏笔 | A → step-2 | step-2 prompt | Beat design |
| 冲突不靠"误会"驱动 | B | step-3 semantic | |
| 中段无"主角无敌碾压"局面 | B | step-2 semantic | |

### C4. 情节逻辑性与分支闭环

| Rule | Home | Target Step | Notes |
|------|------|-------------|-------|
| 所有分支最终汇合或到达明确结局 | **C** | step-2 validator | DAG reachability check |
| 事件因果链清晰可追溯 | B | step-3 semantic | |
| 不依赖巧合推进关键剧情 | B | step-3 semantic | |
| 跨分支的信息不矛盾 | B | step-3 semantic | |
| 每个决策点每选项都有明确跳转目标 | **C** | step-2 validator | DAG edge completeness |
| 不存在"提到但未兑现"的设定 | B | step-3 semantic | |
| structure.json所有leads_to引用存在 | **C** | step-2 validator | Already in validate_structure.py |
| 不存在"凭空出现"的能力/武器 | **C** | step-2 registry | Registry var tracking |
| 已销毁/遗失物品不得后续使用 | **C** | step-2 registry | Registry var tracking |
| 已死亡角色不得复活出场 | **C** | step-2 registry | Registry var tracking |

### C5. 整体节奏安排与开局吸引力

| Rule | Home | Target Step | Notes |
|------|------|-------------|-------|
| EP01开场有"异常"或"冲突" | A → step-2 | step-2 prompt | Beat type for EP01 |
| 第一个互动决策点在EP01前半段 | C | step-1 spine | Check spine node positions |
| 全剧情绪强度"W形"或"锯齿上升" | B | step-2 semantic | |
| 每集时长误差≤30% | **C** | step-2 validator | duration_min arithmetic |
| 最终集节奏比前面更紧凑 | A → step-2 | step-2 prompt | |

---

## D. 互动设计 (Interaction Design)

### D1. 选项与剧情配合度

| Rule | Home | Target Step | Notes |
|------|------|-------------|-------|
| 选择出现在蓄压高潮处 | A → step-2 | step-2 prompt | Beat structure |
| question描述主角"此刻"的困境 | A → step-3 | step-3 prompt | |
| 选项是主角不同行动方式 | A → step-2/3 | Both prompts | |
| 每个选项后有完整结果展开 | A → step-3 | step-3 prompt | |
| 选择前的铺垫提供决策信息 | A → step-2 | step-2 prompt | |

### D2. 选项意义性

| Rule | Home | Target Step | Notes |
|------|------|-------------|-------|
| 0%重复选项text | **C** | step-2 validator | String equality check |
| 0%重复选项outcome | **C** | step-2 validator | String equality check |
| 每个选择不同选项通往不同集 | **C** | step-2 validator | DAG edge target uniqueness |
| ≥1个"无法两全"的选择 | B | step-2 semantic | |
| 不存在"送分选项" | B | step-2 semantic | |
| 选项文本不暗示正确答案 | B | step-2 semantic | |
| Flavor选择question紧扣本集蓄压高潮 | B | step-3 semantic | |
| 每个选项是观众"如果是我也想试试"的行动 | B | step-2 semantic | |

### D3. 玩家掌控感

| Rule | Home | Target Step | Notes |
|------|------|-------------|-------|
| 每集2-4个决策点 | **C** | step-2 | Count choices per episode |
| 选择后下一场景立即体现后果 | A → step-3 | step-3 prompt | |
| 后续集提及/呼应之前选择 | A → step-2 | step-2 prompt | Delayed effects |
| 不存在连续3+场景无互动 | **C** | step-2 | Count scenes between choices |
| 每个选择不同选项有差异化内容 | C | step-3 post-check | Word diff ≥ 300 chars |

### D4. 结局差异化与重玩吸引力

| Rule | Home | Target Step | Notes |
|------|------|-------------|-------|
| ≥4个差异化结局 | **C** | step-2 | Count ending nodes |
| 结局反映玩家全程选择累积 | A → step-2 | step-2 prompt | |
| 存在隐藏结局 | A → step-2 | step-2 prompt | |
| 单次通关只能看到~30-40%总内容 | **C** | step-2 | Path coverage ratio |

### D5. 玩法深度

| Rule | Home | Target Step | Notes |
|------|------|-------------|-------|
| ≥3个选择后果在后续集可见呼应 | **C** | step-2 | Effect→Predicate chain across episodes |
| ≥2个延时分岔 | **C** | step-2 | Same as C1 check |
| 不同路线有独占场景内容 | C | step-3 post-check | |

### D6. 试错空间

| Rule | Home | Target Step | Notes |
|------|------|-------------|-------|
| 死亡结局有≥200字专属描写 | C | step-3 post-check | Word count |
| ≥1个"看起来冒险"的选项提供独特体验 | B | step-2 semantic | |
| 全剧死亡结局数量合理（8集1-3个） | **C** | step-2 | Count dead-end nodes |

---

## E. 结构硬性要求 (Structural Requirements)

### E1. 分支收束结构

| Rule | Home | Notes |
|------|------|-------|
| EP01为共同开局 | **C** | Check entry node has no predicates |
| ≥1个3路分叉 | **C** | Count nodes with 3 out-edges |
| 菱形结构（分叉→汇聚） | **C** | Bottleneck reachability |
| 死胡同散布全剧（15-25%） | **C** | Dead-end node distribution |
| 单次通关路径集数 = round(episodes * playthrough_ratio) | **C** | Shortest path arithmetic |

### E2. 延时分岔与条件解锁

| Rule | Home | Notes |
|------|------|-------|
| ≥1个前置条件解锁 | **C** | Effect(EP X) → Predicate(EP Y), Y > X+1 |
| ≥1个条件触发差异 | **C** | Same effect leads to different node depends on predicate |
| 延时分岔在脚本中有明确体现 | B | Semantic check of prose |

### E3. 时长合规

| Rule | Home | Notes |
|------|------|-------|
| 每集时长在目标范围内 | **C** | `duration_min` arithmetic |
| 总时长在范围内 | **C** | Sum all `duration_min` |

### E4. 内容体量

| Rule | Home | Notes |
|------|------|-------|
| T/S ≥ 1/playthrough_ratio | **C** | Total word count / shortest path word count |

### E5-E9 (Decision Density, Causal Integrity, 爽点 Density, Script Format, Choice Quality)

All have deterministic and semantic components; classified inline above.

---

## Preview & DAG Visual Logic (Preserved)

The old skills rendered:
1. **Overview DAG** via Graphviz (`engine='dot'`, `format='png'`) with CJK font `Heiti SC`
2. **Per-episode graphs** with scene nodes, choice diamonds, branch edges
3. **Preview PDF** via fpdf2 with cover page + stats + graph + script text

**Carried into step-1:**
- Spine DAG renderer (`render_spine_dag.py`) adapts the overview graph pattern
- Node coloring by kind: scene=blue, bottleneck=orange, ending=green, dead_end=red
- Episode clusters as Graphviz subgraphs
- Edge labels show choice text + effects
- CJK font: `fontname='Heiti SC'` on graph/node/edge attrs

---

## High-Value Deterministic Migrations

These were LLM-verified in the old system but are actually deterministic — moved to code:

1. **Ability/weapon tracking**: "角色使用的能力/武器必须在获取后才使用" → Registry boolean `has_<ability>`, set via Effect, checked via Predicate before use node.

2. **Character alive tracking**: "已死亡角色不得在死亡集后出场" → Registry boolean `<char>_alive`, set to false via Effect on death edge.

3. **Item tracking**: "已销毁/遗失物品不得后续使用" → Registry boolean `has_<item>`.

4. **Delayed consequences**: "延迟后果在后续集中有实际兑现" → Effect written in EP X must be read as Predicate in some EP Y where Y > X.

5. **Option uniqueness**: "0%重复选项text/outcome" → String equality check on edge labels.

6. **Duration budget**: "每集时长误差≤30%" → `duration_min` arithmetic per episode.

7. **Branch quality balance**: "各平行线偏差≤30%" → Word count ratio between parallel branches.

---

## NEEDS HUMAN DECISION

1. **Duration heuristic at step-1**: How is `duration_min` estimated for spine nodes before prose exists? Options:
   - Beat count × 3min baseline (current assumption)
   - Fixed per episode (total_duration / episode_count)
   - Weighted by beat complexity (setup=1min, climax=2min)

2. **Episode envelopes**: Default even (`total_budget / episode_count`) or weighted toward climaxes? Current assumption: default even, author can adjust.

3. **Playthrough ratio at step-1**: Step-1 produces a linear spine. Should step-1 estimate how many spine nodes will be on the principal playthrough, or defer this entirely to step-2?

4. **"冲突不靠误会驱动"**: Is this a generation prompt constraint (tell the LLM not to use misunderstandings) or a semantic check? Could be either. Currently classified as B (semantic) since detecting "misunderstanding-driven conflict" requires reading comprehension.

5. **Flavor choice differentiation**: "Flavor选择的question必须紧扣本集蓄压高潮" — step-2 structural or step-3 prose? Currently classified as step-3 semantic since question text is prose.
