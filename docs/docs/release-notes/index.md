# Release notes

Cada versión publicada del producto trae su propia documentación: usá el **selector de versión**
del encabezado para leer la doc de la versión que tenés instalada (la doc de `latest` puede
describir features que tu instalación todavía no tiene).

## 1.0 — release inicial

La primera versión entregable a distribuidores. Incluye:

- **Gateway seguro de IA** con enmascarado de PII/PHI por request y des-enmascarado en la
  respuesta (pipeline completo observable capa a capa).
- **Multi-tenant** con RBAC (administrador, oficial de compliance, cliente) y aislamiento por tenant.
- **Compliance operativa**: proyectos con base legal y nivel de riesgo (GDPR / EU AI Act),
  registro de DPAs, gestión de solicitudes DSR, políticas de retención y panel DPO.
- **Gobierno de costes**: budgets por key, grupo y tenant.
- **Integraciones**: superficies `base_url` (Claude Code, Copilot en modo Ask, Cursor chat/plan)
  y extensión de navegador (ChatGPT / Claude web). Ver la
  [matriz de compatibilidad](../integrations/index.md).
- **White-label**: marca como configuración en runtime (sin fork) para app y documentación.
- **Licenciamiento offline** por asientos (seats), con verificación criptográfica que jamás
  llama a casa, modo degradado documentado y evidencia de auditoría encadenada.
- **Deploy** reproducible: imágenes de producción pinneadas, instalación cloud (IaC, región EU
  por defecto) y camino on-prem/air-gapped por bundle.

## Redirección de modelos — adaptación para América 🟡

La línea América (perfil Argentina) suma la **redirección de modelos**, una política **apagada por
defecto** que permite servir lo que pide una herramienta con otro modelo elegido por el administrador.
Estado: implementada y con pruebas automatizadas con proveedor simulado; **la verificación en vivo
(Azure primero) está pendiente**, por eso toda la sección está 🟡. Incluye:

- **Dos caras**: la cara Claude (Claude Desktop y Claude Code) y la cara de formato de chat estándar
  (opencode, Aider, Continue, Cline/Roo, Zed). Ver [Integraciones](../integrations/index.md).
- **Enmascarado forzado por defecto**, de alcance completo (historial, herramientas y PDF con texto),
  con bloqueo de lo no analizable y analizador fail-closed: seudonimización reversible de
  identificadores detectados.
- **Residencia por región** (`AMERICAS`) con postura por defecto, relajaciones por región y por
  destino de cumplimiento, y reglas de habilitación explícita vacías de fábrica.
- **Caché**: marcadores de enmascarado estables por conversación, afinidad de sesión, marcas de
  caché del proveedor y una caché de análisis que evita repetir el trabajo.
- **Panel «Modelos»**: catálogo con ficha de cumplimiento y semáforo, ids publicados, reglas,
  residencia, kits por herramienta, prueba de fidelidad y costos.

Cambios visibles **aunque la extensión no esté activa**: el ítem del menú «Modelos & Ollama» pasa a
llamarse **Modelos**, y la pantalla de descubrimiento de la pasarela (`GET /api/v1/gw`) deja de
nombrar componentes internos. La puerta `POST /api/v1/gw/v1/chat/completions` figura ahora en la
matriz de integraciones.

Marco normativo: en esta línea rige la Ley 25.326 y los criterios de la AAIP; el GDPR y la EU AI Act
no rigen (ver [Compliance](../compliance/index.md)). Detalle y estado por pieza:
[Redirección de modelos](../administration/redireccionamiento.md).

!!! note "Cómo leer los estados"
    Las páginas de esta doc marcan cada capacidad con 🟢 HOY / 🟡 PARCIAL / 🔵 OBJETIVO.
    Lo que no está 🟢 no se vende como hecho — ese es el contrato de honestidad de esta
    documentación.
