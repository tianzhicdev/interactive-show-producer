import type { BackgroundQueueBinding } from "./backgroundJobsQueue.ts";

export interface R2Bucket {
  put(key: string, value: ReadableStream | ArrayBuffer | string, options?: { httpMetadata?: { contentType?: string } }): Promise<{ key: string; size: number }>;
  get(key: string): Promise<{ key: string; size: number; body: ReadableStream; text(): Promise<string>; arrayBuffer(): Promise<ArrayBuffer> } | null>;
  delete(key: string): Promise<void>;
}

export interface Env {
  DATABASE_URL: string;
  ANTHROPIC_API_KEY: string;
  GEMINI_API_KEY?: string;
  DEEPSEEK_API_KEY?: string;
  FIREWORKS_API_KEY?: string;
  AUTH_SECRET: string;
  QUEUE_CONSUMER_CONCURRENCY?: string;
  QUEUE_RETRY_BASE_DELAY_SECONDS?: string;
  BACKGROUND_QUEUE: BackgroundQueueBinding;
  STORY_BUCKET: R2Bucket;
}
