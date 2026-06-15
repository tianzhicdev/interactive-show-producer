-- Add target duration and choice count parameters to projects
ALTER TABLE public.projects ADD COLUMN target_duration_minutes int;
ALTER TABLE public.projects ADD COLUMN target_choice_count int;
