import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { createProject } from "../db.ts";
import { jsonResponse } from "../edge.ts";
import { createProjectSchema } from "@tomato/domain/schemas.ts";

export async function handleCreateProject(
  sql: NeonSQL,
  _env: Env,
  payload: unknown
) {
  const body = createProjectSchema.parse(payload);
  const project = await createProject(
    sql,
    body.name,
    body.model_profile_id,
    body.steering_notes,
    body.target_duration_minutes,
    body.target_choice_count
  );
  return jsonResponse(200, { project });
}
