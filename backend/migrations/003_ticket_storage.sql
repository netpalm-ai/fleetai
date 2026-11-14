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
