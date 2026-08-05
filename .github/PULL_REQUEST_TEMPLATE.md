## Qué hace este PR

<!-- 1-3 frases. Qué cambia y dónde. -->

## Por qué

<!-- Motivación: issue, feedback de piloto, riesgo. -->
Closes #

## Cómo probarlo

<!-- Pasos concretos para que el reviewer lo verifique. -->

## Checklist (Definition of Done)

- [ ] `pytest tests/ -q` verde
- [ ] Docs afectadas en `docs/docs/**` actualizadas · `make -C deploy check-docs` verde
- [ ] PR < 400 líneas netas y un solo propósito
- [ ] Labels `depto:guardian` / `depto:factory` puestas
- [ ] Si mueve archivos entre áreas: CODEOWNERS actualizado en este PR
- [ ] Si toca claves/firma/auth: review de Cristian solicitada
- [ ] Si es decisión estructural: ADR creado en `docs/adr/`
