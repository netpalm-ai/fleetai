CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE IF NOT EXISTS users (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username                 citext NOT NULL UNIQUE,
  email                    citext NOT NULL UNIQUE,
  first_name               text NOT NULL DEFAULT '',
  last_name                text NOT NULL DEFAULT '',
  password_hash            text NOT NULL,
  status                   text NOT NULL DEFAULT 'active' CHECK (status IN ('active','disabled')),
  email_verified           boolean NOT NULL DEFAULT false,
  email_verified_ts        timestamptz,
  email_verify_token_hash  bytea,
  email_verify_expires_at  timestamptz,
  last_signed_in_ts        timestamptz,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT users_username_len CHECK (char_length(username::text) BETWEEN 1 AND 80),
  CONSTRAINT users_email_len CHECK (char_length(email::text) BETWEEN 3 AND 254),
  CONSTRAINT users_first_name_len CHECK (char_length(first_name) <= 80),
  CONSTRAINT users_last_name_len CHECK (char_length(last_name) <= 80)
);

CREATE TABLE IF NOT EXISTS sessions (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash   bytea NOT NULL UNIQUE,
  created_at   timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  expires_at   timestamptz NOT NULL,
  revoked_at   timestamptz,
  ip           inet,
  user_agent   text,
  CONSTRAINT sessions_user_agent_len CHECK (user_agent IS NULL OR char_length(user_agent) <= 512)
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions (expires_at);

CREATE TABLE IF NOT EXISTS products (
  id   text PRIMARY KEY,
  name text NOT NULL,
  CONSTRAINT products_id_len CHECK (char_length(id) BETWEEN 1 AND 64),
  CONSTRAINT products_name_len CHECK (char_length(name) BETWEEN 1 AND 80)
);

CREATE TABLE IF NOT EXISTS product_tiers (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id text NOT NULL REFERENCES products(id),
  status     text NOT NULL,
  UNIQUE (product_id, status),
  UNIQUE (id, product_id),
  CONSTRAINT product_tiers_status_len CHECK (char_length(status) BETWEEN 1 AND 32)
);

CREATE TABLE IF NOT EXISTS product_features (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id text NOT NULL REFERENCES products(id),
  key        text NOT NULL,
  UNIQUE (product_id, key),
  UNIQUE (id, product_id),
  CONSTRAINT product_features_key_len CHECK (char_length(key) BETWEEN 1 AND 64)
);

CREATE TABLE IF NOT EXISTS tier_entitlements (
  product_id text NOT NULL,
  tier_id    uuid NOT NULL,
  feature_id uuid NOT NULL,
  PRIMARY KEY (tier_id, feature_id),
  CONSTRAINT tier_entitlements_tier_product_fk
    FOREIGN KEY (tier_id, product_id) REFERENCES product_tiers (id, product_id) ON DELETE CASCADE,
  CONSTRAINT tier_entitlements_feature_product_fk
    FOREIGN KEY (feature_id, product_id) REFERENCES product_features (id, product_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_subscriptions (
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  product_id text NOT NULL REFERENCES products(id),
  tier_id    uuid NOT NULL,
  PRIMARY KEY (user_id, product_id),
  FOREIGN KEY (tier_id, product_id) REFERENCES product_tiers (id, product_id)
);

CREATE TABLE IF NOT EXISTS subscription_events (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  product_id   text NOT NULL REFERENCES products(id),
  from_tier_id uuid REFERENCES product_tiers(id),
  to_tier_id   uuid NOT NULL REFERENCES product_tiers(id),
  at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS subscription_events_user_idx ON subscription_events (user_id, at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS product_features_id_product ON product_features (id, product_id);

ALTER TABLE tier_entitlements ADD COLUMN IF NOT EXISTS product_id text;
UPDATE tier_entitlements te
SET product_id = pt.product_id
FROM product_tiers pt
WHERE te.tier_id = pt.id AND te.product_id IS NULL;
ALTER TABLE tier_entitlements DROP CONSTRAINT IF EXISTS tier_entitlements_tier_id_fkey;
ALTER TABLE tier_entitlements DROP CONSTRAINT IF EXISTS tier_entitlements_feature_id_fkey;
DO $$
BEGIN
  BEGIN
    ALTER TABLE tier_entitlements ALTER COLUMN product_id SET NOT NULL;
  EXCEPTION WHEN others THEN
    NULL;
  END;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tier_entitlements_tier_product_fk') THEN
    ALTER TABLE tier_entitlements
      ADD CONSTRAINT tier_entitlements_tier_product_fk
      FOREIGN KEY (tier_id, product_id) REFERENCES product_tiers (id, product_id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tier_entitlements_feature_product_fk') THEN
    ALTER TABLE tier_entitlements
      ADD CONSTRAINT tier_entitlements_feature_product_fk
      FOREIGN KEY (feature_id, product_id) REFERENCES product_features (id, product_id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_username_len') THEN
    ALTER TABLE users ADD CONSTRAINT users_username_len CHECK (char_length(username::text) BETWEEN 1 AND 80);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_email_len') THEN
    ALTER TABLE users ADD CONSTRAINT users_email_len CHECK (char_length(email::text) BETWEEN 3 AND 254);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_first_name_len') THEN
    ALTER TABLE users ADD CONSTRAINT users_first_name_len CHECK (char_length(first_name) <= 80);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'users_last_name_len') THEN
    ALTER TABLE users ADD CONSTRAINT users_last_name_len CHECK (char_length(last_name) <= 80);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'sessions_user_agent_len') THEN
    ALTER TABLE sessions ADD CONSTRAINT sessions_user_agent_len CHECK (user_agent IS NULL OR char_length(user_agent) <= 512);
  END IF;
END $$;

INSERT INTO products (id, name) VALUES ('fleetai', 'FleetAI')
ON CONFLICT (id) DO NOTHING;

INSERT INTO product_tiers (product_id, status) VALUES
  ('fleetai', 'free'),
  ('fleetai', 'trial'),
  ('fleetai', 'paid')
ON CONFLICT (product_id, status) DO NOTHING;

INSERT INTO product_features (product_id, key) VALUES ('fleetai', 'tickets')
ON CONFLICT (product_id, key) DO NOTHING;

INSERT INTO tier_entitlements (product_id, tier_id, feature_id)
SELECT pt.product_id, pt.id, pf.id
FROM product_tiers pt
JOIN product_features pf
  ON pf.product_id = pt.product_id AND pf.key = 'tickets'
WHERE pt.product_id = 'fleetai'
ON CONFLICT DO NOTHING;

CREATE OR REPLACE FUNCTION sessions_revoke_on_password_hash()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.password_hash IS DISTINCT FROM OLD.password_hash THEN
    UPDATE sessions
    SET revoked_at = now()
    WHERE user_id = NEW.id AND revoked_at IS NULL;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS users_password_hash_revoke ON users;
CREATE TRIGGER users_password_hash_revoke
AFTER UPDATE OF password_hash ON users
FOR EACH ROW
EXECUTE FUNCTION sessions_revoke_on_password_hash();

CREATE OR REPLACE FUNCTION subscription_events_on_change()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO subscription_events (user_id, product_id, from_tier_id, to_tier_id)
    VALUES (NEW.user_id, NEW.product_id, NULL, NEW.tier_id);
  ELSIF TG_OP = 'UPDATE' AND NEW.tier_id IS DISTINCT FROM OLD.tier_id THEN
    INSERT INTO subscription_events (user_id, product_id, from_tier_id, to_tier_id)
    VALUES (NEW.user_id, NEW.product_id, OLD.tier_id, NEW.tier_id);
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS user_subscriptions_events ON user_subscriptions;
CREATE TRIGGER user_subscriptions_events
AFTER INSERT OR UPDATE OF tier_id ON user_subscriptions
FOR EACH ROW
EXECUTE FUNCTION subscription_events_on_change();

DROP TABLE IF EXISTS files CASCADE;

DO $$
BEGIN
  IF to_regclass('public.intakes') IS NULL THEN
    DROP TABLE IF EXISTS tickets;
    DROP TABLE IF EXISTS intake_files;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS intakes (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id      uuid REFERENCES sessions(id) ON DELETE SET NULL,
  type            text NOT NULL CHECK (type IN ('email_desc', 'ticket_list', 'project_context')),
  format          text NOT NULL CHECK (format IN ('txt', 'pdf', 'md')),
  status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deactivated')),
  sha256          bytea NOT NULL,
  byte_size       integer NOT NULL CHECK (byte_size >= 0),
  storage_path    text NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  deactivated_at  timestamptz,
  CONSTRAINT intakes_storage_path_len CHECK (char_length(storage_path) BETWEEN 1 AND 512)
);

CREATE UNIQUE INDEX IF NOT EXISTS intakes_user_type_active_idx
  ON intakes (user_id, type) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS intakes_user_idx ON intakes (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS tickets (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  public_id   text NOT NULL,
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id  uuid REFERENCES sessions(id) ON DELETE SET NULL,
  intake_id   uuid REFERENCES intakes(id) ON DELETE SET NULL,
  title       text NOT NULL,
  severity    text NOT NULL DEFAULT '',
  services    text[] NOT NULL DEFAULT '{}',
  context     text NOT NULL DEFAULT '',
  expected    text NOT NULL DEFAULT '',
  kind        text NOT NULL DEFAULT 'new' CHECK (kind IN ('new', 'recurrent')),
  status      text NOT NULL CHECK (status IN ('unresolved', 'verifying', 'completed', 'fixed')),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT tickets_public_id_len CHECK (char_length(public_id) BETWEEN 1 AND 80),
  CONSTRAINT tickets_user_public UNIQUE (user_id, public_id)
);

CREATE INDEX IF NOT EXISTS tickets_user_status_idx ON tickets (user_id, status);

DO $$
BEGIN
  IF to_regclass('public.ticket_runs') IS NULL THEN
    DELETE FROM intakes;
  END IF;
END $$;

ALTER TABLE intakes ADD COLUMN IF NOT EXISTS content bytea NOT NULL;
ALTER TABLE intakes DROP COLUMN IF EXISTS storage_path;

ALTER TABLE tickets ADD COLUMN IF NOT EXISTS handled_at timestamptz;
UPDATE tickets SET handled_at = updated_at WHERE status IN ('fixed', 'completed') AND handled_at IS NULL;
CREATE INDEX IF NOT EXISTS tickets_handled_idx ON tickets (handled_at) WHERE handled_at IS NOT NULL;

ALTER TABLE user_subscriptions
  ADD COLUMN IF NOT EXISTS ticket_retention_days integer DEFAULT 90
  CHECK (ticket_retention_days IS NULL OR ticket_retention_days > 0);

CREATE TABLE IF NOT EXISTS ticket_runs (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ticket_id   uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  run_id      text NOT NULL,
  kind        text NOT NULL CHECK (kind IN ('solve', 'verify')),
  verdict     text,
  prompt      text NOT NULL,
  result      text NOT NULL DEFAULT '',
  created_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ticket_runs_run_id_len CHECK (char_length(run_id) BETWEEN 1 AND 128)
);

CREATE INDEX IF NOT EXISTS ticket_runs_ticket_idx ON ticket_runs (ticket_id, created_at DESC);

ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_secret text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_last_step bigint;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_failed_attempts integer NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS totp_locked_until timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_token_hash bytea;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_expires_at timestamptz;

CREATE TABLE IF NOT EXISTS totp_recovery_codes (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  code_hash  bytea NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, code_hash)
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_logins integer NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS login_locked_until timestamptz;

CREATE TABLE IF NOT EXISTS auth_events (
  id      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  event   text NOT NULL,
  ip      inet,
  at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auth_events_user_idx ON auth_events (user_id, at DESC);

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

ALTER TABLE tickets ADD COLUMN IF NOT EXISTS project_id uuid REFERENCES projects(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS tickets_project_idx ON tickets (project_id, status);

CREATE UNIQUE INDEX IF NOT EXISTS sessions_id_user_idx ON sessions (id, user_id);
CREATE UNIQUE INDEX IF NOT EXISTS intakes_id_user_idx ON intakes (id, user_id);

UPDATE tickets AS t
SET project_id = NULL
WHERE t.project_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM projects AS p WHERE p.id = t.project_id AND p.user_id = t.user_id
  );

UPDATE github_connections AS g
SET project_id = NULL
WHERE g.project_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM projects AS p WHERE p.id = g.project_id AND p.user_id = g.user_id
  );

UPDATE intakes AS i
SET session_id = NULL
WHERE i.session_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM sessions AS s WHERE s.id = i.session_id AND s.user_id = i.user_id
  );

UPDATE tickets AS t
SET session_id = NULL
WHERE t.session_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM sessions AS s WHERE s.id = t.session_id AND s.user_id = t.user_id
  );

UPDATE tickets AS t
SET intake_id = NULL
WHERE t.intake_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM intakes AS i WHERE i.id = t.intake_id AND i.user_id = t.user_id
  );

UPDATE subscription_events AS e
SET product_id = pt.product_id
FROM product_tiers AS pt
WHERE e.to_tier_id = pt.id
  AND e.product_id IS DISTINCT FROM pt.product_id;

UPDATE subscription_events AS e
SET from_tier_id = NULL
WHERE e.from_tier_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM product_tiers AS pt
    WHERE pt.id = e.from_tier_id AND pt.product_id = e.product_id
  );

ALTER TABLE github_repos ADD COLUMN IF NOT EXISTS project_id uuid;

UPDATE github_repos AS r
SET project_id = c.project_id
FROM github_connections AS c
WHERE r.user_id = c.user_id
  AND r.project_id IS NULL
  AND c.project_id IS NOT NULL;

ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_project_id_fkey;
ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_project_user_fk;
ALTER TABLE tickets
  ADD CONSTRAINT tickets_project_user_fk
  FOREIGN KEY (project_id, user_id) REFERENCES projects (id, user_id) ON DELETE CASCADE;

ALTER TABLE github_connections DROP CONSTRAINT IF EXISTS github_connections_project_id_fkey;
ALTER TABLE github_connections DROP CONSTRAINT IF EXISTS github_connections_project_user_fk;
ALTER TABLE github_connections
  ADD CONSTRAINT github_connections_project_user_fk
  FOREIGN KEY (project_id, user_id) REFERENCES projects (id, user_id) ON DELETE SET NULL (project_id);

ALTER TABLE intakes DROP CONSTRAINT IF EXISTS intakes_session_id_fkey;
ALTER TABLE intakes DROP CONSTRAINT IF EXISTS intakes_session_user_fk;
ALTER TABLE intakes
  ADD CONSTRAINT intakes_session_user_fk
  FOREIGN KEY (session_id, user_id) REFERENCES sessions (id, user_id) ON DELETE SET NULL (session_id);

ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_session_id_fkey;
ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_session_user_fk;
ALTER TABLE tickets
  ADD CONSTRAINT tickets_session_user_fk
  FOREIGN KEY (session_id, user_id) REFERENCES sessions (id, user_id) ON DELETE SET NULL (session_id);

ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_intake_id_fkey;
ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_intake_user_fk;
ALTER TABLE tickets
  ADD CONSTRAINT tickets_intake_user_fk
  FOREIGN KEY (intake_id, user_id) REFERENCES intakes (id, user_id) ON DELETE SET NULL (intake_id);

ALTER TABLE subscription_events DROP CONSTRAINT IF EXISTS subscription_events_from_tier_id_fkey;
ALTER TABLE subscription_events DROP CONSTRAINT IF EXISTS subscription_events_to_tier_id_fkey;
ALTER TABLE subscription_events DROP CONSTRAINT IF EXISTS subscription_events_to_tier_product_fk;
ALTER TABLE subscription_events DROP CONSTRAINT IF EXISTS subscription_events_from_tier_product_fk;
ALTER TABLE subscription_events
  ADD CONSTRAINT subscription_events_to_tier_product_fk
  FOREIGN KEY (to_tier_id, product_id) REFERENCES product_tiers (id, product_id);
ALTER TABLE subscription_events
  ADD CONSTRAINT subscription_events_from_tier_product_fk
  FOREIGN KEY (from_tier_id, product_id) REFERENCES product_tiers (id, product_id);

ALTER TABLE github_repos DROP CONSTRAINT IF EXISTS github_repos_project_user_fk;
ALTER TABLE github_repos
  ADD CONSTRAINT github_repos_project_user_fk
  FOREIGN KEY (project_id, user_id) REFERENCES projects (id, user_id) ON DELETE CASCADE;

ALTER TABLE project_contexts DROP CONSTRAINT IF EXISTS project_contexts_owner_chk;
ALTER TABLE project_contexts
  ADD CONSTRAINT project_contexts_owner_chk
  CHECK (
    (project_id IS NULL AND user_id IS NULL)
    OR (project_id IS NOT NULL AND user_id IS NOT NULL)
  );

ALTER TABLE intakes DROP CONSTRAINT IF EXISTS intakes_format_check;
ALTER TABLE intakes ADD CONSTRAINT intakes_format_check
  CHECK (format IN ('txt', 'pdf', 'md', 'png', 'jpeg', 'webp'));

DROP INDEX IF EXISTS intakes_user_type_active_idx;
CREATE UNIQUE INDEX intakes_user_type_active_idx
  ON intakes (user_id, type)
  WHERE status = 'active' AND format IN ('txt', 'pdf', 'md');
