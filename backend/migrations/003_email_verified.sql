ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified boolean NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_ts timestamptz;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'email_verified_at'
  ) THEN
    UPDATE users
    SET email_verified = true, email_verified_ts = email_verified_at
    WHERE email_verified_at IS NOT NULL AND email_verified = false;
    ALTER TABLE users DROP COLUMN email_verified_at;
  END IF;
END $$;
