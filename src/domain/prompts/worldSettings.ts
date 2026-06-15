export const WORLD_SETTINGS_SYSTEM = `你是一个专业的互动剧本世界观设计师。基于小说的故事概要，你需要提取并设计适合互动短剧的世界观设定。

请以JSON格式输出，包含以下字段：
{
  "era": "时代背景描述",
  "location": "主要地点设定",
  "rules": "世界运行规则（如修仙体系、社会规则等）",
  "tone": "整体基调（如热血、温馨、悬疑、黑暗等）",
  "themes": ["主题1", "主题2", "主题3"],
  "power_system": "力量体系描述（如有）",
  "factions": "势力/阵营描述（如有）"
}

设定应该：
- 保留原著的核心世界观
- 适合改编为互动短剧（观众可以做选择）
- 提供足够的细节让编剧理解世界运作方式`;

export function buildWorldSettingsPrompt(storySummary: string, steeringNotes?: string): string {
  let prompt = `基于以下故事概要，提取并设计互动短剧的世界观设定：

## 故事概要
${storySummary}`;

  if (steeringNotes) {
    prompt += `\n\n## 导演备注\n${steeringNotes}`;
  }

  prompt += "\n\n请以JSON格式输出世界观设定。";
  return prompt;
}
