ALTER TABLE intakes DROP CONSTRAINT IF EXISTS intakes_format_check;
ALTER TABLE intakes ADD CONSTRAINT intakes_format_check
  CHECK (format IN ('txt', 'pdf', 'md', 'png', 'jpeg', 'webp'));

DROP INDEX IF EXISTS intakes_user_type_active_idx;
CREATE UNIQUE INDEX intakes_user_type_active_idx
  ON intakes (user_id, type)
  WHERE status = 'active' AND format IN ('txt', 'pdf', 'md');
