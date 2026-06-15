import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { enqueueBackgroundJob, type BackgroundJob } from "../backgroundJobsQueue.ts";
import { jsonResponse } from "../edge.ts";

const DEFAULT_STALE_AFTER_SECONDS = 600;

function parseChunkIndex(targetKey: string | null): number | null {
  const match = targetKey?.match(/^chunk-(\d+)$/);
  return match ? Number.parseInt(match[1], 10) : null;
}

function toQueueMessage(row: {
  id: string;
  project_id: string;
  job_kind: string;
  target_key: string | null;
}): BackgroundJob | null {
  switch (row.job_kind) {
    case "summarize_chunk": {
      const chunkIndex = parseChunkIndex(row.target_key);
      if (chunkIndex === null) return null;
      return {
        kind: "summarize_chunk",
        jobId: row.id,
        projectId: row.project_id,
        chunkIndex,
        queuedAt: new Date().toISOString(),
      };
    }
    case "world_settings":
      return { kind: "world_settings", jobId: row.id, projectId: row.project_id, queuedAt: new Date().toISOString() };
    case "characters":
      return { kind: "characters", jobId: row.id, projectId: row.project_id, queuedAt: new Date().toISOString() };
    case "dag_skeleton":
      return { kind: "dag_skeleton", jobId: row.id, projectId: row.project_id, queuedAt: new Date().toISOString() };
    case "summarize_merge":
      return null; // merge jobs need groupIndex/totalGroups not stored in generation_jobs
    case "scene_script":
      if (!row.target_key) return null;
      return { kind: "scene_script", jobId: row.id, projectId: row.project_id, nodeKey: row.target_key, queuedAt: new Date().toISOString() };
    case "export_docx":
      return { kind: "export_docx", jobId: row.id, projectId: row.project_id, queuedAt: new Date().toISOString() };
    default:
      return null;
  }
}

export async function handleRecoverStaleJobs(sql: NeonSQL, env: Env, payload: unknown) {
  const body = payload as {
    project_id?: string;
    stale_after_seconds?: number;
    include_queued?: boolean;
  };
  if (!body.project_id) {
    return jsonResponse(400, { code: 400, message: "Missing project_id" });
  }

  const staleAfterSeconds =
    Number.isInteger(body.stale_after_seconds) && body.stale_after_seconds! > 0
      ? body.stale_after_seconds!
      : DEFAULT_STALE_AFTER_SECONDS;

  const rows = body.include_queued
    ? await sql`
    SELECT id, project_id, job_kind, target_key
    FROM generation_jobs
    WHERE project_id = ${body.project_id}
      AND status = 'queued'
    `
    : await sql`
    UPDATE generation_jobs
    SET status = 'queued',
        error_message = ${`Recovered from stale running state after ${staleAfterSeconds}s`},
        updated_at = now()
    WHERE project_id = ${body.project_id}
      AND status = 'running'
      AND updated_at < now() - (${staleAfterSeconds} || ' seconds')::interval
    RETURNING id, project_id, job_kind, target_key
  `;

  const requeued: string[] = [];
  const skipped: string[] = [];

  for (const row of rows as unknown as {
    id: string;
    project_id: string;
    job_kind: string;
    target_key: string | null;
  }[]) {
    const message = toQueueMessage(row);
    if (!message) {
      skipped.push(row.id);
      continue;
    }
    await enqueueBackgroundJob(env.BACKGROUND_QUEUE, message);
    requeued.push(row.id);
  }

  return jsonResponse(200, {
    status: "recovered",
    stale_after_seconds: staleAfterSeconds,
    include_queued: body.include_queued === true,
    requeued_count: requeued.length,
    skipped_count: skipped.length,
    requeued,
    skipped,
  });
}
