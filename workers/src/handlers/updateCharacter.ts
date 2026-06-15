import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getCharacters, insertCharacter } from "../db.ts";
import { jsonResponse } from "../edge.ts";
import { z } from "zod";

const schema = z.object({
  project_id: z.string().uuid(),
  name: z.string().min(1),
  profile_data: z.record(z.unknown()),
});

export async function handleUpdateCharacter(
  sql: NeonSQL,
  _env: Env,
  payload: unknown
) {
  const body = schema.parse(payload);

  const existing = await getCharacters(sql, body.project_id);
  const maxVersion = existing.reduce((max, c) => Math.max(max, c.version), 0);
  const newVersion = maxVersion + 1;

  // Insert all existing characters at the new version, updating the one that changed
  for (const char of existing) {
    if (char.name === body.name) {
      await insertCharacter(sql, body.project_id, newVersion, body.name, body.profile_data);
    } else {
      await insertCharacter(sql, body.project_id, newVersion, char.name, char.profile_data);
    }
  }

  // If this is a new character (not found in existing)
  if (!existing.find((c) => c.name === body.name)) {
    await insertCharacter(sql, body.project_id, newVersion, body.name, body.profile_data);
  }

  return jsonResponse(200, { version: newVersion });
}
