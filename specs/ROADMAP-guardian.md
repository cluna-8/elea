# Roadmap — Guardian App Ecosystem

**Última actualización**: 2026-08-13 — **arranca Fase 0 + recambio de tareas**: specs **017 y 018 EN MAIN**
con plan+tasks y las 6 decisiones de producto selladas por JF (PRs [#192](https://github.com/DrZuzzjen/sentinel-guardian/pull/192)/[#194](https://github.com/DrZuzzjen/sentinel-guardian/pull/194));
implementación de la 018 **en curso** (equipo Jeff, [#11](https://github.com/DrZuzzjen/sentinel-guardian/issues/11)); recambio del weekly: Falime→instalaciones,
Cristian→wizard 037 full ownership (**Fase 0 + wizard = v1.0**, ver sección Departamentos); DevRel
estrenada y parkeada (norma+drift gate en main, [PR #188](https://github.com/DrZuzzjen/sentinel-guardian/pull/188)). Actualización anterior (2026-08-12) — **el examen**: el **gate 125 PASÓ** (primer número oficial: run
`20260812-g125-02` sobre main `52e694b`, 4/4 SLOs de oro, chat p95 151 ms; evidencia firmada en
`tech-team/examenes/20260812/`), la deuda #63/#64 de la 016 quedó **CERRADA** (PRs #97/#111 + hardening),
la **035** (harness) está en `main` y estrenada en examen real, el fix del pool está mergeado y **verificado
bajo overload** (#135/#159, rodilla medida 10–25× la carga de sede), y el re-corte de ciclos al **5-SEP**
quedó sellado por JF (ver ciclos en ROADMAP-pisos). Actualización anterior (2026-08-04, la mudanza):
`main` promovido por FF de `dev-fran` (`78637e6`, tag **`checkpoint-camara-2026-08`**); las filas de
Install & Factory viven en [`deploy/ROADMAP-factory.md`](../deploy/ROADMAP-factory.md).
**Base**: forkeado de gatelite "Sentinel Secure AI Gateway" v1.0.0 + feature/012 (ver [`ROADMAP.md`](./ROADMAP.md) para la deuda heredada A–F).
**Gobierna**: [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) v2.2.0 (enmienda D10: `nlp_fail_mode`).
**Tech tree y ciclos**: [`ROADMAP-pisos.md`](./ROADMAP-pisos.md) — fases 0–2, gates 125/250/500 (**125 ✅ PASS 12-ago**) y apuestas por ciclo.

Este roadmap encadena el producto-core de **Sentinel Guardian** a partir del spec **013**, respetando las
specs 001-012 heredadas. Convierte el giro demo→prod (multi-tenant, client-as-data, firewall LiteLLM-native)
en una secuencia SDD, y **absorbe** items pendientes de Cris que ahora son parte del core (C2 Presidio, C3-C5
SSO, D5 env vars).

## Principio de secuenciación

`013` es el **bedrock** (sin multi-tenant + client model nada del resto encaja). `014` es el **titular**
(el firewall que da las demos). El resto son endurecimientos que dependen de esos dos.

## Departamentos (decisión 2026-08-03 — supera la división por módulos del 15-jul)

- **Guardian App Ecosystem — JF (@DrZuzzjen), responsable total**: todo lo de este roadmap. Dentro del
  ecosistema ya no hay sub-owners por persona: 023 pasa a JF por herencia (regla 2 del acuerdo) y las
  filas 015/017/018 son producto con responsable JF.
- **Install & Factory — Falime (@FalimeJ)**: `deploy/` entero + su roadmap propio en
  [`deploy/ROADMAP-factory.md`](../deploy/ROADMAP-factory.md). En mudanza a repo propio
  (`guardian-factory`), desprendiéndose del tag `checkpoint-camara-2026-08`.
- **Cristian (@cluna-8) — gate de review, no departamento**: custodia/rotación de claves de firma,
  RBAC de firma y auth (ver [CODEOWNERS](../.github/CODEOWNERS)).

**Recambio del 2026-08-13 (weekly JF↔Cristian↔Falime) — ajusta el reparto de arriba sin
disolverlo:**

- **Falime pasa a INSTALACIONES**: sedes de cliente (drops de imagen, accesos remotos, operativa
  Hetzner). Sigue siendo el dueño de `deploy/` como operador; el desarrollo que tenía en curso se
  redistribuye.
- **Cristian toma el wizard de onboarding (spec 037) con full ownership**, dentro del Guardian
  ecosystem — hereda de Falime el esqueleto CLI ([PR #103](https://github.com/DrZuzzjen/sentinel-guardian/pull/103))
  y el encargo del schema del perfil (validador + bloques reservados `sso`/`compliance_tier`,
  contrato en `specs/037-wizard-onboarding/`). Mantiene además su gate de review.
- **Guardian (equipos Claude, manager + Jeff) = delivery de Fase 0** (017/018 en implementación).
- **Definición de release: Fase 0 + wizard = el v1.0.** Primer objetivo del wizard: Evidenze
  (sanitario). Principio sellado en ADR-0004: *el perfil configura, la licencia autoriza* —
  todo lo vendible se gatea por `feature_flags` de la licencia firmada (021).

Las costuras entre departamentos (extensión app/distribución, release, zero-day, docs
contenido/entrega, bugs triage/installs) se formalizan como **contratos**: el dueño publica el
artefacto versionado, el otro lo consume pinneado. El doc canónico es «Manos a la obra» (tech-team/).

## Features del core

| Spec | Título | Owner | Prioridad | Estado | Constitución | Absorbe de A–F |
|------|--------|-------|-----------|--------|--------------|----------------|
| **013** | **Multi-Tenant Foundation & Client Model** | — (core) | P1 | **Implementada** (2026-07-10, ver [implementation-notes](./013-multi-tenant-foundation/implementation-notes.md)) — desbloquea 014/015/017 | III, IV, VII | — |
| **014** | **LiteLLM-Native Firewall (base_url clients)** | — (core) | P1 | **Implementada** (US1-US5, 2026-07-10, [notes](./014-litellm-native-firewall/implementation-notes.md)); sólo resta Polish T034-T037 | I, II(exc.), VI, VIII | — |
| 015 | Scoped SecurityPolicy (per-group/per-client) | JF | P2 | Roadmap | I, II | gap "SecurityPolicy global" |
| 016 | Real NLP Masking (Presidio) + streaming unmask hardening | JF | P2 | **Implementada en `main`** ([PR #21](https://github.com/DrZuzzjen/sentinel-guardian/pull/21) absorbido por el FF 2026-08-04). ✅ Deuda #63/#64 **CERRADA** (2026-08-12): paridad NLP en `/gw` + `nlp_fail_mode` gobernable ([PR #97](https://github.com/DrZuzzjen/sentinel-guardian/pull/97), D10 constitución 2.2.0) + paracaídas regex honesto ([PR #111](https://github.com/DrZuzzjen/sentinel-guardian/pull/111)) + hardening #98/#104/#105/#106/#119/#124. Verificado bajo carga: 0 canarios crudos en el gate 125. ⚠️ Deuda nueva con evidencia de run: [#167](https://github.com/DrZuzzjen/sentinel-guardian/issues/167) — fail-closed bloquea tráfico legítimo en arranque-en-frío + ráfaga de logins (confirmar mecanismo ANTES del gate 250) | I, SC-2 | **C2** |
| 017 | Auth hardening & Multi-Tenant RBAC + SSO | JF (gate: Cristian) | **P1** (re-priorizada 12-ago) | **Spec+plan+tasks EN MAIN** ([PR #194](https://github.com/DrZuzzjen/sentinel-guardian/pull/194), 13-ago) con recorte sellado por JF: matriz sobre el shim + auditor read-only (absorbe 034) + rol `lectura` + SSO **solo Entra** por contrato de proveedor gateado por licencia (Google→C3) + RLS partida + hardening cerrado de 4. **Implementación en cola tras el MVP de la 018** (equipo Jeff). Precondiciones 24-ago: merge-order [#137](https://github.com/DrZuzzjen/sentinel-guardian/pull/137) con Cristian + tenant Entra de prueba (DevOps) | III, SC-3 | **C3, C4, C5**, D5, absorbe **034** |
| 018 | Compliance Enforcement Tiers + retention purge | JF | **P1** (re-priorizada 12-ago) | **Spec+plan+tasks EN MAIN** ([PR #192](https://github.com/DrZuzzjen/sentinel-guardian/pull/192), 13-ago; gate de producto sellado: DSAR fuera → spec propia C3 en Guardian, tiers `estricto`/`estándar` sobre el registry 027) — **implementación EN CURSO, equipo Jeff** ([#11](https://github.com/DrZuzzjen/sentinel-guardian/issues/11)): Foundational → MVP purga (gate manager) → tiers. ⚠️ El gate 250 lo destraba la **implementación**, no la spec | II [D3] | A4 |
| 019 | Integration Surfaces & Client Compatibility | JF | P2 | **Implementada** (US1-US5, 2026-07-14, [notes](./019-integration-surfaces/implementation-notes.md)); spikes batch 1 mergeados ([PR #29](https://github.com/DrZuzzjen/sentinel-guardian/pull/29)) + registro de superficies vivo; resta E2E de la extensión en navegador + spike Cline/Continue en vivo (#15) | VI, VIII, II(exc.), IV | promueve browser-DLP del "later" |
| 021 | Licensing & Seat Enforcement (offline Ed25519) — **lib runtime** | JF (gate: Cristian) | P2 | **Implementada** (US1-US5, 2026-07-20, stack [PR #18](https://github.com/DrZuzzjen/sentinel-guardian/pull/18)→#19→#20→[#22](https://github.com/DrZuzzjen/sentinel-guardian/pull/22)). **Mixta**: acá vive solo la lib (`backend/src/licensing`, fuente única); la operativa de emisión/cupos/true-up es de Factory ([roadmap](../deploy/ROADMAP-factory.md)) | VII, III, II | — |
| 022 | Product Documentation Site — **contenido** | JF | P2 | **Implementada** (US1-US7, 2026-07-20, [PR #25](https://github.com/DrZuzzjen/sentinel-guardian/pull/25) + [#26](https://github.com/DrZuzzjen/sentinel-guardian/pull/26) docs-en-DoD). **Mixta**: contenido acá; build+entrega brandeada = Factory. Contrato: `openapi.json` single-source | VII, VIII, II | — |
| 023 | Ahorro de Costes IA en el plano firewall (perfiles + ruteo coste-consciente) | JF (herencia 03-ago) | P2 | **Spec mergeada** ([PR #6](https://github.com/DrZuzzjen/sentinel-guardian/pull/6)); implementación pendiente (#16) | II, IV, VI | generaliza **012** al plano firewall |
| 024 | Unmask + atribución en respuestas byok (rutas bridged) | JF | P2 | **Implementada** (2026-07-21, [PR #31](https://github.com/DrZuzzjen/sentinel-guardian/pull/31), cierra #27); promueve 3 superficies de 019 a FUNCIONA | I, VI, VIII | fix-spec de #27 |
| 027 | Gobernanza configurable + enforcement honesto del firewall | JF | **P1** | **Implementada en `main`** (Foundational+US1+US2; [PR #43](https://github.com/DrZuzzjen/sentinel-guardian/pull/43) absorbido por el fast-forward 2026-08-04). `tasks.md` declara **parciales por diseño** SC-003/SC-005/SC-006; restan T024/T025 (plano motor — **desbloqueadas**: la 016 ya está en `main`), T034 (quickstart e2e) y T036 (P3). **T037 CERRADA**: enmienda D8 sellada el 2026-08-04 — constitución **2.1.0** | I [D8], II, VI, VIII | — |
| 028 | Productización de la extensión de navegador — **features** | JF | P1 | **Implementada en `main`** (US1-US8; fast-forward 2026-08-04, incl. hardening [#44](https://github.com/DrZuzzjen/sentinel-guardian/issues/44)/[PR #45](https://github.com/DrZuzzjen/sentinel-guardian/pull/45) integrado). **Mixta**: features acá; white-label/zip/distribución = Factory. Contratos: `contracts/whoami-proteccion.md` + checksum en MANIFEST. Siguiente: Firefox ([#65](https://github.com/DrZuzzjen/sentinel-guardian/issues/65), nivel 2) | VII, I, C1 | — |
| 029 | Rediseño de la UI del panel — estilo Azure Foundry (claro, lean) | JF | P2 | **Implementada en `main`** (US1-US4; fast-forward 2026-08-04); 6 páginas del piloto + shell | VII, VIII | — |
| 030 | Auto-router semántico + rediseño «Modelos & Ollama» | JF | **P1** | **Implementada en `main`** (US1-US3, 20/20 tareas; fast-forward 2026-08-04); verificada en vivo sobre el stack del piloto (SC-001 = **9/9** contra el seed) | II, V, VI, VIII | — |
| 031 | Auditoría durable de bloqueos (motor/chat/gateway) + UI honesta | JF | **P1** | **Implementada en `main`** (US1-US3, 15/15 tareas; fast-forward 2026-08-04); paga el corte D6 que la 027 había diferido "a la 018"; la **purga de retención sigue en la 018** | II, VIII, I, VI | — |
| 033 | Engine reload sin restart manual + feedback en UI | JF | **P1** | **Roadmap — sin spec** (research 2026-07-30, veredicto en [#50](https://github.com/DrZuzzjen/sentinel-guardian/issues/50)). Prerrequisito de escritura atómica **ya pago** (`1151b1e`, en `main`). Est. ~2-2.5 d con retest E2E del bundle amd64 (retest = costura con Factory) | VI, VIII, VII | — |
| 034 | Rol `auditor` canónico read-only | JF | P2 | **ABSORBIDA por la 017** (13-ago): la matriz canónica de [PR #194](https://github.com/DrZuzzjen/sentinel-guardian/pull/194) define `compliance_officer` read-only con única excepción (resolver human reviews) y sin probar «dueño» — no lleva spec propia; se entrega con la implementación de la 017 | III, SC-3, II | absorbida por **017** |
| **035** | Load harness + gates de carga 125/250/500 — instrumento de La ITV | JF (ejecuta La ITV) | **P1** | **Implementada en `main`** (spec+plan por speckit; consolidada [PR #122](https://github.com/DrZuzzjen/sentinel-guardian/pull/122), corridas reales [PR #163](https://github.com/DrZuzzjen/sentinel-guardian/pull/163)+[#164](https://github.com/DrZuzzjen/sentinel-guardian/pull/164) con doble gate adversarial). **Estrenada el 12-ago: gate 125 PASS** (4/4 SLOs de oro; evidencia firmada `tech-team/examenes/20260812/`) + rodilla de capacidad medida (10–25× sede en ccx33). Deuda del instrumento consolidada: [#168](https://github.com/DrZuzzjen/sentinel-guardian/issues/168) (ciclo 250). Encargo de dimensionamiento **PAUSADO 13-ago** (JF): el sizing envejece igual que el gate (compresor/NLP cambian el perfil de recursos) — corre en el mismo batch que el **gate 250**, cuyo disparador sellado es contenido, no fecha: implementación 018 + [#178](https://github.com/DrZuzzjen/sentinel-guardian/issues/178)/[#147](https://github.com/DrZuzzjen/sentinel-guardian/pull/147) + compresor [#16](https://github.com/DrZuzzjen/sentinel-guardian/issues/16) en main | II, VIII, I | los gates son el pilar de ESCALA del DoD de Fase 0 |
| **036** | Políticas de compliance por cliente/país (region-aware) | Cristian @cluna-8 (gate: manager) | P2 | **En PRs** (stack [#141](https://github.com/DrZuzzjen/sentinel-guardian/pull/141) spec → [#137](https://github.com/DrZuzzjen/sentinel-guardian/pull/137) region por tenant → [#143](https://github.com/DrZuzzjen/sentinel-guardian/pull/143) content filter → [#147](https://github.com/DrZuzzjen/sentinel-guardian/pull/147) API+pantalla+docs). Freeze del examen levantado 12-ago: gates adversariales en ese orden, CI rojos (#143/#147) son tarea de Cristian. Decisiones de producto selladas por JF 12-ago: superficie tal cual · solo admins aprueban · paralelo best-effort | II, III, VII | — |
| **050** | IA Hub: Hub conector fino + Guardian firewall + motores (tabular DuckDB, Presenton, docs 049) | Cristian | **P1** | **Implementada** (hitos 1-6, 12/14-sep-2026, rama `050-ia-hub-conector-motores` de `cluna-8/elea`; [CHANGELOG](./050-ia-hub-conector-motores/CHANGELOG.md), [handoff a Sentinel](./050-ia-hub-conector-motores/HANDOFF-elea-a-sentinel.md)). Incluye fix del firewall: restitución en streaming OpenAI. **Pendiente**: instalador probado desde cero en máquina limpia; atribución de gasto por persona en el engine; allow-list NLP por tenant; specs 047 y 049 | I, VI, VII, VIII | absorbe 046, 048; recorta 045, 049 |
| **051** | Historial de conversaciones en Planillas — investigación de la mejor opción (motor guarda por hilo + registro de hilos en Guardian, hipótesis D) | Cristian | P2 | **Investigación cerrada** (14-sep-2026; [spec](./051-historial-planillas/spec.md), [resultados](./051-historial-planillas/RESULTADOS.md): D para planillas + espacio personal en el motor de documentos para el chat directo, sin LangChain; a aprobar) | I, VII | depende de 050 |

### 033/034 — Paquete «onboarding v2», lado producto (post-instalación Cámara, sin arrancar)
Salen del **research del 2026-07-30** (4 minions + síntesis) sobre el feedback en vivo de Rafa y Javi
durante la instalación del piloto — issues [#49](https://github.com/DrZuzzjen/sentinel-guardian/issues/49)–[#52](https://github.com/DrZuzzjen/sentinel-guardian/issues/52).
Diagnóstico de JF: «el onboarding **es** cargar modelos; urge que tenga sentido o parece amateur».
La tercera pata del paquete —**032 ingress cert modes**— es de Install & Factory y vive en
[su roadmap](../deploy/ROADMAP-factory.md).

- **033 — Engine reload sin restart manual**: wrapper-supervisor como entrypoint del motor (~50 líneas, viaja
  por el volumen) que detecta el cambio de config, valida el YAML y relanza; más `GET /models/status` y estado
  «Aplicando cambios…» en la UI, que es literalmente lo que el cliente pidió ver. **Verificado leyendo el
  código de la imagen pinneada: LiteLLM NO tiene reload sin DB**, así que «que lo haga el motor» no existe
  como opción. Su prerrequisito —escritura atómica del `config.yaml`— **ya está pago** (commit `1151b1e`).
- **034 — Rol `auditor` canónico read-only**: migración del CHECK + gates + deny explícito de chat +
  navegación reducida. El quick-win ([PR #54](https://github.com/DrZuzzjen/sentinel-guardian/pull/54), mergeado)
  sólo hizo creable el `compliance_officer` existente y **declara honestamente que no es read-only**: hoy ese
  rol puede desactivar la política de protección activa y acortar la retención de los registros que audita.
  No consume seats (argumento comercial) y la futura **017** lo absorbe en su matriz definitiva.

### 013 — Multi-Tenant Foundation & Client Model (P1, bedrock)
El aislamiento por tenant + el modelo de "client" como dato. `tenant_id` en todas las entidades + RLS Postgres;
entidad `Tenant`; jerarquía Tenant→Group→Client→Connection; reconciliación de roles (super-admin/tenant-admin +
`role="client"` + `client_type`; clinician/developer → labels); onboarding como config+seed. Migración Alembic
con default-tenant backfill (single-tenant sigue funcionando). **Precondición de todo lo demás.**

### 014 — LiteLLM-Native Firewall (P1, titular)
Portar el gateway del demo (`gatelite .../api/gateway.py`) **bien**, como extensión nativa de LiteLLM:
`CustomGuardrail` (AI-Act + secretos + PII mask/unmask reversible sobre SSE), `custom_auth` (identidad por
User-Agent + virtual key → tenant/client/tool), `CustomLogger` (audit metadata-only), `/v1/messages` nativo.
**Excepción propia:** passthrough OAuth de suscripción en el backend. Router GDPR = N/A (excepción acotada del
Principio II). Incluye el monitor en vivo para demos.

### 015 — Scoped SecurityPolicy (P2)
Reemplazar `get_or_create_default_policy` (singleton global) por resolución en cascada
`client > group > tenant > default`, calcando el patrón per-cliente de `ComplianceProject`. Unicidad de política
activa por scope.

### 016 — Real NLP Masking + streaming hardening (P2)
Activar Presidio NLP real (analyzer, fallback regex de dev/demo) — antes scaffolding inactivo (SC-2). Endurecer
la reversibilidad del masking sobre streaming (los 12 bugs del demo ya resueltos se formalizan como tests de
contrato). Región activa Europa/España (`ES_NIF`/`ES_NIE` built-in de Presidio, región `latam_ar` preparada
pero inactiva). `entity_configs` (MASK/BLOCK) ahora conectado al firewall real, no solo al panel. Fail-closed
real si el NLP no responde. Catálogo de entidades custom con asistente de IA (draft-then-review humano).
Gap PHI clínico español (CIE-10, nº historia clínica) queda fuera de alcance de esta spec.

### 017 — Auth hardening & Multi-Tenant RBAC + SSO (P2)
Cerrar el fallback a admin sin token (SC-3). RBAC scopeado por tenant. SSO real OIDC/SAML (Azure AD, Google
Workspace, Keycloak — C3/C4/C5). Revocación de sesión server-side. Credenciales a env vars (D5).

### 018 — Compliance Enforcement Tiers + retention purge (P3)
Decidir/implementar qué "evidencia" pasa a "gate duro" (consent/retención). Job de purga de retención real
(hoy nunca ejecuta). Cerrar tests de integración compliance (A4).

### 019 — Integration Surfaces & Client Compatibility (P2)
Portar y formalizar el **lado cliente** del firewall (probado en gatelite-demo): Claude Code (passthrough de
suscripción + identidad `X-Sentinel-Key`), VS Code/Copilot (auto-byok, key-in-URL, modo Ask), extensión browser MV3
(mask/unmask en ChatGPT/Claude web). Matriz de compatibilidad: Cursor=parcial (solo chat/plan, como Copilot Ask),
Gemini web=vía DOM-hook (spike), Claude Desktop=MCP tool-plane only. Research: no hay "LiteLLM del browser-DLP";
el approach de Sentinel es el patrón dominante — **moat: des-enmascarar en vez de bloquear** (mantiene UX). Docs de
training/soporte en `docs/integration-surfaces.md`.

### 021 — Licensing & Seat Enforcement (P2)
Enforcement de licencias **offline** para el modelo "install + N seats" (el cliente corre la caja, sin phone-home).
Research build-vs-buy: **DIY Ed25519** — no hay producto que aplique por el air-gap; `seat = Connection activa`
contada en Postgres. Licencia firmada `.lic` (tenant_id, distributor_id, pool_id, max_seats, expiry, `kid`)
verificada en 2 gates fail-closed (arranque + creación de Connection); anti-tamper vía **cadena de hashes +
export de true-up firmado** (deployment key). **Addendum 2026-07-14** (prior-art validado: GitLab/Grafana/
Directus/Replicated): tier distribuidor = **firma CENTRAL de Sentinel + cupo de emisión** (nunca clave delegada);
per-seat capturado en emisión + true-up en renovación; expiry **degrada** (grace → read-only-creación), nunca
mata el box; seat-gate etiquetado best-effort honor-system (ancla real = contrato). Complementa la 020.

### 022 — Product Documentation Site (P2)
Sitio de documentación de producto como **contenedor `docs` propio** (estático, air-gapped, 0 egress en runtime),
separado de la app. Research build-vs-buy: **MkDocs + Material** (air-gap de primera clase vía plugins `offline`+
`privacy`, Python-nativo, white-label por YAML, versionado `mike`, i18n `static-i18n`); plan B **Starlight+Pagefind**.
Audiencia **distribuidor+operador** (install/deploy, admin, API reference, compliance, troubleshooting); sembrada de
`docs/*.md`. **API reference single-source del OpenAPI de FastAPI** (no derivar de las specs — audiencias distintas).
White-label por config (imagen-por-marca), búsqueda offline (nunca Algolia). Runbook/decisión en `docs/whitelabel-deployment.md`.

### 023 — Ahorro de Costes IA en el plano firewall (P2)
Generalizar la **012** (compresión determinista, ahorro neto, KPI — hoy solo en el path legacy del panel)
al **plano byok del firewall**, donde pasa el tráfico real: la cascada `compression_mode` (key > group >
tenant) ya se resuelve en la identidad del motor pero **nada la consume**. Perfiles de optimización por
scope (default developer: coding tools intocables), ahorro medible en presupuesto + audit metadata-only,
y **ruteo coste-consciente** opt-in por reglas de equivalencia con guardia de calidad (nunca sustitución
silenciosa). Plano passthrough fuera de alcance (coste de suscripción fijo). Spec: [PR #6](https://github.com/DrZuzzjen/sentinel-guardian/pull/6).

### 024 — Unmask + atribución en respuestas byok, rutas bridged (P2, fix-spec de #27)
Cerrar el round-trip mask→unmask en el camino byok del **motor** para modelos no-Claude (local vía Ollama
y cloud puenteados) y devolver la **identidad** a los eventos del monitor de ese camino. Tres root causes
verificados en vivo (la evidencia refutó la hipótesis inicial): (1) streaming — `safe_split` soltaba un `[`
pelado y los bridges con deltas de 1-3 chars partían el placeholder ahí (bug latente también en passthrough);
(2) no-streaming — la respuesta bridged es un `dict` plano que el `getattr` ignoraba; (3) atribución — el
logger leía la identidad de un solo metadata-home. Todo en `litellm/extensions/` (Principio VI), con e2e
contra el motor vivo que antes no existía. **Promueve a FUNCIONA** las 3 superficies que la 019 había dejado
en PARCIAL (Ollama upstream, Claude Code → modelo propio, Aider).

### 027 — Gobernanza configurable y enforcement honesto del firewall (P1)
El mapeo del plano firewall (2026-07-22) encontró que **el catálogo de guardianes que la UI presenta como
activos no se corresponde con lo que realmente se ejecuta**: corren tres capas (enmascarado de PII, bloqueo de
secretos, evaluación AI-Act) y las capas "de proveedor" que la UI ofrecía se declaraban "delegadas al motor"
sin que el motor tuviera ninguna habilitada. La 027 entrega el **marco**: registro de capas con **estado real**
(aplicándose / requiere credencial / delegada al proveedor upstream / no disponible), configuración por
**modo de conexión** (Suscripción vs Modelo propio) y por superficie/herramienta con un **piso no-negociable**
siempre activo, y atribución de bloqueo por pedido. **Decisiones selladas**: **D8** — el piso es
*detectar/evaluar/registrar* siempre, el *transformar* (enmascarar) se gobierna absorbiendo `redact_enabled`
de la 013 (confirmada por el owner el 2026-07-22; es el CRITICAL de T037 porque exige enmienda formal de la
constitución 2.0.0→2.1.0); **X-Sentinel-Redact solo-restrictivo** (la superficie confiable nunca puede aflojar el
perfil, solo endurecerlo); **orden de aplicación 016→027** (las tareas 🔀 tocan archivos que el PR #21
reescribe). El cableado real de los guardrails de proveedor **salió del alcance** — pertenece al módulo de
seguridad; el marco lo toma sin cambios de diseño cuando llegue. **Hallazgo abierto** (verificado en vivo
2026-07-23): con `pii_masking=off` el motor enmascara igual porque su guardrail no conoce el perfil (T025) —
no es fuga (enmascara de más), pero la fila dice `skipped` sobre algo que ocurrió.

### 028 — Productización de la extensión de navegador (P1, entregable del piloto)
Llevar la extensión MV3 de la 019 de PoC a **producto entregable**: un solo comando genera el paquete con la
identidad del **partner** (marca + identificador estable, **sin hornear la URL del gateway** — la aporta el
usuario, lo que la hace agnóstica al despliegue), el paquete **viaja dentro del entregable de instalación**
con su checksum en el manifiesto, la extensión **declara su nivel real de protección** y **explica el motivo
real** de un bloqueo reusando el catálogo cerrado de la 027, y la sesión **distingue "sin red" de "sin
permiso"** revalidándose sola. Gate de release que verifica el white-label (US7) y rechazo de keys vencidas o
de otra superficie en el backend (US8). Brief de handoff en [#46](https://github.com/DrZuzzjen/sentinel-guardian/issues/46);
NEXT en `extension/NEXT-028.md`. **Canónica única**: `sentinel-guardian/extension/` (las copias divergentes se
borraron). Precedida por el hardening [#44](https://github.com/DrZuzzjen/sentinel-guardian/issues/44) /
[PR #45](https://github.com/DrZuzzjen/sentinel-guardian/pull/45), que sacó el mapa reversible token→PII del alcance
del proveedor y cerró el bridge que aceptaba mensajes de la página: la 028 **preserva ese hardening, no lo regresa**.

### 029 — Rediseño de la UI del panel, estilo Azure Foundry (P2)
El panel que ve el admin del cliente pasa del tema oscuro (navy/cian, Fira Sans **desde el CDN de Google
Fonts**) a un estilo **claro tipo Azure AI Foundry / Fluent**: canvas gris muy claro, superficies blancas con
bordes finos, sidebar clara con acento, pills de estado semánticas, tipografía Inter. Alcance: las **6 páginas
del piloto** (Login, Dashboard, Firewall en vivo, Usuarios & Presupuestos, Modelos & Ollama, Playground) + el
shell + el auto-guardado del toggle de headroom; el resto hereda tokens y shell. El white-label no se rompe
(Principio VII): el tema claro es **fijo** y solo el **acento** se tiñe con la marca — un brand-pack con
colores oscuros (el de Cámara) ya no vuelve a oscurecer el chrome. Las **fuentes pasan a auto-hospedarse**,
lo que cierra de paso una **fuga de egress preexistente** (el CDN) y es precondición de air-gap.

### 030 — Auto-router semántico + rediseño «Modelos & Ollama» (P1)
Portar el auto-router de llm-guardian **sin sacar el prompt de la máquina**: «Auto» como pseudo-modelo que
clasifica semánticamente cada consulta (embeddings de utterances por ruta + coseno + umbral + best-of) y la
enruta — código/análisis/razonamiento → premium cloud; resumen/redacción/traducción → económico cloud;
**conversación trivial y todo lo que no matchea → modelo local (coste 0)**. llm-guardian usaba Azure para los
embeddings, **inaceptable acá** (Principio I + residencia): se resuelve con embeddings 100% locales vía Ollama
(`qwen3-embedding:0.6b`, 639 MB — 8/9 en el benchmark previo; la **tercera ruta "trivial"** cierra el 9º caso).
Panel de ruteo en «Modelos & Ollama» (accordion, switch on/off, config caliente, generación de frases-ejemplo
con IA local) y **degradación honesta** (si el router no responde se cae a local y **queda registrado**, nunca
en silencio). El coste se calcula sobre el modelo que **contestó**, no sobre el pedido (fix de la asimetría
`request.model` vs `routed_model`, research R7). Decisión visible en el Debugger Técnico y en «Conexiones en
vivo» (Principio VIII). Benchmark reproducible en `specs/030-semantic-auto-router/bench_embeddings.py`.

### 031 — Auditoría durable de bloqueos + UI honesta (P1)
El pitch del producto es «logueamos TODO para compliance» y el evento más importante —**«se intentó y se
impidió»**— era el único sin rastro durable: el motor devolvía el rechazo desde el pre-call y su logger solo
implementaba el hook de éxito; los 3 puntos de bloqueo del chat publicaban al monitor efímero de Redis (TTL
300 s) y hacían `raise` **antes** del único `log_transaction`; y la escritura era **best-effort en todas las
capas** (4xx/5xx/timeout tragados con un `print`), agujero que ya causó pérdida total de auditoría byok en el
ensayo del piloto. La 031 cierra los **tres planos** (motor/guardrail, chat del backend, `/gw` passthrough)
con la convención `compliance_status` `blocked_*` **sin columnas nuevas**, hace la escritura **ruidosa**
(reintento acotado + contador de pérdidas en Redis expuesto en `GET /api/v1/health` autenticado y visible en
la UI de Logs), agrega `SENTINEL_AUDIT_FAIL=open|closed` como config de instalación (en `closed` se rechaza
**antes** de llamar al proveedor: no se gasta dinero en tráfico inauditable), suma el filtro **«Solo
bloqueados»** y vuelve honesto el catálogo de guardianes y la pestaña de retención. **Paga el corte D6 que la
027 había diferido "a la 018"**; la **purga automática de retención sigue siendo de la 018** (Cristian) y se
declara explícitamente fuera de alcance, igual que los 5 guardianes cloud y el dead-letter con reproceso.

## Mantenimiento de este roadmap

Esta tabla es la **fuente de verdad del estado** y debe actualizarse en el **mismo PR que mergea cada spec**
(pasar el Estado a *Implementada* con el link al PR, o *En review* con el link, y cerrar el issue de tracking
con `Closes #NN`). Un roadmap que dice "Roadmap (greenfield)" sobre algo ya mergeado es un bug de proceso.

**Dónde vive cada cosa (desde el 2026-08-04)**: `main` es la **única rama de verdad** — el fast-forward
`78637e6` absorbió todo `dev-fran` (016+fixes, 027-031, los 4 PRs del gate #53-#56) y quedó taggeado como
**`checkpoint-camara-2026-08`**, el punto de desprendimiento del repo de Install & Factory. `dev-fran`
queda **jubilada** (puntero histórico; no recibirá más trabajo). Flujo desde hoy: ramas cortas de feature
contra `main` + gate `/codex-gate` antes de mergear. Ojo: la **sede** de la Cámara corre la imagen de un
bundle anterior a los últimos fixes — el estado exacto instalado es el MANIFEST de ese bundle, no el tag;
el drop de imagen acumulado es operativa de Factory.

## Fuera de scope del core (siguen como research/later)
- **Browser-DLP web** (ChatGPT/Claude/Gemini) — **promovido a spec 019** (viable: el body no está firmado →
  extensión MV3 mask/unmask). La interceptación de **apps desktop nativas** (Claude Desktop) sigue como gap:
  bloqueada por cert-pinning, gobernable solo vía **MCP tool-plane** (ver 019).
- Guardianes cloud reales Lakera/Azure (D1), export PDF firmado (D2), alertas email (D3).
