import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getSceneScript, getSceneScriptVersions, getSceneScriptByVersion } from "../db.ts";
import { jsonResponse } from "../edge.ts";

export async function handleGetScene(
  sql: NeonSQL,
  _env: Env,
  _payload: unknown,
  request: Request
) {
  const url = new URL(request.url);
  const projectId = url.searchParams.get("project_id");
  const nodeKey = url.searchParams.get("node_key");
  if (!projectId || !nodeKey) {
    return jsonResponse(400, { code: 400, message: "Missing project_id or node_key" });
  }

  const current = await getSceneScript(sql, projectId, nodeKey);
  const versions = await getSceneScriptVersions(sql, projectId, nodeKey);

  // Optional version preview
  let preview: { version: number; content: string; status: string; created_at: string } | undefined;
  const versionParam = url.searchParams.get("version");
  if (versionParam) {
    const v = parseInt(versionParam, 10);
    if (!isNaN(v)) {
      const pv = await getSceneScriptByVersion(sql, projectId, nodeKey, v);
      if (pv) {
        preview = { version: pv.version, content: pv.content, status: pv.status, created_at: pv.created_at };
      }
    }
  }

  return jsonResponse(200, {
    current,
    versions: versions.map((v) => ({
      version: v.version,
      status: v.status,
      steering_notes: v.steering_notes,
      created_at: v.created_at,
    })),
    preview,
  });
}
