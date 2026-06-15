export const SUMMARIZE_CHUNK_SYSTEM = `你是一个专业的小说内容分析师。你的任务是对小说文本片段进行详细的结构化总结。

总结应包括：
1. **主要事件**：按时间顺序列出本片段中发生的关键事件
2. **人物出场**：列出本片段中出现的所有角色及其行为
3. **场景描述**：简要描述本片段中的场景/环境
4. **情感基调**：本片段的主要情感氛围
5. **伏笔/悬念**：如果有任何伏笔或悬念，请标注
6. **关键对话**：摘录重要的对话要点

请用中文回答，保持专业和详细。总结长度应为原文的5-10%。`;

export function buildSummarizeChunkPrompt(chunkContent: string, chunkIndex: number, totalChunks: number): string {
  return `这是小说的第 ${chunkIndex + 1}/${totalChunks} 个片段。请对以下内容进行详细的结构化总结：

---
${chunkContent}
---

请按照系统提示中的格式进行总结。`;
}
