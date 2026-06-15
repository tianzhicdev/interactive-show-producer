import type { Env } from "../env.ts";
import type { ModelTaskConfig } from "../modelProfiles.ts";

interface OpenAIMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

interface OpenAIChatResponse {
  choices: { message: { content: string }; finish_reason: string }[];
}

export async function callDeepSeekText(
  env: Env,
  config: ModelTaskConfig,
  systemPrompt: string,
  messages: { role: string; content: string }[]
): Promise<string> {
  const openaiMessages: OpenAIMessage[] = [
    { role: "system", content: systemPrompt },
    ...messages.map((m) => ({
      role: m.role as "user" | "assistant",
      content: m.content,
    })),
  ];

  const response = await fetch("https://api.deepseek.com/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${env.DEEPSEEK_API_KEY}`,
    },
    body: JSON.stringify({
      model: config.model,
      messages: openaiMessages,
      max_tokens: config.maxTokens,
      temperature: config.temperature,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`DeepSeek API error ${response.status}: ${errorText}`);
  }

  const data = (await response.json()) as OpenAIChatResponse;
  const text = data.choices?.[0]?.message?.content;
  if (!text) throw new Error("DeepSeek returned empty response");
  return text;
}

export async function callDeepSeekJson<T>(
  env: Env,
  config: ModelTaskConfig,
  systemPrompt: string,
  messages: { role: string; content: string }[]
): Promise<T> {
  const openaiMessages: OpenAIMessage[] = [
    { role: "system", content: systemPrompt },
    ...messages.map((m) => ({
      role: m.role as "user" | "assistant",
      content: m.content,
    })),
  ];

  const response = await fetch("https://api.deepseek.com/chat/completions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${env.DEEPSEEK_API_KEY}`,
    },
    body: JSON.stringify({
      model: config.model,
      messages: openaiMessages,
      max_tokens: config.maxTokens,
      temperature: config.temperature,
      response_format: { type: "json_object" },
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`DeepSeek API error ${response.status}: ${errorText}`);
  }

  const data = (await response.json()) as OpenAIChatResponse;
  const text = data.choices?.[0]?.message?.content;
  if (!text) throw new Error("DeepSeek returned empty response");
  return JSON.parse(text) as T;
}
