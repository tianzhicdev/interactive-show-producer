import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getSceneScript, getSceneScriptByVersion, insertSceneScript } from "../db.ts";
import { jsonResponse } from "../edge.ts";
import { z } from "zod";

const schema = z.object({
  project_id: z.string().uuid(),
  node_key: z.string(),
  version: z.number().int().positive(),
});

export async function handleRevertSceneScript(
  sql: NeonSQL,
  _env: Env,
  payload: unknown
) {
  const body = schema.parse(payload);

  // Fetch the old version to copy
  const oldVersion = await getSceneScriptByVersion(
    sql, body.project_id, body.node_key, body.version
  );
  if (!oldVersion) {
    return jsonResponse(404, { code: 404, message: "Version not found" });
  }

  // Get current max version
  const current = await getSceneScript(sql, body.project_id, body.node_key);
  const newVersion = current ? current.version + 1 : 1;

  // Insert old content as new version
  await insertSceneScript(
    sql,
    body.project_id,
    body.node_key,
    newVersion,
    oldVersion.content,
    `reverted from v${body.version}`
  );

  return jsonResponse(200, { version: newVersion });
}
