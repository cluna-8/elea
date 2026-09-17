# Handoff — avances de Elea (spec 050) para llevar a Sentinel

**Fecha**: 14-sep-2026. **Origen**: `github.com/cluna-8/elea`, rama `050-ia-hub-conector-motores`
(4 commits sobre `main` = `00df810`, merge del PR #2 de la 044). **Destino**: `cluna-8/sentinel`
(producto base, "Guardian"). **Instalador**: `cluna-8/elea-installer`, rama
`043-044-contrato-alignment` (3 commits sobre `605bfc7`).

Regla de marca al portar: en Sentinel el cliente se llama "Guardian Hub" (default neutro del
código); "Eleia Hub" / "Eleia Guardian" son solo la marca de Elea, fijada por env
(`HUB_BRAND_*`) en el instalador. Nada de "Elea" queda hardcodeado en el código.

---

## 1. Qué se hizo, en una tabla

| Pieza | Dónde | Estado |
|---|---|---|
| Spec 050: Guardian = firewall + usuarios; Hub = conector; motores aparte. Tres partes (qué hace Guardian, qué hace el Hub, cómo se conectan) + 3 contratos + CHANGELOG | `specs/050-ia-hub-conector-motores/` | Implementada |
| Hub sin enmascarado propio; `/api/features`; `/api/tabular/*`; presentaciones, encadenado, artefactos, plantillas (proxy admin), diccionario de datos | `client/` | 37 tests |
| Motor de planillas propio (FastAPI + DuckDB) que reemplaza a DB-GPT | `tabular/` (nuevo) | 74 tests |
| Presenton como motor de presentaciones (compose, red interna, llave `svc.presenton`) | `docker-compose.yml`, instalador | probado en vivo |
| Guardian backend: retiro de DB-GPT; `kind` al crear/leer espacios (FR-041) | `backend/src/api/workspaces.py`, `schemas/workspace.py`, `api/__init__.py` | 5 tests |
| Guardian firewall: **restitución de placeholders en streaming de la API OpenAI** (bug real) + escape JSON + `SENTINEL_NLP_TIMEOUT_S` | `litellm/extensions/sentinel_guardian_policy.py`, `sentinel_guardrail.py` | 30 tests nuevos |
| Instalador: cuentas `svc.tabular`/`svc.presenton`, motores en compose, puerto 8097, timeout NLP, ruta de actualización (revoca y reemite llaves `svc.*`) | `elea-installer/` | probado desde cero y como actualización (14-sep) |
| Imágenes | `ghcr.io/cluna-8/elea-*` (6), tags `latest` y `2026-09-14`, publicadas con `deploy/release/publish-elea.sh` (el backend distribuible sale de `backend/Dockerfile.standalone`, no del de dev) | publicadas |

Pruebas de cierre: integral local 12/12 (documento real, chat `auto`, planilla real, presentación,
encadenado, descarga), multiusuario 17/17, planillas reales de Elea (ventas, forecast, stock) y de
CDCV (5 hojas con título arriba) contra la verdad calculada con pandas.

---

## 2. Qué es portable a Sentinel tal cual (cherry-pick)

Commits en `cluna-8/elea`, en orden:

| Commit | Contenido | Portable |
|---|---|---|
| `f8118e7` | Firewall: streaming OpenAI + escape JSON (+ tests) | **Sí, primero.** Bug del producto base; afecta a cualquier cliente con `stream: true` |
| `904dd37` | Spec 050 completa: Hub, tabular, Presenton, backend (FR-040/041), compose, docs | Sí, con dos cuidados (abajo) |
| `3f09485` | Plantillas vía proxy admin, `SENTINEL_NLP_TIMEOUT_S`, mejoras tabular | Sí |
| `fc1b311` | Diccionario de datos (FR-027) + documentación | Sí |

Cuidados al portar `904dd37`:
1. `backend/src/api/exact_analysis.py` y `services/exact_analysis_service.py` se **borran**: solo
   existen si Sentinel ya había recibido la spec 048 (DB-GPT). Si no, el diff de borrado no aplica.
2. `client/` de Sentinel puede diferir del de Elea si allá no se aplicaron las specs 042/043/044
   (rediseño, espacios con miembros, presupuesto autoservicio). Verificar antes que `main` de
   Sentinel tenga la 044 (`git log --grep 044`); si no, portar primero esas.

Estado de `cluna-8/sentinel` al 14-sep: rama por defecto `026-cli-operador-basa`, último push
10-sep, 65 ramas; no consta que tenga las specs 042/043/044 del Hub. Confirmarlo antes de portar
`client/` (ver cuidado 2).

Alternativa sin cherry-pick: `git diff 00df810..fc1b311 -- litellm/ backend/ tabular/ client/ docker-compose.yml .env.example docs/ specs/050-ia-hub-conector-motores` y aplicar por área.

---

## 3. Qué NO portar / qué es específico de Elea

- Cuentas y llaves creadas en el Guardian local de desarrollo (`svc.tabular`, `svc.presenton`,
  `bruno`, contraseñas de demo). Cada instalación las crea con su `install.sh`.
- `HUB_BRAND_*` con "Eleia" en `elea-installer/docker-compose.yml`.
- Los espacios y planillas de prueba (`Elea ventas y forecast 2025`, `Elea stock`, `CDCV`).
- La plantilla corporativa "HUB Elea" creada en Presenton (vive en el volumen `presenton_data`).
- El modelo por defecto `azure-gpt-5.4-mini` es una elección medida con datos de Elea; en
  Sentinel se configura por env (`TABULAR_MODEL`, `PRESENTON_MODEL`).

---

## 4. Decisiones de diseño que Sentinel debe conocer

1. **Guardian no recibe archivos.** Los archivos crudos viven en los motores (dentro del servidor
   del cliente); la PII se enmascara solo cuando el motor manda el prompt por `engine:4000/v1`.
   Consecuencia: `POST /gw/inspect` y `svc.rag-masking` quedaron sin consumidor (no se borraron).
2. **El Hub usa la API de Guardian** (login, budget, modelos, `/chat/completions`, registro de
   espacios/hilos). No arranca sin Guardian. Hereda el SSO cuando llegue.
3. **Cada motor = contenedor sin puertos, red interna, llave `svc.*` propia, nunca la maestra.**
   El Hub verifica membresía contra Guardian antes de tocar un motor; el motor confía en el Hub.
4. **Límites conocidos de Guardian, documentados en la spec (Parte A.3)**: `/v1/embeddings` no pasa
   por el guardrail; el engine no entiende `model: "auto"` (solo el backend); el gasto de los
   motores cae en la cuenta `svc.*` porque la fila de éxito del engine no guarda
   `acted_for_user_id`; el presupuesto que corta es el del dueño de la llave.
5. **Falsos positivos del NLP** ("OTC", "FASON" tomados por nombres de persona) no rompen nada
   desde el fix de streaming, pero muestran que conviene una allow-list de términos de negocio
   por tenant (config de entidades de Guardian, fuera de esta spec).

---

## 5. Cómo verificar después de portar

```bash
# firewall
cd backend && .venv/bin/python -m pytest -q tests/unit/test_unmask_openai_stream_050.py tests/unit/test_unmask_shapes.py
# backend (necesita Postgres del compose; ver tests/migration_harness.py)
POSTGRES_USER=... POSTGRES_PASSWORD=... .venv/bin/python -m pytest -q tests/integration/test_workspaces_api_043.py
# hub
cd client && npm test
# tabular
cd tabular && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest && .venv/bin/python -m pytest -q
# stack
docker compose --profile rag --profile tabular --profile presentations up -d --build
```

En vivo: con la llave `svc.presenton` (o cualquiera) contra `engine:4000`, una petición con
`stream: true` que contenga un nombre debe volver con el nombre real, no con `[PERSON_0_xxxx]`.

---

## 6. Pendientes que quedan abiertos (para el roadmap de Sentinel)

- Sincronizar `elea-installer` a Azure DevOps y actualizar el servidor de Elea (el instalador ya
  está probado desde cero y como actualización; ver CHANGELOG 14-sep).
- ~~Atribución de gasto por persona en el engine (`acted_for_user_id` en la fila de éxito).~~
  **Cerrado en Elea el 17-sep** (más un precio de respaldo desalineado que se encontró de paso,
  sobrefacturaba hasta 6.7x) — ver
  [`../053-integridad-costos-restriccion-tabular/HANDOFF-elea-a-sentinel.md`](../053-integridad-costos-restriccion-tabular/HANDOFF-elea-a-sentinel.md)
  para el handoff específico de ese fix.
- Allow-list de términos de negocio por tenant en el NLP.
- Spec 049 (motor de documentos docx/xlsx/pdf, "motor 4") y spec 047 (formato de respuesta,
  presupuesto por rol).
- Visibilidad de las imágenes en `ghcr.io/cluna-8`: hoy mezclada (backend y rag-client públicas;
  engine y tabular privadas).
