# Organización: router, reglas y runbooks

Fuente: `Structure/ManosALaObra-SentinelGuardian.html` v4 (05-ago-2026) + estado real del repo.

## Router de responsabilidades

| Situación | Responsable | Notas |
|---|---|---|
| Bug report de cliente o partner | JF | clasifica; instalación/update se deriva a Falime |
| Instalación de cliente nuevo (bundle, sede, IT) | Falime | JF solo si aflora bug de producto |
| Corte de release (vX.Y) | Ambos | JF define contenido; Falime buildea, pinnea digests y publica |
| Zero-day / parche urgente | Ambos | JF parchea código; Falime fabrica bundle-parche y distribuye |
| Emisión/renovación de licencia (.lic, cupos, true-up) | Falime | gate de Cristian si toca custodia o claves |
| Extensión deja de enmascarar tras cambio del proveedor | JF | adapters y rutas de API |
| Distribución de extensión brandeada | Falime | render de marca, zip, manifest.key, CWS |
| Fallo de arranque del stack / fallo de update | Falime | runbooks, preflight, bundle |
| Alta de superficie nueva (Gemini web, MCP…) | JF | spike con evidencia + fila en matriz 019 |
| VPS demo: caída o actualización | Falime | infra; contenido de la demo es de JF |
| TLS / certificados en onboarding | Falime | trust-kit, cert modes |
| Docs para cliente final o partner | Ambos | JF contenido; Falime build brandeado + bundle |
| CI/CD y convención de ramas/releases | Falime | |
| Operabilidad del motor (alta de modelo, reload) | JF | feature del motor |

## Las 5 reglas de operación

1. **Puerta única de clientes**: todo reporte de cliente/partner entra por JF, que clasifica y deriva.
2. **Herencia**: trabajo de Falime sin commits ni PR que caiga en área de producto pasa a JF al 100% (incluye 023/#16). Lo que tenga PR abierto se termina o se traspasa explícitamente.
3. **Gate de custodia**: cambios en claves de firma, keyset o RBAC de firma requieren review de Cristian antes de merge.
4. **Fuente única de licensing**: `backend/src/licensing` es código de Guardian; Factory lo consume como librería, sin copias.
5. **CODEOWNERS**: todo PR que mueva ficheros entre áreas actualiza CODEOWNERS en el mismo PR.

Cambios que requieren a ambos departamentos: contratos-espejo motor↔backend (Redis keys, `_IDENTITY_SQL`, `layer_keys`) · formato bundle/MANIFEST · `api/internal.py` · rotación de `kid` del keyset (+ gate Cristian) · copias de engine-extensions por release · alta de imagen nueva (5 ubicaciones).

## Runbook: instalación / demo de cliente

Orden fijo (ejemplo real: demo Evidenze):

1. **Fran**: confirma tag/versión a instalar (ej. `checkpoint-camara-2026-08`) y la congela — no entra nada más para esa instalación.
2. **Cristian**: define políticas de compliance activas según país del cliente (policy pack).
3. **Falime**: emite la licencia (demo o real) — con gate de Cristian si toca custodia o claves (regla 3) —, crea perfil del cliente en `deploy/clients/` (branding, licencia, país/policy pack), arma bundle desde el tag, corre checks de release, instala. Documenta cada paso: cada instalación es ensayo del kit del partner.
4. Bug durante instalación → issue etiquetado `depto:guardian` (producto) o `depto:factory` (install). Fran no toca la instalación; Falime no parchea producto.

## Runbook: corte de release

1. JF declara contenido (qué specs/fixes entran) y verifica DoD (tests + docs verdes).
2. Falime buildea, pinnea digests, corre los 20 checks de `deploy/release/checks/`, taggea y publica.
3. Copias de engine-extensions y alta de imagen (5 ubicaciones) — checklist compartida.

## Plan de septiembre 2026 (referencia)

Objetivo: el partner instalando a todos los clientes posibles.

1. ~~JF rama instalable~~ — cumplido 04-ago (tag `checkpoint-camara-2026-08`; `dev-fran` jubilada).
2. Falime: CLI `sentinel-admin` MVP (install + license); custodia PKCS8 cifrada, traspaso de firma con review de Cristian. Spec 026 completa, implementación en cero.
3. Falime: Trust-kit TLS (PR #55 mergeado); pendiente pasada en VM Windows real.
4. Falime: camino de update v0 (bundle-parche + procedimiento; hoy solo reinstalación fresca).
5. Ambos: kit del partner (bundle base amd64, overlay por cliente, docs cliente final, agente con skills sobre la CLI, certificación 025).

P1 de producto para JF (además): #63/#64 masking Presidio (degradación silenciosa — prioridad seguridad), spec 033 engine reload sin restart, spec 034 rol auditor.

Fuera de alcance septiembre: Vendor Portal (oct+), Zarf/k3s, build farm, 023.
