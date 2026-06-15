export const DAG_SKELETON_SYSTEM = `你是一个专业的互动剧本结构设计师。你的任务是设计一个互动短剧的剧情DAG（有向无环图）结构，并按集（Episode）组织。

## 核心理念

互动短剧的精髓在于：**每个场景都以观众的选择结束**。没有"过场"节点——每一幕都是一个决策点。

## 集（Episode）划分

故事必须按集（Episode）划分。每集对应原著的一段连续章节，有独立的小故事弧。
- 每集约5-8个场景节点
- 每集有自己的标题
- 集与集之间通过节点连接，形成连续的故事流

## 节点类型

- **choice**: 每个非结局节点都是choice类型。每个场景结束时，观众必须做出选择。
- **ending**: 结局节点（正常结局，故事自然收束）
- **hidden_ending**: 隐藏结局节点（需要在多个选择点做出特定组合才能触发）

**注意：不要使用"normal"类型。所有非结局节点都是choice节点。**

## 节点编号

使用 "EPxx-Cn" 格式，如 "EP01-C1", "EP01-C2", "EP02-C1", "EP03-C5"
- EPxx 是集号（EP01, EP02, ...），两位数字，从01开始
- Cn 是该集内的场景序号（C1, C2, ...），从1开始

## 结构要求（严格执行）

1. **每个choice节点必须有2-3个选项**，**每个选项必须导向不同的target_node_key**（绝对不允许同一节点的两条边指向相同的目标节点！）
2. **不允许线性结构**：每个非结局节点出发的路径必须真正分叉到不同节点
3. **分支可以合流但不能立即合流**：分开后必须至少独立发展2个节点再合流
4. **至少3条从开头到结局完全不同的路径**（不只是结尾不同，中间经历也要有实质差异）
5. **隐藏结局需要特殊条件**：需要在2-3个连续选择点做出特定组合才能触发
6. **总共应有3-6个不同结局**（含1-2个隐藏结局）
7. **跨集连接**：一集的最后节点可以连接到下一集的第一个节点，也可以跨集分叉

**重要提醒：如果一个节点有2条边，它们的target_node_key必须不同。例如：节点A的选项1→B，选项2→C，其中B≠C。绝对不能出现选项1→B，选项2→B的情况。**

## 边（choice_label）

- 从choice节点出发的边需要有选项文字
- 选项文字要简短有力（4-12个字）
- 选项要有真正的取舍，不能有明显的"最优解"
- 不同选项应该体现不同的价值观、性格或策略

## 输出格式

只输出原始JSON对象，不要使用Markdown代码块，不要添加解释文字。格式如下：
{
  "nodes": [
    {
      "node_key": "EP01-C1",
      "title": "节点标题",
      "summary": "节点内容概要（15-30字）",
      "scene_type": "choice|ending|hidden_ending",
      "is_ending": false,
      "is_hidden_ending": false,
      "episode_number": 1,
      "episode_title": "第一集标题"
    }
  ],
  "edges": [
    {
      "source_node_key": "EP01-C1",
      "target_node_key": "EP01-C2",
      "choice_label": "选项文字",
      "choice_index": 0
    }
  ]
}`;

export interface DagSkeletonParams {
  storySummary: string;
  worldSettings: string;
  characters: string;
  steeringNotes?: string;
  storyCharCount?: number;
  targetDurationMinutes?: number;
  targetChoiceCount?: number;
}

export function buildDagSkeletonPrompt(
  storySummary: string,
  worldSettings: string,
  characters: string,
  steeringNotes?: string,
  storyCharCount?: number,
  targetDurationMinutes?: number,
  targetChoiceCount?: number
): string {
  let minNodes: number;
  let maxNodes: number;
  let minEndings = 3;
  let maxEndings = 6;
  let minEpisodes: number;
  let maxEpisodes: number;

  if (targetDurationMinutes) {
    const targetNodes = Math.round(targetDurationMinutes / 1.5);
    minNodes = Math.max(6, Math.round(targetNodes * 0.8));
    maxNodes = Math.round(targetNodes * 1.2);
    minEndings = Math.max(2, Math.round(targetNodes / 15));
    maxEndings = Math.max(minEndings + 1, Math.round(targetNodes / 8));
    minEpisodes = Math.max(2, Math.round(targetNodes / 8));
    maxEpisodes = Math.max(minEpisodes + 2, Math.round(targetNodes / 5));
  } else if (storyCharCount !== undefined) {
    if (storyCharCount < 50000) {
      minNodes = 8;
      maxNodes = 20;
      minEndings = 2;
      maxEndings = 4;
      minEpisodes = 2;
      maxEpisodes = 4;
    } else if (storyCharCount < 200000) {
      minNodes = 20;
      maxNodes = 40;
      minEndings = 3;
      maxEndings = 5;
      minEpisodes = 4;
      maxEpisodes = 6;
    } else {
      minNodes = 40;
      maxNodes = 80;
      minEpisodes = 6;
      maxEpisodes = 12;
    }
  } else {
    minNodes = 40;
    maxNodes = 80;
    minEpisodes = 6;
    maxEpisodes = 12;
  }

  let prompt = `基于以下素材，设计互动短剧的完整剧情DAG结构，按集（Episode）组织：

## 故事概要
${storySummary}

## 世界观设定
${worldSettings}

## 角色设定
${characters}`;

  if (steeringNotes) {
    prompt += `\n\n## 导演备注\n${steeringNotes}`;
  }

  prompt += `\n\n## 结构要求
- 集数：${minEpisodes}-${maxEpisodes}集
- 总节点数：${minNodes}-${maxNodes}个
- 每集约5-8个场景节点
- 结局数：${minEndings}-${maxEndings}个（含隐藏结局）
- **所有非结局节点都是choice类型**，不要使用normal类型
- 每个choice节点必须有2-3条出边，导向不同的后续节点
- 确保至少3条从开头到结局完全不同的路径
- 节点summary必须精简，每个15-30字
- 每个节点必须包含 episode_number 和 episode_title 字段
- 使用 EPxx-Cn 格式的 node_key（如 EP01-C1, EP02-C3）`;

  if (targetDurationMinutes) {
    prompt += `\n- 目标总时长：约${targetDurationMinutes}分钟（每个场景约1-2分钟）`;
  }

  if (targetChoiceCount) {
    prompt += `\n- 互动选择点（choice类型节点）数量：恰好${targetChoiceCount}个`;
  }

  prompt += `\n\n请只输出原始JSON对象，不要使用Markdown代码块，不要添加解释文字。`;
  return prompt;
}
