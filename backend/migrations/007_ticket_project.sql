ALTER TABLE tickets ADD COLUMN IF NOT EXISTS project_id uuid REFERENCES projects(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS tickets_project_idx ON tickets (project_id, status);
