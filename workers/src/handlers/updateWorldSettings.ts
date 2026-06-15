import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getLatestWorldSettings, insertWorldSettings } from "../db.ts";
import { jsonResponse } from "../edge.ts";
import { z } from "zod";

const schema = z.object({
  project_id: z.string().uuid(),
  setting_data: z.record(z.unknown()),
});

export async function handleUpdateWorldSettings(
  sql: NeonSQL,
  _env: Env,
  payload: unknown
) {
  const body = schema.parse(payload);

  const existing = await getLatestWorldSettings(sql, body.project_id);
  const newVersion = existing ? existing.version + 1 : 1;

  await insertWorldSettings(sql, body.project_id, newVersion, body.setting_data);

  return jsonResponse(200, { version: newVersion });
}
