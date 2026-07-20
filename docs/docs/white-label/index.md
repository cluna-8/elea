# White-label & branding

La marca blanca es un principio de diseño del producto, no una capa de pintura: **el
despliegue de cada cliente es configuración + seed, nunca un fork**. Esta página describe qué
garantiza el core, qué contiene el branding pack y cómo se aplica la marca en runtime.

**Leyenda de estado**:

| Marca | Significado |
|---|---|
| 🟢 **HOY** | Implementado y verificable en la versión actual del producto |
| 🟡 **PARCIAL** | Existe la base, falta endurecerlo para producción |
| 🔵 **OBJETIVO** | Roadmap / estado-objetivo, no existe aún |

## Naming neutro en el core 🟢

El distribuidor revende la plataforma bajo su propia marca (o co-marca). Ningún nombre del
motor interno ni de proveedor LLM aparece en la UI, la API pública, los errores ni los logs:

- El código usa naming neutro (`AIEngineClient` / `engine_*`).
- Los errores que origina el motor se reescriben con naming neutro antes de exponerse al
  usuario.

Los nombres de proveedores LLM sólo aparecen donde son la superficie de integración del
operador (BYOK, configuración de modelos del perfil), nunca en la experiencia del usuario
final.

## Never fork 🟢

Sumar un cliente, un demo o una marca jamás implica tocar código:

- **Onboarding-as-data**: personas, herramientas, Connections y presupuestos se siembran
  desde el YAML del perfil por cliente — ver
  [Install / Deploy](../install-deploy/index.md).
- **Marca como configuración en runtime**: el branding se carga al arrancar, no se hornea en
  la imagen.
- **Un solo codebase**: el mismo código corre single-tenant on-premise y multi-tenant cloud;
  toda la variación entre clientes vive en configuración + seed.

## El branding pack 🟡

Por cada cliente/marca, el distribuidor arma un **branding pack**: nombre de producto,
tagline, logo, favicon, paleta de colores y datos de contacto de soporte del distribuidor. Se
aplica durante el flujo de instalación (paso de seed + branding) y se puede actualizar sin
recompilar.

🟡 El código ya es marca-neutro; el mecanismo de branding-por-config-en-runtime es lo que
falta formalizar.

### Marca como config en runtime

El frontend carga la configuración de marca al arrancar desde `/branding/brand.json`; los
assets (logo, favicon…) se montan en runtime junto a ese archivo — **jamás horneados** en la
imagen. Ejemplo de `brand.json` de un distribuidor ficticio:

```json
{
  "name": "Aegis AI Firewall",
  "tagline": "Su pasarela de IA corporativa",
  "logo": "logo.png",
  "supportContact": "soporte@aegis.example",
  "colors": {
    "primary": "#e63946",
    "background": "#10141f",
    "panel": "#1d2433"
  },
  "docsUrl": "https://docs.aegis.example/"
}
```

Además, el frontend resuelve la URL de la API solo a partir de `window.location.hostname`:
cambiar el dominio de un despliegue **no requiere recompilar** el frontend.

### Documentación por marca

El sitio de documentación de producto (este sitio) también es un artefacto de marca blanca:
se publica **una imagen por marca** (`basa-docs:<brand>-<version>`), 100% estática y
0-egress, que viaja dentro del bundle air-gapped junto al resto de imágenes pinneadas. El
contenido nunca se edita por marca — la marca entra como overlay de configuración sobre la
misma base.

## Qué no incluye la marca blanca

La marca blanca cubre naming y branding; no incluye promesas de código "protegido" u
ofuscado. La respuesta oficial a "¿qué protección tiene la imagen instalada?" está en
[Licenciamiento](../install-deploy/licensing.md).
