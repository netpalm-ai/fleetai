ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verify_token_hash bytea;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verify_expires_at timestamptz;
