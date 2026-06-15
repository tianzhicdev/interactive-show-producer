# CREATIVE_WRITING.md — 生成工人指令

你输出的是**结构化 JSON**，harness 做确定性校验，违规即拒绝。

---

## 输入

- **端点 A、B**（外侧接口冻结）
- **故事圣经**（世界观、人物、背景）
- **章节范围** + 原文文本
- **未放置高光**（带权重）— 尽量覆盖高权重高光，放入 `covers`
- **目标**：`entryA_state`、`exitB_contract`、`invariants`、`varying_DO_NOT_REFERENCE`
- **注册表**（Registry）— 所有已声明事实的 ID、初始值、不变量标记
- **扩展类型**：
  - `LENGTH_EXTENDING` — 替换 A→B 直连边
  - `BRANCH_ADDING` — 保留 A→B，旁添平行路线

---

## 输出：每个节点必须包含的字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | 节点唯一标识 |
| `kind` | string | `prologue` / `scene` / `bottleneck` / `ending` |
| `content` | ContentElement[] | 剧本内容元素列表（见下方格式） |
| `chapters` | [int, int] | 覆盖的原作章节范围 |
| `covers` | string[] | 覆盖的高光 ID |
| `produces` | Effect[] | 本节点建立的事实 |
| `requires` | Req[] | 进入前必须已持有的事实 |
| `entry_invariants` | Req[] | 进入时必须成立的不变量 |
| `ending` | string | `NONE` / `ENDING` / `DEAD_END` |
| `question` | string\|null | ≤30 中文字（结局为 null） |
| `choices` | Choice[] | 非结局必须恰好 2 个到 2 个不同目标 |
| `entry_context` | string | WHERE/WHEN 进入场景 |
| `exit_context` | string | WHERE/WHEN 离开场景 |

### content 元素格式

每个元素是 `{type, ...}` 对象。必须以 `scene_header` 开头，普通节点≥15个元素，死胡同≥5个。

| type | 必填字段 | 说明 |
|------|----------|------|
| `scene_header` | `location`, `time`, `characters[]` | 场景头：地点、时段、出场角色 |
| `action` | `text`; 可选 `shot` | 舞台指示/镜头描写 |
| `dialogue` | `speaker`, `line`; 可选 `emotion` | 角色对白 |
| `narration` | `text` | 叙述/旁白 |
| `namecard` | `name`, `title` | 角色字幕条：首次出场时必加 |

示例：
```json
"content": [
  {"type": "scene_header", "location": "密林深处", "time": "深夜", "characters": ["林逸", "苏瑶"]},
  {"type": "action", "text": "月光透过树缝洒下斑驳的光影", "shot": "全景"},
  {"type": "dialogue", "speaker": "林逸", "line": "你确定要走这条路？", "emotion": "担忧"},
  {"type": "narration", "text": "苏瑶没有回答，目光坚定地望向前方"},
  {"type": "action", "text": "远处传来低沉的嚎叫"}
]
```

---

## 会被拒绝的情况（D 检查）

- **D1**: `requires` 中的事实在所有进入路径上的 guaranteed 值不匹配
- **D2**: `label_requires` 在选择时刻的状态不满足
- **D3**: `entry_invariants` 在进入时不成立
- **D5**: 使用了未在注册表中声明的事实 ID
- **D6**: 图有环
- **D7**: 翻转了不变量事实（invariant）
- **D9**: 结构违规 — 具体包括：
  - `kind` 不是 4 种之一
  - 缺少 `entry_context` 或 `exit_context`
  - `content` 非数组或元素数不足（普通≥15，DEAD_END≥5）
  - `content[0]` 不是 `scene_header` 类型
  - DEAD_END 的内容末尾无 `BE` 独立行
  - ENDING 的内容末尾无 `结局：结局名称`
  - 非结局节点不是恰好 2 个选择到 2 个不同目标
  - 结局/死胡同有选择
  - `question` 超 30 字 / `label` 超 8 字
  - `question` 使用泛模板（如何应对/如何回应/怎么办/如何处理/怎么应对）
  - 两个选择 label 前两字相同（必须使用不同动词）
  - `resolution` 不是恰好 2 个短节拍
- **D10**: 不可达或无法到达 ENDING
- **D11**: 场景瞬移 — 父节点 exit_context 与子节点 entry_context 地点无交集

---

## content 写作要求

- `action` 元素标注镜头（`shot` 字段）：特写、中景、全景、手持、俯拍
- `dialogue` 元素格式：`speaker` + `line`，可选 `emotion`
- 在选择前推进到 **TENSION PEAK**，不要在玩家决策前解决冲突
- `DEAD_END` 的最后一个元素必须是 `{"type": "action", "text": "BE"}`
- `ENDING` 的最后一个元素必须是 `{"type": "action", "text": "结局：结局名称"}`

---

## 断言 vs. 预设 — 防 Bug 核心规则

对每个涉及的事实问：*如果读者第一次看到这个节点，能否讲得通？*

- **能 → 断言**：首次出现即引入。`requires: []`。人物直接出场是正常的。
- **不能 → 预设**：回引了之前展示过的内容。加入 `requires`。

**预设触发词**：确指表达（"*那把*铜钥匙"）、"又"、"还是"、"再次"、"如约"、"你还记得"、"同一个人"。
不确指首次出现（"一个叫玛拉的女人"）是断言，无需 requires。

---

## 事实规则

- 优先复用注册表中已有的 fact ID
- 新增事实必须在 `new_facts` 中声明
- 不可翻转 invariant 事实（初始值永远不变）
- `produces` / `requires` 保持最小化
- 事实 ID 前缀：`player.*`（玩家已知）、`char.<名>.* `（角色知道）、`world.*`（客观事实）

---

## 不变量事实详解

注册表中标记 `invariant=true` 的事实是**世界公理** — 值被锁定在 `initial`，永远不能改变。
你的 `produces` 不可将 invariant 事实设为不同于其初始值的值。
prose 中也不可暗示 invariant 事实发生了变化。

---

## 生成顺序（MANDATORY）

你必须按此顺序思考和生成每个非结局节点：

1. **先定选择困境**：基于 A 的 exit_context 和原文，确定 question + 2 个 choice labels
   - question 必须是角色内心的两难，不是"如何应对/回应"
   - 两个 label 必须是语义不同的动作（不同动词），不是同一动作的不同说法
2. **再写 content**：从 A 的 exit_context 出发，逐步升级到 question 描述的两难
3. **最后填元数据**：produces, requires, chapters, covers

---

## 选择规则

- `label` ≤8 中文字，写玩家动作，不写结果，不剧透目标内容
- 每个选择通往**实质不同的状态或路径**
- 禁止伪选择、不合逻辑的选择、倒退选择
- `resolution` 恰好 2 个短句，展示选择结果
- 如果标签提及目标节点才揭示的事物 → 加入 `label_requires`

---

## 选择张力 — 让选择嵌入场景冲突

**核心原则**：选择不是菜单，是角色在压力下的抉择。content 必须把玩家推到不得不选的临界点。

### 五种张力模式（至少用一种）

1. **道德冲突**：两个选项都有代价，无"正确答案"
   - 例：救眼前的人 vs 追凶手防止更多受害者
2. **风险不对称**：一个选项安全但收益低，另一个高风险高回报
   - 例：按计划撤退 vs 孤身潜入敌营
3. **角色考验**：选择暴露角色的价值观或底线
   - 例：遵守承诺 vs 违背承诺救更重要的人
4. **NPC 期望**：选择会让某个 NPC 失望或满意
   - 例：听从师父指示 vs 跟随自己判断
5. **不可逆性**：选择关上一扇门，打开另一扇
   - 例：毁掉证据保护某人 vs 上交证据揭露真相

### content 中如何铺设

- 选择前 3-5 个 action/dialogue 元素必须升级张力（争吵加剧、时间紧迫、新信息冲击）
- question 提炼为角色内心的两难（不是"你想去哪"，而是"你愿意冒这个险吗"）
- label 写玩家的**动作**，不写结果："揭发他" vs "替他隐瞒"（不是"好结局" vs "坏结局"）

---

## 场景连续性 — 禁止瞬移

**核心原则**：entry_context 必须与父节点的 exit_context 在物理上可达。

- 如果 A 结束于"荒野·深夜"，你的场景不能开始于"王府大殿·白天"
- 时间只能前进（除非明确闪回，用 narration 标注）
- scene_header 的 location 必须与 entry_context 一致
- 多章节跨度时，选择最靠近 A.exit_context 时间线的内容，不要跳到更早的章节事件

---

## 禁忌

- 不要预设 `entryA_state` 中没有的事实
- 不要翻转不变量
- 不要在有注册表 ID 的情况下发明新名字
- 不要写引用了 `produces`/`requires` 中未声明内容的文字
- 不要引用 `varying_DO_NOT_REFERENCE` 中的事实

---

## 修复请求

你会收到之前的子图 + 反馈列表。
- 确定性违规（D1-D10）是**权威的**，必须修复
- 语义违规（S1-S5）是建议性的，也应修复
- 逐条处理，最小编辑
- 如果是"普通出场被误当成前置条件" → 删除不必要的 `requires`，在当前节点自然引入
