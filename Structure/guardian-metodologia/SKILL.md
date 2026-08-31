---
name: guardian-metodologia
description: Metodología de desarrollo y coordinación del proyecto Sentinel Guardian (GuardIAn-secure). Usar SIEMPRE que se pida organizar trabajo del equipo (Cristian, Fran/JF, Falime), armar el brief de un ciclo, revisar o redactar un PR, decidir si algo va como módulo/rama/repo/perfil de país, escribir un ADR, clasificar un issue por departamento, redactar mensajes de coordinación al equipo (Slack), o planificar releases, demos e instalaciones de clientes. También ante menciones de "metodología", "cómo lo organizamos", "quién hace qué", o nombres como Fran, Falime, Evidenze, Cámara, guardian-factory.
---

# Metodología Sentinel Guardian

Guía operativa para coordinar el desarrollo de Sentinel Guardian: 2 departamentos con jefe técnico cada uno, Cristian como gate de seguridad y dueño del "cómo". El objetivo permanente: `main` siempre instalable, producción en septiembre 2026, y decisiones escritas una sola vez.

## Estructura del equipo

- **Fran (JF) — Guardian App Ecosystem**: producto. Gateway/API, motor firewall, PII/NLP, extensión (la app), integraciones 3rd-party, UI panel, auditoría, gobernanza, multi-tenant, lib licensing, contenido de docs. Roadmap: `specs/ROADMAP-guardian.md`.
- **Falime — Install & Factory**: distribución. `deploy/` entero: bundles white-label, instalaciones, updates/parches, emisión de licencias, CLI `sentinel-admin`, CI/CD, TLS, perfiles de clientes, distribución de extensión. Roadmap: `deploy/ROADMAP-factory.md`.
- **Cristian — gate, no departamento**: review obligatorio en custodia/rotación de claves de firma, RBAC de firma y auth. Define el "cómo" (esta metodología) y prioriza los ciclos.

Las 5 costuras que requieren a ambos: extensión (JF app / Falime distribución), release (JF contenido / Falime empaqueta), zero-day (JF parche / Falime despliegue), docs (JF contenido / Falime entrega brandeada), bugs (JF triage / installs a Falime).

Para el router completo de "qué situación va a quién" y las 5 reglas de operación, leer `references/organizacion.md`.

## Ciclos de trabajo (Shape Up adaptado)

Ciclos de 2 semanas con fecha fija: se recorta alcance, nunca se mueve la fecha.

1. **Shaping (Cristian, antes del ciclo)**: definir problema, límites y no-metas de cada apuesta en un brief de 1 página (template en `references/plantillas.md`).
2. **Betting (Cristian + jefes, 30 min)**: decidir qué apuestas entran. Lo que no entra NO queda en backlog infinito: se re-apuesta o se descarta.
3. **Building (Fran/Falime, autonomía total dentro del brief)**: cada apuesta se descompone en tareas por el dev, no por Cristian.
4. **Cooldown (2-3 días)**: bugs, deuda, ADRs pendientes.

La operativa diaria (soporte Cámara, bugs de piloto) NO entra en apuestas: fluye por Kanban con límite de trabajo en curso.

## Ramas y PRs (GitHub Flow)

- `main` siempre instalable. Ramas cortas (< 3 días), una rama = una tarea, nunca una rama = una persona (la lección de `dev-fran`). Nombre: `NNN-descripcion-corta` si viene de spec, `fix/...`, `chore/...` si no.
- PR < 400 líneas netas **de código** (specs, planes SDD y docs quedan exentos del tope: son largos por diseño y no se recortan); si el código crece, partir. Título con Conventional Commits: `feat:`, `fix:`, `docs:`, `chore:`, `spec:`, con scope opcional (`feat(extension): ...`).
- Todo PR linkea su issue, usa el template del repo (qué/por qué/cómo probar), y respeta CODEOWNERS. PR que mueve archivos entre áreas actualiza CODEOWNERS en el mismo PR.
- Definition of Done: código + tests (`pytest tests/ -q` verde) + docs afectadas en `docs/docs/**` actualizadas + `make -C deploy check-docs` verde. Doc desactualizada = bug de severidad alta.

Detalle completo de convenciones y ejemplos: `references/convenciones.md`.

## Decisiones estructurales: módulo, rama, repo, país

Reglas por defecto (la excepción requiere ADR):

- **¿Repo nuevo?** Solo si despliega Y versiona de forma independiente con equipo propio. Hoy el único split aprobado es `guardian-factory` (deploy/). Todo lo demás: monorepo.
- **¿Plugin/complemento/integración nueva?** Módulo dentro del monorepo con dueño en CODEOWNERS. Nunca repo nuevo, nunca rama larga.
- **¿País nuevo (Argentina/España/Colombia...)?** NUNCA rama por país. País = perfil de configuración: policy pack de compliance (entidades PII locales: DNI/NIF/cédula), precios, idioma, en `deploy/clients/` + overlays. Un solo código, N perfiles. Si un país exige lógica inexistente → feature en `main` detrás de configuración, con ADR.
- **¿Feature grande?** Spec en `specs/NNN-*/` (proceso Spec-Kit ya vigente), luego ramas cortas por tarea.

Toda decisión estructural se registra como ADR de 1 página en `docs/adr/` (template en `references/plantillas.md`). Si Fran o Falime preguntan algo ya decidido, la respuesta es el link al ADR.

## Qué hacer cuando se invoca esta skill

Según lo que se pida (sirve igual desde el Claude de Cristian, Fran o Falime):

- **"Armar el ciclo" / priorizar**: leer roadmaps actuales (`specs/ROADMAP-guardian.md`, `deploy/ROADMAP-factory.md`), proponer apuestas por dev con el template de brief, respetando la división de departamentos.
- **Revisar/redactar un PR**: verificar contra `references/convenciones.md` (título, tamaño, issue, DoD, CODEOWNERS).
- **Decidir módulo/rama/repo/país**: aplicar las reglas de arriba y redactar el ADR.
- **Clasificar un issue**: usar el router de `references/organizacion.md`; etiquetar `depto:guardian` o `depto:factory`.
- **Mensaje de coordinación (Slack)**: identificar si toca una costura, asignar pasos por persona (Fran/Falime/Cristian) con orden y gates, tono directo y corto.
- **Instalación/demo de cliente**: seguir el runbook de `references/organizacion.md` §Instalaciones (Fran congela versión; Cristian define compliance del país; Falime emite la licencia —con gate de Cristian si toca custodia/claves— y arma perfil+bundle+instala).

Siempre responder en español, concreto, con nombres de archivos/specs/issues reales del repo.
