# Technical Plan: Cliente RAG de Elea

**Depende de**: spec.md de esta carpeta, spec 039 (white-label).

## 1. Servicios y memoria — qué corre para qué

La máquina de desarrollo no soporta el stack completo sostenido. Perfiles de
`docker-compose.yml` propuestos (`elea` + este cliente + AnythingLLM):

| Perfil | Servicios | Para qué | RAM aprox. |
|---|---|---|---|
| `core` (default) | `db`, `redis`, `nlp-analyzer`, `engine`, `backend` | Trabajar login/presupuesto/selector (US1, US2, US5) sin frontend admin ni RAG | ~2-3 GB |
| `rag` | + `anythingllm`, `client` | Sumar cuando se prueba US3/US4 (workspace + enmascarado de ingesta) | +~1.5 GB (AnythingLLM con modelo de embeddings local puede pesar más si no usa embeddings del motor) |
| `full` | + `frontend` | Solo para verificar algo en el panel admin de `elea` | +~0.3 GB |

Regla de trabajo: **apagar `frontend` y `nlp-analyzer` cuando no se están usando** (`docker
compose stop frontend nlp-analyzer`) en vez de mantener los 8 contenedores arriba toda la
sesión. `nlp-analyzer` (spaCy es_core_news_md) es el más pesado en RAM del núcleo — solo
hace falta prendido cuando se prueba US4 (enmascarado) o cualquier chat con contenido real.

## 2. Arquitectura del enmascarado (decisión US4)

**Elegida: opción (a) — enmascarar en el cliente antes de subir a AnythingLLM.**
Razón: la opción (b) (aceptar el riesgo) no es aceptable para un piloto farmacéutico con
datos de calidad/auditoría; y `elea` ya expone el servicio de análisis reutilizable
(`backend/src/services/presidio_service.py::analyze_text_http` /
`mask_text`) — no hay que reimplementar NER, solo llamarlo desde el cliente Node antes del
`POST /api/v1/document/upload` a AnythingLLM.

Flujo de subida de documento:
```
Cliente sube archivo → extract_text.py (ya existe) → texto plano
  → POST {ELEA_BACKEND_URL}/... enmascarar (nuevo uso del servicio existente,
    expuesto vía un endpoint delgado si no hay uno público hoy — confirmar en T001)
  → texto enmascarado → POST AnythingLLM /api/v1/document/upload
  → AnythingLLM embebe SOLO el texto con placeholders, nunca el original
```

El des-enmascarado en la respuesta del chat sigue el mismo patrón que ya usa `elea` en el
plano chat (`GuardianService`/`unmask_text`) — se aplica sobre la respuesta del workspace
antes de mostrarla.

**Confirmar en T001**: si `presidio_service.py` expone hoy un endpoint HTTP público
reutilizable por un cliente externo, o si hace falta agregar uno delgado (`POST
/api/v1/mask` scopeado a la key del cliente RAG) — no asumir, se verifica contra el código
antes de codear.

## 3. Contrato del cliente hacia `elea`

Reemplaza toda la simulación de `server.js`:

| Función actual (simulada) | Reemplazo real |
|---|---|
| `POST /api/auth/login` (sin password) | Proxy a `POST {ELEA_BACKEND_URL}/users/login`, guarda JWT en sesión de proceso |
| Selector de modelo hardcodeado | `GET` catálogo real (confirmar endpoint: `router_config.py` expone el auto-router; el catálogo de modelos vivos puede necesitar `GET /api/v1/models` — confirmar en T001 si existe o hay que agregarlo) |
| `usedUsd` en memoria | `GET` presupuesto real del usuario — **no existe endpoint de autoservicio hoy** (`/{user_id}/spend` es solo admin/compliance_officer). Dos caminos: (a) agregar `GET /users/me/spend` al backend compartido (cambio al repo core, spec aparte), o (b) el cliente Node usa una credencial de servicio propia (no la del usuario) para consultar `/{user_id}/spend` en su nombre, nunca expuesta al navegador. **Elegido para el piloto: (b)**, documentar como deuda a resolver con (a) después. |
| Workspace solo nombre/descripción | `POST AnythingLLM /api/v1/workspace/new` + `POST /api/v1/workspace/{slug}/update` con las 7 opciones de la spec |
| Chat fabricado a mano | `POST AnythingLLM /api/v1/workspace/{slug}/chat` (modo `chat` o `query` según `chatMode` del workspace) |

## 4. Variables de entorno nuevas del cliente

```
ELEA_BACKEND_URL=http://backend:8000/api/v1      # red interna del compose de elea
ELEA_SERVICE_CREDENTIAL=<jwt o key admin de servicio, SOLO server-side>
ANYTHINGLLM_URL=http://anythingllm:3001            # nombre de servicio, no host.docker.internal
ANYTHINGLLM_API_KEY=<generada real, no la de ejemplo>
```

Nunca `GUARDIAN_GATEWAY_URL` apuntando directo al motor desde el cliente — todo pasa por
`elea` (backend o engine vía nombre de servicio interno), nunca se expone el motor al
proceso Node como si fuera el producto.

## 5. Orden de construcción (evita romper todo a la vez)

1. **T001 investigación** (sin código): confirmar los 3 endpoints dudosos de arriba
   (mask HTTP público, catálogo de modelos, spend de autoservicio) leyendo
   `backend/src/api/*.py` — cierra las decisiones "a confirmar" de este plan.
2. Login real (US1) — más chico, desbloquea probar todo lo demás con sesión real.
3. Selector de modelo (US2) — depende de T001.
4. Presupuesto (US5) — depende de T001 y de la decisión (b) del punto 3.
5. Workspace completo + enmascarado en ingesta (US3 + US4) — el más grande, depende de
   AnythingLLM con key real generada a mano una vez (paso manual, documentado en README).
6. Branding (US6) — barrido final, un solo `grep -ril litellm client/` de verificación.
