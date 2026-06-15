-- Preserve comment rows while allowing them to be hidden from the UI.
ALTER TABLE public.comments
  ADD COLUMN IF NOT EXISTS deleted_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_comments_deleted_at ON public.comments(project_id, deleted_at);
