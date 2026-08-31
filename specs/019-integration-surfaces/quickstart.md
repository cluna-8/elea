# Quickstart — Superficies de integración (spec 019)

Cómo enganchar cada cliente a Sentinel Guardian y ver el firewall en vivo. Requiere el stack
levantado (`docker compose up -d`) — backend en `localhost:8091`, motor en `localhost:4010`.

> El monitor común está en **http://localhost:8091/api/v1/gw/monitor** (todas las superficies
> empujan ahí, incl. la extensión con `surface="browser"`).

## 1. Claude Code — passthrough de suscripción (FUNCIONA, aguanta Agent)

La suscripción del cliente paga; Sentinel sólo firewallea.

```bash
export ANTHROPIC_BASE_URL="http://localhost:8091/api/v1/gw"
# (opcional) atribución para la auditoría — NO es credencial:
export ANTHROPIC_CUSTOM_HEADERS="X-Sentinel-Key: sk-sentinel-<tu-connection>"
claude   # tu OAuth de suscripción viaja verbatim a api.anthropic.com
```

El gateway detecta `subscription-passthrough` (no hay `sk-sentinel-…` en un header de auth), aplica la
política (AI-Act/secretos/mask/unmask) y reenvía el OAuth intacto.

## 2. VS Code / GitHub Copilot — byok (PARCIAL, sólo modo Ask)

El motor gobierna (cost tracking + budgets). Copilot no manda header de control → **auto-byok**.

```jsonc
// settings de la herramienta: base URL → el gateway; key = tu virtual key de Sentinel
"anthropic.baseUrl": "http://localhost:8091/api/v1/gw",
"anthropic.apiKey":  "sk-sentinel-<tu-connection>"
```

Si la herramienta no deja mandar la key por header (Copilot manda `x-api-key` vacío), usá el
**fallback key-in-URL** (atajo de demo): `…/api/v1/gw?k=sk-sentinel-<tu-connection>`.

- El gateway detecta la `sk-sentinel-…` → rutea al **motor LiteLLM** (que corre custom_auth + SentinelGuardrail).
- **Usá modo Ask.** En modo Agent con modelos no-Claude el tool-calling se rompe (limitación del
  modelo/cliente, no del gateway) — ver [compatibility.md](./compatibility.md).

## 3. Extensión de navegador (ChatGPT / Claude web) — FUNCIONA

1. **Cargar sin empaquetar**: Chrome → `chrome://extensions` → activar *Developer mode* → *Load
   unpacked* → elegir la carpeta `extension/` del repo.
2. **Conectar**: click en el ícono 🛡️ *Sentinel Guard* → pegar la virtual key `sk-sentinel-…` → *Connect*
   (valida contra `/gw/whoami`; sin key válida la extensión es **fail-closed** y bloquea el envío).
3. **Probar**: abrir ChatGPT o Claude.ai, escribir un prompt con un email y un DNI. Verificar:
   - lo que sale al backend de la web app lleva **placeholders** (`[EMAIL_ADDRESS_0]`, `[DNI_0]`),
   - la respuesta se muestra **des-enmascarada** en el DOM (valores reales),
   - en Claude.ai el **título** de la conversación también se des-enmascara,
   - el evento aparece en el monitor con `surface="browser"`.

> El default apunta a `http://localhost:8091/api/v1/gw`; se puede cambiar en el popup (campo *Gateway*).

## 4. Coexistencia (verificación E2E)

Con Claude Code (passthrough, `X-Sentinel-Key` de atribución) **y** Copilot (byok, `sk-sentinel-…` en la key)
apuntando al **mismo** gateway: Claude Code queda en passthrough (la exclusión de `x-sentinel-*` lo
protege) y Copilot va a byok. Ambos empujan al mismo monitor. Test que lo blinda:
`tests/integration/test_surface_routing.py`.

## Estados y límites

Ver la **[matriz de compatibilidad](./compatibility.md)** (Cursor=PARCIAL, Gemini=roadmap,
Claude Desktop=MCP-only) y las limitaciones conocidas (iframe, cap de inspección, key-in-URL).
