# Licenciamiento

Licenciamiento offline por seats y postura oficial de IP del artefacto instalado. Complementa
la [guía de instalación](index.md).

**Leyenda de estado**:

| Marca | Significado |
|---|---|
| 🟢 **HOY** | Implementado y verificable en la versión actual del producto |
| 🟡 **PARCIAL** | Existe la base, falta endurecerlo para producción |
| 🔵 **OBJETIVO** | Roadmap / estado-objetivo, no existe aún |

!!! success "Implementado hoy"
    🟢 **Todo lo de esta página es capacidad entregable hoy**: el licenciamiento offline
    está implementado y en **enforcement fail-closed** en la versión actual — verificación
    Ed25519 al arranque, gate de seats en las altas, estados de licencia, hard block
    opcional, endpoint de salud y auditoría encadenada. Sin phone-home. La
    [postura de IP del artefacto](#postura-ip) aplica además como postura de producto.

## Modelo de licenciamiento offline

- **Seat = Connection activa.** Un seat consumido = una `APIKey` **activa y no expirada** para
  el tenant. El conteo de seats se deriva del propio esquema de datos del producto, no de un
  servicio externo. **El seat no es el usuario**: desactivar un usuario client **no** libera
  seats; revocar sus Connections **sí**.
- **Licencia Ed25519 firmada, verificada offline al arranque.** El fabricante firma con su
  clave privada un artefacto de licencia (tenant/slug, N seats, fecha de expiración, features
  habilitadas). El despliegue verifica la firma con la **clave pública** embebida — no puede
  falsificarse sin la clave privada del fabricante.
- **Gate de seats fail-closed en las altas.** `POST /api/v1/keys` y `POST /api/v1/users`
  pasan por el gate de licencia: **402** con los seats agotados (el mensaje indica el
  remedio: revocar una Connection o ampliar la licencia) y **403** si la licencia no está
  activa.
- **Estados de licencia**: `active` / `grace` / `expired`, expuestos por el endpoint de
  salud.
- **Hard block opcional.** Con `BASA_LICENSE_HARD_BLOCK`, además de bloquear las altas se
  **cortan las rutas de servicio del gateway** (`/api/v1/gw/...`).
- **Salud de la licencia.** `GET /api/v1/health/license` responde en dos niveles: el tier
  **anónimo** devuelve sólo `{status, clock_rollback_suspected}`; admin y compliance officer
  ven el detalle completo.
- **Auditoría hash-chained + true-up firmado.** Los eventos de licenciamiento quedan en una
  auditoría **encadenada por hash** y la renovación se apoya en un **true-up firmado** — el
  rastro verificable que ancla la postura de IP.
- **Sin phone-home.** La verificación es **100% offline**: apta para on-prem y air-gapped.
  Jamás llama a casa — no hay llamada de vuelta al fabricante ni se filtran datos de uso del
  cliente. Coherente con el modelo de entrega: el fabricante no opera servidores del
  cliente.

## Postura de IP del artefacto — respuesta canónica a "¿qué protección tiene la imagen instalada?" { #postura-ip }

Pregunta recurrente del ciclo de venta on-prem (hospitales incluidos): *"el equipo de IT del
cliente va a abrir la imagen y mirar el código — ¿qué protección tienen?"*. Respuesta oficial
de producto; usarla tal cual en training y preventa — es postura, **aplica hoy**.

**Lo que se responde (tres capas):**

1. **La imagen copiada no trabaja.** El producto exige una licencia firmada (Ed25519,
   offline) atada al tenant: sin licencia activa no da de alta Connections ni usuarios y el
   hard block corta las rutas de servicio (fail-closed 🟢, implementado hoy); moverla a otro
   sitio deja rastro verificable en la renovación (true-up firmado + auditoría
   hash-chained, 🟢).
2. **El contrato es el ancla.** EULA vía distribuidor con no-reverse-engineering,
   no-redistribución y derechos de auditoría — el mismo modelo con el que operan GitLab EE
   (cuyo código enterprise es literalmente público), Grafana Enterprise o Metabase EE. El
   estándar on-prem del mercado es ese: el código se puede ver; usarlo sin licencia es
   incumplimiento contractual.
3. **El valor está en el stream, no en el código congelado.** Librería de compliance viva
   (AI Act, recognizers por región), parches, certificación y soporte del fabricante. Una
   copia es un producto de compliance congelado, sin licencia ni respaldo — exactamente lo
   que un DPO de entorno regulado no puede firmar.

**El giro a favor**: que el hospital inspeccione la imagen es *bueno para la venta* — va a
verificar que el sistema **no exfiltra nada** (0 egress en air-gap, auditoría metadata-only,
sin phone-home). La transparencia de comportamiento es argumento de confianza; ofrecerla
proactivamente (SBOM en v2 vía Zarf — ver [Infraestructura](infrastructure.md)).

**Lo que NO se promete jamás**: código "protegido", "encriptado" u ofuscado como mecanismo de
seguridad. Técnicamente no existe en hardware del cliente (una imagen se abre con dos
comandos; Python se descompila) y prometerlo deja mal parado al canal ante el primer pentest
del propio cliente. Si el canal pide "algo más", existe un pack de **fricción** opcional
(imágenes sin fuentes ni tests, bytecode) — se ofrece como prolijidad del artefacto, nunca
como protección.
