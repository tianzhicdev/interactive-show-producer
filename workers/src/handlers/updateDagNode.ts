import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getDagNodes, getDagEdges, insertDagNode, insertDagEdge } from "../db.ts";
import { jsonResponse } from "../edge.ts";
import { z } from "zod";

const updateSchema = z.object({
  project_id: z.string().uuid(),
  node_key: z.string(),
  title: z.string().optional(),
  summary: z.string().optional(),
  scene_type: z.enum(["normal", "choice", "ending", "hidden_ending"]).optional(),
  is_ending: z.boolean().optional(),
  is_hidden_ending: z.boolean().optional(),
});

const deleteSchema = z.object({
  project_id: z.string().uuid(),
  node_key: z.string(),
});

export async function handleUpdateDagNode(
  sql: NeonSQL,
  _env: Env,
  payload: unknown
) {
  const body = updateSchema.parse(payload);

  const existingNodes = await getDagNodes(sql, body.project_id);
  const existingEdges = await getDagEdges(sql, body.project_id);
  const maxVersion = existingNodes.reduce((max, n) => Math.max(max, n.version), 0);
  const newVersion = maxVersion + 1;

  // Copy all nodes to new version, updating the target node
  for (const node of existingNodes) {
    if (node.node_key === body.node_key) {
      await insertDagNode(sql, body.project_id, newVersion, {
        node_key: node.node_key,
        title: body.title ?? node.title,
        summary: body.summary !== undefined ? body.summary : (node.summary ?? undefined),
        scene_type: body.scene_type ?? node.scene_type,
        is_ending: body.is_ending !== undefined ? body.is_ending : node.is_ending,
        is_hidden_ending: body.is_hidden_ending !== undefined ? body.is_hidden_ending : node.is_hidden_ending,
        position_x: node.position_x,
        position_y: node.position_y,
        requires: node.requires,
        invariants: node.invariants,
        computed_states: node.computed_states,
      });
    } else {
      await insertDagNode(sql, body.project_id, newVersion, {
        node_key: node.node_key,
        title: node.title,
        summary: node.summary ?? undefined,
        scene_type: node.scene_type,
        is_ending: node.is_ending,
        is_hidden_ending: node.is_hidden_ending,
        position_x: node.position_x,
        position_y: node.position_y,
        requires: node.requires,
        invariants: node.invariants,
        computed_states: node.computed_states,
      });
    }
  }

  // Copy all edges unchanged
  for (const edge of existingEdges) {
    await insertDagEdge(sql, body.project_id, newVersion, {
      source_node_key: edge.source_node_key,
      target_node_key: edge.target_node_key,
      choice_label: edge.choice_label ?? undefined,
      choice_index: edge.choice_index,
      effects: edge.effects,
    });
  }

  return jsonResponse(200, { version: newVersion });
}

export async function handleDeleteDagNode(
  sql: NeonSQL,
  _env: Env,
  payload: unknown
) {
  const body = deleteSchema.parse(payload);

  const existingNodes = await getDagNodes(sql, body.project_id);
  const existingEdges = await getDagEdges(sql, body.project_id);
  const maxVersion = existingNodes.reduce((max, n) => Math.max(max, n.version), 0);
  const newVersion = maxVersion + 1;

  // Copy all nodes except the deleted one
  for (const node of existingNodes) {
    if (node.node_key === body.node_key) continue;
    await insertDagNode(sql, body.project_id, newVersion, {
      node_key: node.node_key,
      title: node.title,
      summary: node.summary ?? undefined,
      scene_type: node.scene_type,
      is_ending: node.is_ending,
      is_hidden_ending: node.is_hidden_ending,
      position_x: node.position_x,
      position_y: node.position_y,
      requires: node.requires,
      invariants: node.invariants,
      computed_states: node.computed_states,
    });
  }

  // Copy edges that don't involve the deleted node
  for (const edge of existingEdges) {
    if (edge.source_node_key === body.node_key || edge.target_node_key === body.node_key) continue;
    await insertDagEdge(sql, body.project_id, newVersion, {
      source_node_key: edge.source_node_key,
      target_node_key: edge.target_node_key,
      choice_label: edge.choice_label ?? undefined,
      choice_index: edge.choice_index,
      effects: edge.effects,
    });
  }

  return jsonResponse(200, { version: newVersion, deleted: body.node_key });
}
