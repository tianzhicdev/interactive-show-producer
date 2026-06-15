-- Add chapter_title to story_chunks for chapter-aware chunking
ALTER TABLE public.story_chunks ADD COLUMN IF NOT EXISTS chapter_title text;

-- Allow pipeline_running as valid project status
ALTER TABLE public.projects DROP CONSTRAINT IF EXISTS projects_status_check;
ALTER TABLE public.projects ADD CONSTRAINT projects_status_check
  CHECK (status IN ('draft', 'uploading', 'phase1_running', 'phase1_ready', 'phase2_running', 'phase2_ready', 'done', 'pipeline_running'));
