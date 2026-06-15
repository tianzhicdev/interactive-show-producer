import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getSceneScript, insertSceneScript } from "../db.ts";
import { jsonResponse } from "../edge.ts";
import { z } from "zod";

const schema = z.object({
  project_id: z.string().uuid(),
  node_key: z.string(),
  content: z.string().min(1),
  steering_notes: z.string().optional(),
});

export async function handleUpdateSceneScript(
  sql: NeonSQL,
  _env: Env,
  payload: unknown
) {
  const body = schema.parse(payload);

  // Get current max version
  const existing = await getSceneScript(sql, body.project_id, body.node_key);
  const newVersion = existing ? existing.version + 1 : 1;

  await insertSceneScript(
    sql,
    body.project_id,
    body.node_key,
    newVersion,
    body.content,
    body.steering_notes
  );

  return jsonResponse(200, { version: newVersion });
}
