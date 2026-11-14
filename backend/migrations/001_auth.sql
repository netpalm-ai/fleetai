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
  updated_at               timestamptz NOT NULL DEFAULT now()
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
  user_agent   text
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions (expires_at);

CREATE TABLE IF NOT EXISTS products (
  id   text PRIMARY KEY,
  name text NOT NULL
);

CREATE TABLE IF NOT EXISTS product_tiers (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id text NOT NULL REFERENCES products(id),
  status     text NOT NULL,
  UNIQUE (product_id, status),
  UNIQUE (id, product_id)
);

CREATE TABLE IF NOT EXISTS product_features (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id text NOT NULL REFERENCES products(id),
  key        text NOT NULL,
  UNIQUE (product_id, key)
);

CREATE TABLE IF NOT EXISTS tier_entitlements (
  tier_id    uuid NOT NULL REFERENCES product_tiers(id) ON DELETE CASCADE,
  feature_id uuid NOT NULL REFERENCES product_features(id) ON DELETE CASCADE,
  PRIMARY KEY (tier_id, feature_id)
);

CREATE TABLE IF NOT EXISTS user_subscriptions (
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  product_id text NOT NULL REFERENCES products(id),
  tier_id    uuid NOT NULL,
  PRIMARY KEY (user_id, product_id),
  FOREIGN KEY (tier_id, product_id) REFERENCES product_tiers (id, product_id)
);

INSERT INTO products (id, name) VALUES ('fleetai', 'FleetAI')
ON CONFLICT (id) DO NOTHING;

INSERT INTO product_tiers (product_id, status) VALUES
  ('fleetai', 'free'),
  ('fleetai', 'trial'),
  ('fleetai', 'paid')
ON CONFLICT (product_id, status) DO NOTHING;
