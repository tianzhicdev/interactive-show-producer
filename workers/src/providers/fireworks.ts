import type { Env } from "../env.ts";
import type { ModelTaskConfig } from "../modelProfiles.ts";

interface OpenAIMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

interface OpenAIChatResponse {
  choices: { message: { content: string }; finish_reason: string }[];
}

const MAX_RETRIES = 3;
const BASE_DELAY_MS = 2_000;
const REQUEST_TIMEOUT_MS = 600_000;

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

async function callFireworksWithRetry(
  env: Env,
  config: ModelTaskConfig,
  openaiMessages: OpenAIMessage[],
  extraBody?: Record<string, unknown>
): Promise<OpenAIChatResponse> {
  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await fetchWithTimeout(
        "https://api.fireworks.ai/inference/v1/chat/completions",
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${env.FIREWORKS_API_KEY}`,
          },
          body: JSON.stringify({
            model: config.model,
            messages: openaiMessages,
            max_tokens: config.maxTokens,
            temperature: config.temperature,
            ...(config.extraBody ?? {}),
            ...extraBody,
          }),
        },
        REQUEST_TIMEOUT_MS
      );

      if (response.status === 429 && attempt < MAX_RETRIES) {
        const retryAfter = Number.parseInt(response.headers.get("Retry-After") ?? "", 10);
        const delay = Number.isFinite(retryAfter)
          ? retryAfter * 1000
          : BASE_DELAY_MS * Math.pow(2, attempt) + Math.random() * 1000;
        console.log(`Fireworks 429, retry in ${Math.round(delay)}ms (${attempt + 1}/${MAX_RETRIES})`);
        await new Promise((r) => setTimeout(r, delay));
        continue;
      }

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Fireworks API error ${response.status}: ${errorText}`);
      }

      return (await response.json()) as OpenAIChatResponse;
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        console.log(`Fireworks timeout after ${REQUEST_TIMEOUT_MS}ms (attempt ${attempt + 1}/${MAX_RETRIES})`);
        if (attempt < MAX_RETRIES) continue;
        throw new Error(`Fireworks: request timed out after ${MAX_RETRIES + 1} attempts`);
      }
      throw err;
    }
  }

  throw new Error("Fireworks: max retries exceeded");
}

export async function callFireworksText(
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

  const data = await callFireworksWithRetry(env, config, openaiMessages);
  const text = data.choices?.[0]?.message?.content;
  if (!text) throw new Error("Fireworks returned empty response");
  return text;
}

export async function callFireworksJson<T>(
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

  const data = await callFireworksWithRetry(env, config, openaiMessages, {
    response_format: { type: "json_object" },
  });
  const text = data.choices?.[0]?.message?.content;
  if (!text) throw new Error("Fireworks returned empty response");
  return JSON.parse(text) as T;
}
