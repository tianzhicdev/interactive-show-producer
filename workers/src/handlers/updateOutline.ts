import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import {
  insertWorldSettings,
  insertCharacter,
  insertDagNode,
  insertDagEdge,
  getDagNodes,
  getCharacters,
  getLatestWorldSettings,
  type Predicate,
  type StateEffect,
} from "../db.ts";
import { jsonResponse } from "../edge.ts";
import { updateOutlineSchema } from "@tomato/domain/schemas.ts";

export async function handleUpdateOutline(
  sql: NeonSQL,
  _env: Env,
  payload: unknown
) {
  const body = updateOutlineSchema.parse(payload);
  const projectId = body.project_id;

  // Each update creates a new version — immutable versioning

  if (body.world_settings) {
    const existing = await getLatestWorldSettings(sql, projectId);
    const newVersion = existing ? existing.version + 1 : 1;
    await insertWorldSettings(sql, projectId, newVersion, body.world_settings);
  }

  if (body.characters) {
    const existing = await getCharacters(sql, projectId);
    // Find max version
    const maxVersion = existing.reduce((max, c) => Math.max(max, c.version), 0);
    const newVersion = maxVersion + 1;
    for (const char of body.characters) {
      await insertCharacter(sql, projectId, newVersion, char.name, char.profile_data);
    }
  }

  if (body.dag_nodes || body.dag_edges) {
    const existingNodes = await getDagNodes(sql, projectId);
    const maxVersion = existingNodes.reduce((max, n) => Math.max(max, n.version), 0);
    const newVersion = maxVersion + 1;

    if (body.dag_nodes) {
      for (const node of body.dag_nodes) {
        await insertDagNode(sql, projectId, newVersion, {
          ...node,
          requires: node.requires as Predicate[] | null | undefined,
          invariants: node.invariants as Predicate[] | null | undefined,
        });
      }
    }
    if (body.dag_edges) {
      for (const edge of body.dag_edges) {
        await insertDagEdge(sql, projectId, newVersion, {
          ...edge,
          effects: edge.effects as StateEffect[] | null | undefined,
        });
      }
    }
  }

  return jsonResponse(200, { status: "updated" });
}
