# tech-team

Documentos de arquitectura y organización del equipo. Standalone: se abren con doble clic, sin servidor. Botón de tema claro/oscuro arriba a la derecha.

| Doc | Contenido | Artifact (versión viva) |
|---|---|---|
| [ArquitectOverview-SentinelGuardian.html](ArquitectOverview-SentinelGuardian.html) | El producto en un vistazo, fábrica y ciclo de vida, planos de arquitectura, Vendor Portal, canales, módulos y niveles | https://claude.ai/code/artifact/3ca103b8-65c1-4bce-8e12-26c64faef3ce |
| [ManosALaObra-SentinelGuardian.html](ManosALaObra-SentinelGuardian.html) | Departamentos y responsabilidades: mapa de áreas, router de responsabilidades, reglas de operación, plan de septiembre | https://claude.ai/code/artifact/ecfd1cc0-ba63-494b-aa39-6cd389c08539 |
| [Clientes-SentinelGuardian.html](Clientes-SentinelGuardian.html) | Clientes y canales: matriz de protección por canal + catálogo 3rd-party (integrados, en camino, fuera de alcance) | https://claude.ai/code/artifact/37b0aaf9-df01-425b-ade1-5557c1173021 |
| [EcosystemOverview-SentinelGuardian.html](EcosystemOverview-SentinelGuardian.html) | **Depto Guardian App Ecosystem**: mapa del stack con logos (Python vs JavaScript, Docker), el capítulo browser + matriz de navegadores, flujo de soporte/bugs, los 14 módulos con estado real | https://claude.ai/code/artifact/bca9be7f-55ff-45ce-9c49-10011c924a36 |
| [TechTree-SentinelGuardian.html](TechTree-SentinelGuardian.html) | **Tech Tree Guardian**: Fase 0 (la promesa, nodo por nodo) + examen de gates 125/250/500, Fases 1-2 bloqueadas, ciclos para el betting, preguntas abiertas | https://claude.ai/code/artifact/36b67156-c690-4535-b394-8091ab00f5ac |
| [Licencias-SentinelGuardian.html](Licencias-SentinelGuardian.html) | **El ciclo de las licencias**: las dos llaves (firma vs evidencia), emisión→entrega→verificación offline→seats→degradado→true-up, evolución script→CLI 026→portal, cicatrices del piloto | https://claude.ai/code/artifact/e854bdc5-124e-449d-b40b-71dd4e80177f |
| [RunbookCamara-SentinelGuardian.html](RunbookCamara-SentinelGuardian.html) | **Runbook install Cámara (as-built 30-jul)**: topología delorean/t800, los 10 pasos, los NUNCA, troubleshooting exprés, soporte y pasar-un-fix; sin credenciales (dote a Factory) | https://claude.ai/code/artifact/6f1cffaa-1e9c-4497-8c1e-d86edc83e361 |
| [DevFlow-SentinelGuardian.md](DevFlow-SentinelGuardian.md) | **DevFlow depto Guardian**: operativa propia encima del CONTRIBUTING — orquestación con agentes (Fable/Opus 5), SDD con speckit, testing (código nuevo = tests nuevos), codex-gate y review adversarial, reglas del modo autónomo | — (solo .md) |

La metodología canónica del equipo vive en **`Structure/`** (dueño Cristian, PR #80): ManosALaObra v4 + skill `guardian-metodologia` v2 + copia del CONTRIBUTING — la copia de ManosALaObra de esta carpeta es de referencia visual. Nota: los dos docs nuevos (05-ago) son de alcance **solo departamento Guardian**; el ArquitectOverview del 31-jul es el mapa completo pre-departamentos (histórico). La fuente markdown del Tech Tree vive en el repo: `sentinel-guardian/specs/ROADMAP-pisos.md`.

Versiones **solo-datos** (.md limpio, mismas tablas sin narrativa — para reutilizar en presentaciones/diseño): [EcosystemOverview-SentinelGuardian.md](EcosystemOverview-SentinelGuardian.md) · [TechTree-SentinelGuardian.md](TechTree-SentinelGuardian.md).

Última actualización: 2026-08-07.
