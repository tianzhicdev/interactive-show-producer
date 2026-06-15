import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getDagNodes, getDagEdges, getAllSceneScripts } from "../db.ts";
import { jsonResponse } from "../edge.ts";

export async function handleGetDag(
  sql: NeonSQL,
  _env: Env,
  _payload: unknown,
  request: Request
) {
  const url = new URL(request.url);
  const projectId = url.searchParams.get("project_id");
  if (!projectId) {
    return jsonResponse(400, { code: 400, message: "Missing project_id" });
  }

  const [nodes, edges, scripts] = await Promise.all([
    getDagNodes(sql, projectId),
    getDagEdges(sql, projectId),
    getAllSceneScripts(sql, projectId),
  ]);

  // Build a script status map
  const scriptStatus = new Map<string, { has_script: boolean; version: number }>();
  for (const script of scripts) {
    scriptStatus.set(script.node_key, {
      has_script: true,
      version: script.version,
    });
  }

  return jsonResponse(200, {
    nodes: nodes.map((n) => ({
      ...n,
      script_status: scriptStatus.get(n.node_key) ?? { has_script: false, version: 0 },
    })),
    edges,
  });
}
