# Research (Fase 0) — Spec 035: Harness de carga «El examen existe»

**Fecha**: 2026-08-07 · **Método**: 6 investigadores adversariales en paralelo (workflow
`wf_601e144b`), cada uno con verificación empírica el mismo día (builds ejecutados,
benchmarks corridos, precios consultados con fecha, file:line del repo en rama
`035-load-harness` @ 31374a8). Consolidado por la sesión ITV.
**Restricciones del owner (JF, 07-ago)**: open-source auto-hosteado en infra propia;
pagar solo con justificación; entorno de examen = instancia dedicada AWS; licencias de
test se emiten in-house; estrés observable en vivo.

---

## R1 — Generador de carga

**Decision**: **k6 OSS v1.8.0 + xk6-sse v0.1.12, con pin exacto y binario versionado**
en el módulo del harness. Build reproducible:
`docker run --rm -v "$PWD:/xk6" grafana/xk6 build v1.8.0 --with github.com/phymbert/xk6-sse@v0.1.12`
— **ejecutado y verificado el 07-ago**: compila y el módulo carga. **NO usar k6 v2.x**:
la v2.0.0 (11-may-2026) rompió el module path de extensiones y xk6-sse no migró (PRs
abiertos sin respuesta desde may-jun 2026); la línea 1.x sigue mantenida en paralelo
(v1.8.0 es POSTERIOR a v2.0.0).

**Mapeo del modelo de la spec a k6** (la pieza de diseño clave):
- Regla: N_s sesiones de la superficie s con cadencia media T_s ⇒ scenario
  `constant-arrival-rate` con `rate: N_s, timeUnit: T_s` — la ley de Little de FR-001 y
  modelo ABIERTO garantizado por diseño del executor (FR-002 literal).
- Gate 125: `chat rate:75/120s` (sin streaming — confirmado) · `ext rate:31/195s` ·
  `coding rate:13/210s` (SSE vía `sse.open()`, mide TTFT y cortes) · `admin rate:6/390s`
  (390 = media del rango `[180,600]` de la cadencia admin; el «/300s» de un borrador
  previo era un redondeo — la definición versionada del gate manda, T011).
- Identidad: pool de credenciales del seeder en `SharedArray`, afinidad por
  `iterationInTest % pool` — la sesión mantiene identidad sin cerrar el modelo.
- Evidencia de modelo abierto (edge case del instrumento): threshold
  `dropped_iterations == 0` por scenario → run inválido automático si el generador no
  sostuvo la tasa.
- Gate 250: scenario extra `login_storm rate:250/600s duration:10m` + superficies con
  `startTime` escalonado; fase separable por tag.
- Gate 500: mismos scenarios con `ramping-arrival-rate` (sostenido → ×2 → normal).
- A 500 usuarios la carga es ~3.5 llegadas/s — trivial para k6; headroom del generador
  sobrado y medible.

**Rationale**: `constant-arrival-rate` es un executor de modelo abierto de fábrica;
xk6-sse es imprescindible solo para coding (10% del guion — k6 core bufferea las
respuestas y no puede medir TTFT; SSE nativo en core: cerrado "not planned"); riesgo de
mantenimiento acotado con pin 1.x + plan B barato (vendorear la extensión, Apache-2.0).
Coste $0, un binario Go, sin fricción de adopción.

**Alternatives**: Gatling OSS (SSE first-class y llegadas `.randomized`, pero JVM +
open-core con operación empujada a Enterprise pago) · Artillery (SSE oficialmente
"experimental, not production-ready" — inaceptable en un instrumento) · wrk2/vegeta (sin
SSE ni sesiones; vegeta queda solo como cross-check puntual) · k6 Studio (autoría de
scripts, no generador).

**Open questions**: vida útil de la línea k6 1.x (sin compromiso público de Grafana);
¿vendorear xk6-sse ya o consumir upstream pineado?; re-ejecutar el build en x86_64 (la
verificación fue arm64 — recordar el showstopper de arch del piloto); llegadas uniformes
(no Poisson) — aceptado y documentado en fingerprint; duración de streams SSE del stub
parametrizada en la definición del gate (condiciona maxVUs).

**Coste**: $0 licencias; runner <$0.50 por gate en c6i.xlarge.

---

## R2 — Stub de proveedor

**Decision**: pieza propia del harness: **UN servicio Python asyncio (FastAPI/uvicorn,
1 proceso)** que habla **dos wire-protocols** — OpenAI (`/v1/chat/completions` JSON+SSE,
`/v1/embeddings`) para todo lo que sale del motor, y Anthropic (`/v1/messages` JSON+SSE,
`/v1/messages/count_tokens`, `/v1/models`) para el passthrough de suscripción — más API
de control por run (latencia/ritmo de tokens/errores programables por alias, reset,
reporte). **Detección de canarios INLINE** sobre bytes crudos (medido hoy: 151 µs p50 /
210 µs p95 por request de 5 KB con 100 canarios — <0,5% de un core a carga de gate 500)
**+ spool zstd-JSONL** de payloads para el barrido post-run (SC-004) y forense
(~20-40 MB comprimidos por gate 500; corpus 100% sintético ⇒ no viola metadata-only).
El stub corre en la instancia del GENERADOR y se auto-mide (drift de pacing + CPU; run
inválido si p99 drift >5 ms o CPU >60%).

**Cableado para que el 100% del tráfico pase por él (4 puntos, todos config — cero
parches al producto)**:
1. Perfil de cliente de examen nuevo (`deploy/clients/itv-examen/config.yaml.tmpl`,
   mismo mecanismo que camara-comercio): TODAS las entradas de `model_list` como
   `openai/<alias>` con `api_base` → stub; fallbacks solo entre aliases stub-backed.
2. Env del backend: `SENTINEL_GW_ANTHROPIC_BASE` → stub (existe solo en `gateway.py:125`,
   default api.anthropic.com; NO está en ningún compose — agregarla al overlay).
3. Provider keys VACÍAS en el secrets.env del examen — un alias mal apuntado falla
   ruidoso en vez de gastar o fugar.
4. **Egress bloqueado en el Security Group** del SUT (solo red interna): el candado que
   convierte "creemos que todo pasa por el stub" en "no puede no pasar".

**Rationale**: los puntos de egress reales son exactamente tres y todos configurables
(mecanismo de perfiles que ya se vende — FR-011 respetado); Python single-process
verificado con benchmark hoy (150 SSE concurrentes con pacing 100 tokens@30ms → lateness
p99 0,89 ms; 400 SSE → p99 1,42 ms, 31% de un core) con ≥2-3× de margen sobre el pico
previsto (~150 en vuelo); monorepo 100% Python (mantenibilidad); un proceso mantiene
contadores de canarios sin coordinación multi-worker. Trigger de reevaluación
documentado: drift p99 >5 ms en preflight AWS → 2-4 workers; Go solo si eso no alcanza.

**Alternatives**: Go (ventaja que no compra nada a esta escala; segundo lenguaje) ·
uvicorn multiworker día 1 (rompe contadores en memoria; plan B con trigger) ·
WireMock/MockServer/mocks OSS (ninguno trae SSE con pacing por token + wire Anthropic +
centinela de canarios; el centinela es propio sí o sí porque ES el SLO) ·
`mock_response` de LiteLLM (DESCARTADO: sin observador externo el SLO de canarios es
inevaluable y no cubre el passthrough).

**Open questions**: ¿el guion coding incluye el plano suscripción además de byok? (sin
él, el gap read=60s del passthrough queda sin examinar); smoke-test previo: LiteLLM
1.92.0 pinneado traduce `/v1/messages`→`openai/` con api_base custom manteniendo SSE
(comportamiento estándar, no ejercitado en el repo); vectores fake de `/v1/embeddings`
vs cache/versionado del auto-router (alternativa: gates con auto-router off fijado en la
definición); re-medir benchmark en Linux/AWS con el preflight; alias hardcodeado
`gemini-2.5-flash-lite` en `test_guardrail` si el guion admin toca ese botón;
`count_tokens` aproximado (len/4) — confirmar que ninguna coding tool depende de
precisión.

**Coste**: $0/mes; ~400-600 LOC Python + tests (1-2 días de sesión agéntica).

---

## R3 — Observabilidad y plataforma de resultados

**Decision**: topología **MIXTA «centro persistente + sonda efímera»**, 100% OSS
self-hosted, $0/mes en el caso base:
1. **Centro** (en el servidor AWS de contenedores donde ya viven Plane/Bitwarden):
   compose `harness/observability/` con **Prometheus** (`--web.enable-remote-write-receiver`,
   retención larga ~400d) + **Grafana OSS** (dashboards como código) tras el patrón
   Caddy+auth de la casa. Es el tablero EN VIVO (pedido JF) y la memoria que sobrevive a
   la instancia efímera.
2. **Sonda** (en el SUT): node_exporter + cadvisor + postgres_exporter + redis_exporter
   + Prometheus en **agent mode** con remote_write SALIENTE al centro (push ⇒ sin
   puertos entrantes en el SUT, IP nueva por run irrelevante). El mismo override fija
   rotación de logs (config de entorno, no fix de producto).
3. **k6** (runner fuera del SUT): doble canal — `-o experimental-prometheus-rw` al
   centro para el vivo + `handleSummary()` JSON como fuente del reporte. **REGLA DURA**:
   el veredicto SLO se computa del JSON de k6 + health del producto + detector del stub —
   NUNCA de Prometheus/Grafana (observabilidad caída invalida el tablero, no el examen).
4. **Logs**: sin Loki en ciclo 1 — colector por run (`docker logs --since/--until` →
   tarball comprimido en la evidencia). Loki = evolución de ciclo 2 si los tarballs
   resultan lentos.
5. **Histórico híbrido**: `harness/runs/<id>/` — reporte.md + verdict.json +
   fingerprint.json chicos y diffeables van a la evidencia versionable; lo pesado
   (tarballs, raw k6, ventana de métricas) → `/srv/itv-runs/<id>/` en el servidor
   persistente, servido read-only vía Caddy con auth.

**Grafana Cloud free: DESCARTADO con justificación** — retención 14 días mata el
histórico ago→sept (FR-013), 10k series activas es techo real durante un run, 3 usuarios
< equipo, 500 VUh/mes = UN run del gate 500; el tier Pro (~$60-120/mes para este uso)
compra lo que 3 días-agente de compose dan gratis, y saca las métricas del examen de la
infra propia — mala óptica para un producto de compliance.

**Esfuerzo ciclo 1**: full ≈ 3 días-agente; corte mínimo ≈ 1.5-2 (centro + sonda + un
dashboard vivo + colector de logs + runs/ en git). Difiere sin dolor: redis_exporter,
Loki, comparador automático, alerting.

**Open questions**: headroom real del servidor de contenedores (pedir `docker stats`/
`df -h` a JF); ¿VPC/SG compartidos centro↔SUT? (si remote_write viaja público: TLS +
basic auth obligatorio); estabilidad del flag `experimental-prometheus-rw` (pinnear k6 y
registrar en fingerprint); dashboard comunitario k6 vs propio; cardinalidad real de
series (acotar tags, sin tag por URL); tamaño real del tarball de logs (¿bajar log level
del motor en el perfil de examen?); ¿evidencia pesada navegable web o SSH alcanza en
ciclo 1?

**Coste**: $0/mes caso base; peor caso +EBS 20-50 GB ≈ $2-4/mes o t4g.small dedicada
$12-15/mes solo si el servidor actual no aguanta (verificar antes de gastar).

---

## R4 — Entorno de examen AWS

**Decision**:
1. **SUT = c6i.2xlarge** (8 vCPU Ice Lake fijos, 16 GiB, no-burstable) en
   **eu-central-1**, **tenancy compartida** (NO dedicated), corriendo
   `compose.prod.yml --profile selfhosted` (Postgres+Redis+Caddy en contenedores =
   paridad sede; NO el camino RDS/ElastiCache del root de clientes).
2. **Generador+stub = c6i.xlarge separada** (4 vCPU: 2 stub + 2 k6), misma VPC/AZ,
   tráfico por IP privada.
3. **Operativa**: crear una vez con OpenTofu, **STOP entre runs** (parado = solo EBS
   ~$10/mes), start por run ~1 min, reset `docker compose down -v && up` antes de cada
   gate oficial; destroy/recreate solo si el fingerprint delata drift irreparable.
4. **Aprovisionamiento**: **OpenTofu desde ya, root NUEVO y mínimo** (`harness/infra/` o
   `deploy/terraform/envs/itv/`) reutilizando el patrón `modules/network`; los outputs
   (instance_type, AMI, región) alimentan el fingerprint (FR-009). NO reutilizar el root
   de clientes (provisiona RDS/ElastiCache — rompería FR-011; default t3.small
   prohibido: burstable = gates no repetibles).
5. **Medir a través de Caddy** (ingress del profile selfhosted) para veredictos — Caddy
   participa en los modos de fallo que importan (buffering/timeouts SSE, handshakes de
   la tormenta de login); directo-a-backend solo como diagnóstico no-oficial.

**Rationale** (presupuesto de CPU de los cuellos verificados): backend 2 workers ≈2
cores + motor monoproceso ≈1 + NLP spaCy monoproceso ≈1 (el muro esperado) + Postgres
con hasta 60 conns del backend + Prisma ≈1-2 + Redis/Caddy/frontend ≈1 → ~6-7 vCPU en
saturación: con 8 vCPU los muros que encuentre el examen son los del producto, no un
host asfixiado. 4xlarge no mueve los muros monoproceso (cores ociosos, 2× precio) y
sobre-representa la "sede razonable" (prod actual: CPX32 4 vCPU compartidos). Dedicated
tenancy ~10× sin evidencia de necesidad (Nitro fixed-performance no tiene CPU steal;
SC-005 + fingerprint detectan varianza anómala).

**Coste** (precios eu-central-1 verificados 07-ago vía espejo de la API de AWS):
**~$1.5-2 por run de gate** · **~$50-60/mes** con cadencia del ciclo 1 (25-30 runs) ·
comparativa: par fijo 24/7 ≈ $425/mes; efímero total = mismo dinero + 15-25 min/run.

**Alternatives**: 4xlarge (solo si el gate 500 satura 8 vCPU sin tocar muro monoproceso
— un run comparativo cuesta $2) · dedicated (~10×, sin evidencia) · fijo 24/7 (drift +
7× coste) · efímero total (reservar para re-certificación) · bash sin tofu (deja el
hardware fuera de versionado — justo lo que FR-009 prohíbe) · root de clientes (rompe
paridad) · t3/flex (prohibido: burstable = no repetible).

**Open questions**: ¿la sede termina TLS en Caddy o HTTP plano en LAN? (define
INGRESS_HOST del examen; con TLS la tormenta de login paga handshakes — preguntar a JF);
specs reales de delorean/t800 para calcar la "sede razonable"; cuota de vCPU on-demand
de la cuenta en eu-central-1 (el par pide 12 — verificar ANTES del primer run);
credenciales de registry para pull de imágenes desde la VPC; disponibilidad c6i en la AZ
(sustituto directo: c7i.2xlarge).

---

## R5 — Seeder y licencia de test

**Decision**: **seeder vía API REST admin del backend + licencias in-house con
`backend/scripts/issue_license.py`** (herramienta canónica, NO destructiva, verifica
contra el keyset antes de escribir).
- **Licencias**: emitir DOS para ITV — 300 seats (paridad Cámara, gates 125/250) y 500
  (gate 500); kid ya horneado (`sentinel-dev-2026b`); montar como
  `/app/config/licenses/client.lic` + `SENTINEL_ALLOW_DEV_LICENSE=true` en el overlay de
  examen. **NUNCA** `issue_dev_license.py` sobre stack vivo (regenera el keyset —
  footgun documentado). Instalar la licencia definitiva ANTES de seedear (ampliar en
  caliente ≈5 min de 402 intermitentes).
- **Seeder** (flujo): bootstrap primer admin (`POST /users/login`) → pre-check de seats
  vía `GET /api/v1/health/license` (max_seats/seats_used — fail-fast, cumple el edge
  case) → `POST /users` con passwords reales (imprescindible para login storm y chat
  JWT) → `POST /keys` (users PRIMERO: el seat gate corre también en alta de user client)
  → `POST /budgets`. Sin endpoints bulk y no hacen falta. Idempotente por diseño de la
  API; modo verify-only entre runs.
- **Timing estimado** (no medido): 500 users ≈3-5 min (bcrypt ~250 ms + POST al motor) +
  500 keys ≈1-3 min + budgets <1 min ⇒ **5-10 min secuencial** — 3-6× de holgura en los
  30 min de SC-006. Se seedea UNA vez por despliegue; los runs siguientes verifican.
- **Presupuestos**: generosos por default (max_spend_usd=10000, sin max_budget en keys)
  para no contaminar el gate; cohorte 402 dedicada ~2% para el escenario que lo provoca.
- **Distribución de roles** (enum verificado: super_admin/tenant_admin/
  compliance_officer/client; super_admin no se siembra; admins no consumen seat):
  gate 125 = 119 client (75 chat_ui / 31 desktop / 13 base_url) + 4 tenant_admin +
  2 compliance_officer; gate 250 = 238+8+4; gate 500 = 475 (300/125/50) + 17 + 8 —
  475 seats ≤ 500 con headroom. El lector de SLO usa una cuenta compliance_officer del
  seed.

**Rationale**: la API es el camino real del producto (el seed ES el primer mini-examen
del plano admin); SQL directo deja users sin password ni engine_user_id (422 en keys
posteriores, paneles rotos, sin login storm); el pre-check que la spec pide ya existe
como endpoint; la aritmética hace innecesario cualquier atajo.

**Alternatives**: `apply_profile_seed.py`/SQL (fallback solo-keys; sin login) ·
CLI sentinel-admin 026 (no implementada — no crear dependencia; migrar la emisión cuando
exista) · UI/Playwright (lento y frágil; descartado).

**Open questions**: **custodia de la privada de `sentinel-dev-2026b`** — license_out/ está
gitignored y NO existe en este worktree: confirmar con JF que la tiene (si se perdió:
kid nuevo = rebuild de imagen); medir latencia real de /user/new y /key/generate en el
primer run del seeder; tool_type canónico de la extensión (¿chatgpt/copilot/
claude-desktop?) — copiar la distribución real de la Cámara; mapping client_type
propuesto (extensión=desktop) a validar; ¿el fingerprint incluye lic_id/max_seats?
(propuesta: sí); orden bootstrap-admin en el deploy del examen; gates parten de stack
caliente post-seed (declarado en la definición del gate; el frío lo modela la tormenta
del 250).

**Coste**: $0 — scripts del repo + seeder propio.

---

## R6 — Estructura del módulo y operativa

**Decision**: **módulo raíz `harness/`** (confirma #95; regla de la casa):

```text
harness/
  README.md            # doc canónica: qué es, frontera «mide, no parchea», cómo correr un gate
  gates/               # FR-006: definiciones VERSIONADAS como data (gate-125.yaml, -250, -500)
                       #   con version:, población, duración, fases, mezcla, densidades PII,
                       #   config exigida al stack (masking por scope) y tolerancia SC-005
  corpus/templates/    # plantillas es-ES por superficie (data); canarios NO se commitean (runtime)
  scenarios/           # guiones k6: chat.js, extension.js, coding-sse.js, admin.js + mezcla
  src/                 # Python: stub/ · seeder/ (+populations/*.yaml) · corpus/ (generador
                       #   determinista por semilla) · reporting/ (evaluador SLO, fingerprint,
                       #   comparador) · observe/ (colector out-of-band)
  tests/               # pytest DEL instrumento: unit/ + contract/ (espejo de backend/tests)
  runs/                # SOLO scratch local, .gitignore — evidencia persistida va a la plataforma R3
```

- **CODEOWNERS**: sin precedente de "equipo" (solo handles; @org/team imposible en
  cuenta personal) → sección propia `harness/ @DrZuzzjen` con comentario del team.
  Recomendado: **ADR corto `docs/adr/0002-harness-modulo-monorepo.md`** (CONTRIBUTING
  pide ADR para decisiones estructurales).
- **Corpus**: se genera de cero (NO existe corpus reutilizable en el repo — verificado),
  pero anclado a los reconocedores REALES del producto como espec y oráculo de tests:
  `sentinel_guardian_policy.py` STRUCTURED_ID_PATTERNS + BY_REGION["ES"], built-ins Presidio
  ES_NIF/ES_NIE con checksum, `presidio-analyzer/conf/es.yaml` (nombres españoles
  verosímiles detectables por NER). Un corpus que el NLP no detectaría produciría falsos
  «0 fugas». Candidatos: Faker es_ES + python-stdnum (verificar en plan).
- **Frontera de tests** (DevFlow §3): *pytest prueba el instrumento con datos
  sintéticos; los runs prueban el producto; SC-004 cruza (se ejecuta como run, es DoD
  del instrumento)*. En pytest: evaluador SLO (nulo→FAIL, contador retrocede→inválido,
  reconciliación mismatch), detector de canarios (incl. canario PARTIDO entre chunks
  SSE), generador de corpus (determinismo, densidades, unicidad, matchea las regex del
  producto), fingerprint/comparador, precheck del seeder, contract tests del stub
  in-process. Corriendo: SC-004, headroom/modelo abierto, SC-005, SC-006, smoke US5.
  CI: job `harness-tests` (pytest sin stack) junto a los de #93.
- **Las 3 documentaciones**: docs/ producto NO (economía interna — FR-007 de la 025) ·
  docs-cliente NO · interna SÍ (harness/README.md canónico + línea en README raíz +
  TechTree cuando haya números medidos; AGENTS.md cuando el comando entre al gate común).

**Alternatives**: repo propio (viola CONTRIBUTING; desincroniza contra el stack) ·
backend/tests/load/ o deploy/ (contamina suite por-PR / territorio Falime) · layout
plano sin src/ (rompe precedente backend) · dataset PII externo (sin canarios únicos ni
densidades; riesgo de PII real residual — constitución exige 100% sintético).

**Open questions**: confirmar Faker es_ES + python-stdnum (cobertura y licencias); ¿ADR
0002 obligatorio o basta #95+spec? (decisión JF — recomendación: escribirlo, es 1
página); ¿reportes de gates oficiales commiteados al repo o solo plataforma R3?
(fallback si la plataforma tarda: `harness/runs-official/` temporal); ¿job harness-tests
en el PR del scaffold o diferido? (toca ci.yml recién mergeado); nombre `harness/` vs
`itv/` (mantengo la propuesta literal del #95; decisión estética de JF); CODEOWNERS es
documental hasta que haya branch protection (plan free).

**Coste**: $0.

---

## Resumen ejecutivo de costes

| Pieza | Coste |
|---|---|
| Software (k6, xk6-sse, Prometheus, Grafana, stub, seeder) | $0 — todo OSS/DIY self-hosted |
| API de los gates | $0 por diseño (stub; FR-012/SC-003) |
| Par de instancias AWS (SUT c6i.2xlarge + generador c6i.xlarge, stop/start) | ~$1.5-2/run · ~$50-60/mes ciclo 1 |
| Observabilidad | $0 caso base (servidor propio); peor caso $2-15/mes |
| Smoke US5 (OpenRouter) | presupuesto explícito por run, techo duro (por definir en la definición del smoke) |

**Total estimado del ciclo 1: ~$50-60 USD + smoke acotado.** Sin servicios SaaS pagos.

---

## Addendum 08-ago — coordinación con el core (post-research)

- **PR #97 (a mergear) cambia el perfil que medimos**: la evidencia de R2 «el plano
  gateway enmascara con regex, no con NLP» describe el mundo VIEJO. Post-#97, `/gw`
  llama al sidecar en cada request (~50-200 ms + timeout 2 s fail-closed default,
  `nlp_fail_mode` gobernable `block|degrade`, bloque `nlp` en el health). Consecuencia
  de diseño: casi todo el tráfico del gate pasa a tocar el sidecar spaCy monoproceso
  (chat ya lo hacía; ext y coding se suman) — el muro nº 1 del dossier del 04-ago se
  ejercita de lleno. La definición del gate fija `nlp_fail_mode`, exige imagen con #97,
  y la sonda/evaluador leen el bloque `nlp`. (Absorbido en spec y contrato de gate.)
- **Corpus compartido (#107, decidido con JF 08-ago)**: el corpus de la 035 sube a
  artefacto del departamento — dataset etiquetado versionado (spans por entidad) +
  generador determinista; consumidores: harness (mezclas/canarios runtime-only) y gate
  de calidad de detección del core (precision/recall por entidad contra la imagen real
  de sentinel-nlp). Semilla: regresiones del #63. Refuerza R6 (generador ya anclado a los
  reconocedores reales como oráculo).
- **Radar**: PR #99 (carrera multiprocessing → 422 espurios en altas concurrentes de
  entidades) y #106 (DoS de threadpool del guard ReDoS) — restricciones de guion
  registradas como edge case en la spec.

## Addendum 08-ago (tarde) — provider swap AWS → Hetzner Cloud (aprobado por JF vía DevOps)

- **Motivo**: recon real de la sesión DevOps — la única cuenta AWS accesible
  (530084040072) hospeda producción legal de un cliente (Amplify + DynamoDB con leads
  reales); `tofu apply` con admin ahí = radio de explosión inaceptable; no hay segunda
  cuenta. Además el VPS compartido NO tiene headroom para el centro de observabilidad
  (3,2 GB libres, disco al 55% con los Postgres de Plane/Twenty).
- **Reemplazo (equivalente o mejor)**: project Hetzner dedicado `guardian-itv`
  (aislamiento por token scopeado — el token no ve el project del VPS de prod). SUT
  **CCX33** (8 vCPU DEDICADAS/32 GB) + generador **CCX23** (4/16): las vCPU dedicadas
  eliminan de raíz la varianza por vecinos que R4 mitigaba con Nitro compartido —
  MEJOR para SC-005. Firewall cloud con deny de egress (el candado del stub se
  mantiene). Par ~0,15 €/h → 10-15 €/mes.
- **Observabilidad**: NO va al VPS compartido; va a una **CPX21 fija** (~8 €/mes) en el
  mismo project y red privada → remote_write local sin cruzar internet (mejora sobre
  R3, que asumía cross-cloud con TLS+auth). UI de Grafana pública con auth: a definir
  semana del 11 (reverse proxy del VPS o Caddy en la propia caja).
- **Registry (open question de R4): resuelta con opción (b)** — `docker save/load` +
  scp: sin registry para el ciclo 1, encaja con la caja sin egress y con el patrón
  air-gap de la casa (la Cámara se entregó igual). Orden de provisión: precargar
  imágenes desde la caja de carga ANTES de cerrar el firewall.
- **Qué se mantiene de R4**: dimensionamiento (8 vCPU SUT / 4 generador), cajas
  separadas, medir a través de Caddy, stop entre runs, OpenTofu (solo cambia el
  provider a `hcloud`: server_type ccx33/ccx23, hcloud_firewall, red privada 10.x),
  fingerprint con server_type/datacenter. Nota de honestidad: CCX33 trae 32 GB (el
  doble del diseño c6i) — RAM no era la dimensión que ata (16 «sobraban»); queda
  registrado en fingerprint.
- **Validación ITV del supuesto AWS/c6i (pedida por DevOps antes del lunes 11): NO era
  duro.** El requisito real de la spec es CPU fija dedicada x86_64 + hardware
  registrado en fingerprint + jamás el VPS de prod — CCX lo cumple mejor. Confirmado a
  DevOps por el canal cross-session el 08-ago. Coste total real: 15-25 €/mes.

## Addendum 12-ago — métricas nativas del stack y benchmarks publicados (research post-examen, pedido JF)

Pregunta de JF tras el examen: «¿reinventamos métricas que las librerías ya traen?
¿Hay rangos publicados que nos ahorren escalar 125/250/500?». Research verificado
contra el código de cada tag y fuentes primarias; consolidado operativo en #168.

- **LiteLLM 1.92.0 (la del motor) trae Prometheus `/metrics` completo y es 100% OSS
  en nuestra versión — lo tenemos apagado por config, no por licencia.** Por request:
  latencia total, latencia del proveedor, **overhead del proxy separado**, TTFT,
  tokens in/out, spend por key/team, presupuesto restante. Historia verificada tag
  por tag: enterprise-gated de sept-2024 (discussion BerriAI#5163) a nov-2025; desde
  ~v1.80.5 sin gate premium (confirmado en 1.92.0: métricas incondicionales,
  `_mount_metrics_endpoint()` sin check). **Decisión para el gate 250**: encender
  `prometheus` en callbacks del perfil `deploy/clients/itv-examen` + scrape job en la
  sonda existente. ⚠️ `/metrics` va SIN auth por default y las labels llevan key
  aliases (BerriAI#24530): scrape solo por red privada y/o `PrometheusAuthMiddleware`
  (existe en 1.92.0). **Refina R3 sin cambiar su regla: el veredicto sigue saliendo
  SOLO de k6 + producto + stub — `/metrics` del motor es observabilidad, jamás fuente
  del veredicto.**
- **El backend no tiene ningún middleware de métricas** (solo CORS en `main.py`): la
  latencia server-side por endpoint no la mide nadie. `prometheus-fastapi-instrumentator`
  son ~3 líneas, pero es decisión de producto → recomendación al core en #168
  (frontera: mide, no parchea).
- **Benchmarks publicados como cota, no como sustituto** (gates: 125 ≈ 6-10 req/s
  pico; 500 ≈ 24-40): LiteLLM publica ~293 RPS/instancia en 4 vCPU/8 GB con overhead
  2 ms mediana (docs.litellm.ai/docs/benchmarks) = 7-12× nuestro gate 500 con una
  instancia; FastAPI está a órdenes de magnitud (TechEmpower R22). **Presidio NO
  bracketea**: ~10-25 ms/análisis publicados (microsoft/presidio discussion #1097;
  spaCy ~10k palabras/s CPU) con spaCy MONOPROCESO (nuestro Dockerfile no pasa
  `--workers`) → techo efectivo ~15-40 req/s de chat = exactamente la zona del gate
  500. Consecuencia de diseño: **los gates 250/500 se justifican por el sidecar NLP +
  las escrituras durables de auditoría, no por el plumbing HTTP** — coincide con el
  candidato nº 1 que el core señaló el 08-ago. El bracketing publicado entra a los
  reportes como CONTEXTO; el número oficial sigue siendo el del gate.
- **Ninguna librería del stack cubre los 4 SLOs de oro** (paridad de auditoría,
  canarios PII crudos, bloqueos durables): confirmado — ahí el harness no reinventa,
  inventa lo único que nadie más mide. Valida el diseño R3.
- **Pregunta abierta de validez (prioridad ciclo 250)**: el camino instantáneo de chat
  — en el gate oficial Y el drill, chat volvió en ~88 ms con 800 ms programados en el
  stub mientras coding pagó su piso de 600 ms en los mismos runs; la rampa sí lo pagó
  (901/977 ms = firma piso+producto). Hasta reproducirlo en local (compose + 10
  requests, sin infra), la pata de chat de `zero_raw_canaries` del PASS lleva
  asterisco (atenuante: la rampa atravesó el stub con canarios y dio 0 fugas).
  Triangulación completa con tabla en #168.
