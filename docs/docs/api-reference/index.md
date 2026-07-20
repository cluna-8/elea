# API reference

Referencia de la **API de administración e integración** del producto. Se genera en el
build **desde el esquema OpenAPI del backend** (single-source): no hay páginas de
endpoints escritas a mano y la referencia no puede derivar del código.

- La **API de gateway** que usan las herramientas integradas (superficie `base_url`)
  vive bajo `/api/v1/gw` — el detalle operativo está en
  [Integraciones](../integrations/index.md).
- Las **variables de configuración** de una instalación están en
  [Configuración](configuration.md) (generada de la plantilla de entorno del producto).

!!! tip "Probar contra tu instalación"
    El explorador de abajo es interactivo: apuntalo a tu instancia con el botón
    *Servers* y autorizá con tu key de administración. Nada de esta página llama a
    servicios externos — el explorador y el esquema viven en este mismo sitio.

<swagger-ui src="./openapi.json"/>
