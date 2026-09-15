> **🇦🇷 Nota de localización (Eleia).** Esta spec está escrita sobre **GDPR + EU AI Act**. Para la
> versión argentina, el marco aplicable es la **Ley 25.326 de Protección de Datos Personales** y su
> autoridad de control, la **AAIP**. La spec se mantiene como base compartida —el cliente Elea es
> farmacéutica con operación internacional y el marco europeo le sigue aplicando—, pero **el mapeo a
> la ley argentina está pendiente**: ver "Localización argentina" en [`../README.md`](../README.md).

# Feature Specification: Compliance Policies — GDPR & EU AI Act
**Feature Branch**: `feature/005-compliance-policies`
**Version**: 1.0.0
**Status**: Implementado ✅ (mergeado a master, 2026-06-29)
**Date**: 2026-06-29

---

## 1. Overview

This feature implements a full compliance policy management system for the Sentinel Secure AI Gateway, targeting healthcare deployments in Spain and the EU. It covers:

- **GDPR Art. 9**: Legal basis management for special category health data
- **GDPR Art. 28**: DPA (Data Processing Agreement) registry per LLM provider
- **GDPR Art. 5**: EU region enforcement and log retention policies
- **GDPR Art. 15-17**: Data subject rights tool (access, rectification, erasure)
- **EU AI Act Art. 50**: Mandatory AI disclosure notification (already in force August 2026)
- **EU AI Act Art. 8-19**: Risk classification and human oversight logging (deadline Dec 2027)
- **EU AI Act Art. 19**: Mandatory audit logs for high-risk systems

---

## 2. Motivation

Healthcare AI deployments in Spain processing patient data (PHI/PII) are subject to:

1. **GDPR Art. 9** — datos de salud = categoría especial. Requires explicit legal basis + Art. 9(2) exception documented before processing.
2. **DPIA obligatoria** (AEPD guidance 2024/2026): Any AI system processing personal data requires a Data Protection Impact Assessment before production deployment.
3. **EU AI Act Art. 50** (in force August 2, 2026): Users must be informed they are interacting with an AI system.
4. **DPA required** with every LLM provider before sending PHI — OpenAI, Azure, Google, AWS.
5. **Fines**: GDPR Art. 83(5) → up to 20M EUR or 4% global turnover for violations of Art. 9.

Without this feature, the gateway cannot legally process patient data in a Spanish hospital.

---

## 3. Functional Requirements

### FR-001: Legal Basis per Project
- Admin can create "Compliance Projects" — named contexts (e.g., "Urgencias", "Historia Clínica", "Gestión Administrativa")
- Each project must have a documented legal basis before it can be activated
- Legal basis options: Art. 9(2)(h) healthcare provision, Art. 9(2)(j) public interest research, Art. 9(2)(a) explicit consent, Art. 6(1)(c) legal obligation, Art. 6(1)(e) public task
- Projects without legal basis cannot be activated — system enforces this at API key creation time

### FR-002: DPA Registry
- Admin can register DPAs for each LLM provider in use
- Fields: provider name, DPA type (standard / custom addendum), signing date, expiration date, covers Art. 9 special categories (yes/no), processing region (EU / US / global), document reference
- System warns when DPA is expiring within 30 days
- System blocks routing to a provider that has no registered DPA when a project is marked as processing health data

### FR-003: EU Region Enforcement
- Global toggle: "Enforce EU-only processing for health data projects"
- When active: any call from a project marked as health data that routes to a non-EU endpoint is blocked with a compliance error
- Per-project override available for non-health projects
- All blocked calls logged with reason

### FR-004: Log Retention Policy
- Admin can configure retention periods by log type:
  - Prompt/completion content: default 90 days (configurable 30–365)
  - Usage metadata (tokens, cost, model, timestamps): default 365 days (configurable 90–730)
  - Security/guardrail events: default 365 days (configurable 90–730)
  - Audit config changes: default 730 days (fixed minimum, not reducible below 365)
- Automatic purge job runs daily; purge events are themselves logged and never purged
- All retention settings are documented with justification field (for DPIA evidence)

### FR-005: Data Subject Rights Tool
- Search interface: find all audit log records associated with a patient identifier or user ID
- Export function: generate JSON/CSV report of all records for that identifier (Art. 15 access request)
- Mark-for-erasure: flag all records for a subject for deletion; deletion job runs within 24h (Art. 17)
- Request log: every DSR (Data Subject Request) is logged with: request type, date received, date completed, handled by, outcome

### FR-006: AI Disclosure Notification (EU AI Act Art. 50 — already in force)
- Per-project configuration: enable/disable AI disclosure
- Disclosure message configurable (Spanish/English/other)
- When enabled: the first response in each new session includes a prepended disclosure
- Disclosure delivery is logged in audit log (field: `ai_disclosure_delivered: bool`)
- Default message (Spanish): "Este servicio utiliza inteligencia artificial para generar respuestas. Las respuestas generadas por IA deben ser revisadas por un profesional cualificado antes de ser aplicadas."

### FR-007: Risk Classification (EU AI Act)
- Per-project field: AI Act risk level (Mínimo / Limitado / Alto Riesgo — Annex III / Alto Riesgo — Annex I MDR)
- When Alto Riesgo is selected:
  - Human Review flag is automatically enabled (FR-008)
  - DPIA link becomes required field
  - Retention for audit logs is enforced at minimum 365 days (non-reducible)

### FR-008: Human Review Flag
- Per-project toggle: "Respuestas clínicas requieren confirmación humana"
- When active: API responses include `review_required: true` and `review_token: <uuid>`
- Confirmation endpoint: `POST /api/v1/compliance/review/{review_token}` with fields: `reviewer_id`, `action` (accepted/rejected/corrected), `notes`
- Review confirmations stored in DB and linked to original audit log entry
- Dashboard metric: review completion rate

### FR-009: DPIA Tracking
- Per-project DPIA record: reference number, version, date created, date last reviewed, responsible DPO, storage location (URL/path)
- Alert when DPIA has not been reviewed in 12 months
- For Alto Riesgo projects: DPIA is required — project cannot activate without it

### FR-010: DPO Compliance Dashboard
- Summary view showing:
  - Projects by compliance status (compliant / warnings / blocked)
  - DPAs by status (active / expiring soon / expired)
  - DPIAs by review status (current / review due / missing)
  - Data Subject Requests: open / completed (last 30 days)
  - PHI masking rate (% of calls where Presidio detected and masked entities)
  - EU region compliance rate (% of health data calls routed to EU endpoints)
  - AI disclosure delivery rate
  - Human review completion rate (for Alto Riesgo projects)

---

## 4. Non-Functional Requirements

### NFR-001: White-label constraint (critical — preserved from constitution)
- No references to LiteLLM, specific LLM providers, or underlying technology in API responses or UI
- Provider names in DPA registry are user-entered free text — they will be displayed as entered
- Internal `engine_*` fields never exposed in API responses

### NFR-002: No new frontend dependencies
- Dashboard uses existing Tailwind CSS classes
- No new charting or PDF generation libraries

### NFR-003: Alembic migrations — idempotent
- All new tables use `CREATE TABLE IF NOT EXISTS`
- All new columns use `ADD COLUMN IF NOT EXISTS`

### NFR-004: Performance
- Compliance checks (legal basis, DPA, region) add ≤ 5ms to the request pipeline (DB query with index)
- Log retention purge runs as background job, never blocking request path

### NFR-005: Backward compatibility
- Existing API keys and projects continue to work; compliance features default to permissive (no legal basis required for existing keys unless admin configures it)
- New projects require legal basis if admin enables "Strict Compliance Mode"

---

## 5. Data Model

### compliance_projects
```
id UUID PK
name VARCHAR NOT NULL
description TEXT
legal_basis VARCHAR NOT NULL  -- art_9_2_h | art_9_2_j | art_9_2_a | art_6_1_c | art_6_1_e
legal_basis_notes TEXT
data_category VARCHAR DEFAULT 'standard'  -- standard | health_data | financial | biometric
ai_act_risk_level VARCHAR DEFAULT 'limited'  -- minimal | limited | high_risk_annex3 | high_risk_annex1
is_active BOOLEAN DEFAULT false
eu_region_required BOOLEAN DEFAULT false
human_review_required BOOLEAN DEFAULT false
ai_disclosure_enabled BOOLEAN DEFAULT true
ai_disclosure_message TEXT
dpia_reference VARCHAR
dpia_version VARCHAR
dpia_last_reviewed DATE
created_at TIMESTAMP
updated_at TIMESTAMP
```

### dpa_registry
```
id UUID PK
provider_name VARCHAR NOT NULL  -- free text: "Azure OpenAI", "AWS Bedrock", etc.
dpa_type VARCHAR  -- standard | custom_addendum | enterprise
signed_date DATE
expiration_date DATE
covers_special_categories BOOLEAN DEFAULT false
processing_region VARCHAR  -- eu | us | global
document_reference TEXT
notes TEXT
is_active BOOLEAN DEFAULT true
created_at TIMESTAMP
```

### data_subject_requests
```
id UUID PK
request_type VARCHAR NOT NULL  -- access | rectification | erasure | portability | restriction
subject_identifier VARCHAR NOT NULL  -- patient ID or user ID (pseudonymized)
date_received DATE NOT NULL
date_completed DATE
handled_by VARCHAR
status VARCHAR DEFAULT 'open'  -- open | in_progress | completed | rejected
outcome_notes TEXT
created_at TIMESTAMP
```

### human_reviews
```
id UUID PK
audit_log_id UUID FK -> audit_logs.id
review_token UUID UNIQUE NOT NULL
reviewer_id VARCHAR
action VARCHAR  -- accepted | rejected | corrected
notes TEXT
reviewed_at TIMESTAMP
created_at TIMESTAMP
```

### retention_policies
```
id UUID PK
log_type VARCHAR UNIQUE NOT NULL  -- prompt_content | usage_metadata | security_events | config_audit
retention_days INTEGER NOT NULL
justification TEXT
last_updated TIMESTAMP
updated_by VARCHAR
```

---

## 6. API Endpoints

### Compliance Projects
- `GET /api/v1/compliance/projects` — list all projects
- `POST /api/v1/compliance/projects` — create project
- `PUT /api/v1/compliance/projects/{id}` — update project
- `DELETE /api/v1/compliance/projects/{id}` — deactivate project

### DPA Registry
- `GET /api/v1/compliance/dpas` — list all DPAs
- `POST /api/v1/compliance/dpas` — register DPA
- `PUT /api/v1/compliance/dpas/{id}` — update DPA
- `DELETE /api/v1/compliance/dpas/{id}` — deactivate DPA

### Data Subject Rights
- `GET /api/v1/compliance/dsr` — list all requests
- `POST /api/v1/compliance/dsr` — create DSR
- `PUT /api/v1/compliance/dsr/{id}` — update DSR status
- `GET /api/v1/compliance/dsr/search?subject_id=X` — search audit logs by subject identifier

### Human Review
- `POST /api/v1/compliance/review/{review_token}` — submit review confirmation
- `GET /api/v1/compliance/review/pending` — list pending reviews

### Retention Policies
- `GET /api/v1/compliance/retention` — get current retention config
- `PUT /api/v1/compliance/retention` — update retention settings

### DPO Dashboard
- `GET /api/v1/compliance/dashboard` — aggregated compliance status

---

## 7. UI Pages

### Existing: PoliciesPage.tsx → replaced by CompliancePage.tsx
The existing basic policies page is replaced by a full compliance management page with tabs:

1. **Proyectos** — CRUD for compliance projects with legal basis, risk level, DPIA tracking
2. **DPAs** — Registry of signed DPAs with expiry alerts
3. **Derechos del Interesado** — DSR management and search
4. **Retención de Datos** — Retention policy configuration per log type
5. **Panel del DPO** — Summary compliance dashboard

---

## 8. Compliance with White-Label Constraints

All provider-specific terminology is entered by the admin as free text (DPA registry). The system never auto-populates provider names or references underlying technology brands in the UI or API responses.

---

## 9. Legal Gaps Acknowledged

Per the compliance research report (2026-06-29):

1. **Log retention period**: AEPD has not published a specific number of days for AI gateway logs. Default of 365 days for metadata and 90 days for content is a defensible position; each hospital's DPO should validate.
2. **Presidio PHI coverage**: Clinical PHI specific to Spain (CIE-10, historia clínica numbers) needs validation testing before certifying as GDPR-compliant.
3. **AI Act classification**: Final classification of gateway as High Risk depends on hospital's intended use. This system supports the documentation required for self-assessment.
4. **Digital Omnibus**: December 2027 deadline for Annex III High Risk not yet formally published in EU Official Journal (as of June 2026).
