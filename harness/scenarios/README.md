# Escenarios k6 del harness ITV (spec 035)

Guiones de carga de **modelo ABIERTO** (research R1). Generan la carga; **no** deciden
PASS/FAIL — el veredicto lo computa el evaluador Python del summary de k6 + el `/health`
del producto + el `/control/report` del stub (NUNCA de la observabilidad, regla R3).

## Piezas

| Archivo | Superficie | Ruta real del backend | Auth |
|---|---|---|---|
| `chat.js` | chat | `POST /api/v1/chat/completions` (JSON, sin streaming) | JWT |
| `extension.js` | extensión | `GET /gw/whoami` + `POST /gw/inspect` | `X-Sentinel-Key` |
| `coding-sse.js` | coding (SSE) | `POST /gw/v1/messages` (stream) — mide TTFT y cortes | `X-Sentinel-Key` |
| `admin.js` | admin | GETs de paneles (`/users`,`/keys`,`/budgets`,`/audit-logs`,`/health`) | JWT |
| `login_storm.js` | login | `POST /users/login` (tormenta del gate 250) | — |
| `common.js` | — | pool (`SharedArray`), corpus, métricas, `handleSummary` | — |
| `gate.js` | **principal** | arma `options.scenarios` desde `GATE_CONFIG` | — |

Cada `(superficie, fase)` es un `constant-arrival-rate` con `rate=N_s` sobre
`timeUnit=cadencia_media` (el math sale de `surface_arrival_rates` en Python). El threshold
`dropped_iterations==0` (global + por scenario) es la evidencia dura de modelo abierto: si
k6 no sostuvo la tasa, el run es inválido.

## Construir el binario (k6 v1.8.0 + xk6-sse v0.1.12, PINEADOS, x86_64)

```bash
./scripts/build-k6.sh                 # → harness/bin/k6 (+ k6.sha256 para el fingerprint)
# o con imagen:
docker build -f Dockerfile.k6 --platform linux/amd64 -t sentinel-harness-k6 .
```

⚠️ **NO k6 v2.x**: rompió el module path de extensiones y xk6-sse no migró (R1).

## Correr (normalmente lo invoca el orquestador)

El orquestador (`python -m sentinel_harness.orchestrator --gate 125 ...`) escribe
`runs/<id>/{k6_config.json,pool.json,corpus.json}` y lanza:

```bash
bin/k6 run \
  --env GATE_CONFIG="$(cat runs/<id>/k6_config.json)" \
  --env POOL_FILE=runs/<id>/pool.json \
  --env CORPUS_FILE=runs/<id>/corpus.json \
  --env SUMMARY_FILE=runs/<id>/summary.json \
  scenarios/gate.js
```

## Contrato del pool (`pool.json`)

Lista de identidades del seeder. Cada entrada:
`{username, password, role, client_type, tool_type, sentinel_key}`.

- chat/admin/login usan `username`+`password` → login → JWT (cacheado por VU).
- **extensión/coding necesitan `sentinel_key`** (la Connection del seat). El emit actual del
  seeder (`--emit-credentials`) NO incluye la key todavía — es un pendiente: augmentar el
  seeder para capturar el valor de `POST /keys` en el pool. Sin `sentinel_key`, esas superficies
  cuentan un `harness_errors` y se saltan.
