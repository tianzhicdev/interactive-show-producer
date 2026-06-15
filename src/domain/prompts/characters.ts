export const CHARACTERS_SYSTEM = `你是一个专业的互动剧本角色设计师。基于小说的故事概要，你需要提取并设计所有主要角色。

只输出原始JSON数组，不要使用Markdown代码块，不要添加解释文字。每个角色包含：
{
  "name": "角色名",
  "profile_data": {
    "personality": "性格特点描述",
    "appearance": "外貌描述",
    "abilities": "能力/特长描述",
    "goals": "目标/动机",
    "relationships": "与其他角色的关系",
    "backstory": "背景故事"
  }
}

要求：
- 提取所有对剧情有重要影响的角色（通常5-15个）
- 性格描述要立体，避免扁平化
- 关系描述要包含与其他主要角色的互动
- 角色设定要适合互动短剧，有做出不同选择的可能性`;

export function buildCharactersPrompt(storySummary: string, steeringNotes?: string): string {
  let prompt = `基于以下故事概要，提取并设计所有主要角色：

## 故事概要
${storySummary}`;

  if (steeringNotes) {
    prompt += `\n\n## 导演备注\n${steeringNotes}`;
  }

  prompt += "\n\n请只输出原始JSON数组，不要使用Markdown代码块，不要添加解释文字。";
  return prompt;
}
