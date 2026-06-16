# quality_eval.md — The Goal Post（质量评判标准）

The **single source of truth for "good."** The loop scores each `--mini` output
against this rubric and keeps a code change only if the score moves **toward** it.

**This file is PROTECTED.** The loop may NEVER edit it. Only a human moves the goal post.

## Philosophy — judge the OUTPUT, not the process
We do **not** care *how* the harness produced the result. We care about two things:

1. **Format is decent** — enforced by the harness **JSON schema + PROTECTED
   validators** (`validation.py` D-checks), so a valid `--mini` *already conforms*.
   The eval only RE-CHECKS format as a **hard precondition gate (0 score weight)**: a
   failure means a loop change broke something the gates don't cover → hard-reject.
   **The loop may NOT change the schema** (enforced by a schema-edit guard + protected
   files). The score does not include format.
2. **The plot is great** — the real goal and **the entire 0–100 score**. Judged by an
   LLM against **novel-writing craft + interactive-game mechanics** — **one focused
   call PER dimension** (P1–P6), aggregated (de-correlates the halo effect). The
   self-contained Chinese rubric is the 剧情质量 section below.

A `--mini` run = 1 prologue choice node → 2 different ENDINGs. Each dimension is
0–10; total = weighted sum normalized to 0–100. **This file is self-contained — the
judge is given exactly this rubric and nothing else; every criterion needed to score
is stated below, not referenced elsewhere.**

---

# Bucket 1 — FORMAT & CONFORMANCE  (precondition GATE · 0 score) · deterministic
> Enforced upstream by the harness JSON schema + PROTECTED validators — a valid
> `--mini` already conforms. Re-checked here only as a pass/fail gate; **not scored**.
> The loop may not modify the schema.

### F1. Structure & schema  (weight 15)
| Check | Target |
|---|---|
| Node shape | non-ending nodes have **exactly 2** choices; ENDING nodes have 0 |
| Distinct endings | the prologue's 2 choices reach **two different** ending nodes |
| Question | non-empty `question` (≤30 字); every `选择 NNN` renders a `问题：` line |
| Labels | each choice label is a concrete action (动词+对象/手段), ≤8 字 |
| No dead-ends | `DEAD_END` count == 0 |
| Terminal markers | each ENDING contains a `结局：…` marker |
| Namecards | `【人名字幕条】` on first appearance, none duplicated in a node |
| Opening chapter | `root.chapters[0]` == the processed range's first chapter |

### F2. Scene format (场)  (weight 10)
| Check | Target |
|---|---|
| Starts with header | each node's content begins with a `scene_header` |
| Scene count | each node has **3–5** `scene_header` (场), each a distinct location/time |
| Beats present | each node has action beats; headers carry location+time (→ 场：/景：/时：/人：/▲) |

### F3. Language hygiene  (weight 5)
| Check | Target |
|---|---|
| Chinese | Chinese throughout (foreign language only where the plot demands) |
| JSON-safe | no raw English double quotes in text (uses 「」/『』) |

---

# Bucket 2 — 剧情质量 PLOT GREATNESS  (THE SCORE · 100) · LLM 评审
> 唯一目标：故事是否**精彩**。只评判输出本身，不关心它如何被生成。每个维度由一次
> **独立的、聚焦的 LLM 调用**打分（去除光环效应），再按下方权重聚合为 0–100 总分。
> 严苛打分：10 = 节展级，5 = 合格但平庸，0 = 破碎。以下细则自包含，评审据此打分。
> （P1–P6 权重为相对权重；总分 = 10 × Σ(维度分×权重) / Σ(权重)。）

### P1 — 每个节点都有"戏"：场必须翻转  （权重 18）
不翻转的节点是说明文，不是戏——"删掉或重写"（McKee p.259）。这是本评分的核心。
- **翻转/非事件检验**：节点价值极性必须翻转（+→− 或 −→+）。开场=收场极性 → 平场，重罚。
- **落差（Gap）**：角色预期行动达成的结果 ≠ 实际发生（McKee p.144）。只有动作无落差 = 低分。
- **冲突律**：必须有真实对抗力量；无冲突则无戏。
- **值得在意的节拍**：每个节点至少落一个——爽点（打脸/逆袭/反杀/身份揭露/护短/扮猪吃虎…）、
  反转揭示、或钩子（悬念/威胁）。
- 10 = 每个节点都狠狠翻转并落下难忘节拍；0 = 全是对话说明的"水戏"。

### P2 — 向高潮冲突累积  （权重 12）
开场是一段不断升级、最终引爆为选择的上升动作。
- 张力逐拍**升级**；赌注抬到场景最高层级（生死 > 使命 > 阵营 > 关系 > 脸面）。
- 问题由**最后 1–2 个节拍逼出**——突发、反转或最后通牒，在张力顶点抛出；不是平静的"你怎么做？"菜单。
- **选择前不得解决冲突**。两难必须当场在场：问题点名的地点/物件/对手/时间压力，结尾要摆到主角面前。
- 10 = 真正的高压锅，让选择显得紧迫且不可回避。

### P3 — 开场钩子与锚定  （权重 10）
- 从原著**字面第一场**开始（先抛悬念/谜面，再"为何在意"），不是把后段危机冷开场。
- 主角**身份/能力来源靠现场动作与他人反应演出**——绝不用旁白成段补叙前史。
- 10 = 既勾人、又通过动作交代清楚人/地/因的冷开场。

### P4 — 结局兑现：迥异且有重量  （权重 12）
- 两个结局是**截然不同的体验**——不同价值摆荡、不同命运、不同情绪极性，不是同一场换几个词。
- 每个都是该分支选择的**有力兑现**（选择的代价/收益在画面里落地）。可喜可悲，但必须**落得下去**。
- 倒数极性律：上行的选择别用绵软的上行结局兑现，让摆幅锋利（McKee p.225）。
- 10 = 两个你会真心纠结的结局；0 = 可互换/平淡。

### P5 — 互动游戏机制  （权重 12）
好的互动选择 ≠ 好的线性场景。一个伟大的两难必须满足以下全部：
- **两个竞争性收益**：每个选项写明可见的**卖点**（为何选它）+**代价**（失去什么）；两边都真有吸引力——
  不是"做大胆的事 vs 什么都不做"。
- **同级价值对撞**：真两难 = 同层级目标互撞（忠 vs 义、家人 vs 大局），不是"使命 vs 面子"这种跨层级。
- **最高赌注锚定**：问题挂在场景最高价值上（生死 > 使命 > 阵营 > 关系 > 脸面），而非琐事。
- **无被支配选项**：两边卖点同等具体；不是"立刻赢" vs "或许有用"；不是一边确定收益、一边模糊收益。
- **无置身事外项**：没有"走开/不理/旁观/沉默"——除非文本写明它换来了什么。
- **危险选项更诱人**：冒险项写得更鲜活诱人，稳妥项体面而不窝囊；坏结局也要精彩。
- **人格投票**：每个选项至少是 {爽感型 / 情感型 / 谨慎型} 三种玩家之一的首选；任一选项三票全无 = 伪选择。
- **选错也推进（fail forward）**：没有"无事发生"或变相重选；选错 = 有代价地成功，或跌入新麻烦。
- **合身份逻辑**：选项符合主角的使命、已知信息与人设（拿着叛国铁证的人不会把口角当优先级）。
- **问题点明双边代价**：「为了 A 冒 X 的险，还是保 B 放弃 Y？」——玩家选前必须有依据。
- **真正分叉**：两条路通向**实质不同**的结局——选择改变故事，而非只改措辞。
- **文案形式**：label 动词开头、具体动作（含对象/手段，非态度词如"冷眼退避"）；两 label 语法平行、≤8 字、互斥。
- 10 = 玩家会截图争论的两难；0 = 伪选择。

### P6 — 文笔与呈现  （权重 6）
- **演而非述**：关键事件用动作+对白演出；旁白只承载背景或人物内心，绝不承载剧情转折。
- **潜台词**：对白暗示意图而非直白说出（McKee p.256）。
- **质感与类型贴合**：有画面、具体、贴合原著调性。
- 10 = 电影感且精炼；0 = 套话、直给、说明腔。

---

## H. Genericity (anti-overfit) — HARD GATE (weight 0)
The harness code contains **no** hardcoded story content or story-specific fallbacks
(AGENTS.md "The One Rule"). Any code change that hardcodes content fails the
iteration outright, enforced across the rotating story set — a fix that helps one
genre must not regress another.

---

## Scoring & acceptance
```
score = 10 × Σ(P_score × P_weight) / Σ(P_weight)     # plot only, 0–100
```
- **Format (F1–F3)** is a deterministic **pass/fail gate** — it does NOT enter the
  score. A format failure = hard reject (it shouldn't happen on a valid run).
- **Plot (P1–P6)** is the entire score — **one focused LLM-judge call per dimension**
  (in `loop/eval.py`), aggregated by the weights above.

The loop runs all rotation stories **in parallel** each iteration; the iteration's
signal is the **mean** of the per-story scores. A change is kept only if
**mean ≥ best mean AND no genre fell below its floor (best − ε)**, with tests green
and gate H passing — otherwise reverted. (Mean alone would let a fix trade one genre
for another; the per-story floor forbids that.)

## What a 100 looks like
Well-formed per the schema, AND: opens on a true hook; 每个节点都翻转并落下值得在意的
节拍；张力累积逼出一个两难（两个竞争性收益）；两个迥异且有重量的结局兑现各自的选择；
演而非述的鲜活文笔——在言情、灵异、仙侠各类型上同样成立。

> Edit weights/targets here to steer the loop. Everything downstream reads this file.
