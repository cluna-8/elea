# Retro — Fase 019 e2e hardening (srdev-claude)

**Fecha**: 2026-07-14 · **PR**: #2 · **Trayectoria**: 2 passes, 0 P1 en el último → fase "smooth", retro corta.

## Trayectoria de convergencia
| Pass | P1/High | P2 | P3 | Notas |
|------|----|----|----|-------|
| 1 | 2 | 2 | 3 | Codex(2 P1) + adversarial(7 confirmados). 3 minions paralelos (E2E, FIX-GW, FIX-EXT). |
| 2 | 0 | 2 | 0 | P1 resueltos; integración 153 passed. P2-1 fix (minion FIX-P2 → 156 passed); P2-2 deferido a 020. |

## Categorías de finding
- **Security/authz**: 2 (master-key PROXY_ADMIN bypass; key-format misroute). Ambos HIGH.
- **DLP/masking correctness**: 3 (inspect trunca a 8000; fetch-hook fail-open body no-string; catch reenvía crudo).
- **API contract/consistency**: 2 (X-Sentinel-Key descartada en helpers; audit count).
- **Robustez**: 1 (500 con text no-string).
- **Extension threat-model**: 1 (postMessage forjeable → documentado, no "fixeable" en MV3).

## Scope assessment
- Split de minions **correcto**: E2E (tests/e2e/), FIX-GW (backend Python), FIX-EXT (extensión JS) → **cero solape**, merges limpios. FIX-P2 como wave 2 acotada.
- 3-4 minions fue el sweet spot; ninguno tocó un archivo forbidden.

## Deviations from spec (positivas)
- **Minion E2E corrigió una debilidad de MI coord doc**: el assert central de T3 ("no contiene 'clave desconocida'") no discriminaba (una key válida desviada a byok tampoco la emite). Lo fortaleció con un discriminador grounded en probes en vivo. → Lección: los asserts del coord doc deben probarse por su capacidad de DISCRIMINAR, no solo describir la conducta esperada.

## Patterns to promote → CLAUDE.md (aparecen cross-spec)
1. **Convención `sk-sentinel-` de virtual keys es un invariante cross-spec**: el seed path (013 `seed_client`) y el online path (014 `keys.py`/`ai_engine_client`) DEBEN emitir el mismo formato, porque el ruteo del gateway (019) y la exclusión load-bearing `x-sentinel-*` lo asumen. Un finding HIGH nació de que divergían. → Regla candidata: "toda emisión de virtual key produce `sk-sentinel-…`; el ruteo por prefijo lo asume."
2. **Nunca fallback a master key desde una ruta triggereable por cliente** (fail-closed duro). Aplica a cualquier proxy futuro.
3. **Doble gate de review (Codex + adversarial multi-agente) es complementario**: Codex vio el master-key; el adversarial vio el key-format misroute (que Codex no). Mantener ambos como gate de deploy vale la pena.

## Qué cambiaría la próxima vez
- Poner los asserts del coord doc con su **discriminador explícito** desde el arranque (no solo "no contiene X"), para no depender de que el minion lo detecte.
- Para specs con superficie de navegador: el e2e vivo de la extensión necesita el navegador del usuario — planear esa verificación como paso manual explícito desde el spec, no como sorpresa al final.
