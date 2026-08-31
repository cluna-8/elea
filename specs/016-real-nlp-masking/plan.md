# Implementation Plan: Real NLP Masking & Entity Detection Hardening

**Branch**: `016-real-nlp-masking` | **Date**: 2026-07-17 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/016-real-nlp-masking/spec.md`

## Summary

Reemplaza la detección de PII/PHI regex-only por un motor NLP real (Presidio Analyzer con modelo
español, sidecar HTTP) en el camino de tráfico real del firewall (spec 014), cerrando el gap de
`PERSON` sin prefijo (US1); conecta `SecurityPolicy.entity_configs` (hoy cosmético) al
`SentinelGuardrail.async_pre_call_hook` para que `MASK`/`BLOCK` por tipo de entidad tengan efecto real
(US2); vuelve fail-closed la indisponibilidad del NLP en vez del fail-open heredado (US3); y arregla
la corrupción posible por coincidencias solapadas con una función de resolución determinística (US4).
Unifica las dos listas de patrones duplicadas (`presidio_service.py` / `sentinel_guardian_policy.py`) en
una sola fuente que viaja como `ad_hoc_recognizers` en cada llamada al Analyzer (SC-006).

## Technical Context

**Language/Version**: Python 3.11 (backend FastAPI heredado + extensiones montadas en el contenedor
LiteLLM — mismo split que spec 014). Imagen nueva propia para `presidio-analyzer` (Python, spaCy
`es_core_news_md`), construida y pinneada por digest.

**Primary Dependencies**: Presidio Analyzer (nuevo, HTTP sidecar) + spaCy modelo español; `httpx`
(ya presente en backend, se usa también para el nuevo caller del Analyzer dentro de la librería
compartida); `sentinel_guardian_policy` (extendida, no reescrita); `custom_auth.py` (extiende su query SQL
existente, no agrega dependencias nuevas).

**Storage**: PostgreSQL existente — sin tablas nuevas (ver `data-model.md`); `SecurityPolicy.entity_configs`
pasa de informativo a consultado en caliente por request.

**Testing**: pytest — unit tests nuevos de `resolve_overlaps`/`resolve_entity_action`/
`build_ad_hoc_recognizers` (puros, sin red); contract tests extendidos (`contract_checks.py`) contra el
Analyzer real; integration tests por user story (fail-closed simulando el servicio caído).

**Target Platform**: Linux server en containers (Docker Compose), un servicio nuevo (`nlp-analyzer`, imagen construida desde `presidio-analyzer/`)
sumado al stack existente.

**Project Type**: web-service (backend FastAPI + motor LiteLLM + nuevo sidecar NLP, todos en containers
separados).

**Performance Goals**: llamada al Analyzer async, timeout 2s, objetivo interno ~300ms p95 (research §8)
— no bloquea el event loop del motor; sin objetivo de throughput nuevo (el motor sigue gobernando
rpm/tpm, sin cambios).

**Constraints**: fail-closed ante NLP no disponible (FR-004, decisión del usuario); masking sigue
ocurriendo ANTES de cualquier compresión (sin cambios al orden del pipeline, Principio I); mapa
reversible jamás persistido (Constraint C1, sin cambios); ninguna llamada a terceros externos — el
Analyzer es infraestructura propia containerizada (mantiene residencia de datos EU, Principio I).

**Scale/Scope**: 1 servicio nuevo en compose + 1 imagen custom (Dockerfile propio para el Analyzer con
modelo ES) + extensión de `sentinel_guardian_policy.py` (4 funciones nuevas/modificadas, ver
`contracts/policy-library-functions.md`) + extensión de la query SQL en `custom_auth.py` + cambios
acotados en `sentinel_guardrail.py` (cuerpo de `async_pre_call_hook`, firma sin cambios) + adaptación de
`presidio_service.py`/`guardian_service.py` (backend, camino panel/playground) para converger a la
misma fuente de patrones (FR-012). Sin schema nuevo.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio / Constraint | Cómo lo cumple esta feature | Veredicto |
|---|---|---|
| **I. Privacy & Masking-First** | NLP real reemplaza regex como fuente primaria (cierra "nunca solo regex en prod"); masking sigue ANTES de compresión; mapa reversible sigue sin delegarse a terceros (Analyzer es infra propia, solo detecta rangos — no ve el mapa ni hace el reemplazo). | PASS by-design / a verificar |
| **II. Compliance FIRST** | No modifica el enforcement AI-Act/secretos existente; agrega dos motivos de bloqueo nuevos (`blocked_entity_type`, `nlp_unavailable`) al mismo canal metadata-only. | PASS by-design / a verificar |
| **V. Cost Governance (texto honesto)** | Sin impacto en budget; se documenta el costo de latencia agregado como parte del Technical Context, no se promete algo que no se mide. | N/A — sin cambios |
| **VI. LiteLLM-Native, No Patching** | El motor LiteLLM sigue pinneado por digest, sin dependencias ML agregadas a su imagen; el NLP vive en un sidecar propio, consumido vía HTTP desde el guardrail existente (mismo hook, misma firma). | PASS by-design / a verificar |
| **VII. Containerized & White-Label** | Nuevo servicio containerizado, config-as-data (`NLP_ANALYZER_URL` por env); no introduce nombres de terceros en API pública/UI (mismo naming neutro ya vigente). | PASS by-design / a verificar |
| **VIII. Pipeline Transparency** | El monitor sigue mostrando `pipeline_metadata` real; se agregan las nuevas causas de bloqueo al mismo feed, sin datos cosméticos. | PASS by-design / a verificar |
| **Constraint C1 No Raw PII/PHI Storage** | Auditoría de los nuevos motivos de bloqueo es metadata-only (tipo, no valor) — mismo patrón que hoy. | PASS by-design / a verificar |
| **Constraint C2 NLP real en prod (SC-2)** | Es el objeto central de esta feature — activa el NLP real que hoy es scaffolding inactivo. | Resuelto por esta feature |
| **Dev Workflow — Reuse over Reinvent** | Reusa `AnalyzeFn` (ya inyectable), la query SQL de identidad existente, el canal de bloqueo `str`→HTTPException existente, y `PlaceholderMap`/carry-split sin cambios. No reimplementa transporte HTTP ni framing (Presidio es HTTP simple, sin streaming). | PASS by-design / a verificar |

**Sin violaciones que requieran justificación** — no hay entrada en Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/016-real-nlp-masking/
├── plan.md              # This file
├── spec.md              # Feature spec (4 historias, FR-001..012, SC-001..006)
├── research.md           # Phase 0 (generado): elección Presidio+ES, ad_hoc_recognizers, fail-closed, overlap resolution
├── data-model.md         # Phase 1 (generado): SecurityPolicy/Guardian reutilizados + contratos en memoria nuevos
├── contracts/             # Phase 1 (generado): HTTP Presidio Analyzer + funciones de la librería PURA
│   ├── presidio-analyzer-http.md
│   └── policy-library-functions.md
├── quickstart.md          # Phase 1 (generado): validación end-to-end de las 4 historias
└── tasks.md               # Phase 2 (a generar por /speckit-tasks — NO por este comando)
```

### Source Code (repository root)

```text
litellm/
├── extensions/
│   ├── sentinel_guardian_policy.py     # + resolve_overlaps, resolve_entity_action,
│   │                                  build_ad_hoc_recognizers, presidio_analyze (AnalyzeFn)
│   ├── sentinel_guardrail.py           # cuerpo de async_pre_call_hook: usa entity_configs +
│   │                                  presidio_analyze; NlpUnavailableError -> bloqueo
│   ├── custom_auth.py              # _IDENTITY_SQL: + SecurityPolicy.entity_configs
│   └── contract_checks.py          # + checks de las funciones nuevas y conectividad Analyzer

backend/
├── src/services/
│   ├── presidio_service.py         # analyze_text_http: deja de fail-open; acepta ad_hoc_recognizers
│   └── guardian_service.py         # deja de mantener su propio PATTERNS; reusa build_ad_hoc_recognizers
└── tests/unit/                     # + test_sentinel_guardian_policy.py (resolve_overlaps, resolve_entity_action)

presidio-analyzer/                  # NUEVO — imagen propia
├── Dockerfile                      # build --build-arg NLP_CONF_FILE=conf/es.yaml
└── conf/es.yaml                    # NlpEngineConfig: spaCy es_core_news_md

docker-compose.yml                  # + servicio nlp-analyzer (sentinel-network, sin puerto al host)
.env.example                        # + NLP_ANALYZER_URL
```

**Structure Decision**: se extiende la estructura existente de spec 014 (librería PURA compartida +
guardrail + custom_auth) sin crear un nuevo "proyecto" — el único directorio nuevo de primer nivel es
`presidio-analyzer/` (imagen del sidecar), simétrico a como `litellm/` ya aloja config+extensiones de
su propio servicio.

## Complexity Tracking

*Sin violaciones de Constitution Check — tabla vacía.*
