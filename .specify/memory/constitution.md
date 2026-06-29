<!--
Version change: None -> 1.0.0
List of modified principles: None -> Added 5 principles (Privacy, Compliance, Budget, Containerized/White-label, Playground)
Added sections: Security & Compliance Constraints, Development Workflow
Removed sections: None
Templates requiring updates:
- .specify/templates/plan-template.md (✅ updated)
- .specify/templates/spec-template.md (✅ updated)
- .specify/templates/tasks-template.md (✅ updated)
-->

# Basa Secure AI Gateway (by basa dev)

## Core Principles

### I. Privacy & PHI/PII Masking-First
Every user prompt containing Personally Identifiable Information (PII) or Protected Health Information (PHI) MUST be automatically detected and masked using Microsoft Presidio before leaving the local network. Placeholders must be reconstructed on the output path to ensure a seamless user experience.

### II. Strict Compliance (GDPR & AI Act)
All LLM routing must comply with GDPR data residency (using EU-based endpoints for sensitive data) and the EU AI Act risk classification. Prompt audit logs must be logged securely and must never store raw PII/PHI.

### III. Budget & Resource Enforcement
No LLM request shall be processed without a valid user/group key and sufficient assigned budget. Budget limits (token count and USD spend) must be enforced in real-time, including during streaming, to prevent cost overruns.

### IV. Containerized & White-Label Architecture
The backend (FastAPI wrapper + LiteLLM engine) and frontend (Vite/React UI) must run in separate Docker containers. The LiteLLM implementation must remain entirely hidden (white-labeled) from the user interface and public API endpoints.

### V. Explanatory & Interactive Playground
The Playground interface must visually demonstrate the security and routing pipeline using a step-by-step layer animation, showing the transformation of the prompt and the decision-making process in real-time.

## Security & Compliance Constraints

1. **No Raw PII/PHI Storage**: No raw PII/PHI may be stored in the database, local files, or external logging services.
2. **Encryption**: All data in transit must be encrypted using TLS.
3. **Metadata-Only Auditing**: Audit logs must record the metadata of the masking (e.g., entity types detected, confidence scores, execution time) rather than the sensitive content itself.

## Development Workflow

1. **Spec-Driven Development**: All features must be specified, planned, and reviewed before coding.
2. **Local Verification**: All changes must be verified locally using Docker Compose before pushing to production.

## Governance

This constitution governs all architectural decisions. Any change to the core principles requires a major version bump.

**Version**: 1.0.0 | **Ratified**: 2026-06-29 | **Last Amended**: 2026-06-29
