# Quickstart — Validación de punta a punta de la spec 056

Guía de **validación**: prueba que el ingreso con Microsoft por el Hub funciona y que nada de lo
que funciona hoy se rompe. No trae código. Contratos: [contracts/](contracts/). Base de la
prueba: [GUIA-PRUEBA-LOCAL-SSO.md](GUIA-PRUEBA-LOCAL-SSO.md), que ya cubre el directorio de
prueba, la licencia de desarrollo con `sso` y la carga de la config. Esta guía agrega lo del
**Hub**, el **panel** y la **reversión**.

> Directorio Entra: siempre uno **de prueba** (el personal de Cristian), nunca el de Elea. El
> secreto no se pega en el chat ni se commitea.

## 0. Prerrequisitos

- Pasos 1 a 3 de GUIA-PRUEBA-LOCAL-SSO.md hechos:
  - aplicación registrada con **dos** URIs Web: `http://localhost:8090/sso/callback` y
    `http://localhost:8095/sso/callback`;
  - usuarios `prueba.existente@…` y `prueba.nuevo@…`;
  - `~/.eleia-sso-prueba.env` con los datos;
  - licencia `dev-sso-local.lic` (no se commitea).
- Rama `056-sso-entra-id-hub` con los Tramos A, B y C de tasks.md mergeados localmente.
- En `docker-compose.sso-local.yml` (local, no se commitea), la URI de retorno apunta **al Hub**:

  ```yaml
  services:
    backend:
      environment:
        - SENTINEL_LICENSE_TOKEN_FILE=/app/config/licenses/dev-sso-local.lic
        - SENTINEL_SSO_REDIRECT_URI=http://localhost:8095/sso/callback
  ```

  `SENTINEL_SSO_COOKIE_INSECURE` **no** hace falta para el Hub
  ([guardian-sso-api.md](contracts/guardian-sso-api.md) §3).

```bash
STACK_PREFIX=eleae2e docker compose -f docker-compose.yml -f docker-compose.override.yml \
  -f docker-compose.sso-local.yml up -d
curl -s http://localhost:8091/api/v1/auth/sso/available
# → {"enabled": false, "provider_type": null, "return_origin": "http://localhost:8095"}
```

## 1. Gates automáticos (antes de abrir un navegador)

```bash
cd client && npm test                                   # Hub (incluye los tests de la 056)
cd frontend && npm test                                 # panel
docker compose run --rm --no-deps backend pytest tests/ -q
make -C deploy check                                    # artefactos + docs (check-docs)
```

Resultado esperado: todo verde. Si cambió la API o un `.env.example`, `make -C deploy docs-refs`
y volver a correr `check`.

## 2. Activación desde el panel (US3)

1. Panel `http://localhost:8090` como `admin` con contraseña → Usuarios → "Autenticación & SSO".
2. Cargar tenant, identificador y secreto (tipeados por quien prueba), activar y guardar.
   - **Esperado**: "Secreto cargado", el campo del secreto queda vacío y el `GET` de config no
     trae el secreto.
3. Cerrar sesión en el panel. **Esperado**: el panel **no** muestra "Entrar con Microsoft",
   porque `return_origin` es el Hub (D4).

## 3. Ingreso por el Hub (US1)

Con una ventana de incógnito por caso:

| # | Acción | Esperado |
|---|---|---|
| 1 | Abrir `http://localhost:8095` | Aparece "Ingresar con Microsoft" junto al formulario de siempre |
| 2 | Ingresar con `prueba.existente@…`, dado de alta antes en el panel con grupo y presupuesto | Llega al Hub con el mismo rol, grupo, presupuesto y espacios. Sin modal de cambio de contraseña y sin botón "Contraseña" |
| 3 | Revisar la barra de direcciones y el historial | La URL final es `/`. Ninguna URL contiene un token |
| 4 | Usar chat, Documentos, Planillas y Presentaciones | Funcionan. El gasto se imputa a esa persona y a su grupo |
| 5 | Ingresar con `prueba.nuevo@…` | Se crea como `client`, sin grupo, y ocupa un puesto |
| 6 | Dar de baja a `prueba.existente` en el panel y reintentar | Mensaje "usuario dado de baja". La baja no se revierte |
| 7 | Bajar `max_seats` de la licencia de prueba al número actual y entrar con un tercer usuario nuevo | Mensaje "no quedan puestos". El usuario no se crea |
| 8 | Cancelar en la pantalla de Microsoft | Mensaje "se canceló el ingreso". El formulario sigue usable |
| 9 | Pulsar el botón, esperar 11 minutos y completar el ingreso | "Volvé a intentarlo" |
| 10 | Pulsar el botón, `docker compose restart client` y completar el ingreso | "Volvé a intentarlo" (caso borde de reinicio) |
| 11 | Copiar la URL `/sso/callback?…` de un ingreso y abrirla en **otro** navegador | "Volvé a intentarlo". No se abre sesión (atadura al `sid`) |
| 12 | Abrir el Hub por `http://127.0.0.1:8095` y pulsar el botón | Lo lleva a `http://localhost:8095/sso/login` (origen de retorno) y el ingreso termina bien |

Auditoría: en el panel (eventos de autenticación) hay un `auth_sso_login` por cada ingreso
aceptado y un `auth_sso_denied` por los casos 6, 7, 8, 9, 10 y 11, **sin** emails, `state`,
`code` ni tokens en ninguna columna.

## 4. Regresión y degradación (US2, SC-003)

1. `admin` y un `client` con contraseña, en el Hub y en el panel: igual que antes.
2. Alta con cambio obligatorio de la 055: el modal aparece en el Hub como antes.
3. Romper a propósito el secreto (guardar uno falso desde el panel) e ingresar por Microsoft:
   mensaje "Microsoft no confirmó tu identidad" o "no pudimos contactar a Microsoft". El login
   con contraseña sigue funcionando.
4. Apagar el interruptor en el panel: el botón desaparece del Hub en el próximo ingreso, sin
   reiniciar nada (US3 AS2).
5. Licencia **sin** `sso` (volver a `dev-demo.lic`): sin botón en el Hub ni en el panel, y sin
   errores (US2 AS3).

## 5. Instalador y vuelta atrás (Etapa 1 de DESPLIEGUE-Y-REVERSION.md)

1. Imágenes candidatas: `LATEST=0 VERSION=056-rc1 deploy/release/publish-elea.sh`.
   **Esperado**: en el registro existe `:056-rc1` y `:latest` no se movió.
2. Instalación desde cero con el instalador en el tag anterior (`ELEA_TAG=<fecha-anterior>`),
   con algunos usuarios e historial.
3. Actualizar con `ELEA_TAG=056-rc1 ./install.sh`, **sin** `SENTINEL_SSO_REDIRECT_URI`.
   **Esperado**: todo igual que antes; la pestaña SSO dice "No configurado".
4. Licencia con `sso` en `./license/` y `SENTINEL_LICENSE_TOKEN_FILE=/app/config/licenses/host/<archivo>.lic`.
   **Esperado**: `/auth/sso/available` responde 200 (no 403).
5. Vuelta atrás de nivel 2: `ELEA_TAG=<fecha-anterior> ./install.sh`. **Esperado**: usuarios,
   historial y config SSO intactos. No hay migración que revertir.
6. Repetir 3 → la configuración SSO cargada en el paso 2 se conserva (US3 AS3).

## 6. Evidencia

Anotar resultados y capturas en `RESULTADOS-PRUEBA-LOCAL.md` en esta carpeta (como pide
GUIA-PRUEBA-LOCAL-SSO.md §6) y marcar la fila `login-real` del runbook de la 017. **Listo para
el server de Elea** = §1 a §5 en verde. **Listo de verdad** = un ingreso real de un piloto de
Elea en su Hub (Etapa 4, regla del equipo).
