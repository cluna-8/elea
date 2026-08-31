# Quickstart — validar 016 end-to-end

Prerequisito: stack levantado con el servicio `nlp-analyzer` nuevo agregado a `docker-compose.yml`
(ver `plan.md` Project Structure) y `NLP_ANALYZER_URL` seteada en `.env`.

```bash
cp .env.example .env      # + NLP_ANALYZER_URL si no viene con default en compose
docker compose up -d --build
```

## 1. Detección de PERSON sin prefijo (US1)

```bash
export ANTHROPIC_BASE_URL="http://localhost:8091/api/v1/gw"
claude -p "Juan Pérez tiene turno el jueves a las 10, confirmá el mensaje"
```
**Esperado**: la respuesta del modelo restaura "Juan Pérez" (visible al usuario); en
`http://localhost:8091/api/v1/gw/monitor` la entrada de esa request muestra una entidad `PERSON`
enmascarada — sin haber usado ningún prefijo tipo "paciente"/"doctor".

## 2. Enforcement BLOCK por tipo de entidad (US2)

En el panel (`http://localhost:8090`) → Seguridad → Política activa: setear `CREDIT_CARD: BLOCK`.
```bash
claude -p "Guardame esta tarjeta 4111 1111 1111 1111 para el pago"
```
**Esperado**: la request se rechaza (no llega respuesta del LLM); el monitor muestra el bloqueo con
motivo `blocked_entity_type` (tipo, no el número real).

## 3. Fail-closed si el NLP no responde (US3)

```bash
docker compose stop nlp-analyzer
claude -p "Hola, ¿cómo estás?"
```
**Esperado**: la request se rechaza con motivo `nlp_unavailable` — NO responde como si no hubiera PII
(no hay fallback silencioso a regex en el camino de producción; ver Nota de Contrato en `spec.md`
FR-003 sobre por qué el regex de dev/demo no es equivalente por región y nunca es el camino real).
```bash
docker compose start nlp-analyzer   # restaurar
```

## 4. Integridad ante coincidencias solapadas (US4)

```bash
docker compose run --rm --no-deps backend pytest tests/unit/test_sentinel_guardian_policy.py -k overlap -q
```
**Esperado**: el test de `resolve_overlaps` (nuevo, unit) pasa — texto sintético con rangos solapados
produce un único placeholder por rango disputado, sin corrupción.

## 5. Verificación de contrato (Presidio + libería PURA)

```bash
docker compose exec -T litellm python /app/extensions/contract_checks.py
```
**Esperado**: incluye las nuevas verificaciones de `resolve_overlaps`/`resolve_entity_action`/
`build_ad_hoc_recognizers` (contratos internos) y de conectividad al Analyzer (contrato HTTP externo),
sin romper las verificaciones existentes de spec 014.

## 6. Suite completa

```bash
docker compose run --rm --no-deps backend pytest tests/ -q
```
