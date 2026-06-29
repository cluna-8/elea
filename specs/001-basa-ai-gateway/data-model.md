# Data Model: Basa Secure AI Gateway (by basa dev)

This document describes the database schema for the custom administration backend of the Basa Secure AI Gateway. The schema will be implemented in **PostgreSQL**.

```mermaid
erDiagram
    USER ||--oQ API_KEY : "has"
    GROUP ||--oQ USER : "contains"
    GROUP ||--oQ API_KEY : "has"
    USER ||--oI AUDIT_LOG : "generates"
    API_KEY ||--oI AUDIT_LOG : "used_in"
    USER ||--oQ BUDGET : "has_limit"
    GROUP ||--oQ BUDGET : "has_limit"
```

## 1. Tables

### `users`
Represents the users of the gateway (primarily administrators, compliance officers, and clinicians).
- `id` (UUID, Primary Key): Unique identifier.
- `username` (VARCHAR, Unique, Indexed): User login name.
- `email` (VARCHAR, Unique): Email address.
- `password_hash` (VARCHAR): Hashed password.
- `role` (VARCHAR): Role (`admin`, `compliance_officer`, `clinician`, `developer`).
- `group_id` (UUID, Nullable, Foreign Key -> `groups.id`): Group the user belongs to.
- `is_active` (BOOLEAN): Active status.
- `created_at` (TIMESTAMP): Creation timestamp.
- `updated_at` (TIMESTAMP): Last update timestamp.

### `groups`
Represents departments or teams within the healthcare organization.
- `id` (UUID, Primary Key): Unique identifier.
- `name` (VARCHAR, Unique): Group name (e.g., "Cardiology", "Pediatrics", "Research").
- `description` (TEXT): Description of the group.
- `created_at` (TIMESTAMP): Creation timestamp.

### `budgets`
Defines spending and token limits. Can be linked directly to a user or a group.
- `id` (UUID, Primary Key): Unique identifier.
- `user_id` (UUID, Nullable, Foreign Key -> `users.id`): Linked user (mutually exclusive with `group_id`).
- `group_id` (UUID, Nullable, Foreign Key -> `groups.id`): Linked group.
- `max_spend_usd` (DECIMAL(10, 4)): Maximum monetary spend.
- `current_spend_usd` (DECIMAL(10, 4)): Current accumulated spend.
- `max_tokens` (BIGINT): Maximum token limit.
- `current_tokens` (BIGINT): Current accumulated tokens.
- `reset_period` (VARCHAR): Reset interval (`daily`, `weekly`, `monthly`, `never`).
- `last_reset_at` (TIMESTAMP): Timestamp of the last budget reset.
- `created_at` (TIMESTAMP): Creation timestamp.
- `updated_at` (TIMESTAMP): Last update timestamp.

### `api_keys`
Represents the keys used by external systems or agents to access the gateway.
- `id` (UUID, Primary Key): Unique identifier.
- `key_hash` (VARCHAR, Unique, Indexed): Hashed version of the API key.
- `key_preview` (VARCHAR): First few characters of the key (e.g., `basa_sk_...`).
- `user_id` (UUID, Nullable, Foreign Key -> `users.id`): Owner of the key.
- `group_id` (UUID, Nullable, Foreign Key -> `groups.id`): Group associated with the key.
- `name` (VARCHAR): Friendly name for the key (e.g., "Cardiology Agent Key").
- `is_active` (BOOLEAN): Active status.
- `expires_at` (TIMESTAMP, Nullable): Expiration date.
- `created_at` (TIMESTAMP): Creation timestamp.

### `audit_logs`
Stores transaction metadata for compliance and billing. **No raw PII/PHI is stored here.**
- `id` (UUID, Primary Key): Unique identifier.
- `timestamp` (TIMESTAMP, Indexed): Transaction timestamp.
- `user_id` (UUID, Nullable, Foreign Key -> `users.id`): User who made the request.
- `api_key_id` (UUID, Nullable, Foreign Key -> `api_keys.id`): API key used.
- `model` (VARCHAR): Target LLM model used (e.g., `claude-3-5-sonnet`, `gpt-4o`).
- `prompt_tokens` (INTEGER): Number of input tokens.
- `completion_tokens` (INTEGER): Number of output tokens.
- `cost_usd` (DECIMAL(10, 6)): Cost of the transaction.
- `pii_detected` (BOOLEAN): True if PII/PHI was detected and processed.
- `masked_entities` (JSONB): List of entity types masked (e.g., `["PERSON", "PHONE_NUMBER", "DNI"]`), along with count and confidence. **Does not store the actual values.**
- `compliance_status` (VARCHAR): Compliance check result (`passed`, `flagged_high_risk`, `blocked_by_policy`).
- `latency_ms` (INTEGER): Processing time in milliseconds.
- `tokens_saved_by_optimization` (INTEGER): Tokens saved by context compression (Headroom).

### `security_policies`
Stores configuration for the PII/PHI masking and compliance checks.
- `id` (UUID, Primary Key): Unique identifier.
- `name` (VARCHAR): Policy name.
- `is_active` (BOOLEAN): Active status.
- `entity_configs` (JSONB): Configuration of entities and actions (e.g., `{"PERSON": "MASK", "MEDICAL_LICENSE": "BLOCK"}`).
- `gdpr_mode` (BOOLEAN): Enable GDPR routing rules (EU-only endpoints).
- `ai_act_mode` (BOOLEAN): Enable AI Act risk classification and prompt flagging.
- `headroom_mode` (BOOLEAN): Enable context optimization using Headroom.
- `created_at` (TIMESTAMP): Creation timestamp.
- `updated_at` (TIMESTAMP): Last update timestamp.
