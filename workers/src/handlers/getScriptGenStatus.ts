import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getProject, countJobsByStatus, getJobsByKind } from "../db.ts";
import { jsonResponse } from "../edge.ts";

export async function handleGetScriptGenStatus(
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

  const counts = await countJobsByStatus(sql, projectId, "scene_script");
  const jobs = await getJobsByKind(sql, projectId, "scene_script");

  return jsonResponse(200, {
    project_status: project.status,
    scene_scripts: counts,
    per_node: jobs.map((j) => ({
      node_key: j.target_key,
      status: j.status,
      progress: j.progress,
      error: j.error_message,
    })),
  });
}
