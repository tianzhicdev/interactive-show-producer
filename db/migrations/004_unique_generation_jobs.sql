-- Make queue job creation idempotent for retryable phase starts.
CREATE UNIQUE INDEX IF NOT EXISTS idx_generation_jobs_project_kind_target
  ON public.generation_jobs(project_id, job_kind, target_key);
