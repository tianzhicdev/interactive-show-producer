import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getProject, getDagNodes, updateProjectStatus } from "../db.ts";
import { enqueueSceneScript } from "../backgroundJobsQueue.ts";
import { jsonResponse } from "../edge.ts";
import { projectIdSchema } from "@tomato/domain/schemas.ts";

export async function handleStartScriptGen(
  sql: NeonSQL,
  env: Env,
  payload: unknown
) {
  const { project_id } = projectIdSchema.parse(payload);
  const project = await getProject(sql, project_id);
  if (!project) {
    return jsonResponse(404, { code: 404, message: "Project not found" });
  }

  const dagNodes = await getDagNodes(sql, project_id);
  if (dagNodes.length === 0) {
    return jsonResponse(400, { code: 400, message: "No DAG nodes found" });
  }

  await updateProjectStatus(sql, project_id, "phase2_running");

  // Bulk-create generation_jobs and enqueue in batches
  const BATCH_SIZE = 50;
  for (let batchStart = 0; batchStart < dagNodes.length; batchStart += BATCH_SIZE) {
    const batch = dagNodes.slice(batchStart, batchStart + BATCH_SIZE);
    const projectIds = batch.map(() => project_id);
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
        return enqueueSceneScript(env.BACKGROUND_QUEUE, r.id, project_id, r.target_key);
      })
    );
  }

  return jsonResponse(200, {
    status: "phase2_started",
    total_scenes: dagNodes.length,
  });
}
