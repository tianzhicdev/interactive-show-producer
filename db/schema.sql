-- Tomato Interactive Screenplay Generator - Database Schema

CREATE TABLE public.projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  status text NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'uploading', 'pipeline_running', 'phase1_running', 'phase1_ready', 'phase2_running', 'phase2_ready', 'done')),
  model_profile_id text NOT NULL DEFAULT 'default',
  steering_notes text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.story_chunks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  chunk_index int NOT NULL,
  content text NOT NULL,
  char_count int NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, chunk_index)
);

CREATE TABLE public.story_summaries (
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  version int NOT NULL DEFAULT 1,
  content text NOT NULL,
  arc_breakdown jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, version)
);

CREATE TABLE public.world_settings (
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  version int NOT NULL DEFAULT 1,
  setting_data jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, version)
);

CREATE TABLE public.characters (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  version int NOT NULL DEFAULT 1,
  name text NOT NULL,
  profile_data jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_characters_project_version ON public.characters(project_id, version);

CREATE TABLE public.dag_nodes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  version int NOT NULL DEFAULT 1,
  node_key text NOT NULL,
  title text NOT NULL,
  summary text,
  scene_type text NOT NULL DEFAULT 'normal'
    CHECK (scene_type IN ('normal', 'choice', 'ending', 'hidden_ending')),
  is_ending boolean NOT NULL DEFAULT false,
  is_hidden_ending boolean NOT NULL DEFAULT false,
  episode_number int,
  episode_title text,
  position_x float NOT NULL DEFAULT 0,
  position_y float NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, version, node_key)
);

CREATE TABLE public.dag_edges (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  version int NOT NULL DEFAULT 1,
  source_node_key text NOT NULL,
  target_node_key text NOT NULL,
  choice_label text,
  choice_index int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_dag_edges_project_version ON public.dag_edges(project_id, version);

CREATE TABLE public.scene_scripts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  node_key text NOT NULL,
  version int NOT NULL DEFAULT 1,
  content text NOT NULL,
  steering_notes text,
  status text NOT NULL DEFAULT 'ready'
    CHECK (status IN ('ready', 'pending', 'failed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (project_id, node_key, version)
);

CREATE TABLE public.generation_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  job_kind text NOT NULL
    CHECK (job_kind IN ('summarize_chunk', 'summarize_merge', 'world_settings', 'characters', 'dag_skeleton', 'scene_script', 'export_docx')),
  target_key text,
  status text NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'running', 'done', 'failed')),
  progress float NOT NULL DEFAULT 0,
  error_message text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_generation_jobs_project_kind ON public.generation_jobs(project_id, job_kind, status);
CREATE UNIQUE INDEX idx_generation_jobs_project_kind_target ON public.generation_jobs(project_id, job_kind, target_key);

CREATE TABLE public.comments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  node_key text,
  content text NOT NULL,
  author text,
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
);

CREATE INDEX idx_comments_project ON public.comments(project_id);

CREATE TABLE public.export_artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
  artifact_type text NOT NULL,
  file_data bytea NOT NULL,
  file_name text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
