# Data Model — 024 (sin esquema nuevo)

Esta feature no crea entidades ni migraciones. Toca dos estructuras existentes:

## Mapping de restauración (`pii_tokens`)

- **Qué es**: dict `placeholder → valor original` generado por el pre_call del guardrail
  al enmascarar (`policy.mask_body`). Formato de placeholder: `[TIPO_n_hash]`
  (`policy.PH_TYPE_RE`).
- **Dónde vive**: en el metadata-home del request (`litellm_metadata` en la ruta
  anthropic, `metadata` en el resto — `_metadata_home()`); `_pii_tokens_from()` ya lee
  ambos. **Jamás se persiste**: el audit logger lo scrubbea explícitamente (`_scrub`).
- **Ciclo de vida**: request → pre_call lo crea → post hooks lo consumen → muere con el
  ciclo. Sin cambios en esta feature; solo se consume donde hoy no se consumía.

## Evento de monitor (feed efímero + audit metadata-only)

- **Campos afectados** (hoy `null` en byok bridged): `tool` (UA detectado o tool_type de
  la Connection), `client` (username), `tenant` (slug); más `masked_entities` (conteos
  por tipo, sin contenido).
- **Origen de la identidad**: `UserAPIKeyAuth.metadata["basa"]` (custom_auth) → propagada
  por el proxy como `user_api_key_metadata` dentro del metadata-home del request. El fix
  es LEERLA del home correcto, no cambiar su forma.
- **Sin cambios de esquema**: la tabla audit y el shape del evento ya tienen estos campos.
