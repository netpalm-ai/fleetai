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
