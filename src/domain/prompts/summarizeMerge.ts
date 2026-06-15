export const SUMMARIZE_MERGE_SYSTEM = `你是一个专业的小说分析师。你的任务是将多个片段总结合并为一个连贯的故事概要。

合并后的总结应该：
1. 按时间线整理所有事件
2. 去除重复内容
3. 保持关键情节转折点
4. 维护人物发展脉络
5. 标注主要的故事弧线

输出格式：
## 故事概要
（整体故事线，2000-5000字）

## 故事弧线
- **弧线1名称**：起止范围，核心冲突
- **弧线2名称**：...

## 核心人物
- **人物名**：关键发展轨迹

## 关键转折点
1. 转折描述
2. ...`;

export function buildSummarizeMergePrompt(summaries: string[]): string {
  const numbered = summaries
    .map((s, i) => `### 片段 ${i + 1} 总结\n${s}`)
    .join("\n\n---\n\n");

  return `请将以下 ${summaries.length} 个片段总结合并为一个连贯的故事概要：

${numbered}

请按照系统提示中的格式输出合并后的总结。`;
}
