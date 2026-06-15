import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getProject, updateProjectStatus } from "../db.ts";
import { jsonResponse } from "../edge.ts";
import { projectIdSchema } from "@tomato/domain/schemas.ts";

export async function handleApprovePhase1(
  sql: NeonSQL,
  _env: Env,
  payload: unknown
) {
  const { project_id } = projectIdSchema.parse(payload);
  const project = await getProject(sql, project_id);
  if (!project) {
    return jsonResponse(404, { code: 404, message: "Project not found" });
  }
  if (project.status !== "phase1_ready") {
    return jsonResponse(400, { code: 400, message: `Cannot approve: project status is ${project.status}` });
  }

  // Phase 1 is now locked — ready for Phase 2
  return jsonResponse(200, { status: "phase1_approved" });
}
