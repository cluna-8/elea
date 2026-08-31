# Implementation Plan: Sentinel Secure AI Gateway (by sentinel dev)

**Branch**: `001-sentinel-ai-gateway` | **Date**: 2026-06-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-sentinel-ai-gateway/spec.md`

## Summary

We will build the **Sentinel Secure AI Gateway (by sentinel dev)**, a secure, brandable, and high-performance AI gateway for healthcare. The system consists of a custom FastAPI backend wrapper, a Vite/React frontend UI, a PostgreSQL database, and a LiteLLM engine, all orchestrated via Docker Compose. PII/PHI masking is handled locally in memory by a high-performance regex-based engine in the backend, and an optional context optimizer using Headroom is integrated at the gateway level.

## Technical Context

**Language/Version**: Python 3.12 (Backend), TypeScript / Node 20 (Frontend)

**Primary Dependencies**:
- **Backend**: FastAPI, Uvicorn, SQLAlchemy, Pydantic, httpx, headroom (optional context optimizer)
- **Engine**: LiteLLM (cloned/installed in container)
- **Security**: Zero-dependency local regex-based PII/PHI masking (replaces heavy Microsoft Presidio containers)
- **Frontend**: React, Vite, Vanilla CSS + custom design system, Lucide React (icons)

**Storage**: PostgreSQL 16 (for users, budgets, keys, and audit logs)

**Testing**: Pytest (Backend unit/integration tests)

**Target Platform**: Linux server running Docker / Docker Compose

**Project Type**: Multi-container web service

**Performance Goals**:
- Latency overhead added by the gateway (masking + routing): <150ms p95.
- Throughput: Capable of handling 50 concurrent streaming connections.

**Constraints**:
- Absolutely no exposure of the name "litellm" on any public-facing API or UI.
- Fail-secure: If Presidio or database checks fail, the request must be blocked.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **Principle I (Privacy/Masking)**: Passed. Microsoft Presidio is integrated at the gateway level. All prompts are sanitized before leaving the network.
- **Principle II (GDPR/Compliance)**: Passed. The database logs only metadata. Geo-routing rules are enforced based on compliance settings.
- **Principle III (Budget Enforcement)**: Passed. LiteLLM's database-backed budget tracking is utilized and enforced in real-time.
- **Principle IV (Docker/White-Label)**: Passed. Backend and frontend run in separate containers. The FastAPI wrapper hides LiteLLM.
- **Principle V (Playground Animation)**: Passed. The custom UI will display an animated layer pipeline for each chat request.

## Project Structure

We will use a multi-project (monorepo-style) structure:

```text
/
├── docker-compose.yml       # Orchestrates all 6 containers
├── .env.example             # Environment template
├── README.md                # General documentation
│
├── backend/                 # FastAPI wrapper
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── src/
│   │   ├── main.py          # Entry point
│   │   ├── models/          # SQLAlchemy models
│   │   ├── schemas/         # Pydantic schemas
│   │   ├── services/        # Business logic (Presidio, LiteLLM client, Headroom)
│   │   └── api/             # FastAPI routers
│   └── tests/
│
├── frontend/                # Vite + React UI
│   ├── Dockerfile
│   ├── package.json
│   ├── src/
│   │   ├── components/      # Reusable UI components
│   │   ├── pages/           # 5 Pages (Users, Security, Policies, Audit, Playground)
│   │   └── services/        # API client
│   └── tests/
│
└── litellm/                 # LiteLLM configuration
    └── config.yaml          # LiteLLM routing and guardrails config
```

## Complexity Tracking

No violations of the constitution are present. The architecture is kept as simple as possible while fulfilling all security and performance requirements.
