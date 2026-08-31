# Feature Specification: Sentinel Secure AI Gateway (by sentinel dev)

**Feature Branch**: `001-sentinel-ai-gateway`

**Created**: 2026-06-29

**Status**: Implementado ✅

**Changelog**: [changelog.md](changelog.md) — Registro completo de lo implementado, decisiones técnicas y bugs corregidos.

**Input**: User description: "Un producto para el espacio de datos sanitario by sentinel dev, que actúe como una pasarela segura (gateway) con usuarios, presupuestos, seguridad (enmascaramiento PII/PHI con Presidio u otros), cumplimiento (GDPR y AI Act), y selector de LLM. Debe contar con una interfaz gráfica (UI) de 5 páginas (Usuarios/Presupuestos, Opciones de Seguridad, Políticas/Plantillas, Auditoría y Playground con una animación de capas) y una API. Marca blanca sin menciones a litellm. Se agrega soporte para un optimizador de contexto opcional usando Headroom."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - User and Budget Management (Priority: P1) 🎯 MVP
As an administrator of the healthcare organization, I want to manage users, groups, and assign budget limits (in token count or monetary value) so that I can control and monitor AI spending across different departments.

**Why this priority**: It is the foundation of resource control and cost management, preventing run-away costs when deploying LLM access in large medical organizations.

**Independent Test**: The administrator can create a user, assign a specific budget limit (e.g., $10 or 100,000 tokens), and verify that requests are blocked once the user reaches that limit.

**Acceptance Scenarios**:
1. **Given** a user has a budget of $5 remaining, **When** they make a request that costs $1, **Then** the request is allowed and their remaining budget is updated to $4.
2. **Given** a user has a budget of $0.10 remaining, **When** they attempt to make a request that exceeds this amount, **Then** the request is blocked and they receive an out-of-budget notification.
3. **Given** a streaming chat session is active, **When** the budget limit is hit mid-stream, **Then** the stream is immediately terminated and the user is notified.

---

### User Story 2 - Privacy and PHI/PII Masking (Priority: P1) 🎯 MVP
As a healthcare professional (doctor, nurse, researcher), I want my chat prompts to be automatically scanned for patient PII (names, phone numbers, IDs) and PHI (medical records, diagnosis details) and have them masked before being sent to external LLM providers, with the response automatically unmasked for me.

**Why this priority**: Healthcare data is highly regulated and sensitive. Protecting patient identity is a non-negotiable legal requirement.

**Independent Test**: Send a prompt containing a patient name and DNI, verify that the external model receives a masked prompt (e.g., `<PERSON>`, `<IDENTIFIER>`), and verify that the doctor receives the response with the patient's name restored.

**Acceptance Scenarios**:
1. **Given** a prompt contains "El paciente Juan Pérez DNI 12345678X tiene fiebre", **When** it is sent to the gateway, **Then** the prompt forwarded to the external LLM is "El paciente <PERSON> DNI <IDENTIFIER> tiene fiebre".
2. **Given** the external LLM responds with "Recomiendo reposo para <PERSON>", **When** the response is returned to the doctor, **Then** it is displayed as "Recomiendo reposo para Juan Pérez".

---

### User Story 3 - Compliance and Policy Templates (Priority: P2)
As a compliance officer, I want to enforce GDPR and AI Act policies using preconfigured templates (such as restricting data transit to EU-based endpoints or flagging high-risk prompts) to ensure our organization complies with European regulations.

**Why this priority**: Ensures legal compliance with regional data protection laws (GDPR) and emerging artificial intelligence regulations (AI Act).

**Independent Test**: Configure a GDPR policy that blocks sending prompts to non-EU endpoints when sensitive data is detected, and verify that the gateway routes the request to an EU-based model or blocks it if none is available.

**Acceptance Scenarios**:
1. **Given** a GDPR policy is active, **When** a prompt containing sensitive medical data is processed, **Then** the gateway routes it exclusively to an EU-hosted model instance.
2. **Given** an AI Act policy is active, **When** a user enters a prompt categorized as "High Risk" (e.g., automated diagnostic decision without human override), **Then** the prompt is flagged and requires administrative approval or human-in-the-loop confirmation.

---

### User Story 4 - Audit Logs and Observability (Priority: P2)
As a compliance officer, I want to view a detailed audit log of all interactions, including which PII/PHI entities were masked, which policies were triggered, and the budget consumed, without storing any sensitive patient data in the logs.

**Why this priority**: Necessary for regulatory audits and accountability without creating new privacy leaks in the logging database.

**Independent Test**: Query the audit logs after a masked request and verify that the log entry shows the metadata (e.g., "PERSON masked, DNI masked") but does not contain "Juan Pérez" or "12345678X".

**Acceptance Scenarios**:
1. **Given** a request has been processed, **When** the administrator views the audit page, **Then** they see the timestamp, user ID, model used, cost, and a list of masked entities, but the raw prompt is either fully redacted or shown in its masked form.

---

### User Story 5 - Interactive Playground with Layer Animation (Priority: P1)
As a developer or administrator, I want an interactive Playground where I can chat with the LLMs and see a step-by-step animation of how the prompt passes through the security, compliance, budgeting, and routing layers in real-time.

**Why this priority**: It is the primary differentiator for demonstrating the value of the gateway, showing transparency and giving users confidence that their data is being protected at every step.

**Independent Test**: Enter a prompt in the Playground and verify that a visual pipeline shows the prompt moving through: Input ➔ Masking ➔ Compliance check ➔ Routing/Budget check ➔ LLM ➔ Unmasking ➔ Output. If the optional Context Optimizer is enabled, show the optimization layer.

**Acceptance Scenarios**:
1. **Given** the user submits a message in the Playground, **When** the message is processing, **Then** the UI displays an animated sequence showing the "Masking Layer" activating (highlighting detected PII), the "Compliance Layer" verifying policies, and the "Routing Layer" displaying the selected model and remaining budget.
2. **Given** the Context Optimizer is enabled, **When** a message is sent in the Playground, **Then** the UI displays an animation for the "Optimization Layer" showing the percentage of context compressed in real-time.

---

### Edge Cases

- **Presidio Service Outage**: If the masking service is unavailable or times out, the gateway MUST block all requests by default (fail-secure) to prevent accidental data leaks.
- **Mid-stream Budget Exhaustion**: If a user runs out of budget while receiving a streaming response, the connection must be closed immediately and the consumed portion billed correctly.
- **Nested PII**: Handling complex prompts where PII is nested within medical jargon or unstructured text without failing the sanitization.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST support user and group creation, with the ability to assign token and monetary budgets.
- **FR-002**: The system MUST intercept all incoming prompts and scan them for PII and PHI using a configurable entity list.
- **FR-003**: The system MUST replace detected PII/PHI with placeholder tokens before forwarding the request to any external LLM provider.
- **FR-004**: The system MUST reconstruct the original values in the LLM response if the response contains the placeholder tokens.
- **FR-005**: The system MUST support routing rules based on data residency requirements (e.g., routing to EU-only endpoints).
- **FR-006**: The system MUST record audit logs containing metadata of every transaction (timestamp, user, model, tokens, masked entities, policy status) while ensuring no raw PII/PHI is stored.
- **FR-007**: The system MUST expose a management API for all administrative functions (managing users, budgets, security settings, and logs).
- **FR-008**: The system MUST provide an administration UI consisting of 5 pages:
  1. Users & Budgets
  2. Security & Optimization Options (including Presidio and Headroom settings)
  3. Policies & Templates (GDPR / AI Act)
  4. Audit Logs
  5. Playground (with real-time pipeline layer animation)
- **FR-009**: The system MUST be fully brandable, showing no references, names, or logos of "litellm" on any user-facing screen or public API response.
- **FR-010**: The system MUST support an optional context optimization layer using Headroom to compress prompts and reduce token usage.
- **FR-011**: The system MUST allow administrators to toggle context optimization on or off in the settings.

### Key Entities *(include if feature involves data)*

- **User**: Represents an individual accessing the gateway. Has attributes like User ID, Name, Role, Active Status, and API Keys.
- **Group / Department**: Represents a collection of users. Can have shared budgets and policies.
- **Budget**: Defines the spending limits (monetary in USD or token count) and time windows (daily, monthly) associated with a User or Group.
- **Security & Optimization Policy**: Configures which PII/PHI entities to detect, the action to take (Mask or Block), and whether context optimization (Headroom) is enabled.
- **Compliance Template**: Predefined rulesets for GDPR and AI Act compliance (e.g., Geo-routing constraints, risk thresholds).
- **Audit Log**: A secure, non-PII record of a transaction, linking a User's request to the model used, cost, and security actions taken.

## Technical Implementation & Architectural Decisions

### 1. Zero-Dependency Local PII/PHI Masking
To achieve a lightweight local footprint, the heavy external Microsoft Presidio containers (`presidio-analyzer` and `presidio-anonymizer`) were removed from [docker-compose.yml](file:///home/drexgen/Documents/EVIDENZE/LLM-Router/docker-compose.yml). They were replaced by a high-performance, local regex-based masking engine in [presidio_service.py](file:///home/drexgen/Documents/EVIDENZE/LLM-Router/backend/src/services/presidio_service.py). This engine:
* Detects and masks critical entities (PERSON, DNI, CUIL, EMAIL_ADDRESS, PHONE_NUMBER).
* Performs reversible masking in-memory without external network calls.
* Reduces RAM overhead by several gigabytes.

### 2. Hierarchical RBAC & Virtual Keys
We implemented a hierarchical access model:
* **Teams (Equipos)**: Groups of users (e.g. "Cardiología") with shared budgets.
* **Virtual Keys**: Generated with a secure prefix `sentinel_sk_...`. Only the SHA-256 hash is stored in the database. The plain-text key is shown only once upon creation.
* **Key-level Governance**: Virtual keys enforce budgets, log transactions in `audit_logs` (storing `api_key_id`), and authorize API requests via `Authorization: Bearer sentinel_sk_...`.

### 3. Dynamic Model Filtering
To prevent showing inactive or failing models in the user interface:
* The available models list is filtered dynamically at the `/api/v1/chat/models` endpoint.
* It checks if the required API keys (e.g., `AZURE_API_KEY` for Azure OpenAI, `GEMINI_API_KEY` for Google AI Studio) are defined in the environment.
* Only models with active credentials are shown in the Playground dropdown.

### 4. White-Labeling & Error Cleaning
Strict white-labeling is enforced:
* Any reference to `litellm` or `LiteLLM` in error responses is replaced with `Sentinel Gateway`.
* Internal Python exception prefixes (e.g., `litellm.NotFoundError:`) are stripped from error details, returning clean, native-looking errors from the underlying providers (e.g. Azure's `DeploymentNotFound` details) without leaking the proxy's existence.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can view the complete step-by-step layer animation of their prompt's journey in the Playground in real-time as the response is generated.
- **SC-002**: 100% of configured PII/PHI entities are replaced before the prompt leaves the local network boundary.
- **SC-003**: The system overhead (latency added by the gateway for masking and routing, excluding LLM generation time) is under 150ms.
- **SC-004**: Compliance officers can generate and export a GDPR/AI Act audit report for any time range.
- **SC-005**: Zero raw patient PII/PHI is present in the database logs or audit tables.
- **SC-006**: When context optimization is enabled, the prompt token count sent to the LLM is reduced by at least 50% for prompts exceeding 2000 tokens.

## Assumptions

- **Local Network Safety**: The communication between the frontend, backend wrapper, and the database runs within a private Docker network.
- **External LLM Availability**: External LLM providers (Azure OpenAI, Google AI Studio) are accessible via internet connection.
- **Branding Customizability**: All UI components are custom-built, allowing complete white-labeling under the "Sentinel Secure AI Gateway (by sentinel dev)" brand.
- **No Direct Proxy UI Access**: The built-in LiteLLM admin UI is disabled or blocked from public access, and all administration is performed via our custom UI.
- **Active Credentials**: The user provides valid Azure OpenAI (`gpt-4o-mini` deployment) and Gemini API keys in the `.env` file.
