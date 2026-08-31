# Uso seguro y auditado de IA

Esta plataforma es una **pasarela**: todo lo que su organización escribe hacia un modelo
de inteligencia artificial pasa antes por ella. La pasarela detecta los datos personales
del texto y los **enmascara** antes de que salgan hacia el modelo, deja **registro
auditable** de cada petición y permite **controlar el gasto** por persona y por equipo.

![Panel Principal de la pasarela, con métricas de peticiones, costo total, incidentes de datos personales y bloqueos](assets/screenshots/02-panel-principal.png)

## Qué resuelve

- **Protección de datos personales.** Nombres, documentos de identidad, teléfonos o
  direcciones se sustituyen por marcadores antes de enviarse al modelo. Cuando llega la
  respuesta, los datos originales se restauran localmente, de modo que quien consulta ve
  el texto completo aunque el modelo nunca lo haya recibido.
- **Trazabilidad.** Cada petición queda registrada con su origen, el modelo utilizado y
  las capas de seguridad aplicadas, sin guardar el texto del prompt ni datos personales
  en claro.
- **Control de costes.** Puede asignar presupuestos y límites de consumo a cada persona y
  a cada equipo, y consultar el gasto acumulado.
- **Un único punto de acceso.** Las personas usan el portal web, y las herramientas y
  aplicaciones se conectan con llaves de acceso emitidas por la propia organización.

## A quién va dirigida cada guía

| Si usted es… | Empiece por… |
| --- | --- |
| **Administrador** de la plataforma: da de alta personas, emite llaves, fija presupuestos y revisa la auditoría. | [Guía del administrador](admin/index.md) |
| **Usuario**: consulta la IA desde el portal, desde su navegador o desde sus herramientas. | [Guía del usuario](usuario/index.md) |

## Mapa de la documentación

- **[Primeros pasos del administrador](admin/index.md)** — primer acceso, recorrido del
  panel y checklist de puesta en marcha.
- **[Confiar el certificado en los equipos](admin/certificado.md)** — el paso de puesta
  en marcha que habilita el acceso por https y la extensión del navegador.
- **[Personas y equipos](admin/usuarios.md)** — crear equipos, registrar miembros y
  asignarles rol y perfil de cumplimiento.
- **[Llaves de acceso](admin/llaves.md)** y **[presupuestos](admin/presupuestos.md)** —
  emitir credenciales para herramientas y limitar cuánto puede consumir cada una.
- **[Modelos de IA](admin/modelos.md)** — qué modelos están disponibles en la pasarela y
  cómo añadir otros del catálogo.
- **[Auditoría](admin/auditoria.md)** y **[políticas de protección de datos](admin/politicas.md)** —
  consultar el registro de actividad y revisar qué se enmascara y qué se bloquea.
- **[Guía del usuario](usuario/index.md)** — el
  [asistente y las herramientas conectadas](usuario/conectar-herramienta.md), la
  [extensión del navegador](usuario/extension.md) y qué significan los
  [datos protegidos y los bloqueos](usuario/proteccion-datos.md).

!!! note "Soporte"
    Si algo no funciona como se describe aquí, escriba a **soporte@sentinel-dev.com**
    indicando qué pantalla estaba usando y a qué hora ocurrió.
