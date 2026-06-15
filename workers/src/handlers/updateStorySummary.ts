import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { insertStorySummary, getLatestStorySummary } from "../db.ts";
import { jsonResponse } from "../edge.ts";
import { z } from "zod";

const schema = z.object({
  project_id: z.string().uuid(),
  content: z.string().min(1),
});

export async function handleUpdateStorySummary(
  sql: NeonSQL,
  _env: Env,
  payload: unknown
) {
  const body = schema.parse(payload);

  // Store with a unique version for manual edits (100000+)
  const existing = await getLatestStorySummary(sql, body.project_id);
  const newVersion = existing ? existing.version + 1 : 1;

  await insertStorySummary(sql, body.project_id, newVersion, body.content);

  return jsonResponse(200, { version: newVersion });
}
