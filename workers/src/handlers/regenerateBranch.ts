import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getProject, getDagNodes, getDagEdges, createGenerationJob } from "../db.ts";
import { enqueueSceneScript } from "../backgroundJobsQueue.ts";
import { jsonResponse } from "../edge.ts";
import { regenerateBranchSchema } from "@tomato/domain/schemas.ts";

export async function handleRegenerateBranch(
  sql: NeonSQL,
  env: Env,
  payload: unknown
) {
  const body = regenerateBranchSchema.parse(payload);
  const project = await getProject(sql, body.project_id);
  if (!project) {
    return jsonResponse(404, { code: 404, message: "Project not found" });
  }

  const [dagNodes, dagEdges] = await Promise.all([
    getDagNodes(sql, body.project_id),
    getDagEdges(sql, body.project_id),
  ]);

  // BFS walk from root_node_key to find all downstream nodes
  const adjacency = new Map<string, string[]>();
  for (const edge of dagEdges) {
    const children = adjacency.get(edge.source_node_key) ?? [];
    children.push(edge.target_node_key);
    adjacency.set(edge.source_node_key, children);
  }

  const downstream = new Set<string>();
  const queue = [body.root_node_key];
  while (queue.length > 0) {
    const current = queue.shift()!;
    downstream.add(current);
    for (const child of adjacency.get(current) ?? []) {
      if (!downstream.has(child)) {
        queue.push(child);
      }
    }
  }

  // Enqueue regeneration for all downstream nodes
  const jobPromises: Promise<void>[] = [];
  for (const nodeKey of downstream) {
    jobPromises.push(
      (async () => {
        const job = await createGenerationJob(sql, body.project_id, "scene_script", nodeKey);
        await enqueueSceneScript(
          env.BACKGROUND_QUEUE,
          job.id,
          body.project_id,
          nodeKey,
          body.steering_notes
        );
      })()
    );
  }
  await Promise.all(jobPromises);

  return jsonResponse(200, {
    status: "regenerating_branch",
    total_nodes: downstream.size,
    node_keys: [...downstream],
  });
}
