# Spec 056 — Despliegue en el server de Elea y vuelta atrás

**Para**: el equipo (uso interno). **Fecha**: 23-sep-2026.
**Server del cliente**: `eleavdmia` (`172.16.0.120`), instalador en `~/Eleia-cli`. Hoy se accede
por HTTP: Guardian en `:8090` y Hub en `:8095`.

## Respuesta corta a Elea

Sí, se puede instalar sin riesgo para lo que ya funciona:

- El ingreso con Microsoft es **un camino más**. El login con usuario y contraseña no se toca y
  sigue disponible siempre.
- Se despliega **apagado**: con la versión nueva instalada, nadie ve nada distinto hasta que un
  admin lo enciende desde el panel.
- Se puede **apagar en segundos desde el panel** si algo no convence. Si hiciera falta, se vuelve
  a la versión anterior de las imágenes con un comando.
- **No cambia la base de datos**: la tabla de configuración SSO ya existe desde la spec 017. No
  hay migración que revertir.
- Antes de tocar el server se prueba todo en local, con un directorio Entra de prueba nuestro.

## Principios

1. **Nada llega al server hasta pasar la prueba local.** Se desarrolla en la rama
   `056-sso-entra-id-hub`. Las imágenes de prueba se publican **con tag propio, sin mover
   `latest`**, para que un `./install.sh` en el server no las tome por accidente.
2. **Se despliega apagado y se enciende aparte.** Instalar el código y activar el SSO son dos
   pasos distintos, en días distintos si hace falta.
3. **Toda vuelta atrás está probada antes de usarla.** Cada nivel de reversión se ensaya en local.
4. **Verificación idéntica al uso real** (regla del equipo): no se declara listo sin un ingreso
   real con una cuenta de Elea en su Hub.

## Cambios previos que habilitan esto (entran en las tareas de la 056)

| Cambio | Para qué |
|---|---|
| `publish-elea.sh` con opción para **no mover `latest`** (por ejemplo `LATEST=0`) | Publicar candidatas de prueba sin riesgo |
| `elea-installer/docker-compose.yml` con tag de imagen parametrizable (`ELEA_TAG`, default `latest`) | Fijar versión y volver atrás con `ELEA_TAG=<fecha> ./install.sh` |
| Licencia de Elea con `sso`, **montada desde el host** en lugar de horneada en la imagen | Cambiarla o revertirla sin reconstruir imágenes |
| `SENTINEL_SSO_REDIRECT_URI` pasada al backend desde `.env` | Vacía = sin SSO, sin errores |
| Formulario de configuración SSO en el panel (US3) | Activar y desactivar desde el server de Elea |

## Etapas

### Etapa 1 — Prueba local (nuestra infraestructura, sin Elea)

1. Directorio Entra de prueba propio (el de nuestra cuenta de Azure, o un tenant de desarrollo de
   Microsoft 365) con una aplicación registrada. En local Entra acepta
   `http://localhost:8095/sso/callback`, así que no hace falta HTTPS.
2. Stack de dev (`STACK_PREFIX=eleae2e`) con la rama 056.
3. Pruebas:
   - un usuario existente con el mismo email entra por Microsoft y conserva rol, grupo y presupuesto;
   - un usuario nuevo se crea como `client`;
   - un usuario dado de baja es rechazado;
   - se prende y se apaga desde el panel;
   - Microsoft caído o secreto erróneo solo rompen el botón.
4. Regresión completa:
   - login con contraseña (`admin`, `bruno`);
   - cambio obligatorio de la 055;
   - chat, Documentos, Planillas y Presentaciones;
   - presupuestos.
5. **Ensayo de reversión**: instalación desde cero con el instalador (receta de
   `elea-instalador-prueba-desde-cero`), actualización a la 056 y vuelta atrás con `ELEA_TAG` a
   la versión anterior. Confirmar que los usuarios y el historial quedan intactos.

**Salida**: imágenes candidatas publicadas como `056-rc1` (sin `latest`) y reporte de pruebas en
esta carpeta.

### Etapa 2 — Preparación de Elea (en paralelo con la Etapa 1)

Elea completa lo que pide [SOLICITUD-A-ELEA.md](SOLICITUD-A-ELEA.md): confirmar la
sincronización AD ↔ Entra, registrar la aplicación, nombre DNS con certificado, salida a
Microsoft, usuarios piloto y ventana de mantenimiento.

### Etapa 3 — Instalación en el server, apagado (ventana de mantenimiento, ~1 h)

Antes de tocar nada:

```bash
cd ~/Eleia-cli
docker compose images > ~/pre-056-imagenes.txt
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -Fc "$POSTGRES_DB"' > ~/pre-056-guardian.dump
cp .env ~/pre-056.env
```

Anotar el tag vigente, por ejemplo `2026-09-21`, que fue el del deploy de la 055. Después:

1. `git pull` del instalador y `./install.sh` con `ELEA_TAG=056-rc1`. Todavía **sin**
   `SENTINEL_SSO_REDIRECT_URI` y sin cargar nada en el panel.
2. Verificar que todo sigue igual:
   - `admin` y un usuario real entran con contraseña;
   - un chat, una planilla y un documento funcionan;
   - la pestaña SSO del panel dice "no configurado".
3. Configurar HTTPS en el nombre que dio Elea (proxy TLS delante del Hub) y verificar que el Hub
   abre por `https://<nombre>` además de por `:8095`.

### Etapa 4 — Activación con un piloto

1. Completar `SENTINEL_SSO_REDIRECT_URI=https://<nombre>/sso/callback` en `.env` y correr
   `./install.sh`.
2. El admin o el IT de Elea carga tenant, identificador y secreto desde el panel
   ("Autenticación & SSO") y activa el interruptor. **El secreto lo tipea Elea; no pasa por
   nosotros.**
3. Los 2 o 3 usuarios piloto entran por "Ingresar con Microsoft", en su PC y con su cuenta real.
   Se verifica rol, grupo, presupuesto y espacios de cada uno.
4. Si el piloto está bien: se deja encendido y se avisa al resto. Si no: se apaga el interruptor
   y se analiza con calma.

### Etapa 5 — Cierre

- Promover `056-rc1` a `latest` (republicar con fecha) para que las próximas actualizaciones
  normales la incluyan.
- Escribir `HANDOFF-elea-a-sentinel.md` en esta carpeta.
- Actualizar `docs/docs/install-deploy/sso.md` (Definition of Done del repo) y el estado de la
  spec.

## Vuelta atrás, de la más liviana a la más pesada

| Nivel | Qué se hace | Cuánto tarda | Qué se pierde |
|---|---|---|---|
| 0 | **Apagar el interruptor** en el panel | Segundos | Nada. Los usuarios vuelven a entrar con contraseña. Los usuarios creados por SSO quedan dados de alta, sin poder entrar hasta que se reactive. |
| 1 | Vaciar `SENTINEL_SSO_REDIRECT_URI` en `.env` y `./install.sh` | Minutos | Nada |
| 2 | `ELEA_TAG=<tag anterior> ./install.sh`: vuelve a las imágenes previas | ~10 min | Nada. No hay migración de base en esta spec. |
| 3 | Restaurar `~/pre-056-guardian.dump` | ~30 min | Lo cargado después del backup. Solo si algo inesperado dañara datos, que no está previsto. |

**Qué falta para que "volver atrás" sea real**: hoy el compose tiene `latest` fijo, así que el
nivel 2 depende del cambio `ELEA_TAG` de arriba. Hasta que esté, la alternativa es retaguear a
mano en el server (`docker tag ghcr.io/cluna-8/<imagen>:<fecha-anterior> …:latest` y
`docker compose up -d`).

## Riesgos conocidos

- **UPN distinto del email cargado en Guardian**: crea usuarios duplicados. Antes de la Etapa 4 se
  cruza la lista de usuarios de Guardian con la lista de UPN que manda Elea.
- **Certificado no confiable en las PC de Elea**: el navegador muestra una advertencia. Usar la CA
  interna de Elea, distribuida por GPO, o un certificado público.
- **Sesiones del Hub en memoria**: cada actualización cierra las sesiones abiertas. Avisar a los
  usuarios de la ventana.
- **Vencimiento del secreto** (máximo 24 meses): anotar la fecha y agendar la renovación. Cuando
  vence, solo falla el botón de Microsoft.
