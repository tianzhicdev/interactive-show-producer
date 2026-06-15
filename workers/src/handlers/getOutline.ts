import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import {
  getProject,
  getLatestStorySummary,
  getLatestWorldSettings,
  getCharacters,
  getDagNodes,
  getDagEdges,
} from "../db.ts";
import { jsonResponse } from "../edge.ts";

export async function handleGetOutline(
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

  const project = await getProject(sql, projectId);
  if (!project) {
    return jsonResponse(404, { code: 404, message: "Project not found" });
  }

  const [summary, worldSettings, characters, dagNodes, dagEdges] = await Promise.all([
    getLatestStorySummary(sql, projectId),
    getLatestWorldSettings(sql, projectId),
    getCharacters(sql, projectId),
    getDagNodes(sql, projectId),
    getDagEdges(sql, projectId),
  ]);

  return jsonResponse(200, {
    project,
    story_summary: summary?.content ?? null,
    world_settings: worldSettings?.setting_data ?? null,
    characters: characters.map((c) => ({
      id: c.id,
      name: c.name,
      profile_data: c.profile_data,
    })),
    dag: {
      nodes: dagNodes,
      edges: dagEdges,
    },
  });
}
