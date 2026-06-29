# Contract: LiteLLM Management API

**Base URL interna**: `http://litellm:4000`
**Auth**: `Authorization: Bearer {LITELLM_MASTER_KEY}`

---

## POST /team/new
Crea un team en LiteLLM.

**Request**:
```json
{ "team_alias": "Cardiología", "max_budget": 50.0, "budget_duration": "30d" }
```
**Response**:
```json
{ "team_id": "team_abc123", "team_alias": "Cardiología", "max_budget": 50.0 }
```
**Guardamos**: `litellm_team_id = team_id`

---

## POST /user/new
Crea un usuario en LiteLLM.

**Request**:
```json
{ "user_id": "dr.garcia@hospital.es", "max_budget": 10.0 }
```
**Response**:
```json
{ "user_id": "dr.garcia@hospital.es", "max_budget": 10.0 }
```
**Guardamos**: `litellm_user_id = user_id`

---

## POST /key/generate
Genera una virtual key.

**Request**:
```json
{
  "key_alias": "key-cardiologia-prod",
  "team_id": "team_abc123",
  "user_id": null,
  "max_budget": 50.0,
  "budget_duration": "30d",
  "models": ["azure-gpt-4o", "gemini-1.5-flash"]
}
```
**Response**:
```json
{ "key": "sk-abc123xyz...", "key_alias": "key-cardiologia-prod", "expires": null }
```
**Guardamos**: `litellm_key_token = key[:10]`, `key_hash = sha256(key)`, `key_preview = "sk-...{key[-6:]}"`
**Mostramos una sola vez**: `plain_key = key`

---

## GET /key/info?key={litellm_key_token}
Consulta info y gasto de una key.

**Response**:
```json
{
  "info": {
    "key": "sk-abc123...",
    "spend": 1.2345,
    "max_budget": 50.0,
    "models": ["azure-gpt-4o"],
    "team_id": "team_abc123"
  }
}
```

---

## GET /team/info?team_id={litellm_team_id}
Consulta info y gasto de un team.

**Response**:
```json
{
  "team_id": "team_abc123",
  "team_alias": "Cardiología",
  "spend": 12.50,
  "max_budget": 50.0,
  "budget_reset_at": "2026-07-29T00:00:00Z"
}
```

---

## GET /user/info?user_id={litellm_user_id}
Consulta info y gasto de un usuario.

**Response**:
```json
{
  "user_id": "dr.garcia@hospital.es",
  "spend": 0.50,
  "max_budget": 10.0
}
```

---

## DELETE /key/delete
Revoca una key.

**Request**:
```json
{ "keys": ["sk-abc123xyz..."] }
```
**Response**:
```json
{ "deleted_keys": ["sk-abc123xyz..."] }
```
