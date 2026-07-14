# Spec 019 — Notas de implementación

**Fecha**: 2026-07-14 · **Estado**: **US1 + US2 + US3 implementadas y verificadas** (las 3 P1);
**US4 + US5** entregadas como documentación (matriz + Gemini roadmap). Falta sólo el **E2E vivo
de la extensión** en ChatGPT/Claude.ai (requiere el navegador del usuario — ver quickstart).

## Qué se entregó

- **Foundational (T004/T005)**: research contra las fuentes reales (demo gateway 1162 líneas con
  auto-byok/key-in-URL/inspect/whoami; `basa-browser-dlp/` extensión). Criterios de estado de la
  matriz en [compatibility.md](./compatibility.md).
- **Reconciliación 014↔019 (clave)**: la 019 pide un gateway de **puerta única**. Mi 014 lo hizo
  passthrough-only. La resolución: el gateway ahora auto-rutea — `subscription-passthrough` (política
  del gateway + Anthropic) vs `byok` (**router fino al motor**, sin política, porque el motor ya corre
  custom_auth + BasaGuardrail). Esto evita el **doble-masking** del port literal del demo (cuyo motor
  no tenía guardrail) y mantiene el Principio VI: el gateway rutea, el motor gobierna byok.
- **US1 Claude Code passthrough** (T006-T011): ya estaba en 014; se agregó `X-Basa-Upstream` +
  detección por UA (copilot/vscode sumados al `TOOL_UA` compartido). Verificado live (OAuth verbatim →
  401 real de Anthropic).
- **US2 Copilot auto-byok** (T012-T018): `_BASA_KEY_RE` scan **excluyendo `x-basa-*`** (load-bearing),
  key-in-URL (`?k=…`), branch byok→motor. `count_tokens`/`models` honran auto-byok. Verificado live
  (byok → 401 de mi custom_auth = llegó al motor).
- **US3 extensión + endpoints browser** (T019-T025): `backend/src/api/inspect.py` (`GET /gw/whoami`
  fail-closed, `POST /gw/inspect` con `basa_guardian_policy` → `replacements`, `surface="browser"`,
  audit metadata-only). Extensión portada a `extension/` (6 archivos), base path ajustado a
  `/api/v1/gw`. El shape de `/inspect` coincide exacto con el `background.js` de la extensión.
- **US4 matriz** (T026-T028) + **US5 Gemini roadmap** (T029): [compatibility.md](./compatibility.md).
- **Polish**: [quickstart.md](./quickstart.md); onboarding-as-data (una superficie soportada = Connection).

## Verificación

| Caso | Resultado |
|---|---|
| Tests base_url (`test_surface_routing.py`) | passthrough→Anthropic, auto-byok→motor, exclusión `x-basa-*`, key-in-URL, X-Basa-Upstream, models auto-byok |
| Tests browser (`test_gw_inspect.py`) | whoami fail-closed, inspect mask + `replacements` reversibles, entities, empty-text |
| Unit (`test_tool_detection.py`) | UA→tool (claude/copilot/vscode/cursor), degradación honesta |
| Suite completa | **134 passed / 3 skip** (contra Postgres real) |
| Extensión | `node --check` OK en los 4 JS + manifest JSON válido |
| Live (HTTP real) | passthrough→401 Anthropic (`request_id`), byok→401 custom_auth (motor), key-in-URL→motor, `/gw/whoami` + `/gw/inspect` fail-closed 401 |
| Motor (contract+integration) | verdes tras sumar copilot/vscode + surface al monitor |

> **No verificado (requiere el navegador del usuario)**: el E2E vivo de la extensión en ChatGPT/
> Claude.ai (cargar unpacked, tipear PII, ver mask→unmask + título). El contrato backend
> (`/gw/inspect`/`/gw/whoami`) sí está testeado; la validación de adapters/DOM es manual (como el
> demo) — pasos en el quickstart. Tampoco un round-trip byok real (no hay provider key en dev).

## Decisiones tomadas

- **byok NO enmascara en el gateway** (el motor lo hace) — la diferencia clave con el port literal del
  demo. Documentado arriba y en el docstring de `gateway.py`.
- **`/gw/inspect` usa `basa_guardian_policy` (regex)**, no `PresidioService` (que acá es scaffolding).
  Presidio real = spec 016; el shape del endpoint no cambia.
- **`surface="browser"`** se agregó como campo opcional del evento de monitor (aditivo).
- **key-in-URL** marcada como atajo de demo (prod = SSO), igual que el demo.

## Qué queda

- **E2E vivo de la extensión** (manual, navegador del usuario) — quickstart §3.
- **Gemini web** (US5) = roadmap documentado (adapter + host + spike DOM-hook). No entregable de 019.
- **Secret-blocking en `/gw/inspect`**: hoy sólo enmascara PII (como el demo); bloquear secretos en la
  superficie browser es una mejora posible (el preview del monitor ya scrubbea secretos por C1).
