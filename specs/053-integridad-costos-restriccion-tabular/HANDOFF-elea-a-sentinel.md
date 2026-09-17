# Handoff — spec 053 (Elea) para llevar a Sentinel

**Fecha**: 17-sep-2026. **Origen**: `github.com/cluna-8/elea`, rama `050-ia-hub-conector-motores`
(sin commitear al momento de este handoff — ver `git diff` local antes de portar). **Destino**:
`cluna-8/sentinel` (producto base, "Guardian"). **Instalador**: no toca `elea-installer`.

Esta spec cierra el pendiente #3 del [CHANGELOG de la spec 050](../050-ia-hub-conector-motores/CHANGELOG.md#estado-al-cierre-14-sep-2026-y-pendientes)
("Atribución de gasto por persona en el engine") y el punto 4.4 del
[handoff de la 050](../050-ia-hub-conector-motores/HANDOFF-elea-a-sentinel.md#4-decisiones-de-diseño-que-sentinel-debe-conocer)
("el gasto de los motores cae en la cuenta `svc.*` porque la fila de éxito del engine no guarda
`acted_for_user_id`") — ambos ya anotados como deuda conocida el 14-sep. **Es código 100% de la
base**, no de la localización argentina: afecta a cualquier instalación (Sentinel incluido) por
igual, y solo se implementó acá porque acá es donde el cliente (Tomás Mc Nally, mail 16-sep) lo
reportó primero. Misma regla que ya se aplicó al fix del paracaídas `latam_ar`
(`specs/README.md` §3): la sesión de Sentinel lo toma por merge, no reescribe un gemelo.

---

## 1. Qué se hizo (solo la User Story 1, portable hoy)

| Pieza | Dónde | Qué corrige |
|---|---|---|
| Atribución en el camino de ÉXITO del logger de auditoría | `litellm/extensions/sentinel_audit_logger.py::_log` | Agrega `acted_for_user_id` al `entry` — hasta ahora solo lo tenía el camino de bloqueo (`sentinel_guardrail.py`, fix del 9-sep). El gasto por usuario real de tráfico que pasa por el motor quedaba invisible (atribuido a la cuenta de servicio). |
| Resolución del grupo real en el desglose de costos | `backend/src/api/costs.py::by_group` | `LEFT JOIN users` vía `COALESCE(acted_for_user_id, user_id)` antes de resolver el grupo, mismo criterio que ya usaba `by_user`. Antes usaba `a.user_group_id` crudo (el de la Connection, casi siempre `NULL`) — el gasto de un usuario con grupo asignado nunca aparecía bajo su grupo. |
| Precio de respaldo desalineado | `backend/src/services/budget_service.py::MODEL_PRICING` | Agrega `azure-gpt-5.1-chat` ($1.25/$10 por millón) y `azure-gpt-5.4-mini` ($0.75/$4.50 por millón) — sin ellos, cualquier pedido que cayera al fallback (header nativo de costo no disponible) se facturaba al `default` genérico ($5/$15), de 1.5x a 6.7x el precio real. **Ojo al portar**: estos dos nombres de modelo (`azure-gpt-5.1-chat`/`azure-gpt-5.4-mini`) y sus precios son específicos del catálogo de Elea (`litellm/config.yaml`) — Sentinel debe agregar las entradas que correspondan a SU catálogo real, no copiar los nombres/precios literales. Lo que sí es portable tal cual es el patrón: (a) mantener `MODEL_PRICING` espejado con los `model_info.input_cost_per_token`/`output_cost_per_token` puestos a mano en el `config.yaml` propio, y (b) el `logger.warning` nuevo. |
| Traza del fallback genérico | `backend/src/services/budget_service.py::calculate_cost` | `logger.warning` cada vez que un modelo cae al `default` — antes era silencioso, así que el bug de precio pudo estar activo meses sin que nadie lo viera. |

Diagnóstico completo, con file:line y el hallazgo adicional (LiteLLM nativo no resuelve esto,
justificación de por qué no migrar) en [`spec.md`, User Story 1](spec.md#user-story-1---atribución-y-precisión-del-gasto-por-usuario-y-por-grupo-priority-p1--🟢-implementada-17-sep).

**No incluido en este handoff** (US2/US3 de la spec 053, sin implementar todavía): el campo de
precio manual al alta de modelo, el reload periódico del cost map de LiteLLM, y la restricción de
`.csv`/`.xlsx` en el chat RAG — esta última específica del Hub de Elea, revisar si aplica a
Sentinel antes de portar.

---

## 2. Qué es portable a Sentinel tal cual (cherry-pick)

Sin commit todavía en `elea` al momento de este handoff — portar por diff, no por hash de commit:

```bash
git diff -- litellm/extensions/sentinel_audit_logger.py backend/src/api/costs.py \
  backend/src/services/budget_service.py backend/tests/integration/test_costs_by_group_attribution_053.py
```

- `sentinel_audit_logger.py` y `costs.py`: **portar tal cual**, sin cuidados — no dependen de
  nada específico de Elea.
- `budget_service.py`: portar el patrón (comentarios, `logger.warning`, estructura), pero cargar
  los nombres y precios de modelo que correspondan al catálogo real de la instalación de Sentinel
  que se esté actualizando — verificar `litellm/config.yaml` de esa instalación antes de copiar.
- El test de integración `test_costs_by_group_attribution_053.py` es portable tal cual — usa
  fixtures genéricos (`User`, `Group`, `AuditLog`), no depende de nombres de modelo de Elea salvo
  el string `"azure-gpt-5.1-chat"` en el payload de la fila de prueba, que es solo un valor libre
  de `model` (no se valida contra el catálogo) — no hace falta cambiarlo, pero puede reemplazarse
  por cualquier modelo real de Sentinel sin afectar el test.

---

## 3. Cómo verificar después de portar

```bash
cd backend
export POSTGRES_HOST=localhost POSTGRES_PORT=5433 POSTGRES_USER=<el de esa instalación> \
       POSTGRES_PASSWORD=<...> POSTGRES_DB=<...>
PYTHONPATH="$PWD/..:$PWD/../litellm:$PYTHONPATH" .venv/bin/python -m pytest -q \
  tests/integration/test_costs_by_group_attribution_053.py \
  tests/integration/test_costs_by_user_attribution_043.py \
  tests/unit/test_budget_precision.py \
  tests/unit/test_sentinel_guardrail_acted_for_user_043.py
```

Verificado en Elea el 17-sep **por mutación**: revertido el fix de `costs.py`, el test nuevo pasó
a fallar; reaplicado, vuelve a pasar. 45 tests relacionados en verde, sin regresiones. Recomendado
repetir la misma verificación por mutación al portar, no solo confiar en que el diff aplica limpio.

---

## 4. Pendiente que este handoff NO cierra (para el roadmap de Sentinel)

- User Story 2 de la spec 053 (tarifario: precio manual al alta de modelo vía los campos nativos
  de `model_info` de LiteLLM, más `POST /schedule/model_cost_map_reload` programado) y User
  Story 3 (restricción de `.csv`/`.xlsx` en el chat RAG) — ninguna de las dos implementada
  todavía en Elea; ver `spec.md` para el diseño completo antes de decidir si aplican a Sentinel.
- El hallazgo documentado y sin resolver de los dos sistemas de tracking de costo que pueden
  divergir (spend nativo de LiteLLM vs. `audit_logs` propio) — sigue abierto en ambos productos.
