# Netpalm product subscription ERD

Yes. The diagram below is the entity-relationship diagram for Netpalm.ai products, per-product tiers, and feature entitlements.

`users` is identity only. Product, tier, and entitlements are catalog tables. A user’s access is a row in `user_subscriptions`. Do not store `registered_product` or `subscription_status` on `users`.

```mermaid
erDiagram
  users ||--o{ user_subscriptions : subscribes
  products ||--o{ product_tiers : has
  products ||--o{ product_features : has
  products ||--o{ user_subscriptions : "sold as"
  product_tiers ||--o{ user_subscriptions : "grants"
  product_tiers ||--o{ tier_entitlements : allows
  product_features ||--o{ tier_entitlements : "entitled by"

  users {
    uuid id PK
    citext username
    citext email
    text status
    timestamptz last_signed_in_ts
  }

  products {
    text id PK
    text name
  }

  product_tiers {
    uuid id PK
    text product_id FK
    text status
  }

  product_features {
    uuid id PK
    text product_id FK
    text key
  }

  tier_entitlements {
    uuid tier_id PK_FK
    uuid feature_id PK_FK
  }

  user_subscriptions {
    uuid user_id PK_FK
    text product_id PK_FK
    uuid tier_id FK
  }
```

## Tables

- `products` — Netpalm products. `fleetai` is one row.
- `product_tiers` — unique `(product_id, status)`. Each product has its own tier names.
- `product_features` — unique `(product_id, key)`. Features belong to a product.
- `tier_entitlements` — which features that product-tier turns on.
- `user_subscriptions` — unique `(user_id, product_id)`. One subscription per user per product, pointing at that product’s tier.

Runtime entitlements: join `user_subscriptions` → `product_tiers` → `tier_entitlements`. Do not copy a feature list onto the user.

## Example shape (FleetAI)

| product | tier | entitled features |
|---|---|---|
| `fleetai` | `free` | (named later) |
| `fleetai` | `trial` | (named later) |
| `fleetai` | `paid` | (named later) |

Signup for FleetAI inserts `user_subscriptions (user, fleetai, free)`. A plan change updates `tier_id` on that row. Another Netpalm product is another `products` row and another `user_subscriptions` row, not another column on `users`.

FleetAI is seeded in `backend/migrations/001_auth.sql`: product `fleetai`, tiers `free` / `trial` / `paid`, no feature keys yet.
