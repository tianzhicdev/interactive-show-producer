import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getProject, countJobsByStatus } from "../db.ts";
import { jsonResponse } from "../edge.ts";

export async function handleGetPhase1Status(
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

  const [chunkCounts, mergeCounts, wsCounts, charCounts, dagCounts] = await Promise.all([
    countJobsByStatus(sql, projectId, "summarize_chunk"),
    countJobsByStatus(sql, projectId, "summarize_merge"),
    countJobsByStatus(sql, projectId, "world_settings"),
    countJobsByStatus(sql, projectId, "characters"),
    countJobsByStatus(sql, projectId, "dag_skeleton"),
  ]);

  return jsonResponse(200, {
    project_status: project.status,
    pipeline: {
      summarize_chunk: chunkCounts,
      summarize_merge: mergeCounts,
      world_settings: wsCounts,
      characters: charCounts,
      dag_skeleton: dagCounts,
    },
  });
}
