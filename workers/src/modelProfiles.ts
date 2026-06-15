export type ModelProfileId = "default" | "premium" | "budget";
export type ModelTask =
  | "summarize_chunk"
  | "summarize_merge"
  | "world_settings"
  | "characters"
  | "dag_skeleton"
  | "scene_script";

export interface ModelTaskConfig {
  provider: "gemini" | "anthropic" | "deepseek" | "fireworks";
  model: string;
  maxTokens: number;
  temperature: number;
  extraBody?: Record<string, unknown>;
}

export interface ModelProfile {
  id: ModelProfileId;
  label: string;
  tasks: Record<ModelTask, ModelTaskConfig>;
}

// Default: all Anthropic (Gemini/DeepSeek can be swapped in when keys are available)
const DEFAULT_TASKS: Record<ModelTask, ModelTaskConfig> = {
  summarize_chunk: {
    provider: "anthropic",
    model: "claude-sonnet-4-20250514",
    maxTokens: 8192,
    temperature: 0.2,
  },
  summarize_merge: {
    provider: "anthropic",
    model: "claude-sonnet-4-20250514",
    maxTokens: 16384,
    temperature: 0.2,
  },
  world_settings: {
    provider: "anthropic",
    model: "claude-sonnet-4-20250514",
    maxTokens: 8192,
    temperature: 0.5,
  },
  characters: {
    provider: "anthropic",
    model: "claude-sonnet-4-20250514",
    maxTokens: 4096,
    temperature: 0.5,
  },
  dag_skeleton: {
    provider: "anthropic",
    model: "claude-sonnet-4-20250514",
    maxTokens: 16384,
    temperature: 0.4,
  },
  scene_script: {
    provider: "anthropic",
    model: "claude-sonnet-4-20250514",
    maxTokens: 8192,
    temperature: 0.7,
  },
};

const PREMIUM_TASKS: Record<ModelTask, ModelTaskConfig> = {
  ...DEFAULT_TASKS,
  world_settings: {
    provider: "anthropic",
    model: "claude-opus-4-20250514",
    maxTokens: 8192,
    temperature: 0.5,
  },
  characters: {
    provider: "anthropic",
    model: "claude-opus-4-20250514",
    maxTokens: 4096,
    temperature: 0.5,
  },
  dag_skeleton: {
    provider: "anthropic",
    model: "claude-sonnet-4-20250514",
    maxTokens: 16384,
    temperature: 0.4,
  },
  scene_script: {
    provider: "anthropic",
    model: "claude-opus-4-20250514",
    maxTokens: 8192,
    temperature: 0.7,
  },
};

const BUDGET_TASKS: Record<ModelTask, ModelTaskConfig> = {
  ...DEFAULT_TASKS,
  summarize_chunk: {
    provider: "anthropic",
    model: "claude-haiku-4-5-20251001",
    maxTokens: 8192,
    temperature: 0.2,
  },
  summarize_merge: {
    provider: "anthropic",
    model: "claude-haiku-4-5-20251001",
    maxTokens: 16384,
    temperature: 0.2,
  },
};

const PROFILES: Record<ModelProfileId, ModelProfile> = {
  default: { id: "default", label: "Default (Sonnet)", tasks: DEFAULT_TASKS },
  premium: { id: "premium", label: "Premium (Opus)", tasks: PREMIUM_TASKS },
  budget: { id: "budget", label: "Budget (Haiku + Sonnet)", tasks: BUDGET_TASKS },
};

export function getTaskConfig(profileId: ModelProfileId, task: ModelTask): ModelTaskConfig {
  const profile = PROFILES[profileId];
  if (!profile) throw new Error(`Unknown model profile: ${profileId}`);
  return profile.tasks[task];
}

export function getAvailableProfiles(): ModelProfile[] {
  return Object.values(PROFILES);
}
