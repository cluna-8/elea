# Install / Deploy

Guía de despliegue para el **distribuidor** (el partner que revende la plataforma bajo su
propia marca, la instala, da el training y el soporte) y para el **operador** que administra
una instalación. Cubre el modelo de entrega, los artefactos que componen un despliegue y el
flujo de instalación de punta a punta.

Páginas de esta sección:

- [Infraestructura](infrastructure.md) — arquitectura de despliegue objetivo: cloud, on-prem/air-gapped, secretos y storage.
- [Licenciamiento](licensing.md) — licenciamiento offline por seats y postura de IP del artefacto.
- [White-label & branding](../white-label/index.md) — el branding pack y la marca como configuración en runtime.

!!! warning "Nota de honestidad (léala antes que nada)"
    Esta guía distingue explícitamente lo **implementado hoy** de lo **forward-looking**:
    describe el **estado-objetivo** (cómo debe desplegarse en producción) y, en cada bloque,
    marca qué es real hoy y qué falta construir. Nada aspiracional se declara como hecho.
    **OpenTofu, imágenes de producción, secrets manager gestionado y el licenciamiento
    offline son estado-objetivo.** Lo que sí existe hoy es el stack Docker Compose dev/demo,
    el onboarding-as-data (seed por slug) y el bootstrap de admin. Ver la tabla de estado.

**Leyenda de estado** (se usa en toda la documentación):

| Marca | Significado |
|---|---|
| 🟢 **HOY** | Implementado y verificable en la versión actual del producto |
| 🟡 **PARCIAL** | Existe la base, falta endurecerlo para producción |
| 🔵 **OBJETIVO** | Roadmap / estado-objetivo, no existe aún |

---

## Estado actual vs objetivo (resumen ejecutivo)

| Pieza del deploy | Estado-actual | Estado-objetivo (producción cliente) | Estado |
|---|---|---|---|
| Orquestación | `docker-compose.yml` con 5 servicios (db, redis, motor, backend, frontend) | Módulo OpenTofu + compose de producción (v1) / k3s+Helm+Zarf (v2) | 🟡 |
| Imágenes backend/frontend | Dev: `uvicorn --reload`, `npm run dev`, bind-mount del código fuente | Imágenes de producción multi-stage, sin reload, deps pinneadas, front servido estático | 🔵 |
| Imagen del motor | Pinneada por **tag+digest** en el stack de referencia | Pin por digest en todos los despliegues | 🟡 |
| Base de datos / cache | Contenedores `postgres:16-alpine` / `redis:7-alpine` con volumen local | Postgres y Redis **gestionados** (RDS/Cloud SQL/Azure DB · ElastiCache/MemoryStore) | 🔵 |
| Secretos | `.env` en claro (con defaults inseguros en compose) | Secrets manager gestionado (AWS SM / GCP SM / Vault) **o SOPS/age** (cifrado sin servidor) para v1/air-gapped, inyectando env al arrancar | 🔵 |
| TLS + DNS | HTTP plano en puertos altos | TLS terminado — **Caddy (auto-TLS)** en v1, ALB/nginx en cloud — + DNS por cliente, región EU | 🔵 |
| Onboarding de cliente | `seed_clients_from_config(db, tenant_slug, path)` idempotente desde YAML | Igual, invocado por el flujo de instalación | 🟢 |
| Tenant por slug | Modelo `Tenant.slug` único; on-prem = 1 tenant (default `…0001`) | Igual; cloud = N tenants aislados por RLS | 🟢 / 🟡 (RLS es forward-looking) |
| Bootstrap de admin | Primer login `admin` crea `tenant_admin`; email `admin@basa.com.ar` | Igual + rotación de credencial obligatoria post-instalación | 🟡 (rotación sólo por SQL hoy) |
| Branding white-label | Naming neutro en el código (`AIEngineClient`/`engine_*`, errores del motor reescritos a naming neutro) | Branding pack (nombre/logo/paleta) por cliente como **config-as-data en runtime** (sin recompilar) | 🟡 |
| Licenciamiento offline | Sin wirear (la primitiva criptográfica con Ed25519 está disponible en el backend, sin uso) | Licencia Ed25519 firmada, seat = Connection activa, sin phone-home | 🔵 |

---

## El modelo de entrega (óptica del distribuidor)

La plataforma se distribuye bajo un modelo **install + N licencias**, no como SaaS operado
por el fabricante. Como distribuidor, usted es el dueño de la relación con el cliente final:

- **Usted revende bajo su propia marca (o co-marca).** Ningún nombre del motor interno ni de
  proveedor LLM aparece en la UI, la API pública, los errores ni los logs — el código usa
  naming neutro (`AIEngineClient`/`engine_*`) y los errores del motor se reescriben antes de
  exponerse. Esto es 🟢 en el core; el branding visual (nombre de producto, logo, paleta) se
  aplica por cliente — ver [White-label & branding](../white-label/index.md).
- **Usted da el training y el soporte de nivel 1/2.** Instala (o acompaña la instalación),
  capacita, resuelve incidencias y escala al fabricante sólo los bugs de producto.
- **El fabricante no instala al cliente final ni opera servidores.** No tiene acceso a la
  infraestructura del cliente, no ve sus datos y el producto no hace phone-home. El
  fabricante entrega **artefactos** (imágenes/tarball, branding pack, perfil por cliente,
  módulo OpenTofu, licencia) y usted o el cliente los despliegan.
- **El cliente levanta el stack donde quiera, con OpenTofu.** El cliente final es dueño de su
  infraestructura (su VPC, su cuenta cloud o su datacenter on-prem/air-gapped). El **mismo
  código** corre **single-tenant on-premise** (un tenant por instalación, apto para modelos
  locales Ollama/vLLM) y **multi-tenant cloud**. El despliegue por cliente es
  **configuración + seed, nunca un fork**.
- **Licencias = seats.** El contrato fija N seats. Un **seat = una Connection activa** (una
  `APIKey` con `is_active=True` por herramienta/persona). El enforcement de seats es offline
  y firmado — ver [Licenciamiento](licensing.md).

**Frontera de responsabilidad (quién hace qué):**

| Actor | Responsabilidad |
|---|---|
| **Fabricante** | Construye el producto, publica imágenes/tarball + branding pack + módulo OpenTofu + licencia firmada. No instala, no opera, no ve datos. |
| **Distribuidor (usted)** | Empaqueta el perfil del cliente, corre el despliegue (o acompaña al cliente), da training y soporte, gestiona licencias/seats. |
| **Cliente final** | Es dueño de su infra (cuenta cloud / datacenter), aplica el OpenTofu, custodia sus secretos y sus datos. |

---

## Qué se entrega (deliverables)

Por cada cliente/despliegue, el distribuidor arma un paquete con:

1. **Imágenes de producción o tarball air-gapped.**
    - **Cloud con egress** → imágenes de producción publicadas en un registry desde el que el
      cliente pueda hacer `pull` (backend, frontend y el motor pinneado por digest). 🔵
      Estado-objetivo: **hoy las imágenes de `backend`/`frontend` son de desarrollo**
      (`uvicorn --reload` / `npm run dev` y bind-mount del código). Producción exige imágenes
      multi-stage, sin reload, dependencias pinneadas y el frontend compilado servido como
      estático.
    - **On-prem / air-gapped (sin egress)** → **tarball** con todas las imágenes
      (`docker save` de db, redis, motor@digest, backend, frontend) + checksums, para
      `docker load` en la máquina destino. El motor **debe ir pinneado por digest** para que
      el tarball sea reproducible. 🔵 El sitio de documentación de producto viaja como una
      imagen más del release (`basa-docs:<brand>-<version>`, una por marca, 100% estática y
      0-egress).

2. **Branding pack.** Nombre de producto, logo, favicon, paleta y datos de contacto de
   soporte del distribuidor. Se aplica como **config-as-data en runtime** (el frontend carga
   la configuración de branding al arrancar, no se hornea en la imagen), nunca tocando
   código. 🟡 El código ya es marca-neutro; el mecanismo de branding-por-config-en-runtime es
   lo que falta formalizar. Detalle completo en
   [White-label & branding](../white-label/index.md).

3. **Perfil por cliente (onboarding-as-data).** 🟢 Es el corazón del "config + seed, never
   fork":
    - **`tenant`**: nombre + `slug` único + `deployment_mode` (`on_premise` | `cloud`) +
      defaults de contexto legal (`default_legal_basis`, `default_risk_level`) y de
      compresión.
    - **`config/clients.yaml`**: lista de clients (personas/herramientas) con sus Connections
      (una virtual key por `tool_type`), Budget en USD y toggles por-key (`redact_enabled`,
      `compression_mode`, `allowed_models`, `allowed_tools`, `rpm_limit`, `tpm_limit`,
      `upstream_mode`). El schema está documentado en el `clients.example.yaml` que acompaña
      al producto. Sumar un cliente o un demo = **editar el YAML y correr el seed**, nunca
      tocar código.

4. **Módulo OpenTofu.** 🔵 Estado-objetivo: un módulo parametrizado por cliente (VPC,
   DB/Redis gestionados, cómputo, secretos, TLS+DNS, región) — ver
   [Infraestructura](infrastructure.md). Se usa **OpenTofu, no Terraform**: como el
   distribuidor **entrega el IaC a terceros** y la licencia de Terraform es **BSL**, OpenTofu
   (fork MPL, drop-in, mismos `.tf` y `tofu apply`) evita el riesgo de licenciamiento en la
   redistribución. Hasta que exista, el despliegue se hace con el Docker Compose actual sobre
   una VM provisionada a mano.

5. **Licencia firmada (Ed25519).** 🔵 Estado-objetivo. Archivo de licencia offline que
   habilita N seats — ver [Licenciamiento](licensing.md).

---

## Flujo de instalación de punta a punta

Flujo **objetivo** (🔵 en su forma OpenTofu; los pasos de seed y bootstrap son 🟢 y se pueden
correr hoy a mano sobre el compose):

1. **`tofu apply`** con el `tfvars` del cliente (región EU, tamaños de DB/cómputo, dominio,
   `tenant` name+slug, `deployment_mode`). Provisiona VPC + Postgres/Redis gestionados +
   cómputo + secrets manager + TLS/DNS, y arranca el stack. 🔵
2. **Secretos generados, no hardcodeados.** OpenTofu / el secrets manager generan
   `POSTGRES_PASSWORD`, la clave maestra del motor, `FERNET_SECRET_KEY` y `JWT_SECRET_KEY`
   (aleatorios, fuertes) y los inyectan como variables de entorno. **Se descartan los
   defaults del compose.** 🔵
3. **Arranque + migraciones.** El backend corre `alembic upgrade head` al bootear, creando el
   esquema multi-tenant. El motor corre sus propias migraciones de base de datos. ⚠️ En el
   **primer boot** el motor puede reportarse `unhealthy` por timeout aunque haya arrancado
   bien — ver [el gotcha](#gotcha-boot).
4. **Seed del tenant por slug.** Se crea el `Tenant` (name + `slug` +
   `deployment_mode=on_premise` para instalaciones single-tenant; el default determinista
   termina en `…0001`). El slug es la clave del despliegue por cliente. 🟢
5. **Seed de clients + branding.**
    - `seed_clients_from_config(db, tenant_slug="<slug>", path="config/clients.yaml")`
      siembra, de forma **idempotente**, cada persona/herramienta: `User role="client"` + N
      Connections (una `APIKey` por `tool_type`) + Budget, todo tenant-scoped. Devuelve las
      **keys en claro SÓLO de las Connections recién creadas** — se entregan una vez al
      cliente y no se pueden recuperar después (sólo queda el hash). 🟢
    - Se aplica el **branding pack** (configuración del frontend) — ver
      [White-label & branding](../white-label/index.md). 🟡
6. **Bootstrap de admin + rotación.** El primer login como `admin` crea un `tenant_admin` con
   la password que se envía en ese primer login (el email del bootstrap es
   `admin@basa.com.ar` — un TLD reservado tipo `.local` rompía la validación, ver
   [el gotcha](#gotcha-email)). **Rotar la credencial inmediatamente**: hoy **no hay endpoint
   de cambio de password**, así que la rotación es por SQL
   ([gotcha](#gotcha-password)); el endpoint es parte del roadmap de endurecimiento de
   auth. 🟡
7. **Instalación de la licencia.** Se coloca el archivo de licencia Ed25519 que habilita los
   N seats contratados. 🔵 Ver [Licenciamiento](licensing.md).
8. **Smoke test post-deploy**:
    - `docker ps` → 5 contenedores `Up`/`healthy` (o los tasks equivalentes en v2).
    - `curl` a `/health/readiness` del motor → 200; a un endpoint del backend → 200.
    - Login como `admin` desde el navegador en la **URL/dominio real** (no `localhost`).
    - Apuntar `ANTHROPIC_BASE_URL` de un Claude Code a la ruta `/v1/messages` del motor con
      una virtual key sembrada → verificar bloqueo/masking; abrir `/monitor` y ver el
      before/after real.

---

## Gotchas de instalación verificados

Todos verificados en despliegues reales o en el comportamiento actual del producto.

### On-prem sin egress: clonar/pull falla { #gotcha-egress }

En redes sin salida a Internet, `git clone` devuelve **403** y `docker pull` no resuelve.
Para código, usar un **espejo** accesible desde esa red. Para imágenes, entregar el
**tarball air-gapped** (`docker save`/`docker load`, ver deliverables). Recordar además que
**el acceso a los proveedores de LLM también requiere egress**, salvo que se usen **modelos
locales** (Ollama/vLLM) — en air-gapped puro, la lista de modelos del perfil debe apuntar
sólo a modelos locales.

### El motor se reporta `unhealthy` en el primer boot (no es un fallo) { #gotcha-boot }

En el primer arranque el motor tarda varios minutos (migraciones de base de datos) y el
timeout del healthcheck de `docker compose` puede agotarse **aunque el contenedor haya
arrancado bien**. Verificar con `docker logs <contenedor-del-motor>` (si dice "Application
startup complete" y `/health/readiness` responde 200, está sano). **Solución**: correr
`docker compose up -d` **de nuevo** — como db/redis/motor ya quedan corriendo, la segunda
pasada sólo levanta backend/frontend y es rápida.

### Bootstrap de admin con email `.local` rompe la pestaña de Usuarios { #gotcha-email }

El bootstrap de admin usa un email hardcodeado. Con un TLD reservado
(`.local`/`.test`/`.example`/`.invalid`), una versión reciente de `email-validator`
(dependencia de Pydantic) lo rechaza como inválido y devuelve **500** en cualquier respuesta
que incluya la lista de usuarios — rompía toda la pestaña "Usuarios & Presupuestos".
**Corregido en el producto** (el bootstrap usa `admin@basa.com.ar`). Para un despliegue que
**ya** tiene un admin con el email viejo, corregir a mano en la base:

```bash
docker exec <db-container> psql -U <user> -d <db> \
  -c "UPDATE users SET email='admin@basa.com.ar' WHERE username='admin';"
```

### La consola web parte secretos/URLs de más de ~80 caracteres { #gotcha-consola }

Al pegar en una consola web (sin GUI) una URL o secreto de más de ~80 caracteres, la consola
inserta un **salto de línea real** en medio del texto, rompiendo la autenticación con un
error confuso ("Malformed input to a URL function" / "Authentication failed"). **Solución**:
partir cualquier secreto/URL larga en variables de shell cortas (≤25-30 chars cada una) en
líneas separadas, y concatenarlas al usarlas:

```bash
P1="mitad1delaclave"
P2="mitad2delaclave"
echo "${P1}${P2}" | wc -c   # verificar longitud antes de usarla
```

### "Sin usuario" en el desglose de costos — no es un bug { #gotcha-sin-usuario }

El gasto se atribuye a una persona sólo cuando ésta tiene una **llave personal** en el motor,
creada automáticamente recién al asignarle un perfil de presupuesto. Las consultas hechas
**antes** de asignar presupuesto viajan con la llave maestra compartida y aparecen como "Sin
usuario". No es retroactivo. Explicarlo en el training para no confundirlo con un fallo de
atribución.

### No hay endpoint para cambiar la password de un usuario ya creado { #gotcha-password }

Ni en UI ni en API se puede rotar la password de un usuario existente (sólo se define al
crearlo). Hasta que llegue el endpoint (roadmap de endurecimiento de auth), la rotación del
admin post-instalación es por SQL:

```bash
docker exec <db-container> psql -U <user> -d <db> \
  -c "UPDATE users SET password_hash='<sha256-del-nuevo-valor>' WHERE username='admin';"
```

Este hueco es más relevante cuanta más gente tenga acceso a la red donde corre el stack —
cerrarlo bien es precisamente el objetivo del roadmap de endurecimiento de auth.

---

## Mantenimiento: actualización del motor

La imagen del motor se **fija por tag+digest**. Para actualizar el motor:

1. Cambiar el **digest** en el `docker-compose.yml` / módulo OpenTofu.
2. Correr la **suite de contract tests** del producto: firmas de los hooks del guardrail y
   del hook de autenticación del motor + ejecución sobre `/v1/messages`.
3. Si pasa → adoptar el nuevo digest. Si falla → **no reescribir los hooks a ciegas**:
   investigar el cambio de firma del motor. **Actualizar el motor = correr tests, no
   parchear.**
