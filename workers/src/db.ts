import { neon } from "@neondatabase/serverless";

export type NeonSQL = (
  strings: TemplateStringsArray,
  ...values: unknown[]
) => Promise<Record<string, unknown>[]>;

export function createSQL(databaseUrl: string): NeonSQL {
  return neon(databaseUrl) as NeonSQL;
}

// --- Projects ---

export interface ProjectRow {
  id: string;
  name: string;
  status: string;
  model_profile_id: string;
  steering_notes: string | null;
  target_duration_minutes: number | null;
  target_choice_count: number | null;
  created_at: string;
  updated_at: string;
}

export async function createProject(
  sql: NeonSQL,
  name: string,
  modelProfileId: string = "default",
  steeringNotes?: string,
  targetDurationMinutes?: number,
  targetChoiceCount?: number
): Promise<ProjectRow> {
  const rows = await sql`
    INSERT INTO projects (name, model_profile_id, steering_notes, target_duration_minutes, target_choice_count)
    VALUES (${name}, ${modelProfileId}, ${steeringNotes ?? null}, ${targetDurationMinutes ?? null}, ${targetChoiceCount ?? null})
    RETURNING *
  `;
  return rows[0] as unknown as ProjectRow;
}

export async function getProject(sql: NeonSQL, id: string): Promise<ProjectRow | null> {
  const rows = await sql`SELECT * FROM projects WHERE id = ${id} LIMIT 1`;
  return (rows[0] as unknown as ProjectRow) ?? null;
}

export async function listProjects(sql: NeonSQL): Promise<ProjectRow[]> {
  const rows = await sql`SELECT * FROM projects ORDER BY created_at DESC`;
  return rows as unknown as ProjectRow[];
}

export async function updateProjectStatus(
  sql: NeonSQL,
  id: string,
  status: string
): Promise<void> {
  await sql`UPDATE projects SET status = ${status}, updated_at = now() WHERE id = ${id}`;
}

// --- Story Chunks ---

export interface StoryChunkRow {
  id: string;
  project_id: string;
  chunk_index: number;
  content: string;
  char_count: number;
  chapter_title: string | null;
}

export async function insertStoryChunk(
  sql: NeonSQL,
  projectId: string,
  chunkIndex: number,
  content: string,
  chapterTitle?: string | null
): Promise<void> {
  await sql`
    INSERT INTO story_chunks (project_id, chunk_index, content, char_count, chapter_title)
    VALUES (${projectId}, ${chunkIndex}, ${content}, ${content.length}, ${chapterTitle ?? null})
  `;
}

export async function upsertStoryChunk(
  sql: NeonSQL,
  projectId: string,
  chunkIndex: number,
  content: string
): Promise<void> {
  await sql`
    INSERT INTO story_chunks (project_id, chunk_index, content, char_count)
    VALUES (${projectId}, ${chunkIndex}, ${content}, ${content.length})
    ON CONFLICT (project_id, chunk_index)
    DO UPDATE SET content = EXCLUDED.content, char_count = EXCLUDED.char_count
  `;
}

export async function clearStoryChunks(sql: NeonSQL, projectId: string): Promise<void> {
  await sql`DELETE FROM story_chunks WHERE project_id = ${projectId}`;
}

export async function getStoryChunkStats(
  sql: NeonSQL,
  projectId: string
): Promise<{ count: number; min_index: number | null; max_index: number | null; char_count: number }> {
  const rows = await sql`
    SELECT
      count(*)::int AS count,
      min(chunk_index)::int AS min_index,
      max(chunk_index)::int AS max_index,
      COALESCE(sum(char_count), 0)::int AS char_count
    FROM story_chunks
    WHERE project_id = ${projectId}
  `;
  return rows[0] as unknown as {
    count: number;
    min_index: number | null;
    max_index: number | null;
    char_count: number;
  };
}

export async function getStoryChunks(sql: NeonSQL, projectId: string): Promise<StoryChunkRow[]> {
  const rows = await sql`
    SELECT * FROM story_chunks WHERE project_id = ${projectId} ORDER BY chunk_index
  `;
  return rows as unknown as StoryChunkRow[];
}

export async function getStoryChunkCount(sql: NeonSQL, projectId: string): Promise<number> {
  const rows = await sql`SELECT count(*)::int as count FROM story_chunks WHERE project_id = ${projectId}`;
  return (rows[0] as unknown as { count: number }).count;
}

// --- Story Summaries ---

export interface StorySummaryRow {
  project_id: string;
  version: number;
  content: string;
  arc_breakdown: unknown;
}

export async function insertStorySummary(
  sql: NeonSQL,
  projectId: string,
  version: number,
  content: string,
  arcBreakdown?: unknown
): Promise<void> {
  await sql`
    INSERT INTO story_summaries (project_id, version, content, arc_breakdown)
    VALUES (${projectId}, ${version}, ${content}, ${JSON.stringify(arcBreakdown ?? null)})
    ON CONFLICT (project_id, version) DO UPDATE SET
      content = EXCLUDED.content,
      arc_breakdown = EXCLUDED.arc_breakdown
  `;
}

export async function getLatestStorySummary(
  sql: NeonSQL,
  projectId: string
): Promise<StorySummaryRow | null> {
  const rows = await sql`
    SELECT * FROM story_summaries WHERE project_id = ${projectId}
    ORDER BY version DESC LIMIT 1
  `;
  return (rows[0] as unknown as StorySummaryRow) ?? null;
}

// --- World Settings ---

export async function insertWorldSettings(
  sql: NeonSQL,
  projectId: string,
  version: number,
  settingData: unknown
): Promise<void> {
  await sql`
    INSERT INTO world_settings (project_id, version, setting_data)
    VALUES (${projectId}, ${version}, ${JSON.stringify(settingData)})
    ON CONFLICT (project_id, version) DO UPDATE SET
      setting_data = EXCLUDED.setting_data
  `;
}

export async function getLatestWorldSettings(
  sql: NeonSQL,
  projectId: string
): Promise<{ project_id: string; version: number; setting_data: unknown } | null> {
  const rows = await sql`
    SELECT * FROM world_settings WHERE project_id = ${projectId}
    ORDER BY version DESC LIMIT 1
  `;
  return (rows[0] as unknown as { project_id: string; version: number; setting_data: unknown }) ?? null;
}

// --- Characters ---

export interface CharacterRow {
  id: string;
  project_id: string;
  version: number;
  name: string;
  profile_data: unknown;
}

export async function insertCharacter(
  sql: NeonSQL,
  projectId: string,
  version: number,
  name: string,
  profileData: unknown
): Promise<void> {
  await sql`
    INSERT INTO characters (project_id, version, name, profile_data)
    VALUES (${projectId}, ${version}, ${name}, ${JSON.stringify(profileData)})
  `;
}

export async function getCharacters(
  sql: NeonSQL,
  projectId: string,
  version?: number
): Promise<CharacterRow[]> {
  if (version !== undefined) {
    const rows = await sql`
      SELECT * FROM characters WHERE project_id = ${projectId} AND version = ${version} ORDER BY name
    `;
    return rows as unknown as CharacterRow[];
  }
  // Get latest version
  const vRows = await sql`
    SELECT max(version) as max_v FROM characters WHERE project_id = ${projectId}
  `;
  const maxV = (vRows[0] as unknown as { max_v: number | null }).max_v;
  if (maxV === null) return [];
  const rows = await sql`
    SELECT * FROM characters WHERE project_id = ${projectId} AND version = ${maxV} ORDER BY name
  `;
  return rows as unknown as CharacterRow[];
}

// --- DAG Nodes ---

export interface Predicate {
  key: string;
  cmp: "eq" | "ne" | "gt" | "gte" | "lt" | "lte";
  value: unknown;
}

export interface StateEffect {
  key: string;
  op: "set" | "add";
  value: unknown;
}

export interface DagNodeRow {
  id: string;
  project_id: string;
  version: number;
  node_key: string;
  title: string;
  summary: string | null;
  scene_type: string;
  is_ending: boolean;
  is_hidden_ending: boolean;
  episode_number: number | null;
  episode_title: string | null;
  position_x: number;
  position_y: number;
  requires: Predicate[] | null;
  invariants: Predicate[] | null;
  computed_states: Record<string, unknown[]> | null;
}

export async function insertDagNode(
  sql: NeonSQL,
  projectId: string,
  version: number,
  node: {
    node_key: string;
    title: string;
    summary?: string;
    scene_type?: string;
    is_ending?: boolean;
    is_hidden_ending?: boolean;
    episode_number?: number;
    episode_title?: string;
    position_x?: number;
    position_y?: number;
    requires?: Predicate[] | null;
    invariants?: Predicate[] | null;
    computed_states?: Record<string, unknown[]> | null;
  }
): Promise<void> {
  await sql`
    INSERT INTO dag_nodes (project_id, version, node_key, title, summary, scene_type, is_ending, is_hidden_ending, episode_number, episode_title, position_x, position_y, requires, invariants, computed_states)
    VALUES (
      ${projectId}, ${version}, ${node.node_key}, ${node.title},
      ${node.summary ?? null}, ${node.scene_type ?? "normal"},
      ${node.is_ending ?? false}, ${node.is_hidden_ending ?? false},
      ${node.episode_number ?? null}, ${node.episode_title ?? null},
      ${node.position_x ?? 0}, ${node.position_y ?? 0},
      ${node.requires ? JSON.stringify(node.requires) : null},
      ${node.invariants ? JSON.stringify(node.invariants) : null},
      ${node.computed_states ? JSON.stringify(node.computed_states) : null}
    )
  `;
}

export async function getDagNodes(
  sql: NeonSQL,
  projectId: string,
  version?: number
): Promise<DagNodeRow[]> {
  if (version !== undefined) {
    const rows = await sql`
      SELECT * FROM dag_nodes WHERE project_id = ${projectId} AND version = ${version} ORDER BY node_key
    `;
    return rows as unknown as DagNodeRow[];
  }
  const vRows = await sql`
    SELECT max(version) as max_v FROM dag_nodes WHERE project_id = ${projectId}
  `;
  const maxV = (vRows[0] as unknown as { max_v: number | null }).max_v;
  if (maxV === null) return [];
  const rows = await sql`
    SELECT * FROM dag_nodes WHERE project_id = ${projectId} AND version = ${maxV} ORDER BY node_key
  `;
  return rows as unknown as DagNodeRow[];
}

// --- DAG Edges ---

export interface DagEdgeRow {
  id: string;
  project_id: string;
  version: number;
  source_node_key: string;
  target_node_key: string;
  choice_label: string | null;
  choice_index: number;
  effects: StateEffect[] | null;
  resolution: string[] | null;
}

export async function insertDagEdge(
  sql: NeonSQL,
  projectId: string,
  version: number,
  edge: {
    source_node_key: string;
    target_node_key: string;
    choice_label?: string;
    choice_index?: number;
    effects?: StateEffect[] | null;
    resolution?: string[] | null;
  }
): Promise<void> {
  await sql`
    INSERT INTO dag_edges (project_id, version, source_node_key, target_node_key, choice_label, choice_index, effects, resolution)
    VALUES (${projectId}, ${version}, ${edge.source_node_key}, ${edge.target_node_key}, ${edge.choice_label ?? null}, ${edge.choice_index ?? 0}, ${edge.effects ? JSON.stringify(edge.effects) : null}, ${edge.resolution ? JSON.stringify(edge.resolution) : null})
  `;
}

export async function getDagEdges(
  sql: NeonSQL,
  projectId: string,
  version?: number
): Promise<DagEdgeRow[]> {
  if (version !== undefined) {
    const rows = await sql`
      SELECT * FROM dag_edges WHERE project_id = ${projectId} AND version = ${version}
    `;
    return rows as unknown as DagEdgeRow[];
  }
  const vRows = await sql`
    SELECT max(version) as max_v FROM dag_edges WHERE project_id = ${projectId}
  `;
  const maxV = (vRows[0] as unknown as { max_v: number | null }).max_v;
  if (maxV === null) return [];
  const rows = await sql`
    SELECT * FROM dag_edges WHERE project_id = ${projectId} AND version = ${maxV}
  `;
  return rows as unknown as DagEdgeRow[];
}

// --- Scene Scripts ---

export interface SceneScriptRow {
  id: string;
  project_id: string;
  node_key: string;
  version: number;
  content: string;
  steering_notes: string | null;
  status: string;
  created_at: string;
}

export async function insertSceneScript(
  sql: NeonSQL,
  projectId: string,
  nodeKey: string,
  version: number,
  content: string,
  steeringNotes?: string
): Promise<void> {
  await sql`
    INSERT INTO scene_scripts (project_id, node_key, version, content, steering_notes)
    VALUES (${projectId}, ${nodeKey}, ${version}, ${content}, ${steeringNotes ?? null})
  `;
}

export async function getSceneScript(
  sql: NeonSQL,
  projectId: string,
  nodeKey: string
): Promise<SceneScriptRow | null> {
  const rows = await sql`
    SELECT * FROM scene_scripts
    WHERE project_id = ${projectId} AND node_key = ${nodeKey}
    ORDER BY version DESC LIMIT 1
  `;
  return (rows[0] as unknown as SceneScriptRow) ?? null;
}

export async function getSceneScriptVersions(
  sql: NeonSQL,
  projectId: string,
  nodeKey: string
): Promise<SceneScriptRow[]> {
  const rows = await sql`
    SELECT * FROM scene_scripts
    WHERE project_id = ${projectId} AND node_key = ${nodeKey}
    ORDER BY version DESC
  `;
  return rows as unknown as SceneScriptRow[];
}

export async function getAllSceneScripts(
  sql: NeonSQL,
  projectId: string
): Promise<SceneScriptRow[]> {
  // Latest version per node_key
  const rows = await sql`
    SELECT DISTINCT ON (node_key) *
    FROM scene_scripts
    WHERE project_id = ${projectId} AND status = 'ready'
    ORDER BY node_key, version DESC
  `;
  return rows as unknown as SceneScriptRow[];
}

export async function getSceneScriptByVersion(
  sql: NeonSQL,
  projectId: string,
  nodeKey: string,
  version: number
): Promise<SceneScriptRow | null> {
  const rows = await sql`
    SELECT * FROM scene_scripts
    WHERE project_id = ${projectId} AND node_key = ${nodeKey} AND version = ${version}
    LIMIT 1
  `;
  return (rows[0] as unknown as SceneScriptRow) ?? null;
}

// --- Generation Jobs ---

export interface GenerationJobRow {
  id: string;
  project_id: string;
  job_kind: string;
  target_key: string | null;
  status: string;
  progress: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export async function createGenerationJob(
  sql: NeonSQL,
  projectId: string,
  jobKind: string,
  targetKey?: string
): Promise<GenerationJobRow> {
  const rows = await sql`
    INSERT INTO generation_jobs (project_id, job_kind, target_key)
    VALUES (${projectId}, ${jobKind}, ${targetKey ?? null})
    ON CONFLICT (project_id, job_kind, target_key)
    DO UPDATE SET status = 'queued', progress = 0, error_message = NULL, updated_at = now()
    RETURNING *
  `;
  return rows[0] as unknown as GenerationJobRow;
}

export async function getGenerationJob(
  sql: NeonSQL,
  jobId: string
): Promise<GenerationJobRow | null> {
  const rows = await sql`SELECT * FROM generation_jobs WHERE id = ${jobId}`;
  return (rows[0] as unknown as GenerationJobRow) ?? null;
}

export async function updateGenerationJob(
  sql: NeonSQL,
  jobId: string,
  status: string,
  progress?: number,
  errorMessage?: string
): Promise<void> {
  await sql`
    UPDATE generation_jobs
    SET status = ${status},
        progress = COALESCE(${progress ?? null}, progress),
        error_message = ${errorMessage ?? null},
        updated_at = now()
    WHERE id = ${jobId}
  `;
}

export async function getJobsByKind(
  sql: NeonSQL,
  projectId: string,
  jobKind: string
): Promise<GenerationJobRow[]> {
  const rows = await sql`
    SELECT * FROM generation_jobs
    WHERE project_id = ${projectId} AND job_kind = ${jobKind}
    ORDER BY created_at
  `;
  return rows as unknown as GenerationJobRow[];
}

export async function countJobsByStatus(
  sql: NeonSQL,
  projectId: string,
  jobKind: string
): Promise<{ queued: number; running: number; done: number; failed: number }> {
  const rows = await sql`
    SELECT status, count(*)::int as count
    FROM generation_jobs
    WHERE project_id = ${projectId} AND job_kind = ${jobKind}
    GROUP BY status
  `;
  const counts = { queued: 0, running: 0, done: 0, failed: 0 };
  for (const row of rows) {
    const r = row as unknown as { status: string; count: number };
    counts[r.status as keyof typeof counts] = r.count;
  }
  return counts;
}

// --- Export Artifacts ---

export async function insertExportArtifact(
  sql: NeonSQL,
  projectId: string,
  artifactType: string,
  fileData: Uint8Array,
  fileName: string
): Promise<string> {
  const rows = await sql`
    INSERT INTO export_artifacts (project_id, artifact_type, file_data, file_name)
    VALUES (${projectId}, ${artifactType}, ${fileData as unknown as string}, ${fileName})
    RETURNING id
  `;
  return (rows[0] as unknown as { id: string }).id;
}

export async function getExportArtifact(
  sql: NeonSQL,
  artifactId: string
): Promise<{ id: string; artifact_type: string; file_data: Uint8Array; file_name: string } | null> {
  const rows = await sql`
    SELECT id, artifact_type, file_data, file_name FROM export_artifacts WHERE id = ${artifactId} LIMIT 1
  `;
  return (rows[0] as unknown as { id: string; artifact_type: string; file_data: Uint8Array; file_name: string }) ?? null;
}

export async function getExportArtifacts(
  sql: NeonSQL,
  projectId: string
): Promise<{ id: string; artifact_type: string; file_name: string; created_at: string }[]> {
  const rows = await sql`
    SELECT id, artifact_type, file_name, created_at
    FROM export_artifacts WHERE project_id = ${projectId}
    ORDER BY created_at DESC
  `;
  return rows as unknown as { id: string; artifact_type: string; file_name: string; created_at: string }[];
}

// --- Comments ---

export interface CommentRow {
  id: string;
  project_id: string;
  node_key: string | null;
  content: string;
  author: string | null;
  created_at: string;
  deleted_at: string | null;
}

export async function getComments(
  sql: NeonSQL,
  projectId: string,
  nodeKey?: string
): Promise<CommentRow[]> {
  if (nodeKey) {
    const rows = await sql`
      SELECT
        id,
        project_id,
        node_key,
        CASE WHEN deleted_at IS NULL THEN content ELSE '' END AS content,
        author,
        created_at,
        deleted_at
      FROM comments
      WHERE project_id = ${projectId} AND node_key = ${nodeKey}
      ORDER BY created_at DESC
    `;
    return rows as unknown as CommentRow[];
  }
  const rows = await sql`
    SELECT
      id,
      project_id,
      node_key,
      CASE WHEN deleted_at IS NULL THEN content ELSE '' END AS content,
      author,
      created_at,
      deleted_at
    FROM comments
    WHERE project_id = ${projectId}
    ORDER BY created_at DESC
  `;
  return rows as unknown as CommentRow[];
}

export async function createComment(
  sql: NeonSQL,
  projectId: string,
  content: string,
  nodeKey?: string,
  author?: string
): Promise<CommentRow> {
  const rows = await sql`
    INSERT INTO comments (project_id, node_key, content, author)
    VALUES (${projectId}, ${nodeKey ?? null}, ${content}, ${author ?? null})
    RETURNING *
  `;
  return rows[0] as unknown as CommentRow;
}

export async function softDeleteComment(
  sql: NeonSQL,
  projectId: string,
  commentId: string
): Promise<CommentRow | null> {
  const rows = await sql`
    UPDATE comments
    SET deleted_at = COALESCE(deleted_at, now())
    WHERE project_id = ${projectId} AND id = ${commentId}
    RETURNING
      id,
      project_id,
      node_key,
      '' AS content,
      author,
      created_at,
      deleted_at
  `;
  return (rows[0] as unknown as CommentRow) ?? null;
}
