import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getProject, getStoryChunkCount, updateProjectStatus } from "../db.ts";
import { enqueueSummarizeChunkBatch } from "../backgroundJobsQueue.ts";
import { jsonResponse } from "../edge.ts";
import { projectIdSchema } from "@tomato/domain/schemas.ts";

/**
 * Start the full continuous pipeline: summarize → merge → world/chars → DAG → scene scripts.
 * Sets status to pipeline_running so the queue consumer auto-continues after DAG.
 */
export async function handleStartPipeline(
  sql: NeonSQL,
  env: Env,
  payload: unknown
) {
  const { project_id } = projectIdSchema.parse(payload);
  const project = await getProject(sql, project_id);
  if (!project) {
    return jsonResponse(404, { code: 404, message: "Project not found" });
  }

  const chunkCount = await getStoryChunkCount(sql, project_id);
  if (chunkCount === 0) {
    return jsonResponse(400, { code: 400, message: "No story chunks uploaded yet" });
  }

  await updateProjectStatus(sql, project_id, "pipeline_running");

  // Bulk-create summarize jobs (same pattern as startPhase1)
  const DB_BATCH = 200;
  const allJobs: { jobId: string; projectId: string; chunkIndex: number }[] = [];

  for (let batchStart = 0; batchStart < chunkCount; batchStart += DB_BATCH) {
    const batchEnd = Math.min(batchStart + DB_BATCH, chunkCount);
    const indices = Array.from({ length: batchEnd - batchStart }, (_, j) => batchStart + j);
    const projectIds = indices.map(() => project_id);
    const kinds = indices.map(() => "summarize_chunk");
    const targetKeys = indices.map((i) => `chunk-${i}`);

    const rows = await sql`
      INSERT INTO generation_jobs (project_id, job_kind, target_key)
      SELECT * FROM UNNEST(
        ${projectIds}::uuid[],
        ${kinds}::text[],
        ${targetKeys}::text[]
      )
      ON CONFLICT (project_id, job_kind, target_key)
      DO UPDATE SET
        status = CASE
          WHEN generation_jobs.status = 'done' THEN generation_jobs.status
          ELSE 'queued'
        END,
        error_message = CASE
          WHEN generation_jobs.status = 'done' THEN generation_jobs.error_message
          ELSE NULL
        END,
        updated_at = now()
      RETURNING id, target_key, status
    `;

    for (const row of rows) {
      const r = row as unknown as { id: string; target_key: string; status: string };
      if (r.status === "done") continue;
      allJobs.push({
        jobId: r.id,
        projectId: project_id,
        chunkIndex: parseInt(r.target_key.replace("chunk-", "")),
      });
    }
  }

  await enqueueSummarizeChunkBatch(env.BACKGROUND_QUEUE, allJobs);

  return jsonResponse(200, {
    status: "pipeline_started",
    total_chunks: chunkCount,
    enqueued_chunks: allJobs.length,
  });
}
