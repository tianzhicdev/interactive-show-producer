import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getProject, createGenerationJob } from "../db.ts";
import { enqueueSceneScript } from "../backgroundJobsQueue.ts";
import { jsonResponse } from "../edge.ts";
import { regenerateNodesSchema } from "@tomato/domain/schemas.ts";

export async function handleRegenerateNodes(
  sql: NeonSQL,
  env: Env,
  payload: unknown
) {
  const body = regenerateNodesSchema.parse(payload);
  const project = await getProject(sql, body.project_id);
  if (!project) {
    return jsonResponse(404, { code: 404, message: "Project not found" });
  }

  const jobPromises: Promise<void>[] = [];
  for (const nodeKey of body.node_keys) {
    jobPromises.push(
      (async () => {
        const job = await createGenerationJob(sql, body.project_id, "scene_script", nodeKey);
        await enqueueSceneScript(
          env.BACKGROUND_QUEUE,
          job.id,
          body.project_id,
          nodeKey,
          body.steering_notes
        );
      })()
    );
  }
  await Promise.all(jobPromises);

  return jsonResponse(200, {
    status: "regenerating",
    total_nodes: body.node_keys.length,
    node_keys: body.node_keys,
  });
}
