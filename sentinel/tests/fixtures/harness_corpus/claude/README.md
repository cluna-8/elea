# Corpus de pedidos de las herramientas Claude (T031)

Pedidos **sintéticos** con la forma que mandan Claude Code, Claude Desktop (Chat y sondeo de arranque)
y Cowork a `/gw/v1/*`. Sin datos de personas ni credenciales reales; las llaves son literales de prueba.

| Archivo | Qué reproduce |
|---|---|
| `claude_code_messages_beta.json` | `POST /v1/messages?beta=true` con stream, herramientas, razonamiento, `context_management`, `cache_control`, cabeceras `anthropic-beta`, `safeguards` y un campo desconocido (evidencia de elea del 6-oct) |
| `claude_code_count_tokens.json` | `POST /v1/messages/count_tokens?beta=true` |
| `claude_desktop_sondeo.json` | sondeo de arranque `max_tokens: 1`, llave por `x-api-key` |
| `cowork_multiturno.json` | varios turnos, razonamiento firmado ajeno, captura en `tool_result`, `system` intermedio |
| `claude_code_stream_largo.json` | respuesta en stream de un destino traducido (razonamiento, texto largo, herramienta, uso) |

Se leen con `sentinel/tests/corpus_claude.py` (`load(nombre)`, `sse(...)`). Cada archivo tiene `body`,
`headers`, `path` y `query` (los de stream tienen `events`). La forma de un pedido nuevo de una
herramienta se agrega acá, nunca en el test.
