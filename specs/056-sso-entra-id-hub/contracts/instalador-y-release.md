# Contrato — Instalador (`cluna-8/elea-installer`) y publicación de imágenes

Cubre FR-009b, FR-010 y FR-011, y las tareas previas de
[DESPLIEGUE-Y-REVERSION.md](../DESPLIEGUE-Y-REVERSION.md) §"Cambios previos". Decisiones:
[research.md](../research.md) D7 (opción B: sin servicio TLS), D8, D9 y D14 (gates en
`make -C deploy check`, F9 del QA).

**Base en enfoque**: los nombres de variable (`SENTINEL_SSO_REDIRECT_URI`,
`SENTINEL_LICENSE_TOKEN_FILE`) son los mismos que usa Sentinel, para portar el enfoque a su
wizard (spec 065 allá) sin traducir nombres. `ELEA_TAG` es propio de este instalador.

## 1. Variables nuevas en `.env` / `.env.example`

| Variable | Default | Efecto | Vacía / ausente |
|---|---|---|---|
| `ELEA_TAG` | `latest` | Tag de las seis imágenes propias (`elea-guardian-backend`, `-frontend`, `-engine`, `-nlp`, `elea-rag-client`, `elea-tabular`). | Se usa `latest`, igual que hoy. |
| `SENTINEL_SSO_REDIRECT_URI` | *(vacía)* | Se pasa al servicio `backend`. Debe ser **byte a byte** la URI registrada en Entra: `https://<nombre-del-hub>/sso/callback`. | El backend arranca igual y `/auth/sso/available` devuelve `return_origin: null`, así que el Hub **no dibuja el botón** (FR-001, FR-015, F4 del QA). Si alguien llega igual a `/sso/login`, corta con `sso_redirect_uri_no_configurado` y el Hub muestra `sso_no_disponible` (FR-009b, FR-006). Vaciarla es la vuelta atrás de nivel 1: el botón desaparece del Hub. |
| `SENTINEL_LICENSE_TOKEN_FILE` | `/app/config/licenses/dev-demo.lic` | Licencia que lee el backend. Para usar la del host: `/app/config/licenses/host/<archivo>.lic`. | Se usa la horneada en la imagen, como hoy. |

`.env.example` documenta las tres en un bloque comentado "Ingreso con Microsoft (opcional)" y
"Versión de imágenes", **sin valores de Elea**: marcadores `<nombre-del-hub>`.

## 2. `docker-compose.yml`

```yaml
# imágenes propias (6): antes `:latest` fijo
image: ghcr.io/cluna-8/elea-guardian-backend:${ELEA_TAG:-latest}
# … igual para frontend, engine, nlp, rag-client y tabular. postgres, redis, anythingllm y
# presenton NO cambian: ya están fijadas o son de terceros.

backend:
  environment:
    - SENTINEL_LICENSE_TOKEN_FILE=${SENTINEL_LICENSE_TOKEN_FILE:-/app/config/licenses/dev-demo.lic}
    - SENTINEL_SSO_REDIRECT_URI=${SENTINEL_SSO_REDIRECT_URI:-}
  volumes:
    - ./license:/app/config/licenses/host:ro
```

- `SENTINEL_ALLOW_DEV_LICENSE=true` **se mantiene** (deuda conocida, research D8).
- **No** se agrega `SENTINEL_SSO_COOKIE_INSECURE`: el Hub no la necesita
  ([guardian-sso-api.md](guardian-sso-api.md) §3) y en producción la cookie del panel debe ser `Secure`.
- **No** se agrega ningún servicio TLS ni proxy (D7-B).
- `./license/` existe en el repo del instalador con un `.gitkeep` y una regla de `.gitignore`
  para `*.lic`: la licencia de un cliente **nunca** se versiona.

Verificación: `docker compose config` sin `.env` nuevo renderiza `:latest`, la licencia
`dev-demo.lic` y `SENTINEL_SSO_REDIRECT_URI` vacía. Con `ELEA_TAG=056-rc1` renderiza ese tag en
las seis imágenes.

## 3. `install.sh`

- El `docker pull` explícito del motor (`install.sh:56`) usa `${ELEA_TAG:-latest}`.
- El resumen final imprime el tag en uso, por ejemplo `Versión de imágenes: 056-rc1`, para
  anotarlo antes de la próxima actualización (vuelta atrás de nivel 2).
- Si `SENTINEL_SSO_REDIRECT_URI` no está vacía y **no** empieza con `https://` (y tampoco es
  `http://localhost…`), avisa sin cortar: "Microsoft solo acepta https salvo localhost".
- Si `SENTINEL_LICENSE_TOKEN_FILE` apunta a `/app/config/licenses/host/…` y el archivo no está
  en `./license/`, corta con un error claro antes de levantar el backend.

## 4. HTTPS: proxy TLS de Elea (D7-B, solo documentación)

El instalador no termina TLS. Lo que la documentación (README del instalador,
`docs/docs/install-deploy/sso.md`, SOLICITUD y DESPLIEGUE) tiene que dejar claro:

| Requisito | Detalle |
|---|---|
| Nombre DNS | `<nombre-del-hub>` resuelve al server. Es el mismo host de `SENTINEL_SSO_REDIRECT_URI` y de la URI registrada en Entra. |
| Certificado | Confiable por las PC de los usuarios (CA interna distribuida por GPO o certificado público). |
| Reenvío | `https://<nombre-del-hub>/*` → `http://<server>:8095/*`, **todas** las rutas, query intacto (incluye `/sso/login` y `/sso/callback`). |
| Cabeceras | `Host`, `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Host`: las estándar. El Hub **no depende** de ellas (redirecciones relativas, research D7). |
| Salida | El server sale por 443 a `login.microsoftonline.com`. La necesita el backend, no el Hub. |
| Puerto 8095 | Puede seguir abierto en la LAN. Quien entre por ahí ve el botón, que lo lleva al nombre HTTPS (D4). |

## 5. `deploy/release/publish-elea.sh` (repo `elea`)

| Variable | Default | Efecto |
|---|---|---|
| `LATEST` | `1` | `1`: igual que hoy, etiqueta y empuja `:${VERSION}` **y** `:latest` (`publish-elea.sh:34`, `:42`). `0`: solo `:${VERSION}`. **No** construye ni empuja `:latest`. |
| `PROMOTE_FROM` | *(vacía)* | **Promoción por re-etiquetado** (N2 del QA v2). Vacía: el script construye como hoy. Con un tag (p. ej. `056-rc1`), **no construye**: por cada imagen de `ONLY` hace `docker pull <imagen>:${PROMOTE_FROM}`, la etiqueta `:${VERSION}` y, si `LATEST=1`, `:latest`, y empuja esas etiquetas. El digest publicado es **el mismo** de la candidata. Tampoco corre el chequeo de la imagen del backend (`:35-40`), que ya pasó al publicar la candidata. Si el `pull` falla, corta sin empujar nada de esa imagen. |

**Qué significa "promover a `latest`"**: re-etiquetar y empujar la candidata **probada** en la
Etapa 1, la misma que ya corre en el server de producción de Elea y que usó el grupo piloto de 2
o 3 usuarios en la Etapa 4, con los mismos digests. **Nunca** reconstruir: un `build` nuevo
produce bits distintos de los probados (el `npm install` sin lockfile de
`client/Dockerfile:10-11` y las capas `apk`/`pip` sin fijar de `:4-6` pueden traer otras versiones)
y rompe los principios 1 y 4 de DESPLIEGUE-Y-REVERSION.md.

Usos:

- Candidatas (Etapa 1): `LATEST=0 VERSION=056-rc1 deploy/release/publish-elea.sh`. Se anotan las
  líneas `PINNED <imagen>=<repo>@sha256:…` que imprime el script (`publish-elea.sh:43`).
- Promoción (Etapa 5): `PROMOTE_FROM=056-rc1 VERSION=<fecha> deploy/release/publish-elea.sh`. Las
  líneas `PINNED` que imprime tienen que ser **idénticas** a las de la candidata; si alguna
  difiere, la promoción no se da por buena.

El encabezado de uso del script documenta los tres modos (publicar, candidata y promoción). El
resto del script no cambia.

Verificación sin publicar: correr el script con `docker` sustituido por un *stub* en el `PATH`
que registre los argumentos y devuelva un digest fijo en `inspect`, y comprobar:

- con `LATEST=0` no aparece ningún `:latest`;
- con el default sí aparece;
- con `PROMOTE_FROM=056-rc1` **no** hay ningún `docker build` ni `docker run`, hay
  `pull …:056-rc1`, `tag …:056-rc1 …:latest` y `push …:latest`, y la línea `PINNED` sale del
  digest de la candidata;
- con `PROMOTE_FROM` y un `pull` que falla (el stub sale con error), no hay ningún `push`.

## 6. Gates en `make -C deploy check` (`deploy/Makefile`, F3 y F9 del QA)

`make -C deploy check` corre una lista explícita de targets (`deploy/Makefile:42`). Un script nuevo
en `deploy/release/checks/` no corre solo. Se suman dos targets, ninguno usa Docker:

| Target | Corre | Lo agrega | Protege |
|---|---|---|---|
| `check-release-publish` | `deploy/release/checks/test_publish_elea_latest.sh` (con el `docker` de prueba) | Tramo D | Que `LATEST=0` nunca mueva `:latest` y que `PROMOTE_FROM` nunca construya (riesgo central del despliegue: lo que se entrega es lo que se probó y ya corre en producción). |
| `check-hub-whitelabel` | `node --test client/tests/unit/whitelabel-hub-056.test.js` (solo `node:fs`, sin `npm ci`) | Tramo E, con el Hub ya mergeado | FR-013 y FR-014 sobre lo visible del Hub ([hub-sso.md](hub-sso.md) §7, tests 21 y 22). |

Los dos entran a la lista de `check` y a `.PHONY`. `deploy/Makefile` lo editan los tramos D y E,
que no corren en paralelo.
