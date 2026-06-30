# Implementation Plan: Feature 005 — Compliance Policies GDPR & EU AI Act

## Phase 1 — Backend: Data Models + Alembic Migration

### Step 1.1 — New SQLAlchemy models
Create `backend/src/models/compliance.py` with 5 models:
- `ComplianceProject`
- `DPARegistry`
- `DataSubjectRequest`
- `HumanReview`
- `RetentionPolicy`

Also add `review_token` (UUID) and `ai_disclosure_delivered` (bool) columns to `AuditLog`.

### Step 1.2 — Alembic migration 004
`backend/alembic/versions/004_compliance_tables.py`
- CREATE TABLE IF NOT EXISTS for all 5 new tables
- ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS review_token UUID
- ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS ai_disclosure_delivered BOOLEAN DEFAULT false
- Seed default RetentionPolicy rows (4 rows, one per log type)

---

## Phase 2 — Backend: Compliance API

### Step 2.1 — Compliance router
Create `backend/src/api/compliance.py` with all endpoints:
- Projects CRUD
- DPA Registry CRUD
- DSR management + search
- Human review submission
- Retention policy GET/PUT
- DPO dashboard summary

### Step 2.2 — Register router
Update `backend/src/api/__init__.py` to include compliance_router at `/api/v1/compliance`.

### Step 2.3 — Compliance middleware in chat.py
Add compliance checks to the chat request pipeline:
1. **AI disclosure**: if project has `ai_disclosure_enabled=true` and it's the first message of a session → prepend disclosure to response and set `ai_disclosure_delivered=true` in audit log
2. **Human review token**: if project has `human_review_required=true` → generate review_token UUID, store in audit log, include in response
3. **EU region check**: if project has `eu_region_required=true` and the model endpoint is non-EU → block with compliance error (503 with white-label message)

Note: compliance checks use a simple in-memory cache (dict) for project config lookups to keep latency impact ≤ 5ms.

---

## Phase 3 — Frontend: CompliancePage

### Step 3.1 — API service additions
Add to `frontend/src/services/api.ts`:
- `getComplianceProjects`, `createComplianceProject`, `updateComplianceProject`, `deleteComplianceProject`
- `getDPAs`, `createDPA`, `updateDPA`, `deleteDPA`
- `getDSRs`, `createDSR`, `updateDSR`, `searchDSR`
- `getRetentionPolicies`, `updateRetentionPolicies`
- `getComplianceDashboard`

### Step 3.2 — CompliancePage.tsx
Replace `PoliciesPage.tsx` with `CompliancePage.tsx` (keep old file as reference, replace routing in App.tsx).

Structure: tabbed interface with 5 tabs:
1. **Proyectos** — list + modal create/edit
2. **DPAs** — registry table + modal + expiry badge
3. **Derechos del Interesado** — DSR list + create + search by subject ID
4. **Retención** — 4-row config table with day inputs
5. **Panel DPO** — summary cards grid

### Step 3.3 — App.tsx update
- Update nav: "Políticas de Cumplimiento" → routes to CompliancePage
- Remove PoliciesPage import (replaced)

---

## Phase 4 — Commit & Push

Single commit per phase:
- `feat(005): compliance data models + Alembic migration 004`
- `feat(005): compliance API — projects, DPA, DSR, retention, DPO dashboard`
- `feat(005): compliance UI — CompliancePage with 5 tabs + App.tsx update`
- `docs(spec): feature 005 spec, plan, tasks, changelog`

---

## Architecture Decisions

**No new tables in LiteLLM's DB**: All compliance data lives in our own PostgreSQL tables. LiteLLM's internal tables are not modified.

**Session detection for AI disclosure**: Use a simple approach — the chat API checks if this is the first request from a given `api_key_id` in the current calendar day. If yes, disclosure is delivered. This avoids needing a session store.

**EU region check**: The model name in the request is matched against a configurable list of "EU-confirmed" model prefixes (e.g., `azure-`, `bedrock-`, `vertex-`). This list is seeded with sensible defaults but admin can configure it.

**Human review token**: UUID generated per call when `human_review_required=true`. Stored in audit_logs. No expiry — reviewed asynchronously by clinical staff.

**Retention purge**: Implemented as an async background task triggered by the FastAPI startup event (runs once on startup then every 24h). Uses raw SQL DELETE with timestamp comparison. Purge events written to a `purge_log` JSONB column on `retention_policies`.
