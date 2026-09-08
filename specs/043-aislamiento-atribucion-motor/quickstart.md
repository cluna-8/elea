# Quickstart — Validación de 043 (motor + backend + instalador)

Guía para probar la spec 043 de punta a punta **sin** la UI (el Hub Chat y el panel son la spec
044) — usando `curl`/`httpie` contra el backend y el motor directamente. Sirve como base del guion
de integración de la 044 (US6) una vez que ambas specs estén implementadas.

## Prerrequisitos

- Stack levantado localmente: `docker compose --profile rag up -d` (o el perfil que corresponda)
  desde la raíz del repo `elea`, con la migración nueva aplicada (`alembic upgrade head` dentro del
  contenedor `backend`).
- Dos usuarios de prueba creados (`account_type='person'`): `ana` y `luis`, ambos con presupuesto
  asignado (`Budget`), vía el flujo admin existente o `elea-installer/create-tester.sh`.
- Un admin autenticado (`admin`/contraseña del `.env`).
- Un CSV real con un nombre repetido en varias filas (usar el mismo tipo de archivo que reportó el
  cliente — varias filas con "Julián" separadas por más de 4000 caracteres entre sí).

## 1 — Aislamiento (US1 / contrato 1)

```bash
# Ana crea un espacio y lo puebla (vía el flujo existente de creación de workspace)
TOKEN_ANA=$(curl -s -X POST $BACKEND/users/login -d '{"username":"ana","password":"..."}' | jq -r .token)
curl -s -X POST $BACKEND/workspaces -H "Authorization: Bearer $TOKEN_ANA" -d '{"display_name":"Contabilidad"}'

# Luis lista espacios: NO debe ver "Contabilidad"
TOKEN_LUIS=$(curl -s -X POST $BACKEND/users/login -d '{"username":"luis","password":"..."}' | jq -r .token)
curl -s $BACKEND/workspaces -H "Authorization: Bearer $TOKEN_LUIS"
# Esperado: lista vacía o sin "Contabilidad"

# Luis intenta acceder directo por id conocido -> 403, no 404
curl -s -o /dev/null -w "%{http_code}\n" $BACKEND/workspaces/<id-de-contabilidad> -H "Authorization: Bearer $TOKEN_LUIS"
# Esperado: 403

# Ana agrega a Luis como miembro
curl -s -X POST $BACKEND/workspaces/<id>/members -H "Authorization: Bearer $TOKEN_ANA" -d '{"username":"luis"}'
# Luis vuelve a listar: ahora SÍ ve "Contabilidad"
```

**Sin sesión** — ninguna de estas llamadas sin `Authorization` debe devolver datos:
```bash
curl -s -o /dev/null -w "%{http_code}\n" $BACKEND/workspaces
# Esperado: 401
```

## 2 — Enmascarado determinista (US3 / contrato 3)

```bash
DOC_ID=$(uuidgen)
# Simular 2 chunks del mismo CSV, cada uno con "Julián" en una fila
curl -s -X POST $BACKEND/gw/inspect -H "X-Sentinel-Key: $MASKING_KEY" \
  -d "{\"text\":\"nombre,edad\\nJulián,40\", \"tool\":\"quickstart\", \"document_id\":\"$DOC_ID\"}" | jq .masked

curl -s -X POST $BACKEND/gw/inspect -H "X-Sentinel-Key: $MASKING_KEY" \
  -d "{\"text\":\"nombre,edad\\nJulián,52\", \"tool\":\"quickstart\", \"document_id\":\"$DOC_ID\"}" | jq .masked
```
**Esperado**: el placeholder de "Julián" es idéntico en ambas respuestas.

```bash
# Otro documento (sin document_id compartido) -> placeholder DEBE diferir
curl -s -X POST $BACKEND/gw/inspect -H "X-Sentinel-Key: $MASKING_KEY" \
  -d "{\"text\":\"nombre,edad\\nJulián,40\", \"tool\":\"quickstart\", \"document_id\":\"$(uuidgen)\"}" | jq .masked
```

## 3 — Atribución y presupuesto (US2 / contrato 2)

```bash
# Presupuesto propio, autoservicio (sin sesión de admin)
curl -s $BACKEND/users/me/budget -H "Authorization: Bearer $TOKEN_ANA"
# Esperado: {"used_usd": ..., "max_usd": ..., "status": "ok"}

# Simular un pedido "en nombre de" Ana desde la llave de servicio
curl -s -X POST $BACKEND/gw/inspect -H "X-Sentinel-Key: $MASKING_KEY" \
  -H "X-Guardian-Acting-User: <user-id-de-ana>" \
  -d '{"text":"algo con un DNI 30123456","tool":"quickstart"}'

# Verificar en la vista de costos que el consumo quedó bajo Ana, no bajo la cuenta de servicio
curl -s "$BACKEND/costs/by-user" -H "Authorization: Bearer $TOKEN_ADMIN" | jq '.[] | select(.username=="ana")'
```

Agotar el presupuesto de Ana (repetir hasta superar su `max_usd`) y verificar:
```bash
curl -s -o /dev/null -w "%{http_code}\n" $BACKEND/gw/inspect -H "X-Sentinel-Key: $MASKING_KEY" \
  -H "X-Guardian-Acting-User: <user-id-de-ana>" -d '{"text":"otro pedido","tool":"quickstart"}'
# Esperado: 402
```

## 4 — Vistas sin ruido (US4 / contrato 4)

```bash
curl -s $BACKEND/users -H "Authorization: Bearer $TOKEN_ADMIN" | jq '.users | length'
# Esperado: NO incluye svc.anythingllm-provider ni svc.rag-masking

curl -s "$BACKEND/users?include_service=true" -H "Authorization: Bearer $TOKEN_ADMIN" | jq '.users[] | select(.account_type=="service")'
# Esperado: las 2 cuentas, con "purpose"

curl -s $BACKEND/costs/top-models -H "Authorization: Bearer $TOKEN_ADMIN" | jq '.[].model'
# Esperado: solo modelos reales (p. ej. azure-gpt-4o-mini), nunca "license" ni "chat-ui"
```

## 5 — Ciclo de vida de usuarios (US5 / contrato 5)

```bash
curl -s -X PATCH $BACKEND/users/<id> -H "Authorization: Bearer $TOKEN_ADMIN" -d '{"role":"compliance_officer"}'
# Verificar que email/username no cambiaron

curl -s -X DELETE $BACKEND/users/<id> -H "Authorization: Bearer $TOKEN_ADMIN"
# Esperado: 200 {"status":"deactivated",...}

curl -s -o /dev/null -w "%{http_code}\n" -X POST $BACKEND/users/login -d '{"username":"<baja>","password":"..."}'
# Esperado: 401 (mismo mensaje que credenciales inválidas)
```

## 6 — Branding (US6 / contrato 6)

```bash
grep -riE "litellm|anythingllm|presidio" <(curl -s $BACKEND/openapi.json)
# Esperado: 0 coincidencias (salvo lista de excepciones documentada en tasks.md)

curl -s $BACKEND/guardians -H "Authorization: Bearer $TOKEN_ADMIN" | jq '.[].name'
# Esperado: ningún nombre menciona "Presidio"
```

## Resultado esperado del quickstart

Los 6 bloques pasan sin intervención manual sobre una instalación levantada desde cero
(`docker compose up` + migración). Cualquier fallo acá bloquea el guion de integración de la spec
044 (US6) — no tiene sentido probar la UI sobre un backend que no pasa esto primero.
