CREATE TABLE IF NOT EXISTS projects (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name       text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, name),
  CONSTRAINT projects_name_len CHECK (char_length(name) BETWEEN 1 AND 64)
);

CREATE UNIQUE INDEX IF NOT EXISTS projects_id_user_idx ON projects (id, user_id);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'project_contexts' AND column_name = 'context'
  ) THEN
    DROP TABLE project_contexts;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS project_contexts (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id       uuid,
  user_id          uuid,
  org              text NOT NULL,
  product_name     text NOT NULL,
  codebase_context text NOT NULL,
  tech_stack       text NOT NULL DEFAULT '',
  updated_at       timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT project_contexts_org_len CHECK (char_length(org) BETWEEN 1 AND 80),
  CONSTRAINT project_contexts_product_name_len CHECK (char_length(product_name) BETWEEN 1 AND 80),
  CONSTRAINT project_contexts_codebase_len CHECK (char_length(codebase_context) BETWEEN 1 AND 200000),
  CONSTRAINT project_contexts_tech_stack_len CHECK (char_length(tech_stack) <= 4000),
  CONSTRAINT project_contexts_project_fk FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  CONSTRAINT project_contexts_user_fk FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT project_contexts_project_user_fk
    FOREIGN KEY (project_id, user_id) REFERENCES projects (id, user_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS project_contexts_project_idx
  ON project_contexts (project_id) WHERE project_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS project_contexts_catalog_idx
  ON project_contexts (org, product_name) WHERE project_id IS NULL;

ALTER TABLE github_connections ADD COLUMN IF NOT EXISTS project_id uuid REFERENCES projects(id);

INSERT INTO projects (user_id, name)
SELECT user_id, project_name
FROM github_connections
WHERE project_name IS NOT NULL AND btrim(project_name) <> ''
ON CONFLICT (user_id, name) DO NOTHING;

UPDATE github_connections AS g
SET project_id = p.id
FROM projects AS p
WHERE g.project_id IS NULL
  AND g.project_name IS NOT NULL
  AND p.user_id = g.user_id
  AND p.name = g.project_name;
