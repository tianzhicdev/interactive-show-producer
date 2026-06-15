export interface BackgroundQueueBinding {
  send(message: BackgroundJob, options?: { delaySeconds?: number }): Promise<void>;
  sendBatch(messages: { body: BackgroundJob }[], options?: { delaySeconds?: number }): Promise<void>;
}

export interface QueueMessage<T> {
  body: T;
  attempts?: number;
  ack(): void;
  retry(options?: { delaySeconds?: number }): void;
}

export interface QueueBatch<T> {
  messages: QueueMessage<T>[];
}

// --- Job Types ---

export interface SummarizeChunkJob {
  kind: "summarize_chunk";
  jobId: string;
  projectId: string;
  chunkIndex: number;
  queuedAt: string;
}

export interface SummarizeMergeJob {
  kind: "summarize_merge";
  jobId: string;
  projectId: string;
  groupIndex: number;
  totalGroups: number;
  queuedAt: string;
}

export interface WorldSettingsJob {
  kind: "world_settings";
  jobId: string;
  projectId: string;
  queuedAt: string;
}

export interface CharactersJob {
  kind: "characters";
  jobId: string;
  projectId: string;
  queuedAt: string;
}

export interface DagSkeletonJob {
  kind: "dag_skeleton";
  jobId: string;
  projectId: string;
  queuedAt: string;
}

export interface SceneScriptJob {
  kind: "scene_script";
  jobId: string;
  projectId: string;
  nodeKey: string;
  steeringNotes?: string;
  queuedAt: string;
}

export interface ExportDocxJob {
  kind: "export_docx";
  jobId: string;
  projectId: string;
  queuedAt: string;
}

export type BackgroundJob =
  | SummarizeChunkJob
  | SummarizeMergeJob
  | WorldSettingsJob
  | CharactersJob
  | DagSkeletonJob
  | SceneScriptJob
  | ExportDocxJob;

// --- Enqueue Helpers (accept jobId from DB-generated generation_jobs row) ---

export async function enqueueSummarizeChunk(
  queue: BackgroundQueueBinding,
  jobId: string,
  projectId: string,
  chunkIndex: number
): Promise<void> {
  await queue.send({
    kind: "summarize_chunk",
    jobId,
    projectId,
    chunkIndex,
    queuedAt: new Date().toISOString(),
  });
}

export async function enqueueBackgroundJob(queue: BackgroundQueueBinding, message: BackgroundJob): Promise<void> {
  await queue.send({
    ...message,
    queuedAt: new Date().toISOString(),
  });
}

// Batch enqueue for summarize_chunk jobs — sends in chunks with rate limit handling
export async function enqueueSummarizeChunkBatch(
  queue: BackgroundQueueBinding,
  jobs: { jobId: string; projectId: string; chunkIndex: number }[]
): Promise<void> {
  const now = new Date().toISOString();
  const makeBody = (j: typeof jobs[0]) => ({
    kind: "summarize_chunk" as const,
    jobId: j.jobId,
    projectId: j.projectId,
    chunkIndex: j.chunkIndex,
    queuedAt: now,
  });

  const BATCH_LIMIT = 25;
  const MAX_RETRIES = 2;
  const SEND_SPACING_MS = 250;

  async function retryQueueOperation(operation: () => Promise<void>, label: string): Promise<boolean> {
    for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
      try {
        await operation();
        return true;
      } catch (e: unknown) {
        const errMsg = String(e);
        if (errMsg.includes("Too Many Requests") && attempt < MAX_RETRIES) {
          const delay = 2000 * Math.pow(2, attempt);
          console.log(`Queue rate limited on ${label}, retry in ${delay}ms (${attempt + 1}/${MAX_RETRIES})`);
          await new Promise((r) => setTimeout(r, delay));
        } else {
          if (errMsg.includes("Too Many Requests")) return false;
          throw e;
        }
      }
    }
    return false;
  }

  for (let i = 0; i < jobs.length; i += BATCH_LIMIT) {
    const batch = jobs.slice(i, i + BATCH_LIMIT);
    const batchNumber = Math.floor(i / BATCH_LIMIT);
    const sent = await retryQueueOperation(
      () => queue.sendBatch(batch.map((j) => ({ body: makeBody(j) }))),
      `batch ${batchNumber}`
    );

    if (!sent) {
      console.log(`Queue batch ${batchNumber} stayed rate limited; falling back to individual sends`);
      for (const job of batch) {
        const sentSingle = await retryQueueOperation(
          () => queue.send(makeBody(job)),
          `job ${job.jobId}`
        );
        if (!sentSingle) {
          throw new Error(`Queue send failed after retries for job ${job.jobId}: Too Many Requests`);
        }
        await new Promise((r) => setTimeout(r, SEND_SPACING_MS));
      }
    }

    if (i + BATCH_LIMIT < jobs.length) {
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
}

export async function enqueueSummarizeMerge(
  queue: BackgroundQueueBinding,
  jobId: string,
  projectId: string,
  groupIndex: number,
  totalGroups: number
): Promise<void> {
  await queue.send({
    kind: "summarize_merge",
    jobId,
    projectId,
    groupIndex,
    totalGroups,
    queuedAt: new Date().toISOString(),
  });
}

export async function enqueueWorldSettings(
  queue: BackgroundQueueBinding,
  jobId: string,
  projectId: string
): Promise<void> {
  await queue.send({
    kind: "world_settings",
    jobId,
    projectId,
    queuedAt: new Date().toISOString(),
  });
}

export async function enqueueCharacters(
  queue: BackgroundQueueBinding,
  jobId: string,
  projectId: string
): Promise<void> {
  await queue.send({
    kind: "characters",
    jobId,
    projectId,
    queuedAt: new Date().toISOString(),
  });
}

export async function enqueueDagSkeleton(
  queue: BackgroundQueueBinding,
  jobId: string,
  projectId: string
): Promise<void> {
  await queue.send({
    kind: "dag_skeleton",
    jobId,
    projectId,
    queuedAt: new Date().toISOString(),
  });
}

export async function enqueueSceneScript(
  queue: BackgroundQueueBinding,
  jobId: string,
  projectId: string,
  nodeKey: string,
  steeringNotes?: string
): Promise<void> {
  await queue.send({
    kind: "scene_script",
    jobId,
    projectId,
    nodeKey,
    steeringNotes,
    queuedAt: new Date().toISOString(),
  });
}

export async function enqueueExportDocx(
  queue: BackgroundQueueBinding,
  jobId: string,
  projectId: string
): Promise<void> {
  await queue.send({
    kind: "export_docx",
    jobId,
    projectId,
    queuedAt: new Date().toISOString(),
  });
}
