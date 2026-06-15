import type { Env } from "../env.ts";
import type { ModelTaskConfig } from "../modelProfiles.ts";

interface AnthropicMessage {
  role: "user" | "assistant";
  content: string;
}

interface AnthropicRequest {
  model: string;
  max_tokens: number;
  temperature: number;
  system: string;
  messages: AnthropicMessage[];
}

interface AnthropicResponse {
  content: { type: string; text?: string }[];
  stop_reason: string;
}

const REQUEST_TIMEOUT_MS = 600_000;

export async function callAnthropicText(
  env: Env,
  config: ModelTaskConfig,
  systemPrompt: string,
  messages: { role: string; content: string }[]
): Promise<string> {
  const body: AnthropicRequest = {
    model: config.model,
    max_tokens: config.maxTokens,
    temperature: config.temperature,
    system: systemPrompt,
    messages: messages.map((m) => ({
      role: m.role as "user" | "assistant",
      content: m.content,
    })),
  };

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  let response: Response;
  try {
    response = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": env.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeoutId);
  }

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Anthropic API error ${response.status}: ${errorText}`);
  }

  const data = (await response.json()) as AnthropicResponse;
  const textBlock = data.content.find((b) => b.type === "text");
  if (!textBlock?.text) throw new Error("Anthropic returned empty response");
  return textBlock.text;
}

export async function callAnthropicJson<T>(
  env: Env,
  config: ModelTaskConfig,
  systemPrompt: string,
  messages: { role: string; content: string }[]
): Promise<T> {
  const text = await callAnthropicText(env, config, systemPrompt, messages);
  let jsonStr = text.trim();
  const fenced = jsonStr.match(/^```(?:json)?\s*([\s\S]*?)\s*```$/i);
  if (fenced?.[1]) {
    jsonStr = fenced[1].trim();
  } else if (jsonStr.startsWith("```")) {
    jsonStr = jsonStr.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "").trim();
  }
  try {
    return JSON.parse(jsonStr) as T;
  } catch (e) {
    console.error("JSON parse failed. First 500 chars:", jsonStr.slice(0, 500));
    throw new Error(`JSON parse failed: ${(e as Error).message}`);
  }
}
