import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { jsonResponse } from "../edge.ts";
import { z } from "zod";

const schema = z.object({
  project_id: z.string().uuid(),
  positions: z.array(
    z.object({
      node_key: z.string(),
      position_x: z.number(),
      position_y: z.number(),
    })
  ),
});

export async function handleUpdateNodePositions(
  sql: NeonSQL,
  _env: Env,
  payload: unknown
) {
  const body = schema.parse(payload);

  // Get latest version
  const rows = await sql`
    SELECT MAX(version) as max_v FROM dag_nodes WHERE project_id = ${body.project_id}
  `;
  const version = rows[0]?.max_v ?? 1;

  // Update positions in place (no new version — positions are visual-only)
  for (const p of body.positions) {
    await sql`
      UPDATE dag_nodes
      SET position_x = ${p.position_x}, position_y = ${p.position_y}
      WHERE project_id = ${body.project_id}
        AND version = ${version}
        AND node_key = ${p.node_key}
    `;
  }

  return jsonResponse(200, { updated: body.positions.length });
}
