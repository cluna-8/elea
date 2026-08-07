# Plantillas

## Brief de apuesta (Shape Up, 1 página máx.)

```markdown
# Apuesta: [nombre corto]
**Ciclo:** [fechas] · **Dev:** [Fran|Falime] · **Apetito:** [1|2] semanas

## Problema
[Qué duele hoy y a quién. 2-4 frases. Incluir evidencia: issue, feedback de piloto, riesgo.]

## Solución a grandes rasgos
[El "qué" sin el "cómo" detallado. El dev decide la implementación.]

## Límites (rabbit holes)
[Qué NO resolver aunque tiente. Ej.: "no tocar el formato del bundle", "UI mínima, sin pulido".]

## No-metas
[Explícitamente fuera de alcance.]

## Done cuando
[2-4 criterios observables. Ej.: "un modelo nuevo aparece sin reiniciar el stack y la UI lo refleja".]
```

## ADR (Architecture Decision Record, 1 página máx.)

Archivo: `docs/adr/NNNN-titulo-corto.md`, numeración secuencial.

```markdown
# ADR-NNNN: [título de la decisión]
**Fecha:** AAAA-MM-DD · **Estado:** propuesto | aceptado | reemplazado por ADR-XXXX
**Decisores:** [Cristian, JF, Falime — quienes participaron]

## Contexto
[Qué situación obliga a decidir. 3-5 frases con hechos, no opiniones.]

## Decisión
[Qué se decidió, en una frase afirmativa. Ej.: "Los países se implementan como
perfiles de configuración en deploy/clients/, nunca como ramas ni forks."]

## Alternativas consideradas
[1-3 alternativas y por qué se descartaron, una línea cada una.]

## Consecuencias
[Qué se gana, qué se paga, qué queda prohibido a partir de ahora.]
```

## Mensaje de coordinación (Slack)

Estructura: contexto en 1 línea → pasos numerados con dueño y orden → dónde queda registrado.

```
[Contexto: qué y para cuándo.]
1. @persona — [acción concreta] [gate/dependencia si aplica]
2. @persona — [acción concreta]
3. ...
Bugs/decisiones que salgan de esto → issue con depto:guardian / depto:factory. Decisión estructural → ADR.
```

## Issue mínimo

```markdown
**Qué pasa / qué falta:** [1-3 frases]
**Dónde:** [archivo, servicio, cliente afectado]
**Evidencia:** [log, screenshot, link a Slack]
Labels: depto:guardian | depto:factory · [P1|P2|P3]
```
