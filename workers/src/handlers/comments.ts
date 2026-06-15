import { jsonResponse, type JsonResponse } from "../edge.ts";
import type { NeonSQL } from "../db.ts";
import { getComments, createComment, softDeleteComment } from "../db.ts";
import { z } from "zod";

const createSchema = z.object({
  project_id: z.string().uuid(),
  node_key: z.string().nullable().optional(),
  content: z.string().trim().min(1),
  author: z.string().trim().nullable().optional(),
});

const deleteSchema = z.object({
  project_id: z.string().uuid(),
  comment_id: z.string().uuid(),
});

export async function handleGetComments(
  sql: NeonSQL,
  request: Request
): Promise<JsonResponse<unknown>> {
  const url = new URL(request.url);
  const projectId = url.searchParams.get("project_id");
  if (!projectId) return jsonResponse(400, { code: 400, message: "Missing project_id" });

  const nodeKey = url.searchParams.get("node_key") || undefined;
  const comments = await getComments(sql, projectId, nodeKey);
  return jsonResponse(200, { comments });
}

export async function handleCreateComment(
  sql: NeonSQL,
  payload: unknown
): Promise<JsonResponse<unknown>> {
  const body = createSchema.parse(payload);

  const comment = await createComment(
    sql,
    body.project_id,
    body.content,
    body.node_key ?? undefined,
    body.author ?? undefined
  );

  return jsonResponse(201, { comment });
}

export async function handleDeleteComment(
  sql: NeonSQL,
  payload: unknown
): Promise<JsonResponse<unknown>> {
  const body = deleteSchema.parse(payload);
  const comment = await softDeleteComment(sql, body.project_id, body.comment_id);

  if (!comment) {
    return jsonResponse(404, { code: 404, message: "Comment not found" });
  }

  return jsonResponse(200, { comment });
}
