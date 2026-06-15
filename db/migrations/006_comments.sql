-- Comments on project nodes (scenes/episodes)
CREATE TABLE IF NOT EXISTS comments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  node_key text,
  content text NOT NULL,
  author text,
  created_at timestamptz DEFAULT now()
);

CREATE INDEX idx_comments_project ON comments(project_id);
CREATE INDEX idx_comments_node ON comments(project_id, node_key);
