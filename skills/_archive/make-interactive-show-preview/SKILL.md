---
name: make-interactive-show-preview
description: "Preview an interactive show design: story bible + 爽点mining + heavy-branching episode DAG. No scripts."
---

# /make-interactive-show-preview

快速预览互动影游的故事圣经、爽点挖掘和集级分支结构。不生成脚本，仅输出摘要 + 流程图 PDF。

## 核心模型：爽点驱动短剧集

每集约 3 分钟，遵循抉择驱动节奏：

```
[铺垫/蓄压 setup ~1.5min] → [抉择时刻 CHOICE] → [分支结果 resolution ~1.5min per option]
```

- **铺垫/蓄压**：建立压力、困境、挑衅，蓄积情绪张力，把主角逼到必须行动的墙角
- **抉择时刻**：在最紧张的一刻，画面定格——观众替主角选择行动方式
- **分支结果**：每个选项各自展开不同的爽点释放方式，并以钩子收尾引向下集

**一集 = 一个蓄压 + 一个抉择 + 两种爽法。**

铁律：选择 = 主角的行动决策，不是剧情走向。
- 观众控制的是"主角怎么做"，不是"接下来发生什么"
- 选择出现在主角被逼到墙角、必须立刻行动的那个瞬间
- 每个选项都是一种合理的、观众"如果是我也想试试"的行动
- 选项之后的内容是该行动的结果——不同的爽点释放方式

## 爽点类型分类

| 类型 | 标签 | 描述 | 必要铺垫 |
|------|------|------|----------|
| 打脸 | `face_slap` | 嘲讽者被事实啪啪打脸 | 先有嘲讽/轻视 |
| 扮猪吃虎 | `hidden_power` | 隐藏实力后一鸣惊人 | 先被低估/伪装 |
| 升级突破 | `breakthrough` | 修为/能力发生质变 | 先有瓶颈/积累/危机 |
| 碾压 | `domination` | 以压倒性优势击败强敌 | 先展示敌人的强大 |
| 获宝 | `treasure` | 获得珍稀资源/宝物/功法 | 先铺垫宝物的珍贵 |
| 揭秘 | `revelation` | 关键真相大白 | 先有悬念/误导/伏笔 |
| 复仇 | `revenge` | 以牙还牙、恩怨了结 | 先有被害/压迫 |
| 逆袭 | `comeback` | 绝境翻盘 | 先有绝望/困境 |
| 智斗 | `outwit` | 用智谋击败对手 | 先有信息差/陷阱布局 |
| 团队高光 | `team_moment` | 团队配合创造奇迹 | 先有分歧/磨合 |

## 钩子类型分类

| 类型 | 标签 | 描述 | 示例效果 |
|------|------|------|----------|
| 悬念钩 | `suspense` | 抛出未答的关键问题 | "那个人究竟是谁？" |
| 反转钩 | `twist` | 出乎意料的转折 | "等等，他居然是…？" |
| 情绪钩 | `emotional` | 在情绪最高点戛然而止 | 观众的情绪无处释放 |
| 信息钩 | `info_gap` | 部分透露，关键缺失 | "他知道了真相，但…" |
| 危机钩 | `crisis` | 新的威胁/危险迫近 | "暗处，一双眼睛…" |
| 身份钩 | `identity` | 身份即将暴露/被发现 | "他缓缓摘下面具…" |

## 参数

解析用户指令中的以下参数：

| 参数 | 必填 | 默认值 | 示例 |
|------|------|--------|------|
| `--file` | 是 | - | `/path/to/story.txt` 或已有项目目录 |
| `--episodes` | 否 | `50` | `30`, `50`, `80` |
| `--episode-duration` | 否 | `3m` | `2m`, `5m` |
| `--playthrough-ratio` | 否 | `0.6` | `0.5`, `0.7` |
| `--options-per-selection` | 否 | `2-3` | `2-4` |
| `--branching` | 否 | `heavy` | `light`, `medium`, `heavy` |
| `--note` | 否 | `""` | `"修仙+种田+轻松幽默"` |
| `--lang` | 否 | `zh` | `en`, `zh` |
| `--output` | 否 | `~/Downloads` | `/path/to/output` |
| `--chapter-range` | 否 | 全部 | `1-80` |

如有必填参数缺失，向用户询问。

**语言规则**: 所有输出内容一律使用中文，除非情节或台词需要外语。JSON key 保持英文，value 使用 `--lang` 语言。

**参数推导**（自动计算）：
```
total_duration = episodes * episode_duration
playthrough_episodes = round(episodes * playthrough_ratio)
playthrough_duration = playthrough_episodes * episode_duration
```

示例：`--episodes 50 --episode-duration 3m --playthrough-ratio 0.5` → 总150分钟，单次通关25集=75分钟

**分支密度**（由 `--branching` 决定）：

| 级别 | 分叉点密度 | 单次通关占比 | 适合 |
|------|-----------|-------------|------|
| `light` | 每10集1个分叉 | 70-80% | 线性叙事、新手向 |
| `medium` | 每6集1个分叉 | 55-65% | 平衡型 |
| `heavy` | 每4集1个分叉 | 45-55% | 高复玩性、多路线 |

**智能输入检测**：如果 `--file` 指向含 `chunks/manifest.json` 的目录，跳过 CHUNK。如果含 `story_bible.json`，跳过 DISTILL + BIBLE。如果含 `beats.json`，跳过 MINE。

## 制作流程总览

```
Phase 1: CHUNK    → 切分大文本为可处理的块
Phase 2: DISTILL  → 提炼每个块的摘要（并行）
Phase 3: BIBLE    → 合并为故事圣经
Phase 4: MINE     → 从故事中挖掘爽点+钩子 ★ 核心新步骤
Phase 5: TOPOLOGY → 将爽点编排为集级DAG + 设计分支
Phase 6: RENDER   → 生成预览 PDF
```

## 执行指令

### Step 0: 初始化

```bash
PROJECT_DIR="$OUTPUT_DIR/interactive_show_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$PROJECT_DIR"
```

保存参数（含推导值）到 `$PROJECT_DIR/args.json`。

**大纲检测**：如果 `--note` 中包含 `.docx` 文件路径，用 `python-docx` 读取该文件并存储为 `outline_text`，供 TOPOLOGY 阶段使用。

### Step 1: CHUNK 切分故事

**如果已有切分（检测到 `$PROJECT_DIR/chunks/manifest.json`），跳过。**

如果指定了 `--chapter-range`（如 `1-80`），先用 `grep`/`awk` 从原文中提取指定章节范围，写入临时文件，再切分。

运行切分脚本：

```bash
python "$SKILL_DIR/../make-interactive-show/lib/chunker.py" "$STORY_FILE" "$PROJECT_DIR" --max-chars 30000 --overlap 2000
```

技能库路径：
`/Users/biubiu/projects/interactive-show-producer/skills/make-interactive-show/lib/chunker.py`

读取 `$PROJECT_DIR/chunks/manifest.json` 确认切分结果。

### Step 2: DISTILL 提炼摘要

**如果已有故事圣经（检测到 `$PROJECT_DIR/story_bible.json`），跳过此步和 Step 3。**

对每个块文件，**使用 Task 代理并行处理**（每次最多 4 个）：

```markdown
# 第 NNN 块摘要

## 核心事件
- [事件 1]

## 登场/发展角色
- [角色名]：[描述]

## 世界观细节
- [设定]

## 人物关系与冲突
- [关系]

## 情感节拍
- [关键情感时刻]

## 爽点时刻（初步标记）
- [潜在爽点 1：类型 + 简述]
- [潜在爽点 2：类型 + 简述]

## 章节范围
- 覆盖章节：[范围]
```

### Step 3: 合并为故事圣经

写入 `$PROJECT_DIR/story_bible.json`（格式同之前版本）。

### Step 4: MINE 爽点挖掘 ★

**核心新步骤：从原始故事中系统性挖掘爽点和钩子时刻。**

**如果已有 `$PROJECT_DIR/beats.json`，跳过此步。**

#### 4.1 并行爽点挖掘

读取故事圣经和所有块。**使用 Task 代理并行处理**——每个代理处理 1-2 个块。

每个代理的任务：
1. **读取分配的块文件原文**（不是摘要，是原文 `chunks/chunk_NNN.txt`）
2. 同时参考故事圣经（了解全局上下文）
3. 识别其中所有"爽点时刻"——满足感释放点
4. 为每个爽点确定完整结构

代理输出格式：
```json
{
  "chunk_id": "chunk_001",
  "chapter_range": "第1-8章",
  "beats": [
    {
      "rank": 1,
      "chapter": "第3章",
      "chapter_position": "中段",
      "satisfaction_type": "hidden_power",
      "satisfaction_label": "扮猪吃虎",
      "setup_summary": "铺垫描述（100字内）",
      "satisfaction_summary": "爽点描述（100字内）",
      "hook_type": "suspense",
      "hook_label": "悬念钩",
      "hook_summary": "钩子描述（100字内）",
      "branch_potential": "high|medium|low",
      "branch_idea": "分支创意描述",
      "emotional_intensity": 8,
      "key_characters": ["角色1", "角色2"],
      "connects_to_previous": "与上一个爽点的叙事连接",
      "original_text_excerpt": "原文关键段落摘录（200字内）"
    }
  ]
}
```

代理提示模板：
```
你是一位爽文节奏分析师。请从以下章节原文中挖掘所有"爽点时刻"。

爽点 = 读者积累了期待/压抑后，获得满足感释放的瞬间。

识别标准：
1. 有明确的"先抑后扬"：前面有压力/困境/挑衅/被低估，后面有反转/释放/胜利
2. 读者会忍不住说"爽！""好看！""打得好！"的时刻
3. 情感强度 ≥ 5（10分制）

对每个爽点，还要找到它之后最自然的"钩子"——紧接爽点发生后的悬念/危机/反转，能让读者"不看下一段会死"。

以及判断这个爽点处是否适合设置互动分支（branch_potential）——是否有自然的二选一/三选一时刻。

## 故事圣经（全局上下文）
{story_bible_summary}

## 原文
{chunk_text}

请输出 JSON 格式。宁可多挖不要漏，后续会筛选。
```

#### 4.2 爽点汇总与筛选

汇总所有代理结果。按以下标准筛选出 `--episodes` 个爽点：

**筛选算法**：
1. 按 `emotional_intensity` 降序排列
2. **保障叙事完整性**：确保故事主线不断裂——如果删除某个爽点会导致后续剧情无法理解，则必须保留
3. **类型多样性**：连续3个爽点不能是同一类型
4. **分支优先**：`branch_potential = high` 的爽点在同等强度下优先
5. **节奏曲线**：确保强度有起伏——不能单调递增，中间需要"谷底"来为后续高潮蓄力
6. 如果章节范围限定（`--chapter-range`），只从该范围内筛选

写入 `$PROJECT_DIR/beats.json`：
```json
{
  "mining_stats": {
    "total_mined": 120,
    "selected": 50,
    "dropped": 70,
    "selection_criteria": "intensity + narrative_continuity + diversity + branch_potential"
  },
  "beats": [
    {
      "episode_id": "EP01",
      "chapter_source": "第1-2章",
      "satisfaction_type": "hidden_power",
      "satisfaction_label": "扮猪吃虎",
      "setup": "铺垫描述",
      "satisfaction": "爽点描述",
      "hook_type": "suspense",
      "hook_label": "悬念钩",
      "hook": "钩子描述",
      "branch_potential": "high",
      "branch_idea": "分支创意",
      "emotional_intensity": 8,
      "key_characters": ["角色1"]
    }
  ],
  "intensity_curve": [8, 6, 7, 9, 5, 6, 8, 10, ...]
}
```

### Step 5: TOPOLOGY 集级DAG拓扑

基于 `beats.json` 中的爽点（和大纲，如有）设计集级有向无环图。

#### 5.1 大纲驱动拓扑（当检测到大纲时）

当 Step 0 检测到大纲 `.docx` 时，TOPOLOGY 分三步：

**Phase 1: 解析大纲** — 从 docx 中提取：
- 主要分叉结构（路线 A/B/C）
- 关键选择节点及其具体 A/B 选项和后果
- 汇聚点和结局

**Phase 2: 从大纲构建骨架 DAG** — 大纲结构 = DAG 骨架：
- 公共前缀集：大纲中首次分叉前的事件
- 分叉点：完全按大纲指定
- 关键节点集：大纲中"关键节点"章节的内容
- 填充集：用 MINE 阶段的 beats 填充关键节点之间的空隙
- 汇聚和结局集：按大纲安排

**Phase 3: 设计菱形 DAG + 死胡同** — 对每一集：
- 每集 2-3 个选项，每个选项通往不同的集
- 在关键节点使用大纲中的选项（作为菱形的分叉点）
- 菱形分支经 1-2 集后汇聚
- 按死胡同散布规则（每 3-5 集穿插 1 个死胡同选项）添加死胡同集

未检测到大纲时，直接基于 `beats.json` 构建菱形 DAG（按下方 DAG 构建规则）。

#### 5.2 选择规则：每集必须有选择，每个选项必须通往不同的集

**核心铁律 #1：每一集都必须有观众选择。没有例外。不存在无互动的"过场集"。**

**核心铁律 #2：每集的每个选项必须 `next` 到不同的集。没有例外。**

没有"flavor"选择。每个选择都是真正的分叉——玩家看到不同的内容。

**所有选择必须满足：**
1. 2-3 个选项，每个 `next` 指向不同的集（或死胡同集）
2. 选项文本唯一，≤ 8 中文字符
3. 每个选项有不同的 `outcome`
4. `question` 描述主角此刻面对的困境（禁止通用"接下来怎么办"）
5. 至少部分选项指向死胡同集（错误选择 = 游戏结束）

**好示例：**

| 钩子 | 问题 | 选项A | 选项B | 选项C |
|------|------|-------|-------|-------|
| 官差鞭打大夫人 | 如何对付沿途官差？ | "恩威并施" → EP05a | "杀鸡儆猴" → EP05b | "忍气吞声" → DE03（死胡同：官差变本加厉） |
| 发现跟踪者 | 暗处有人窥视，如何应对？ | "设饵引蛇" → EP08a | "以退为进" → EP08b | — |

**禁止：**
- 两个选项 `next` 指向同一集（即使文本不同也不行）
- 两个选项文本或 outcome 相同
- 问题是通用模板（"下一步怎么办"、"你的选择是"）

#### 5.3 DAG构建规则：菱形结构 + 死胡同

**核心结构：菱形（Diamond）**

每个选择点分裂为 2-3 条路径，经过 1-2 集后重新汇聚。这样每个选择都通往不同的集，但总集数可控。

```
        EP-A ──→ ┐
EP-X ──→         EP-Y（汇聚点）
        EP-B ──→ ┘
        DE-1（死胡同，游戏结束）
```

**死胡同（Dead End）散布规则：**
- 总集数的 15-25% 应为死胡同集（如30集中有5-8个死胡同）
- 死胡同必须**均匀散布**全剧——不能集中在开头或结尾
- 每 3-5 个正常集之间至少出现 1 个死胡同选项
- 死胡同集很短（~30秒），展示"选错了"的后果，然后游戏结束
- 死胡同集的 `choice` 为 `null`

**DAG 构建步骤：**

1. **排列主线爽点**：按叙事顺序排列筛选出的爽点
2. **设计菱形**：每集的选择 → 2-3 个不同集（含可能的死胡同）
3. **汇聚**：菱形的两条路径在 1-2 集后汇聚到同一个后续集
4. **多结局分叉**：终局段不汇聚，而是走向不同结局

**单次通关路径**：玩家从 EP01 到结局，经过的集数 = `playthrough_episodes`。
**总集数** = 主线集 + 菱形分支集 + 死胡同集。

##### 菱形DAG模板（30集示例）

```
EP01 → EP02a / EP02b / DE01
EP02a → EP03 / DE02          ← 菱形：EP02a和EP02b都汇聚到EP03
EP02b → EP03 / DE02
EP03 → EP04a / EP04b
EP04a → EP05 / DE03
EP04b → EP05 / DE04
EP05 → EP06a / EP06b / DE05
...
EP-last → ENDING_A / ENDING_B / ENDING_C  ← 终局不汇聚

单次通关约 12-15 集（从30集中走一条路径）
死胡同 5-8 集，散布全剧
```

**关键**：没有任何一集的两个选项指向同一集。

#### 5.4 structure.json — 精简结构

structure.json 只负责 **DAG 拓扑 + 选择设计**。角色/世界观在 story_bible.json，爽点详情在 beats.json。脚本生成时三者联合使用。

**设计原则**：
- 一个 `episodes` 数组即是图——`choice.options[].next` 定义边
- 不单独维护 `episode_graph.nodes` 或 `fork_points`（从 episodes 可推导）
- 每集只保留：id、标题、路线、一句话概要、爽点类型标签、选择
- 不存 `entry_state`/`exit_state`/`subtitle`/`duration_minutes`（脚本阶段按需从 story_bible 推断）

写入 `$PROJECT_DIR/structure.json`：

```json
{
  "episodes": [
    {
      "id": "EP01",
      "title": "集标题（4-8字）",
      "thread": "主线",
      "chapter_source": "第1-2章",
      "summary": "一句话概要（≤40字）",
      "beat_type": "hidden_power",
      "beat_label": "扮猪吃虎",
      "is_dead_end": false,
      "choice": {
        "question": "主角此刻面对的困境——必须行动的那一刻",
        "options": [
          {"text": "主角的行动方式A（≤8字）", "outcome": "后果A", "next": "EP02a"},
          {"text": "主角的行动方式B（≤8字）", "outcome": "后果B", "next": "EP02b"},
          {"text": "主角的行动方式C（≤8字）", "outcome": "后果C（死胡同）", "next": "DE01"}
        ]
      }
    },
    {
      "id": "DE01",
      "title": "死胡同标题",
      "thread": "死胡同",
      "chapter_source": "",
      "summary": "选错了的后果",
      "beat_type": "dead_end",
      "beat_label": "死胡同",
      "is_dead_end": true,
      "choice": null
    }
  ],
  "endings": [
    {
      "id": "ENDING_A",
      "name": "结局名称",
      "episode": "EP-last-a",
      "tone": "欢喜|苦乐参半|悲剧|开放",
      "description": "一句话结局描述"
    }
  ],
  "stats": {
    "total_episodes": 30,
    "total_dead_ends": 6,
    "story_episodes": 24,
    "playthrough_episodes": 12,
    "total_endings": 3,
    "playthrough_ratio": 0.4
  }
}
```

### Step 6: RENDER 生成预览 PDF

组装预览状态文件 `$PROJECT_DIR/state.json`：

```json
{
  "version": "3.0",
  "mode": "preview",
  "model": "shuangdian_driven",
  "metadata": {
    "title": "...",
    "source_file": "...",
    "episodes": 50,
    "episode_duration": "3m",
    "playthrough_ratio": 0.5,
    "branching": "heavy",
    "options_per_selection": "2-3",
    "note": "...",
    "lang": "zh",
    "created_at": "ISO 时间戳"
  },
  "story_bible": { "...来自 story_bible.json..." },
  "structure": { "...来自 structure.json..." },
  "beats": { "...来自 beats.json..." },
  "scripts": {}
}
```

运行渲染器（预览模式）：

```bash
python "/Users/biubiu/projects/interactive-show-producer/skills/make-interactive-show/lib/renderer.py" "$PROJECT_DIR" --preview
```

### Step 6.5: OUTLINE 生成大纲文档 (.docx)

基于 `story_bible.json`、`structure.json`、`beats.json` 生成一份正式的互动影游大纲 Word 文档。

#### 6.5.1 角色小传生成

使用 Task 代理按 `skills/interactive-play-writer-characters-intro/SKILL.md` 的规范为每个角色生成 ~300 字中文小传。输出 JSON：

```json
{
  "characters": [
    {"name": "角色名", "identity": "一句话身份", "bio": "~300字小传", "group": "主角|盟友|反派|中立"}
  ]
}
```

保存到 `$PROJECT_DIR/characters.json`。

#### 6.5.2 DAG 图渲染

用 Graphviz 渲染 DAG 拓扑图（PNG），直接从 `structure.json` 构建：

```python
import graphviz, tempfile, os

CJK_FONT = 'Heiti SC'
g = graphviz.Digraph('OUTLINE', format='png', engine='dot')
g.attr('graph', fontname=CJK_FONT, rankdir='TB', dpi='200', ...)
g.attr('node', fontname=CJK_FONT, fontsize='9', style='filled')
g.attr('edge', fontname=CJK_FONT, fontsize='7', color='#78909c')

# 节点样式：
# 主线集 EP##: 蓝色实线框 (#e3f2fd/#1565c0)
# 变体集 EP##A: 蓝色虚线框 (#e8eaf6/#3949ab)
# 死胡同 DE##: 红色框 (#ffcdd2/#c62828)
# 结局 END##: 绿色框 (#c8e6c9/#2e7d32)

# 边样式：
# → 死胡同: 红色虚线
# → 结局: 绿色粗线
# → 变体: 蓝色虚线
# 变体汇入: 灰色点线
```

保存到 `$PROJECT_DIR/dag.png`。

#### 6.5.3 DOCX 生成

生成 Word 文档，包含以下章节：

1. **封面**：作品名 + 互动影游制作大纲 + 章节范围·集数·节点数（不含日期）
2. **一、项目概述**：改编范围、集数规划、单次通关时长、总内容量、目标受众、核心类型、原著综述、本季弧线、核心看点
3. **二、世界观设定**：时代背景、核心设定
4. **三、角色设定**：按阵营分组（主角/家族/反派/盟友/中立），每人附 ~300 字小传
5. **四、DAG 结构总览**：菱形分支说明、节点统计、嵌入 DAG 图片、图例
6. **五、分集大纲**：每集含章节来源、概要、**主要情节**（3 个）、玩家抉择（2-3 选项 + 后果）、变体集说明、死胡同说明
7. **六、结局**：所有结局的基调和描述

**术语规范**：
- 使用「主要情节」而非「叙事节拍」
- 核心类型使用中文原生网文术语（如「古代言情·女强·穿越空间」）
- 不包含 S2/下一季 内容
- 不显示生成日期

保存到 `$PROJECT_DIR/output/互动影游大纲_XXX.docx`。

### Step 7: 报告

向用户汇报：
1. 输出文件位置
2. 爽点挖掘结果：挖掘总数 → 筛选数 → 类型分布
3. 集级DAG概览：总集数、单次通关集数、分叉点数、独立路线数
4. 选择质量概览：fork vs flavor 分布，选项差异化情况
5. 结局数（正式 + 死亡）
6. 强度曲线概览（情绪起伏节奏）
7. 可复玩性分析

**交付物清单**（`$PROJECT_DIR/` 下）：

```
output/
  互动剧本_XXX_预览.pdf    ← 预览 PDF（摘要 + 爽点列表 + DAG流程图）
  互动影游大纲_XXX.docx    ← 大纲文档（角色小传 + DAG拓扑图 + 分集大纲）
state.json                  ← 预览状态（可传入 /make-interactive-show 继续生产）
story_bible.json            ← 故事圣经
structure.json              ← 拓扑结构（集级DAG + 选择设计）
beats.json                  ← 爽点挖掘结果
characters.json             ← 角色小传
dag.png                     ← DAG拓扑图
args.json                   ← 原始参数
chunks/                     ← 切分块
summaries/                  ← 块摘要
```

用户审核预览后，可将此项目目录传入 `/make-interactive-show --file $PROJECT_DIR` 继续生成完整剧本。
