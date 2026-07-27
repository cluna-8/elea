# Implementation Plan: Productización de la extensión de navegador (028)

**Branch**: `028-extension-productizacion` | **Date**: 2026-07-24 | **Spec**: [spec.md](./spec.md)

**Input**: [spec.md](./spec.md) + [research.md](./research.md) (verificaciones contra `dev-fran`) + issue #46 (brief).

## Summary

Productizar la extensión MV3 (superficie navegador: Claude + ChatGPT) para el primer piloto real (Cámara de Comercio, install del martes 28-jul). Lo nuevo es: (1) empaquetado white-label por partner desde el brand-pack, (2) conexión agnóstica configurada por el usuario (URL + key) que funciona de verdad vía `optional_host_permissions`, (3) honestidad de protección ("detección por patrones"), (4) mostrar el motivo real de un bloqueo de gobernanza, (5) sesión que distingue sin-red de sin-permiso, y (6) que el zip viaje en el bundle de install. El grueso del lado servidor de bloqueos ya lo trajo la 027 (ver research D2); la 028 es mayormente extensión + dos añadidos server chicos.

## Technical Context

**Language/Version**: JavaScript (extensión MV3, sin build step — archivos planos) · Python 3.12 (backend FastAPI) · Bash (scripts de release).
**Primary Dependencies**: Chrome/Chromium MV3 (`chrome.storage.local`, `chrome.permissions`, `chrome.alarms`, service worker) · FastAPI (backend) · el brand-pack de deploy (`deploy/clients/<slug>/brand.json`).
**Storage**: `chrome.storage.local` (key + gateway + estado de sesión) — sin keychain en MV3. Backend: Postgres (solo lectura de `api_keys.expires_at` para US8a). Sin migración nueva en el alcance del piloto.
**Testing**: pytest (backend: whoami proteccion, filtro expires_at) · bash de release (gate white-label, bundle) · verificación viva en Chrome cargando el paquete (US1/US2/US4/US5/US6 se prueban end-to-end contra un gateway real).
**Target Platform**: Chrome/Edge (MV3) en el navegador del usuario · backend en el compose selfhosted del cliente.
**Project Type**: Web (extensión de navegador + backend existente + scripts de deploy).
**Constraints**: HTTPS obligatorio para gateway remoto (credencial por usuario) · fail-closed ante fallo del gateway o falta de permiso · white-label: cero marca del fabricante en el paquete del partner · sin re-inyectar ni persistir la key antes de validar (hardening #45, no regresar).
**Scale/Scope**: piloto de ~25 plazas, 1 partner (Cámara). Gemini y superficie canónica: fuera (fast-follow).

## Constitution Check

*GATE: pasa antes de Fase 0; re-check tras Fase 1.*

- **Principio VII (white-label):** US2/US3/US7 lo refuerzan (paquete sin marca del fabricante, gate que lo verifica). El nombre publicado de la extensión es el del partner (`cc-guardian` para Cámara). ✅
- **C1 (auditoría metadata-only) / honestidad-por-plano:** US4/US5 respetan el catálogo cerrado de motivos, sin texto inspeccionado ni nombres de motor (reusan `governance_status` y el `_MOTIVO_POR_CAPA` de inspect.py). ✅
- **Principio I (masking-first):** la extensión conserva el enmascarado reversible en el DOM; el hardening #45 (no fugar el mapa token→PII) se preserva, no se regresa. ✅
- **Fail-closed:** conexión sin permiso de host, gateway caído, o key inválida/vencida → bloquear, nunca dejar pasar en claro. ✅
- Sin violaciones que requieran Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/028-extension-productizacion/
├── spec.md
├── research.md          # verificaciones contra dev-fran
├── plan.md              # este archivo
├── data-model.md        # entidades: brand-pack, paquete, proteccion, conexión
├── quickstart.md        # armar el zip del partner + probar conexión
├── contracts/
│   └── whoami-proteccion.md   # shape del bloque proteccion (US4); US5 referencia el contrato 027
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
extension/                          # canónica única (superficie navegador)
├── manifest.json                   # optional_host_permissions (US2); key para ID estable (US1)
├── background.js                   # SW: request de permiso de host, revalidación (US2/US6), dueño de sesión
├── bridge.js                       # relay MAIN↔SW (no tocar el hardening #45)
├── basa-guard.js                   # MAIN: parsear blocked/motivo (US5), chip proteccion (US4)
├── popup.html / popup.js           # inputs URL+key, estados de sesión (US2/US6), chip (US4)
└── config.js                       # default de URL editable (no fija)

backend/src/api/inspect.py          # whoami: + bloque `proteccion` (US4); gw_inspect ya bloquea (027)
backend/src/api/gateway.py          # _resolve_attribution: + filtro expires_at (US8a)
backend/src/services/governance_status.py  # fuente del copy (_PISO_SIGUE) para US4 — solo lectura

deploy/release/
├── render_extension_brand.sh       # NUEVO: brand-pack → extension-<slug>.zip (solo marca)
├── bundle.sh                       # + el zip de la extensión al images/MANIFEST (US1)
└── checks/
    ├── test_extension_whitelabel.sh   # NUEVO: gate white-label del zip (US7)
    └── prohibited_names.txt           # + lista de marca del fabricante (US7)

deploy/clients/camara-comercio/brand.json   # marca cc-guardian para el render
```

**Structure Decision**: Web con tres zonas — extensión (JS plano MV3), backend (FastAPI, dos añadidos chicos) y scripts de release (bash). El grueso vive en `extension/`. No hay build step de la extensión: archivos planos + un render que sustituye marca.

## Fases de implementación (orden por prioridad del spec)

**Fase A — Entregable (US1+US3): render por partner + bundle + gate.**
`render_extension_brand.sh` (deriva marca del brand-pack, genera `manifest.key`, produce `extension-<slug>.zip`) → `bundle.sh` lo incluye con sha256 → `test_extension_whitelabel.sh` + `prohibited_names.txt` con marca del fabricante → `brand.json` de Cámara (cc-guardian). Es lo que instalás; va primero.

**Fase B — Conexión (US2): que la URL editable funcione de verdad.**
`optional_host_permissions` en el manifest + `chrome.permissions.request({origins})` en el gesto Conectar (SW) + validación https (remoto) + default editable en `config.js` + mensaje claro si se deniega el permiso. Sin esto nada conecta al gateway real.

**Fase C — Honestidad y bloqueos (US4+US5).**
US4 server: bloque `proteccion` en `whoami` (regla plano gateway ⇒ "patrones", copy de `_PISO_SIGUE`). US4 ext: chip ámbar. US5 ext: parsear `blocked`/`blocked_by_layer`/`motivo` y mostrar el `motivo` del server (server ya hecho por 027). Fallback conservador si el server no informa protección.

**Fase D — Sesión (US6) + endurecimiento (US8a).**
US6: tres estados (conectado/no-verificado/desconectado), 401≠403, `chrome.alarms` cada ~30min + `onStartup`, un solo dueño del estado (SW; el popup deja de escribir `basa_connected`). US8a: filtro `expires_at` en `_resolve_attribution` (error indistinguible).

**Verificación:** backend con pytest (whoami proteccion, expires_at) · release con los checks (whitelabel, bundle) · extensión cargada en Chrome contra un gateway real (el ensayo `camara-ensayo`): conectar con permiso, enmascarar, ver chip ámbar, ver motivo de un bloqueo, revocar plaza y ver la desconexión.

## Complexity Tracking

Sin violaciones de constitución. N/A.
