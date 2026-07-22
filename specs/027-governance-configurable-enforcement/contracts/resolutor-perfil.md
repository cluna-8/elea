# Contrato — Resolutor puro de perfil (`basa_guardian_policy`)

Contrato de `resolve_profile` + `apply_layers` en
`litellm/extensions/basa_guardian_policy.py` — el único archivo que los planos ya
comparten (`gateway.py:76`, `basa_guardrail.py:40`). Un resolutor, tres call-sites
(gateway passthrough, guardrail del motor, chat UI); si esto no es único, 027 se
implementa tres veces y SC-003 se vuelve infalsificable (research D3).

## Pureza y firma

1. **PURA = sin DB, sin servicios, sin I/O** — el mismo estándar que el módulo ya declara
   (`basa_guardian_policy.py:13-15`). Las decisiones del tenant (`config`) llegan ya
   leídas por el caller, donde ya hay sesión/SQL: `_resolve_attribution` en el gateway y
   el SQL de identidad + cache de `custom_auth` en el motor. Cero I/O nuevo en el camino
   caliente.
2. **`resolve_profile(mode, surface, config, *, surface_trusted, connection_overrides=None)
   -> Profile`** — determinista: mismos inputs ⇒ mismo `Profile` (FR-006).
   `mode ∈ {subscription, gateway-models}` — **el mismo token, carácter a carácter, que el
   CHECK de `governance_profiles.scope_value`** (data-model §1.2): el codominio de la función
   de mapeo ES el dominio de la tabla, sin traducción intermedia. `surface` es un `tool_type`
   del CHECK de la Connection o `None`; `surface_trusted` dice si proviene de la Connection
   (confiable) o del User-Agent (spoofeable) — ver #5. `config` son las filas de decisión del
   tenant (ausencia = heredar). `connection_overrides` es el override por-key para las capas
   que lo declaran (hoy solo `pii_masking` vía `redact_enabled`, D8), propagado **TRI-ESTADO
   desde el valor crudo de la columna**: `None` = sin override (la cascada sigue), `on`/`off` =
   decisión explícita de esa Connection. El caller NO puede colapsar el `None` a un default —
   el colapso actual de `custom_auth.py:149` (`... if ... is not None else True`) debe
   eliminarse, o toda Connection sin toggle presentaría un override de nivel Connection que
   tapa superficie/modo/tenant; el default se resuelve **dentro** del resolutor (último nivel,
   default de producto).
3. **El piso no es representable como apagado**: el `Profile` construye las capas
   `tier=floor` **adentro**, desde el registry `GOVERNANCE_LAYERS` (D1). No existe input
   — ni `config` vacío, ni filas maliciosas, ni `None` — que produzca un `Profile` sin el
   piso (SC-004 estructural). Test de propiedad: `∀ config: piso ⊆ resolve_profile(...)`.

## Precedencia canónica (FR-006)

4. El piso **no participa de la cascada** (siempre presente). Para las capas opcionales,
   de mayor a menor:

   ```
   Connection (override por-key)  >  superficie confiable  >  modo de conexión
     >  default de tenant  >  default de producto
   ```

   resuelta con `_first_not_none` y `NULL=heredar` — el contrato ya vigente de
   `context_resolution.py:23-27`, espejado en `custom_auth.py:86-90`. El nivel Connection
   es el toggle per-key **existente** (`redact_enabled`, absorbido por `pii_masking`, D8) —
   entra como `connection_overrides`, no como fila de `governance_profiles`.
5. **Relajar exige superficie confiable** (D5 refinada): una decisión `surface` que AGREGA
   (`on` sobre capa que el modo dejó apagada) aplica siempre. Una decisión `surface` que
   RELAJA (`off` sobre capa opcional — el caso insignia de D8: `pii_masking=off` para
   coding tools) aplica **solo si `surface_trusted=True`** (superficie = `tool_type` de la
   Connection, dato del admin). Con `surface_trusted=False` (superficie derivada del
   User-Agent, spoofeable), las filas que relajan se tratan como *heredar*: spoofear el UA
   no consigue relajación alguna. Las capas de piso no se relajan en ningún caso — no son
   representables como apagadas (#3).

   **Cierre del bypass `X-Basa-Redact`** (hallazgo ronda 2): el header por-request del
   gateway (`_resolve_redact`, `gateway.py:256-262`) hoy apaga el masking por encima del
   toggle de la Connection — un override controlado por el cliente, exactamente lo que esta
   regla prohíbe. Con 027 el header queda **solo en sentido restrictivo**: puede forzar
   `pii_masking=on` para ese request (agregar protección es siempre legal para señal no
   confiable); el valor "off" se **ignora** con telemetría. Ningún input por-request entra a
   la cascada como relajación. Cambio de comportamiento observable: se actualiza la entrada
   `X-Basa-Redact` del discovery (`gateway.py:666`) y se declara en el changelog del gateway.

## Los ejes: cómo entran, no cómo se adivinan

6. **Modo, jamás `upstream_mode` crudo** (D5): entra por la función de mapeo explícita y
   testeada desde el ruteo **efectivo**. Hoy es constante del plano: al policy-path del
   gateway solo llega suscripción (byok se rutea al motor **antes** de la política,
   `gateway.py:473-475`) y todo lo que llega al motor resuelve `gateway-models`. Ruta
   efectiva no mapeada ⇒ `gateway-models` — el modo sin protección upstream: se degrada
   hacia **más** capas, nunca hacia menos.
7. **Superficie y su procedencia**: la superficie de enforcement es el `tool_type` de la
   Connection (`ident['tool_type']` en el gateway con `X-Basa-Key`;
   `metadata['basa']['tool_type']` en el motor, `custom_auth.py:146-147`) →
   `surface_trusted=True`. Sin Connection resuelta, la señal de UA (`detect_tool`) puede
   usarse **solo** con `surface_trusted=False` (relajaciones inertes, #5). Superficie fuera
   del enum (Responses #28, extensión browser) ⇒ `None` → cae a la cascada desde
   `connection_mode`/`tenant_default` (fallback explícito, D5).

## `apply_layers` — aplicar el perfil y producir la atribución

8. **`apply_layers(profile, body, analyze=default_analyze) -> PolicyResult`** — pura, con
   el detector inyectado (mismo patrón `AnalyzeFn` existente). Generaliza la 4-tupla de
   `evaluate_request_policy` (`gateway.py:158`) agregando la atribución:

   ```
   PolicyResult = (block_reason | None, status, ph_to_orig, masked_entities,
                   applied_layers, blocked_by_layer)
   ```

   Orden de aplicación canónico (el del guardrail hoy, `basa_guardrail.py:74-101`):
   evaluación AI-Act → bloqueo de secretos → detección PII → enmascarado **solo si** la
   capa `pii_masking` está `on` en el perfil.
9. **D8 codificado en atribución, no en texto**: con `pii_masking=off`, la detección corre
   igual (piso) y `applied_layers` lleva `pii_detection` con su hallazgo y `pii_masking`
   con `status=skipped`. Esa combinación **es** el registro "PII detectada, no enmascarada
   por configuración" (FR-002) — la frase humana la renderiza la UI/monitor desde los
   códigos; el JSONB jamás lleva texto (C1).
10. **`applied_layers` es exhaustiva sobre el perfil**: TODA capa del `Profile` aparece con
    su status por-pedido (`applied|skipped|not_configured|requires_credential|delegated|
    degraded`) — también las que no corrieron. Sin esto, "no la aplicamos" y "no corrió"
    vuelven a ser indistinguibles (SC-003/SC-005). Shape del elemento:
    [evento-monitor-atribucion.md](./evento-monitor-atribucion.md) / data-model.md.
11. **`blocked_by_layer`** es el `layer_key` del registry de la capa que produjo el
    bloqueo, o `None` — jamás el nombre de display del guardián (editable y white-label;
    el antipatrón de `guardian_service.py:190` rompe la atribución histórica en un
    rename, D6).

## Paridad y evolución

12. **El contract test de paridad pasa a verificarse sobre el resolutor**:
    `tests/contract/test_route_parity.py` (nivel 1) deja de comparar
    `evaluate_request_policy` contra la lib "a mano" y pasa a assertar que **cada
    call-site** produce exactamente lo que `resolve_profile` + `apply_layers` producen en
    directo — verdicto, tipos enmascarados **y** `applied_layers`. Un call-site que
    aplique política sin pasar por `apply_layers` rompe la paridad por diseño.
13. **Enganche 015 sin romper el contrato**: la granularidad por grupo/cliente se integra
    insertando **dos niveles más en la misma lista** de `_first_not_none` — la firma, la
    pureza y los invariantes 3-5 no cambian; la posición exacta de esos niveles la define
    la 015 (el enum de `scope_type` de 027 queda cerrado, D2).
