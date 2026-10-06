# Contrato — Cara OpenAI genérica en Eleia (`/api/v1/gw/v1/chat/completions`, `/gw/v1/models`)

**Base**: el contrato de la 068 rige tal cual (Sentinel
`specs/068-politica-redireccionamiento-modelos/contracts/cara-generica.md`, `6a70855`). La puerta
`/gw/v1/chat/completions` la trae T-A (`9c17500` + `efb2c94`, HANDOFF Anexo A).

## Con la redirección apagada (US5 esc. 5, FR-053)

- Solo llave del producto; sin traducir formatos; la política de seguridad base del motor (bloqueos,
  secretos, enmascarado reversible, auditoría) se aplica igual que en `/gw/v1/messages`; se sirve el
  modelo pedido.
- Restauración de marcadores en streaming: la de Eleia (`f8118e7`, spec 050), no `9fe188f`.
- Sin llave virtual: `401` con `_openai_error` y texto neutro.

## Con la redirección encendida

| Pedido | Respuesta |
|---|---|
| `GET /gw/v1/models` sin `anthropic-version` | `{"object":"list","data":[{"id":"<alias>","object":"model","created":<ts>,"owned_by":"organization"}]}` solo con alias `face=openai_generic` publicados para el alcance (FR-055) |
| `POST …/chat/completions` con alias publicado | se reescribe al destino; stream y no-stream; tools; `model` de la respuesta = alias (FR-054) |
| alias inexistente para el alcance | `404`, `error.code = model_not_found`, texto neutro |
| ningún destino cumple la postura o `offregion_default = reject` | `403`, `error.code = region_not_allowed`, sin nombrar destinos |
| silencio del destino en stream | comentario `: keep-alive` cada ≤ 15 s (FR-056) |
| `max_tokens` hacia gpt-5+ en Azure/OpenAI | el guard lo pasa a `max_completion_tokens` y aplica el piso de 16 (HANDOFF §A.5) |

## Fuera del MVP

El modelo `auto` por esta puerta (`fd515ff`, `_resolver_auto`): sin él, el test
`test_listado_generico_suma_auto_para_los_servicios` se marca `skip` con referencia (HANDOFF §A.4).

## Harness de la prueba en vivo (SC-014)

Al menos dos de: opencode, Aider (modo OpenAI), Continue, Cline/Roo, Zed. Configuración: dirección
`https://<dominio>/api/v1/gw/v1`, llave virtual como API key, modelo = alias.
