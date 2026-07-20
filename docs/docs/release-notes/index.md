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

!!! note "Cómo leer los estados"
    Las páginas de esta doc marcan cada capacidad con 🟢 HOY / 🟡 PARCIAL / 🔵 OBJETIVO.
    Lo que no está 🟢 no se vende como hecho — ese es el contrato de honestidad de esta
    documentación.
