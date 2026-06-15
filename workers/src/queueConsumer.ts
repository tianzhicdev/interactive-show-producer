import type { NeonSQL } from "./db.ts";
import type { Env } from "./env.ts";
import type {
  BackgroundJob,
  QueueBatch,
} from "./backgroundJobsQueue.ts";
import {
  enqueueSummarizeMerge,
  enqueueWorldSettings,
  enqueueCharacters,
  enqueueDagSkeleton,
  enqueueSceneScript,
} from "./backgroundJobsQueue.ts";
import {
  getStoryChunks,
  insertStorySummary,
  getLatestStorySummary,
  insertWorldSettings,
  insertCharacter,
  insertDagNode,
  insertDagEdge,
  insertSceneScript,
  updateGenerationJob,
  getGenerationJob,
  countJobsByStatus,
  getProject,
  updateProjectStatus,
  createGenerationJob,
  getDagNodes,
  getDagEdges,
  getSceneScript,
  getCharacters,
  getLatestWorldSettings,
} from "./db.ts";
import { callLlmText, callLlmJson } from "./llm.ts";
import { getTaskConfig } from "./modelProfiles.ts";
import type { ModelProfileId } from "./modelProfiles.ts";
import type { DagSkeleton, CharacterProfile, WorldSettings } from "@tomato/domain/dagTypes.ts";
import {
  SUMMARIZE_CHUNK_SYSTEM,
  buildSummarizeChunkPrompt,
} from "@tomato/domain/prompts/summarizeChunk.ts";
import {
  SUMMARIZE_MERGE_SYSTEM,
  buildSummarizeMergePrompt,
} from "@tomato/domain/prompts/summarizeMerge.ts";
import {
  WORLD_SETTINGS_SYSTEM,
  buildWorldSettingsPrompt,
} from "@tomato/domain/prompts/worldSettings.ts";
import {
  CHARACTERS_SYSTEM,
  buildCharactersPrompt,
} from "@tomato/domain/prompts/characters.ts";
import {
  DAG_SKELETON_SYSTEM,
  buildDagSkeletonPrompt,
} from "@tomato/domain/prompts/dagSkeleton.ts";
import {
  SCENE_SCRIPT_SYSTEM,
  buildSceneScriptPrompt,
} from "@tomato/domain/prompts/sceneScript.ts";

const MERGE_GROUP_SIZE = 20;
const DEFAULT_CONSUMER_CONCURRENCY = 5;
const DEFAULT_RETRY_BASE_DELAY_SECONDS = 30;
const MAX_QUEUE_ATTEMPTS = 5;

/** Version numbering for story_summaries rows */
const CHUNK_SUMMARY_VERSION_OFFSET = 1;
const MERGE_GROUP_VERSION_OFFSET = 10000;
const FINAL_SUMMARY_VERSION = 99999;

function parsePositiveInt(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function retryDelaySeconds(attempts: number, baseDelaySeconds: number): number {
  return Math.min(900, baseDelaySeconds * Math.max(1, Math.pow(2, attempts - 1)));
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isRateLimitLike(error: unknown): boolean {
  const message = errorMessage(error).toLowerCase();
  return message.includes("429") || message.includes("too many requests") || message.includes("rate limit");
}

function normalizeCharacters(value: unknown): { name: string; profile_data: CharacterProfile }[] {
  const maybeRecord = value as { characters?: unknown; data?: unknown; items?: unknown };
  const raw = Array.isArray(value)
    ? value
    : Array.isArray(maybeRecord.characters)
      ? maybeRecord.characters
      : Array.isArray(maybeRecord.data)
        ? maybeRecord.data
        : Array.isArray(maybeRecord.items)
          ? maybeRecord.items
          : null;

  if (!raw) {
    throw new Error(`Characters returned invalid structure: ${JSON.stringify(value).slice(0, 200)}`);
  }

  return raw.map((item, index) => {
    const character = item as {
      name?: unknown;
      profile_data?: unknown;
      profile?: unknown;
    };
    if (typeof character.name !== "string" || character.name.length === 0) {
      throw new Error(`Character ${index} missing name`);
    }
    const profile = character.profile_data ?? character.profile;
    if (!profile || typeof profile !== "object") {
      throw new Error(`Character ${character.name} missing profile_data`);
    }
    return {
      name: character.name,
      profile_data: profile as CharacterProfile,
    };
  });
}

async function processWithConcurrency<T>(
  items: T[],
  concurrency: number,
  worker: (item: T) => Promise<void>
): Promise<void> {
  let nextIndex = 0;
  const workers = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (nextIndex < items.length) {
      const current = items[nextIndex++];
      await worker(current);
    }
  });
  await Promise.allSettled(workers);
}

export async function processBackgroundJobsBatch(
  sql: NeonSQL,
  env: Env,
  batch: QueueBatch<BackgroundJob>
): Promise<void> {
  const concurrency = parsePositiveInt(env.QUEUE_CONSUMER_CONCURRENCY, DEFAULT_CONSUMER_CONCURRENCY);
  const retryBaseDelaySeconds = parsePositiveInt(
    env.QUEUE_RETRY_BASE_DELAY_SECONDS,
    DEFAULT_RETRY_BASE_DELAY_SECONDS
  );

  await processWithConcurrency(batch.messages, concurrency, async (message) => {
    const job = message.body;
    if (!job?.kind) {
      console.error("Skipping malformed queue message");
      message.ack();
      return;
    }

    try {
      // Idempotency guard: skip already-done or missing jobs (queue retries / stale messages)
      const existingJob = await getGenerationJob(sql, job.jobId);
      if (!existingJob) {
        console.log(`Job ${job.jobId} not found in DB (stale message), skipping`);
        message.ack();
        return;
      }
      if (existingJob.status === "done") {
        console.log(`Job ${job.jobId} already done, skipping`);
        message.ack();
        return;
      }

      switch (job.kind) {
        case "summarize_chunk":
          await processSummarizeChunk(sql, env, job.projectId, job.chunkIndex, job.jobId);
          break;
        case "summarize_merge":
          await processSummarizeMerge(sql, env, job.projectId, job.groupIndex, job.totalGroups, job.jobId);
          break;
        case "world_settings":
          await processWorldSettings(sql, env, job.projectId, job.jobId);
          break;
        case "characters":
          await processCharacters(sql, env, job.projectId, job.jobId);
          break;
        case "dag_skeleton":
          await processDagSkeleton(sql, env, job.projectId, job.jobId);
          break;
        case "scene_script":
          await processSceneScript(sql, env, job.projectId, job.nodeKey, job.jobId, job.steeringNotes);
          break;
        case "export_docx":
          await processExportDocx(sql, env, job.projectId, job.jobId);
          break;
      }
      message.ack();
    } catch (error) {
      const attempts = message.attempts ?? 1;
      const messageText = errorMessage(error);
      const retryable = attempts < MAX_QUEUE_ATTEMPTS;
      const delaySeconds = retryDelaySeconds(
        attempts,
        isRateLimitLike(error) ? retryBaseDelaySeconds : Math.max(5, Math.floor(retryBaseDelaySeconds / 2))
      );

      console.error(`Job ${job.kind} failed on attempt ${attempts}:`, error);

      if (retryable) {
        await updateGenerationJob(sql, job.jobId, "queued", undefined, messageText);
        message.retry({ delaySeconds });
        return;
      }

      await updateGenerationJob(sql, job.jobId, "failed", undefined, messageText);
      message.ack();
    }
  });
}

// --- Summarize Chunk ---
async function processSummarizeChunk(
  sql: NeonSQL,
  env: Env,
  projectId: string,
  chunkIndex: number,
  jobId: string
): Promise<void> {
  await updateGenerationJob(sql, jobId, "running");

  const project = await getProject(sql, projectId);
  if (!project) throw new Error("Project not found");

  const profileId = project.model_profile_id as ModelProfileId;
  const config = getTaskConfig(profileId, "summarize_chunk");

  const chunks = await getStoryChunks(sql, projectId);
  const chunk = chunks.find((c) => c.chunk_index === chunkIndex);
  if (!chunk) throw new Error(`Chunk ${chunkIndex} not found`);

  const prompt = buildSummarizeChunkPrompt(chunk.content, chunkIndex, chunks.length);
  const summary = await callLlmText(env, config, SUMMARIZE_CHUNK_SYSTEM, [
    { role: "user", content: prompt },
  ], { profileId, task: "summarize_chunk", projectId });

  await insertStorySummary(sql, projectId, chunkIndex + CHUNK_SUMMARY_VERSION_OFFSET, summary);
  await updateGenerationJob(sql, jobId, "done", 1);

  // Check if all chunk summaries are done → trigger merge phase
  await checkAndTriggerMerge(sql, env, projectId);
}

async function checkAndTriggerMerge(
  sql: NeonSQL,
  env: Env,
  projectId: string
): Promise<void> {
  const counts = await countJobsByStatus(sql, projectId, "summarize_chunk");
  if (counts.queued > 0 || counts.running > 0) return;
  if (counts.failed > 0) {
    console.error(`${counts.failed} chunk summaries failed for project ${projectId}`);
    return;
  }

  // Idempotency guard: check if merge jobs already exist (race condition with parallel chunks)
  const mergeCounts = await countJobsByStatus(sql, projectId, "summarize_merge");
  if (mergeCounts.queued > 0 || mergeCounts.running > 0 || mergeCounts.done > 0) {
    console.log(`Merge jobs already exist for project ${projectId}, skipping trigger`);
    return;
  }

  // All chunks summarized — kick off merge
  const chunks = await getStoryChunks(sql, projectId);
  const totalGroups = Math.ceil(chunks.length / MERGE_GROUP_SIZE);

  for (let i = 0; i < totalGroups; i++) {
    const job = await createGenerationJob(sql, projectId, "summarize_merge", `group-${i}`);
    await enqueueSummarizeMerge(env.BACKGROUND_QUEUE, job.id, projectId, i, totalGroups);
  }
}

// --- Summarize Merge ---
async function processSummarizeMerge(
  sql: NeonSQL,
  env: Env,
  projectId: string,
  groupIndex: number,
  totalGroups: number,
  jobId: string
): Promise<void> {
  await updateGenerationJob(sql, jobId, "running");

  const project = await getProject(sql, projectId);
  if (!project) throw new Error("Project not found");

  const profileId = project.model_profile_id as ModelProfileId;
  const config = getTaskConfig(profileId, "summarize_merge");

  // Get chunk summaries for this group
  const chunks = await getStoryChunks(sql, projectId);
  const startIdx = groupIndex * MERGE_GROUP_SIZE;
  const endIdx = Math.min(startIdx + MERGE_GROUP_SIZE, chunks.length);

  const summaries: string[] = [];
  for (let i = startIdx; i < endIdx; i++) {
    const rows = await sql`
      SELECT content FROM story_summaries WHERE project_id = ${projectId} AND version = ${i + CHUNK_SUMMARY_VERSION_OFFSET}
    `;
    if (rows[0]) {
      summaries.push((rows[0] as unknown as { content: string }).content);
    }
  }

  const prompt = buildSummarizeMergePrompt(summaries);
  const merged = await callLlmText(env, config, SUMMARIZE_MERGE_SYSTEM, [
    { role: "user", content: prompt },
  ], { profileId, task: "summarize_merge", projectId });

  await insertStorySummary(sql, projectId, MERGE_GROUP_VERSION_OFFSET + groupIndex, merged);
  await updateGenerationJob(sql, jobId, "done", 1);

  // If all merge groups done, do final merge or proceed to world/chars/DAG
  await checkAndTriggerFinalMerge(sql, env, projectId, totalGroups);
}

async function checkAndTriggerFinalMerge(
  sql: NeonSQL,
  env: Env,
  projectId: string,
  totalGroups: number
): Promise<void> {
  const counts = await countJobsByStatus(sql, projectId, "summarize_merge");
  if (counts.queued > 0 || counts.running > 0) return;

  // Idempotency guard: check if world/chars jobs already exist (race condition with parallel merges)
  const wsCounts = await countJobsByStatus(sql, projectId, "world_settings");
  const chCounts = await countJobsByStatus(sql, projectId, "characters");
  if (wsCounts.queued > 0 || wsCounts.running > 0 || wsCounts.done > 0 ||
      chCounts.queued > 0 || chCounts.running > 0 || chCounts.done > 0) {
    console.log(`World/characters jobs already exist for project ${projectId}, skipping trigger`);
    return;
  }

  if (totalGroups > 1) {
    // Need a final merge of all group summaries
    const groupSummaries: string[] = [];
    for (let i = 0; i < totalGroups; i++) {
      const rows = await sql`
        SELECT content FROM story_summaries WHERE project_id = ${projectId} AND version = ${MERGE_GROUP_VERSION_OFFSET + i}
      `;
      if (rows[0]) {
        groupSummaries.push((rows[0] as unknown as { content: string }).content);
      }
    }

    const project = await getProject(sql, projectId);
    if (!project) return;
    const profileId = project.model_profile_id as ModelProfileId;
    const config = getTaskConfig(profileId, "summarize_merge");

    const prompt = buildSummarizeMergePrompt(groupSummaries);
    const finalSummary = await callLlmText(env, config, SUMMARIZE_MERGE_SYSTEM, [
      { role: "user", content: prompt },
    ], { profileId, task: "summarize_merge", projectId });

    await insertStorySummary(sql, projectId, FINAL_SUMMARY_VERSION, finalSummary);
  }

  // Now trigger world settings, characters, and DAG skeleton in parallel
  const wsJob = await createGenerationJob(sql, projectId, "world_settings");
  const chJob = await createGenerationJob(sql, projectId, "characters");

  await Promise.all([
    enqueueWorldSettings(env.BACKGROUND_QUEUE, wsJob.id, projectId),
    enqueueCharacters(env.BACKGROUND_QUEUE, chJob.id, projectId),
  ]);
}

// --- World Settings ---
async function processWorldSettings(
  sql: NeonSQL,
  env: Env,
  projectId: string,
  jobId: string
): Promise<void> {
  await updateGenerationJob(sql, jobId, "running");

  const project = await getProject(sql, projectId);
  if (!project) throw new Error("Project not found");

  const profileId = project.model_profile_id as ModelProfileId;
  const config = getTaskConfig(profileId, "world_settings");

  const summary = await getLatestStorySummary(sql, projectId);
  if (!summary) throw new Error("No story summary found");

  const prompt = buildWorldSettingsPrompt(summary.content, project.steering_notes ?? undefined);
  const worldData = await callLlmJson<WorldSettings>(env, config, WORLD_SETTINGS_SYSTEM, [
    { role: "user", content: prompt },
  ], { profileId, task: "world_settings", projectId });

  await insertWorldSettings(sql, projectId, 1, worldData);
  await updateGenerationJob(sql, jobId, "done", 1);

  // Check if both world and characters are done → trigger DAG skeleton
  await checkAndTriggerDag(sql, env, projectId);
}

// --- Characters ---
async function processCharacters(
  sql: NeonSQL,
  env: Env,
  projectId: string,
  jobId: string
): Promise<void> {
  await updateGenerationJob(sql, jobId, "running");

  const project = await getProject(sql, projectId);
  if (!project) throw new Error("Project not found");

  const profileId = project.model_profile_id as ModelProfileId;
  const config = getTaskConfig(profileId, "characters");

  const summary = await getLatestStorySummary(sql, projectId);
  if (!summary) throw new Error("No story summary found");

  const prompt = buildCharactersPrompt(summary.content, project.steering_notes ?? undefined);
  const rawCharacters = await callLlmJson<unknown>(
    env, config, CHARACTERS_SYSTEM,
    [{ role: "user", content: prompt }],
    { profileId, task: "characters", projectId }
  );
  const characters = normalizeCharacters(rawCharacters);

  for (const char of characters) {
    await insertCharacter(sql, projectId, 1, char.name, char.profile_data);
  }
  await updateGenerationJob(sql, jobId, "done", 1);

  await checkAndTriggerDag(sql, env, projectId);
}

async function checkAndTriggerDag(
  sql: NeonSQL,
  env: Env,
  projectId: string
): Promise<void> {
  const wsCounts = await countJobsByStatus(sql, projectId, "world_settings");
  const chCounts = await countJobsByStatus(sql, projectId, "characters");

  if (wsCounts.done > 0 && chCounts.done > 0) {
    // Idempotency guard: check if dag_skeleton job already exists
    const dagCounts = await countJobsByStatus(sql, projectId, "dag_skeleton");
    if (dagCounts.queued > 0 || dagCounts.running > 0 || dagCounts.done > 0) return;

    const dagJob = await createGenerationJob(sql, projectId, "dag_skeleton");
    await enqueueDagSkeleton(env.BACKGROUND_QUEUE, dagJob.id, projectId);
  }
}

// --- DAG Skeleton ---
async function processDagSkeleton(
  sql: NeonSQL,
  env: Env,
  projectId: string,
  jobId: string
): Promise<void> {
  await updateGenerationJob(sql, jobId, "running");

  const project = await getProject(sql, projectId);
  if (!project) throw new Error("Project not found");

  const profileId = project.model_profile_id as ModelProfileId;
  const config = getTaskConfig(profileId, "dag_skeleton");

  const [summary, worldSettings, characters] = await Promise.all([
    getLatestStorySummary(sql, projectId),
    getLatestWorldSettings(sql, projectId),
    getCharacters(sql, projectId),
  ]);

  if (!summary) throw new Error("No story summary");
  if (!worldSettings) throw new Error("No world settings");

  // Get total story character count for scaling
  const storyChunks = await getStoryChunks(sql, projectId);
  const totalCharCount = storyChunks.reduce((sum, c) => sum + (c.char_count ?? c.content.length), 0);

  const prompt = buildDagSkeletonPrompt(
    summary.content,
    JSON.stringify(worldSettings.setting_data, null, 2),
    JSON.stringify(characters.map((c) => ({ name: c.name, ...c.profile_data as object })), null, 2),
    project.steering_notes ?? undefined,
    totalCharCount,
    project.target_duration_minutes ?? undefined,
    project.target_choice_count ?? undefined
  );

  console.log(`[dag_skeleton] Starting LLM call for project ${projectId}, charCount=${totalCharCount}`);
  let dag = await callLlmJson<DagSkeleton>(env, config, DAG_SKELETON_SYSTEM, [
    { role: "user", content: prompt },
  ], { profileId, task: "dag_skeleton", projectId });

  console.log(`[dag_skeleton] LLM returned ${dag.nodes?.length ?? 0} nodes and ${dag.edges?.length ?? 0} edges`);

  if (!dag.nodes || !Array.isArray(dag.nodes) || dag.nodes.length === 0) {
    throw new Error(`DAG skeleton returned invalid structure: ${JSON.stringify(dag).slice(0, 200)}`);
  }

  // Validate DAG branching quality
  const validation = validateDagBranching(dag);
  if (!validation.valid) {
    console.warn(`[dag_skeleton] Validation failed: ${validation.issues.join(", ")}. Retrying with correction...`);
    const correctionPrompt = `之前生成的DAG结构有以下问题：
${validation.issues.map((i) => `- ${i}`).join("\n")}

请修复这些问题，确保：
1. 所有非结局节点都是choice类型，每个都有2-3条出边
2. 不存在线性链（连续节点之间只有一条路径）
3. 至少3条从开头到结局完全不同的路径

    原始DAG：
${JSON.stringify(dag, null, 2)}

请只输出修正后的原始JSON对象，不要使用Markdown代码块，不要添加解释文字。`;

    dag = await callLlmJson<DagSkeleton>(env, config, DAG_SKELETON_SYSTEM, [
      { role: "user", content: correctionPrompt },
    ], { profileId, task: "dag_skeleton", projectId });
    console.log(`[dag_skeleton] Retry returned ${dag.nodes?.length ?? 0} nodes`);
  }

  // Auto-layout: position nodes in a tree-like structure
  const positioned = autoLayoutDag(dag);
  console.log(`[dag_skeleton] Auto-layout complete, inserting into DB...`);

  // Clear any partial data from previous failed attempts
  await sql`DELETE FROM dag_edges WHERE project_id = ${projectId} AND version = 1`;
  await sql`DELETE FROM dag_nodes WHERE project_id = ${projectId} AND version = 1`;

  for (const node of positioned.nodes) {
    await insertDagNode(sql, projectId, 1, node);
  }
  for (const edge of positioned.edges) {
    await insertDagEdge(sql, projectId, 1, edge);
  }

  console.log(`[dag_skeleton] DB insert complete, marking done`);
  await updateGenerationJob(sql, jobId, "done", 1);

  // Continuous pipeline: if pipeline_running, auto-enqueue scene scripts
  const updatedProject = await getProject(sql, projectId);
  if (updatedProject?.status === "pipeline_running") {
    console.log(`[dag_skeleton] Pipeline mode — auto-enqueuing ${positioned.nodes.length} scene_script jobs`);
    await enqueueAllSceneScripts(sql, env, projectId, positioned.nodes);
  } else {
    await updateProjectStatus(sql, projectId, "phase1_ready");
  }
}

function autoLayoutDag(dag: DagSkeleton): DagSkeleton & { nodes: (DagSkeleton["nodes"][0] & { position_x: number; position_y: number })[] } {
  // Build adjacency for topological ordering
  const adjacency = new Map<string, string[]>();
  const inDegree = new Map<string, number>();

  for (const node of dag.nodes) {
    adjacency.set(node.node_key, []);
    inDegree.set(node.node_key, 0);
  }
  for (const edge of dag.edges) {
    adjacency.get(edge.source_node_key)?.push(edge.target_node_key);
    inDegree.set(edge.target_node_key, (inDegree.get(edge.target_node_key) ?? 0) + 1);
  }

  // BFS for layered layout
  const layers: string[][] = [];
  const queue: string[] = [];
  const nodeLayer = new Map<string, number>();

  for (const [key, deg] of inDegree) {
    if (deg === 0) queue.push(key);
  }

  let layer = 0;
  while (queue.length > 0) {
    const currentLayer = [...queue];
    layers.push(currentLayer);
    queue.length = 0;

    for (const key of currentLayer) {
      nodeLayer.set(key, layer);
      for (const child of adjacency.get(key) ?? []) {
        inDegree.set(child, (inDegree.get(child) ?? 0) - 1);
        if (inDegree.get(child) === 0) {
          queue.push(child);
        }
      }
    }
    layer++;
  }

  const NODE_X_GAP = 250;
  const NODE_Y_GAP = 150;

  const positionedNodes = dag.nodes.map((node) => {
    const l = nodeLayer.get(node.node_key) ?? 0;
    const layerNodes = layers[l] ?? [node.node_key];
    const idx = layerNodes.indexOf(node.node_key);
    const xOffset = -(layerNodes.length - 1) * NODE_X_GAP / 2;

    return {
      ...node,
      position_x: xOffset + idx * NODE_X_GAP,
      position_y: l * NODE_Y_GAP,
    };
  });

  return { nodes: positionedNodes, edges: dag.edges };
}

// --- DAG Validation ---
function validateDagBranching(dag: DagSkeleton): { valid: boolean; issues: string[] } {
  const issues: string[] = [];

  // Count unique targets per source (not just edge count)
  const uniqueTargets = new Map<string, Set<string>>();
  for (const node of dag.nodes) uniqueTargets.set(node.node_key, new Set());
  for (const edge of dag.edges) {
    const targets = uniqueTargets.get(edge.source_node_key);
    if (targets) targets.add(edge.target_node_key);
  }

  const nonEndingNodes = dag.nodes.filter((n) => !n.is_ending && !n.is_hidden_ending);
  const linearNodes = nonEndingNodes.filter((n) => (uniqueTargets.get(n.node_key)?.size ?? 0) < 2);
  if (linearNodes.length > 0) {
    issues.push(`${linearNodes.length}个非结局节点的选项导向不同目标少于2个: ${linearNodes.slice(0, 5).map((n) => n.node_key).join(", ")}`);
  }

  // Check for duplicate edges (same source→target with different labels)
  const dupeEdgeNodes: string[] = [];
  for (const [nodeKey, targets] of uniqueTargets) {
    const edgeCount = dag.edges.filter((e) => e.source_node_key === nodeKey).length;
    if (edgeCount > targets.size) dupeEdgeNodes.push(nodeKey);
  }
  if (dupeEdgeNodes.length > 0) {
    issues.push(`${dupeEdgeNodes.length}个节点有多条边指向相同目标（选项应导向不同节点）: ${dupeEdgeNodes.join(", ")}`);
  }

  const inDegree = new Map<string, number>();
  for (const node of dag.nodes) inDegree.set(node.node_key, 0);
  for (const edge of dag.edges) inDegree.set(edge.target_node_key, (inDegree.get(edge.target_node_key) ?? 0) + 1);

  let linearChainCount = 0;
  for (const edge of dag.edges) {
    const srcTargets = uniqueTargets.get(edge.source_node_key)?.size ?? 0;
    const tgtIn = inDegree.get(edge.target_node_key) ?? 0;
    const tgtNode = dag.nodes.find((n) => n.node_key === edge.target_node_key);
    if (srcTargets === 1 && tgtIn === 1 && tgtNode && !tgtNode.is_ending && !tgtNode.is_hidden_ending) {
      linearChainCount++;
    }
  }
  if (linearChainCount > dag.nodes.length * 0.2) {
    issues.push(`过多线性链接 (${linearChainCount}条)，需要更多分支`);
  }

  return { valid: issues.length === 0, issues };
}

// --- Auto-enqueue scene scripts (for continuous pipeline) ---
async function enqueueAllSceneScripts(
  sql: NeonSQL,
  env: Env,
  projectId: string,
  nodes: { node_key: string }[]
): Promise<void> {
  const BATCH_SIZE = 50;
  for (let batchStart = 0; batchStart < nodes.length; batchStart += BATCH_SIZE) {
    const batch = nodes.slice(batchStart, batchStart + BATCH_SIZE);
    const projectIds = batch.map(() => projectId);
    const kinds = batch.map(() => "scene_script");
    const targetKeys = batch.map((n) => n.node_key);

    const rows = await sql`
      INSERT INTO generation_jobs (project_id, job_kind, target_key)
      SELECT * FROM UNNEST(
        ${projectIds}::uuid[],
        ${kinds}::text[],
        ${targetKeys}::text[]
      )
      RETURNING id, target_key
    `;

    await Promise.all(
      rows.map((row) => {
        const r = row as unknown as { id: string; target_key: string };
        return enqueueSceneScript(env.BACKGROUND_QUEUE, r.id, projectId, r.target_key);
      })
    );
  }
}

// --- Scene Script ---
async function processSceneScript(
  sql: NeonSQL,
  env: Env,
  projectId: string,
  nodeKey: string,
  jobId: string,
  steeringNotes?: string
): Promise<void> {
  await updateGenerationJob(sql, jobId, "running");

  const project = await getProject(sql, projectId);
  if (!project) throw new Error("Project not found");

  const profileId = project.model_profile_id as ModelProfileId;
  const config = getTaskConfig(profileId, "scene_script");

  const [summary, worldSettings, characters, dagNodes, dagEdges] = await Promise.all([
    getLatestStorySummary(sql, projectId),
    getLatestWorldSettings(sql, projectId),
    getCharacters(sql, projectId),
    getDagNodes(sql, projectId),
    getDagEdges(sql, projectId),
  ]);

  if (!summary || !worldSettings) throw new Error("Missing story data");

  const currentNode = dagNodes.find((n) => n.node_key === nodeKey);
  if (!currentNode) throw new Error(`Node ${nodeKey} not found`);

  // Find predecessor's script
  const predecessorEdge = dagEdges.find((e) => e.target_node_key === nodeKey);
  let predecessorScript: string | undefined;
  if (predecessorEdge) {
    const predScript = await getSceneScript(sql, projectId, predecessorEdge.source_node_key);
    predecessorScript = predScript?.content;
  }

  // Build DAG skeleton string (just titles/summaries)
  const dagSummary = dagNodes
    .map((n) => `[${n.node_key}] ${n.title}: ${n.summary ?? ""}`)
    .join("\n");

  const prompt = buildSceneScriptPrompt({
    storySummary: summary.content,
    worldSettings: JSON.stringify(worldSettings.setting_data, null, 2),
    relevantCharacters: JSON.stringify(characters.map((c) => ({ name: c.name, ...c.profile_data as object })), null, 2),
    dagSkeleton: dagSummary,
    currentNode: {
      node_key: currentNode.node_key,
      title: currentNode.title,
      summary: currentNode.summary ?? "",
      scene_type: currentNode.scene_type,
    },
    predecessorScript,
    steeringNotes: steeringNotes ?? project.steering_notes ?? undefined,
  });

  const script = await callLlmText(env, config, SCENE_SCRIPT_SYSTEM, [
    { role: "user", content: prompt },
  ], { profileId, task: "scene_script", projectId });

  // Get next version number
  const existingVersions = await sql`
    SELECT max(version) as max_v FROM scene_scripts
    WHERE project_id = ${projectId} AND node_key = ${nodeKey}
  `;
  const maxV = (existingVersions[0] as unknown as { max_v: number | null }).max_v ?? 0;

  await insertSceneScript(sql, projectId, nodeKey, maxV + 1, script, steeringNotes);
  await updateGenerationJob(sql, jobId, "done", 1);

  // Check if all scene scripts are done → update project status
  await checkScriptGenComplete(sql, projectId);
}

async function checkScriptGenComplete(sql: NeonSQL, projectId: string): Promise<void> {
  const counts = await countJobsByStatus(sql, projectId, "scene_script");
  if (counts.queued === 0 && counts.running === 0 && counts.done > 0) {
    const project = await getProject(sql, projectId);
    if (project?.status === "pipeline_running") {
      await updateProjectStatus(sql, projectId, "done");
    } else {
      await updateProjectStatus(sql, projectId, "phase2_ready");
    }
  }
}

// --- Export DOCX ---
async function processExportDocx(
  sql: NeonSQL,
  env: Env,
  projectId: string,
  jobId: string
): Promise<void> {
  const { generateAllExports } = await import("./docxExport.ts");
  await generateAllExports(sql, env, projectId, jobId);
}
