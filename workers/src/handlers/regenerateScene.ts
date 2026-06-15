import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getProject, createGenerationJob } from "../db.ts";
import { enqueueSceneScript } from "../backgroundJobsQueue.ts";
import { jsonResponse } from "../edge.ts";
import { regenerateSceneSchema } from "@tomato/domain/schemas.ts";

export async function handleRegenerateScene(
  sql: NeonSQL,
  env: Env,
  payload: unknown
) {
  const body = regenerateSceneSchema.parse(payload);
  const project = await getProject(sql, body.project_id);
  if (!project) {
    return jsonResponse(404, { code: 404, message: "Project not found" });
  }

  const job = await createGenerationJob(sql, body.project_id, "scene_script", body.node_key);
  await enqueueSceneScript(
    env.BACKGROUND_QUEUE,
    job.id,
    body.project_id,
    body.node_key,
    body.steering_notes
  );

  return jsonResponse(200, { status: "regenerating", job_id: job.id });
}
