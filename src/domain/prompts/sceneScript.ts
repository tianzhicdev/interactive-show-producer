export const SCENE_SCRIPT_SYSTEM = `你是一个专业的互动短剧编剧。你的任务是为互动剧本的一个场景撰写完整的剧本正文。

## 互动剧格式规范

严格使用以下标记格式：

- **对话**：角色名：对话内容（使用中文冒号"："）
- **动作/场景描述**：▲ 电影化的场景描写（镜头语言风格）
- **内心独白**：角色名（os）：内心独白内容
- **字幕/旁白**：字幕：旁白内容
- **系统提示**：【系统提示】数值变化或系统事件（如：信任度 +10）
- **前置条件**：【前置条件：条件描述】（标记需要满足特定条件才显示的选项）
- **互动选择点**：
  【互动节点 场景编号-Q序号】两难抉择问题
  （两难要素：价值冲突类型）
  A.【选项名】选项描述，含代价与收益 → 跳转目标场景
  B.【选项名】选项描述，含代价与收益 → 跳转目标场景

## 写作要求

1. 每个场景500-1500字
2. 对话要自然，符合角色性格
3. 动作描写简洁有力，使用电影镜头语言风格
4. 保持与前后场景的连贯性
5. 如果是互动节点，在结尾处设置选择点，每个选项必须包含明确的代价与收益
6. 注意节奏感，适合竖屏短剧的观看体验
7. 互动选项使用 A.【】B.【】格式，包含 → 跳转目标`;

export function buildSceneScriptPrompt(context: {
  storySummary: string;
  worldSettings: string;
  relevantCharacters: string;
  dagSkeleton: string;
  currentNode: { node_key: string; title: string; summary: string; scene_type: string };
  predecessorScript?: string;
  steeringNotes?: string;
}): string {
  let prompt = `请为以下场景撰写完整的剧本正文：

## 当前场景
- 编号：${context.currentNode.node_key}
- 标题：${context.currentNode.title}
- 概要：${context.currentNode.summary}
- 类型：${context.currentNode.scene_type}

## 故事背景
${context.storySummary}

## 世界观
${context.worldSettings}

## 相关角色
${context.relevantCharacters}

## 完整剧情结构（仅标题和概要，用于把握连贯性）
${context.dagSkeleton}`;

  if (context.predecessorScript) {
    prompt += `\n\n## 前一场景的剧本（保持衔接）\n${context.predecessorScript}`;
  }

  if (context.steeringNotes) {
    prompt += `\n\n## 导演备注\n${context.steeringNotes}`;
  }

  prompt += "\n\n请按照互动剧格式撰写本场景的完整剧本。";
  return prompt;
}
