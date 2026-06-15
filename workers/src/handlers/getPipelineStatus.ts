import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getProject, countJobsByStatus } from "../db.ts";
import { jsonResponse } from "../edge.ts";

export async function handleGetPipelineStatus(
  sql: NeonSQL,
  _env: Env,
  _payload: unknown,
  request: Request
) {
  const url = new URL(request.url);
  const projectId = url.searchParams.get("project_id");
  if (!projectId) {
    return jsonResponse(400, { code: 400, message: "Missing project_id" });
  }

  const project = await getProject(sql, projectId);
  if (!project) {
    return jsonResponse(404, { code: 404, message: "Project not found" });
  }

  const [chunkCounts, mergeCounts, wsCounts, charCounts, dagCounts, scriptCounts] = await Promise.all([
    countJobsByStatus(sql, projectId, "summarize_chunk"),
    countJobsByStatus(sql, projectId, "summarize_merge"),
    countJobsByStatus(sql, projectId, "world_settings"),
    countJobsByStatus(sql, projectId, "characters"),
    countJobsByStatus(sql, projectId, "dag_skeleton"),
    countJobsByStatus(sql, projectId, "scene_script"),
  ]);

  const elapsedSeconds = Math.round(
    (Date.now() - new Date(project.updated_at).getTime()) / 1000
  );

  const toStage = (counts: { queued: number; running: number; done: number; failed: number }) => ({
    ...counts,
    total: counts.queued + counts.running + counts.done + counts.failed,
  });

  return jsonResponse(200, {
    project_status: project.status,
    elapsed_seconds: elapsedSeconds,
    stages: {
      summarize_chunk: toStage(chunkCounts),
      summarize_merge: toStage(mergeCounts),
      world_settings: toStage(wsCounts),
      characters: toStage(charCounts),
      dag_skeleton: toStage(dagCounts),
      scene_script: toStage(scriptCounts),
    },
  });
}
