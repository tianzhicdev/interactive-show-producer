-- Add episode grouping fields to dag_nodes
ALTER TABLE public.dag_nodes
  ADD COLUMN episode_number int,
  ADD COLUMN episode_title text;

-- Remove restrictive CHECK on export_artifacts to allow per-episode types
ALTER TABLE public.export_artifacts DROP CONSTRAINT IF EXISTS export_artifacts_artifact_type_check;

-- Add pipeline_running to projects status CHECK
ALTER TABLE public.projects DROP CONSTRAINT IF EXISTS projects_status_check;
ALTER TABLE public.projects ADD CONSTRAINT projects_status_check
  CHECK (status IN ('draft', 'uploading', 'pipeline_running', 'phase1_running', 'phase1_ready', 'phase2_running', 'phase2_ready', 'done'));
