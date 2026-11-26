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
