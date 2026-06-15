import type { NeonSQL } from "../db.ts";
import type { Env } from "../env.ts";
import { getProject } from "../db.ts";
import { enqueueExportDocx } from "../backgroundJobsQueue.ts";
import { jsonResponse } from "../edge.ts";
import { projectIdSchema } from "@tomato/domain/schemas.ts";

export async function handleExportDeliverables(
  sql: NeonSQL,
  env: Env,
  payload: unknown
) {
  const { project_id } = projectIdSchema.parse(payload);
  const project = await getProject(sql, project_id);
  if (!project) {
    return jsonResponse(404, { code: 404, message: "Project not found" });
  }

  // Upsert: reset existing export job or create new one
  const rows = await sql`
    INSERT INTO generation_jobs (project_id, job_kind, target_key, status, progress)
    VALUES (${project_id}, 'export_docx', 'export', 'queued', 0)
    ON CONFLICT (project_id, job_kind, target_key)
    DO UPDATE SET status = 'queued', progress = 0, error_message = NULL, updated_at = now()
    RETURNING *
  `;
  const job = rows[0] as { id: string };
  await enqueueExportDocx(env.BACKGROUND_QUEUE, job.id, project_id);

  return jsonResponse(200, { status: "exporting", job_id: job.id });
}
