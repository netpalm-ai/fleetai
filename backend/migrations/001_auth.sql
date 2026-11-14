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
