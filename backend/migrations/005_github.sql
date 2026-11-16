CREATE TABLE IF NOT EXISTS github_connections (
  user_id       uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  github_login  text NOT NULL,
  access_token  text NOT NULL,
  project_name  text,
  connected_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE github_connections ADD COLUMN IF NOT EXISTS project_name text;

CREATE TABLE IF NOT EXISTS github_repos (
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  full_name  text NOT NULL,
  PRIMARY KEY (user_id, full_name),
  CONSTRAINT github_repos_full_name_len CHECK (char_length(full_name) BETWEEN 3 AND 200)
);
