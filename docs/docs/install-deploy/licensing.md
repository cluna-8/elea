# Licenciamiento

Licenciamiento offline por seats y postura oficial de IP del artefacto instalado. Complementa
la [guía de instalación](index.md).

**Leyenda de estado**:

| Marca | Significado |
|---|---|
| 🟢 **HOY** | Implementado y verificable en la versión actual del producto |
| 🟡 **PARCIAL** | Existe la base, falta endurecerlo para producción |
| 🔵 **OBJETIVO** | Roadmap / estado-objetivo, no existe aún |

!!! warning "Estado-objetivo"
    🔵 **Nada de esto está wireado hoy** (la primitiva criptográfica con soporte Ed25519
    está disponible en el backend, sin uso). Se resume acá para training y soporte;
    trátese como **roadmap de licenciamiento**, no como capacidad entregable hoy. La
    [postura de IP del artefacto](#postura-ip) sí **aplica hoy**: es postura de producto,
    no código.

## Modelo de licenciamiento offline

- **Seat = Connection activa.** Un seat consumido = una `APIKey` con `is_active=True` para el
  tenant. El conteo de seats se deriva del propio esquema de datos del producto, no de un
  servicio externo.
- **Licencia Ed25519 firmada.** El fabricante firma con su clave privada un artefacto de
  licencia (tenant/slug, N seats, fecha de expiración, features habilitadas). El despliegue
  verifica la firma con la **clave pública** embebida — no puede falsificarse sin la clave
  privada del fabricante.
- **Sin phone-home.** La verificación es **100% offline**: apta para on-prem y air-gapped. No
  hay llamada de vuelta al fabricante, no se filtran datos de uso del cliente. Coherente con
  el modelo de entrega: el fabricante no opera servidores del cliente.
- **Enforcement blando/duro (en definición).** El comportamiento al exceder seats o expirar
  la licencia (avisar vs bloquear altas de Connection) se define dentro del mismo roadmap de
  licenciamiento.

## Postura de IP del artefacto — respuesta canónica a "¿qué protección tiene la imagen instalada?" { #postura-ip }

Pregunta recurrente del ciclo de venta on-prem (hospitales incluidos): *"el equipo de IT del
cliente va a abrir la imagen y mirar el código — ¿qué protección tienen?"*. Respuesta oficial
de producto; usarla tal cual en training y preventa — es postura, **aplica hoy**.

**Lo que se responde (tres capas):**

1. **La imagen copiada no trabaja.** El producto exige una licencia firmada (Ed25519,
   offline) atada al tenant: sin ella no arranca ni crea Connections (fail-closed 🔵);
   moverla a otro sitio deja rastro verificable en la renovación (true-up firmado +
   auditoría hash-chained).
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
