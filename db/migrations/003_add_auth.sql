-- Auth tables migration

CREATE TABLE public.users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username text NOT NULL UNIQUE,
  password_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_users_username ON public.users(username);

-- Add user_id to projects (nullable for backward compatibility with existing data)
ALTER TABLE public.projects
  ADD COLUMN user_id uuid REFERENCES public.users(id) ON DELETE SET NULL;

CREATE INDEX idx_projects_user_id ON public.projects(user_id);
