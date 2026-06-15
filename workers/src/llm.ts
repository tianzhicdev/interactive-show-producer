import type { Env } from "./env.ts";
import type { ModelTaskConfig, ModelTask, ModelProfileId } from "./modelProfiles.ts";
import { callGeminiText, callGeminiJson } from "./providers/gemini.ts";
import { callAnthropicText, callAnthropicJson } from "./providers/anthropic.ts";
import { callDeepSeekText, callDeepSeekJson } from "./providers/deepseek.ts";
import { callFireworksText, callFireworksJson } from "./providers/fireworks.ts";

export interface LlmMessage {
  role: "user" | "assistant";
  content: string;
}

export interface LlmInvocationContext {
  profileId: ModelProfileId;
  task: ModelTask;
  projectId?: string;
}

export async function callLlmText(
  env: Env,
  config: ModelTaskConfig,
  systemPrompt: string,
  messages: LlmMessage[],
  _context: LlmInvocationContext
): Promise<string> {
  switch (config.provider) {
    case "gemini":
      return callGeminiText(env, config, systemPrompt, messages);
    case "anthropic":
      return callAnthropicText(env, config, systemPrompt, messages);
    case "deepseek":
      return callDeepSeekText(env, config, systemPrompt, messages);
    case "fireworks":
      return callFireworksText(env, config, systemPrompt, messages);
    default:
      throw new Error(`Unknown provider: ${config.provider}`);
  }
}

export async function callLlmJson<T>(
  env: Env,
  config: ModelTaskConfig,
  systemPrompt: string,
  messages: LlmMessage[],
  _context: LlmInvocationContext
): Promise<T> {
  switch (config.provider) {
    case "gemini":
      return callGeminiJson<T>(env, config, systemPrompt, messages);
    case "anthropic":
      return callAnthropicJson<T>(env, config, systemPrompt, messages);
    case "deepseek":
      return callDeepSeekJson<T>(env, config, systemPrompt, messages);
    case "fireworks":
      return callFireworksJson<T>(env, config, systemPrompt, messages);
    default:
      throw new Error(`Unknown provider: ${config.provider}`);
  }
}
