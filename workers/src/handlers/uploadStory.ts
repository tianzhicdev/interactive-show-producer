import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import {
  clearStoryChunks,
  getStoryChunkStats,
  getStoryChunks,
  updateProjectStatus,
  getProject,
  upsertStoryChunk,
} from "../db.ts";
import { jsonResponse } from "../edge.ts";
import { chunkStoryText } from "../chunker.ts";

const MAX_CHUNK_CHARS = 40_000;

/**
 * Main upload handler: accepts JSON body with text field OR raw PUT body.
 * When R2 is available, stores to R2 first then chunks from there.
 * Falls back to in-memory chunking for JSON uploads.
 */
export async function handleUploadStory(
  sql: NeonSQL,
  env: Env,
  payload: unknown,
  request: Request
) {
  const url = new URL(request.url);
  const projectId = url.searchParams.get("project_id");
  if (!projectId) {
    return jsonResponse(400, { code: 400, message: "Missing project_id" });
  }

  const project = await getProject(sql, projectId);
  if (!project) {
    return jsonResponse(404, { code: 404, message: "Project not found" });
  }

  await updateProjectStatus(sql, projectId, "uploading");

  let text: string;

  if (request.method === "PUT") {
    // R2 path: stream to R2 then read back
    if (!request.body) {
      return jsonResponse(400, { code: 400, message: "Empty request body" });
    }

    const r2Key = `stories/${projectId}/raw.txt`;
    const bodyBytes = await request.arrayBuffer();
    await env.STORY_BUCKET.put(r2Key, bodyBytes, {
      httpMetadata: { contentType: "text/plain" },
    });

    const r2Object = await env.STORY_BUCKET.get(r2Key);
    if (!r2Object) {
      return jsonResponse(500, { code: 500, message: "Failed to read from R2" });
    }
    text = await r2Object.text();
  } else {
    // Legacy JSON path
    const body = payload as { text?: string };
    if (!body.text) {
      return jsonResponse(400, { code: 400, message: "Missing text field" });
    }
    text = body.text;
  }

  // Smart chunk with overlap + chapter awareness
  const chunks = chunkStoryText(text);

  // Bulk insert using UNNEST for efficiency
  const BATCH_SIZE = 50;
  for (let batchStart = 0; batchStart < chunks.length; batchStart += BATCH_SIZE) {
    const batch = chunks.slice(batchStart, batchStart + BATCH_SIZE);
    const indices = batch.map((_, j) => batchStart + j);
    const contents = batch.map((c) => c.content);
    const charCounts = batch.map((c) => c.content.length);
    const projectIds = batch.map(() => projectId);
    const chapterTitles = batch.map((c) => c.chapterTitle ?? null);

    await sql`
      INSERT INTO story_chunks (project_id, chunk_index, content, char_count, chapter_title)
      SELECT * FROM UNNEST(
        ${projectIds}::uuid[],
        ${indices}::int[],
        ${contents}::text[],
        ${charCounts}::int[],
        ${chapterTitles}::text[]
      )
    `;
  }

  await updateProjectStatus(sql, projectId, "draft");
  return jsonResponse(200, {
    project_id: projectId,
    total_chunks: chunks.length,
    status: "uploaded",
  });
}

export async function handleBeginChunkedUpload(
  sql: NeonSQL,
  _env: Env,
  payload: unknown
) {
  const body = payload as { project_id?: string };
  if (!body.project_id) {
    return jsonResponse(400, { code: 400, message: "Missing project_id" });
  }

  const project = await getProject(sql, body.project_id);
  if (!project) {
    return jsonResponse(404, { code: 404, message: "Project not found" });
  }

  await updateProjectStatus(sql, body.project_id, "uploading");
  await clearStoryChunks(sql, body.project_id);

  return jsonResponse(200, {
    project_id: body.project_id,
    status: "uploading",
  });
}

export async function handleUploadStoryChunk(
  sql: NeonSQL,
  _env: Env,
  payload: unknown
) {
  const body = payload as {
    project_id?: string;
    chunk_index?: number;
    content?: string;
  };

  if (!body.project_id || body.chunk_index === undefined || body.content === undefined) {
    return jsonResponse(400, { code: 400, message: "Missing project_id, chunk_index, or content" });
  }
  if (!Number.isInteger(body.chunk_index) || body.chunk_index < 0) {
    return jsonResponse(400, { code: 400, message: "Invalid chunk_index" });
  }
  if (body.content.length > MAX_CHUNK_CHARS) {
    return jsonResponse(400, {
      code: 400,
      message: `Chunk is too large; max ${MAX_CHUNK_CHARS} characters`,
    });
  }

  const project = await getProject(sql, body.project_id);
  if (!project) {
    return jsonResponse(404, { code: 404, message: "Project not found" });
  }

  await upsertStoryChunk(sql, body.project_id, body.chunk_index, body.content);

  return jsonResponse(200, {
    project_id: body.project_id,
    chunk_index: body.chunk_index,
    char_count: body.content.length,
    status: "chunk_uploaded",
  });
}

export async function handleFinalizeChunkedUpload(
  sql: NeonSQL,
  _env: Env,
  payload: unknown
) {
  const body = payload as {
    project_id?: string;
    total_chunks?: number;
    total_chars?: number;
  };

  if (!body.project_id || body.total_chunks === undefined || body.total_chars === undefined) {
    return jsonResponse(400, { code: 400, message: "Missing project_id, total_chunks, or total_chars" });
  }
  if (!Number.isInteger(body.total_chunks) || body.total_chunks <= 0) {
    return jsonResponse(400, { code: 400, message: "Invalid total_chunks" });
  }

  const project = await getProject(sql, body.project_id);
  if (!project) {
    return jsonResponse(404, { code: 404, message: "Project not found" });
  }

  const stats = await getStoryChunkStats(sql, body.project_id);
  const contiguous =
    stats.count === body.total_chunks &&
    stats.min_index === 0 &&
    stats.max_index === body.total_chunks - 1;

  if (!contiguous || stats.char_count !== body.total_chars) {
    return jsonResponse(409, {
      code: 409,
      message: "Uploaded chunks are incomplete or inconsistent",
      expected: {
        total_chunks: body.total_chunks,
        total_chars: body.total_chars,
      },
      actual: stats,
    });
  }

  // Reassemble raw transport chunks and re-chunk with smart chunking
  const rawChunks = await getStoryChunks(sql, body.project_id);
  const fullText = rawChunks.map((c) => c.content).join("");
  const smartChunks = chunkStoryText(fullText);

  // Replace raw chunks with smart chunks
  await clearStoryChunks(sql, body.project_id);
  const BATCH_SIZE = 50;
  for (let batchStart = 0; batchStart < smartChunks.length; batchStart += BATCH_SIZE) {
    const batch = smartChunks.slice(batchStart, batchStart + BATCH_SIZE);
    const indices = batch.map((_, j) => batchStart + j);
    const contents = batch.map((c) => c.content);
    const charCounts = batch.map((c) => c.content.length);
    const projectIds = batch.map(() => body.project_id);
    const chapterTitles = batch.map((c) => c.chapterTitle ?? null);

    await sql`
      INSERT INTO story_chunks (project_id, chunk_index, content, char_count, chapter_title)
      SELECT * FROM UNNEST(
        ${projectIds}::uuid[],
        ${indices}::int[],
        ${contents}::text[],
        ${charCounts}::int[],
        ${chapterTitles}::text[]
      )
    `;
  }

  await updateProjectStatus(sql, body.project_id, "draft");

  return jsonResponse(200, {
    project_id: body.project_id,
    total_chunks: smartChunks.length,
    total_chars: fullText.length,
    status: "uploaded",
  });
}
