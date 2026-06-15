import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { listProjects } from "../db.ts";
import { jsonResponse } from "../edge.ts";

interface JobProgress {
  project_id: string;
  total: number;
  done: number;
  running: number;
  failed: number;
}

export async function handleListProjects(sql: NeonSQL, _env: Env) {
  const projects = await listProjects(sql);

  // Get aggregated job progress per project for running projects
  const runningIds = projects
    .filter((p: { status: string }) => p.status === "phase1_running" || p.status === "phase2_running")
    .map((p: { id: string }) => p.id);

  let progressMap: Record<string, JobProgress> = {};
  if (runningIds.length > 0) {
    const rows = await sql`
      SELECT project_id,
        COUNT(*)::int AS total,
        COUNT(*) FILTER (WHERE status = 'done')::int AS done,
        COUNT(*) FILTER (WHERE status = 'running')::int AS running,
        COUNT(*) FILTER (WHERE status = 'failed')::int AS failed
      FROM generation_jobs
      WHERE project_id = ANY(${runningIds})
      GROUP BY project_id
    `;
    for (const row of rows) {
      const r = row as unknown as JobProgress;
      progressMap[r.project_id] = r;
    }
  }

  const enriched = projects.map((p: { id: string; status: string }) => {
    const progress = progressMap[p.id];
    if (progress) {
      const pct = progress.total > 0
        ? Math.round(((progress.done + progress.running * 0.3) / progress.total) * 100)
        : 0;
      return { ...p, progress: { ...progress, percent: pct } };
    }
    return p;
  });

  return jsonResponse(200, { projects: enriched });
}
