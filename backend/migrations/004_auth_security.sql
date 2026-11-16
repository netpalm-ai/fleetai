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
