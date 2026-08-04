# Roadmap — Guardian App Ecosystem

**Última actualización**: 2026-08-04 — **la mudanza**: (1) `main` promovido por fast-forward de `dev-fran`
(`78637e6`) y taggeado **`checkpoint-camara-2026-08`** — el punto de desprendimiento para el repo de
Install & Factory; (2) este roadmap queda **solo con el producto** (Guardian App Ecosystem, JF): las filas
de Install & Factory (020, 025, 026, 032 y la operativa) se mudan a
[`deploy/ROADMAP-factory.md`](../deploy/ROADMAP-factory.md), que viaja con `deploy/` cuando Falime haga su
repo; (3) los estados 016/027-031 pasan a **Implementada en `main`** (ya no "en dev-fran").
**Base**: forkeado de gatelite "Basa Secure AI Gateway" v1.0.0 + feature/012 (ver [`ROADMAP.md`](./ROADMAP.md) para la deuda heredada A–F).
**Gobierna**: [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) v2.0.0.

Este roadmap encadena el producto-core de **Basa Guardian** a partir del spec **013**, respetando las
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

Las costuras entre departamentos (extensión app/distribución, release, zero-day, docs
contenido/entrega, bugs triage/installs) se formalizan como **contratos**: el dueño publica el
artefacto versionado, el otro lo consume pinneado. El doc canónico es «Manos a la obra» (tech-team/).

## Features del core

| Spec | Título | Owner | Prioridad | Estado | Constitución | Absorbe de A–F |
|------|--------|-------|-----------|--------|--------------|----------------|
| **013** | **Multi-Tenant Foundation & Client Model** | — (core) | P1 | **Implementada** (2026-07-10, ver [implementation-notes](./013-multi-tenant-foundation/implementation-notes.md)) — desbloquea 014/015/017 | III, IV, VII | — |
| **014** | **LiteLLM-Native Firewall (base_url clients)** | — (core) | P1 | **Implementada** (US1-US5, 2026-07-10, [notes](./014-litellm-native-firewall/implementation-notes.md)); sólo resta Polish T034-T037 | I, II(exc.), VI, VIII | — |
| 015 | Scoped SecurityPolicy (per-group/per-client) | JF | P2 | Roadmap | I, II | gap "SecurityPolicy global" |
| 016 | Real NLP Masking (Presidio) + streaming unmask hardening | JF | P2 | **Implementada en `main`** (integrada vía `dev-fran` con fixes; [PR #21](https://github.com/DrZuzzjen/basa-guardian/pull/21) absorbido por el fast-forward 2026-08-04). ⚠️ Deuda viva: degradación **silenciosa** a regex en el plano backend ([#63](https://github.com/DrZuzzjen/basa-guardian/issues/63)) + paracaídas regex pobre y con etiquetas engañosas ([#64](https://github.com/DrZuzzjen/basa-guardian/issues/64)) — caso real del piloto 04-ago | I, SC-2 | **C2** |
| 017 | Auth hardening & Multi-Tenant RBAC + SSO | JF (gate: Cristian) | P2 | Roadmap | III, SC-3 | **C3, C4, C5**, D5 |
| 018 | Compliance Enforcement Tiers + retention purge | JF | P3 | Roadmap | II [D3] | A4 |
| 019 | Integration Surfaces & Client Compatibility | JF | P2 | **Implementada** (US1-US5, 2026-07-14, [notes](./019-integration-surfaces/implementation-notes.md)); spikes batch 1 mergeados ([PR #29](https://github.com/DrZuzzjen/basa-guardian/pull/29)) + registro de superficies vivo; resta E2E de la extensión en navegador + spike Cline/Continue en vivo (#15) | VI, VIII, II(exc.), IV | promueve browser-DLP del "later" |
| 021 | Licensing & Seat Enforcement (offline Ed25519) — **lib runtime** | JF (gate: Cristian) | P2 | **Implementada** (US1-US5, 2026-07-20, stack [PR #18](https://github.com/DrZuzzjen/basa-guardian/pull/18)→#19→#20→[#22](https://github.com/DrZuzzjen/basa-guardian/pull/22)). **Mixta**: acá vive solo la lib (`backend/src/licensing`, fuente única); la operativa de emisión/cupos/true-up es de Factory ([roadmap](../deploy/ROADMAP-factory.md)) | VII, III, II | — |
| 022 | Product Documentation Site — **contenido** | JF | P2 | **Implementada** (US1-US7, 2026-07-20, [PR #25](https://github.com/DrZuzzjen/basa-guardian/pull/25) + [#26](https://github.com/DrZuzzjen/basa-guardian/pull/26) docs-en-DoD). **Mixta**: contenido acá; build+entrega brandeada = Factory. Contrato: `openapi.json` single-source | VII, VIII, II | — |
| 023 | Ahorro de Costes IA en el plano firewall (perfiles + ruteo coste-consciente) | JF (herencia 03-ago) | P2 | **Spec mergeada** ([PR #6](https://github.com/DrZuzzjen/basa-guardian/pull/6)); implementación pendiente (#16) | II, IV, VI | generaliza **012** al plano firewall |
| 024 | Unmask + atribución en respuestas byok (rutas bridged) | JF | P2 | **Implementada** (2026-07-21, [PR #31](https://github.com/DrZuzzjen/basa-guardian/pull/31), cierra #27); promueve 3 superficies de 019 a FUNCIONA | I, VI, VIII | fix-spec de #27 |
| 027 | Gobernanza configurable + enforcement honesto del firewall | JF | **P1** | **Implementada en `main`** (Foundational+US1+US2; [PR #43](https://github.com/DrZuzzjen/basa-guardian/pull/43) absorbido por el fast-forward 2026-08-04). `tasks.md` declara **parciales por diseño** SC-003/SC-005/SC-006; restan T024/T025 (plano motor — **desbloqueadas**: la 016 ya está en `main`), T034 (quickstart e2e) y T036 (P3). **T037 CERRADA**: enmienda D8 sellada el 2026-08-04 — constitución **2.1.0** | I [D8], II, VI, VIII | — |
| 028 | Productización de la extensión de navegador — **features** | JF | P1 | **Implementada en `main`** (US1-US8; fast-forward 2026-08-04, incl. hardening [#44](https://github.com/DrZuzzjen/basa-guardian/issues/44)/[PR #45](https://github.com/DrZuzzjen/basa-guardian/pull/45) integrado). **Mixta**: features acá; white-label/zip/distribución = Factory. Contratos: `contracts/whoami-proteccion.md` + checksum en MANIFEST. Siguiente: Firefox ([#65](https://github.com/DrZuzzjen/basa-guardian/issues/65), nivel 2) | VII, I, C1 | — |
| 029 | Rediseño de la UI del panel — estilo Azure Foundry (claro, lean) | JF | P2 | **Implementada en `main`** (US1-US4; fast-forward 2026-08-04); 6 páginas del piloto + shell | VII, VIII | — |
| 030 | Auto-router semántico + rediseño «Modelos & Ollama» | JF | **P1** | **Implementada en `main`** (US1-US3, 20/20 tareas; fast-forward 2026-08-04); verificada en vivo sobre el stack del piloto (SC-001 = **9/9** contra el seed) | II, V, VI, VIII | — |
| 031 | Auditoría durable de bloqueos (motor/chat/gateway) + UI honesta | JF | **P1** | **Implementada en `main`** (US1-US3, 15/15 tareas; fast-forward 2026-08-04); paga el corte D6 que la 027 había diferido "a la 018"; la **purga de retención sigue en la 018** | II, VIII, I, VI | — |
| 033 | Engine reload sin restart manual + feedback en UI | JF | **P1** | **Roadmap — sin spec** (research 2026-07-30, veredicto en [#50](https://github.com/DrZuzzjen/basa-guardian/issues/50)). Prerrequisito de escritura atómica **ya pago** (`1151b1e`, en `main`). Est. ~2-2.5 d con retest E2E del bundle amd64 (retest = costura con Factory) | VI, VIII, VII | — |
| 034 | Rol `auditor` canónico read-only | JF | P2 | **Roadmap — sin spec** (research 2026-07-30, veredicto en [#52](https://github.com/DrZuzzjen/basa-guardian/issues/52)). El quick-win [PR #54](https://github.com/DrZuzzjen/basa-guardian/pull/54) (**mergeado 2026-08-04**) sólo expone el `compliance_officer` existente **declarando que NO es read-only**; la **017** lo absorbe en su matriz definitiva. Est. 1-1.5 d | III, SC-3, II | adelanta parte de **017** |

### 033/034 — Paquete «onboarding v2», lado producto (post-instalación Cámara, sin arrancar)
Salen del **research del 2026-07-30** (4 minions + síntesis) sobre el feedback en vivo de Rafa y Javi
durante la instalación del piloto — issues [#49](https://github.com/DrZuzzjen/basa-guardian/issues/49)–[#52](https://github.com/DrZuzzjen/basa-guardian/issues/52).
Diagnóstico de JF: «el onboarding **es** cargar modelos; urge que tenga sentido o parece amateur».
La tercera pata del paquete —**032 ingress cert modes**— es de Install & Factory y vive en
[su roadmap](../deploy/ROADMAP-factory.md).

- **033 — Engine reload sin restart manual**: wrapper-supervisor como entrypoint del motor (~50 líneas, viaja
  por el volumen) que detecta el cambio de config, valida el YAML y relanza; más `GET /models/status` y estado
  «Aplicando cambios…» en la UI, que es literalmente lo que el cliente pidió ver. **Verificado leyendo el
  código de la imagen pinneada: LiteLLM NO tiene reload sin DB**, así que «que lo haga el motor» no existe
  como opción. Su prerrequisito —escritura atómica del `config.yaml`— **ya está pago** (commit `1151b1e`).
- **034 — Rol `auditor` canónico read-only**: migración del CHECK + gates + deny explícito de chat +
  navegación reducida. El quick-win ([PR #54](https://github.com/DrZuzzjen/basa-guardian/pull/54), mergeado)
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
suscripción + identidad `X-Basa-Key`), VS Code/Copilot (auto-byok, key-in-URL, modo Ask), extensión browser MV3
(mask/unmask en ChatGPT/Claude web). Matriz de compatibilidad: Cursor=parcial (solo chat/plan, como Copilot Ask),
Gemini web=vía DOM-hook (spike), Claude Desktop=MCP tool-plane only. Research: no hay "LiteLLM del browser-DLP";
el approach de Basa es el patrón dominante — **moat: des-enmascarar en vez de bloquear** (mantiene UX). Docs de
training/soporte en `docs/integration-surfaces.md`.

### 021 — Licensing & Seat Enforcement (P2)
Enforcement de licencias **offline** para el modelo "install + N seats" (el cliente corre la caja, sin phone-home).
Research build-vs-buy: **DIY Ed25519** — no hay producto que aplique por el air-gap; `seat = Connection activa`
contada en Postgres. Licencia firmada `.lic` (tenant_id, distributor_id, pool_id, max_seats, expiry, `kid`)
verificada en 2 gates fail-closed (arranque + creación de Connection); anti-tamper vía **cadena de hashes +
export de true-up firmado** (deployment key). **Addendum 2026-07-14** (prior-art validado: GitLab/Grafana/
Directus/Replicated): tier distribuidor = **firma CENTRAL de Basa + cupo de emisión** (nunca clave delegada);
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
silenciosa). Plano passthrough fuera de alcance (coste de suscripción fijo). Spec: [PR #6](https://github.com/DrZuzzjen/basa-guardian/pull/6).

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
constitución 2.0.0→2.1.0); **X-Basa-Redact solo-restrictivo** (la superficie confiable nunca puede aflojar el
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
de otra superficie en el backend (US8). Brief de handoff en [#46](https://github.com/DrZuzzjen/basa-guardian/issues/46);
NEXT en `extension/NEXT-028.md`. **Canónica única**: `basa-guardian/extension/` (las copias divergentes se
borraron). Precedida por el hardening [#44](https://github.com/DrZuzzjen/basa-guardian/issues/44) /
[PR #45](https://github.com/DrZuzzjen/basa-guardian/pull/45), que sacó el mapa reversible token→PII del alcance
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
la UI de Logs), agrega `BASA_AUDIT_FAIL=open|closed` como config de instalación (en `closed` se rechaza
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
