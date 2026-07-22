"""Monitor en vivo del firewall (spec 014 US3, FR-017) — la vitrina de las demos.

Sirve el feed efímero que el ``BasaAuditLogger`` (extensión del motor) publica en
Redis por request: qué herramienta/cliente/tenant, verdicto de compliance, entidades
enmascaradas y un preview **ya enmascarado** (lo que vio el upstream). Nada de PII
cruda (Constitución VIII: animación cosmética, datos reales; C1: sin texto sensible).

- ``GET /gw/monitor``  → página HTML autocontenida que refresca el feed (sin datos adentro).
- ``GET /gw/events``   → JSON del ring, **con sesión** (para la página y para integraciones).

**Spec 027 / T032 — un cambio en el acceso y tres en el render:**

0. **El feed dejó de ser público** (hallazgo A1 de la verificación adversarial de US2). Este
   router no declaraba ``dependencies``, así que ``GET /gw/events`` respondía 200 **sin
   ningún header ``Authorization``**. Con la 027 eso pasó de "metadata de tráfico" a algo
   peor: el evento suma ``applied_layers``/``blocked_by_layer`` —la postura de seguridad del
   tenant, qué capa bloqueó y cuáles no corrieron— y además el CRUD de gobernanza publicaba
   acá sus cambios de configuración con ``updated_by`` y ``tenant``. Es decir: lo que
   ``governance.py`` protege con ``require_role("admin")`` salía por un endpoint abierto,
   contradiciendo el invariante #1 de ``contracts/api-gobernanza.md``. Se cerró por los dos
   lados: gobernanza ya no publica configuración en ningún feed, y **los DATOS exigen
   sesión**, con los mismos roles que el nav le da a la página (``admin`` y
   ``compliance_officer``, ``App.tsx:29``).

   **Dónde va exactamente la dependencia, y por qué no en el ``APIRouter``**: el patrón del
   repo es declararla en el router (``guardians.py:17``) y acá se rompe ese patrón a
   propósito, una sola vez y documentado. ``GET /gw/monitor`` devuelve una **página HTML que
   un humano abre en una pestaña**, y un browser no puede poner ``Authorization`` en una
   navegación: con la dependencia en el router, la vitrina no quedaría protegida sino
   **muerta** —irreproducible en las demos y en los 5 lugares de la documentación que la
   citan—. Así que la sesión se exige en el endpoint que devuelve datos (``/events``) y el
   ``/monitor`` sirve un **cascarón sin ningún dato del tenant** (CSS, JS y el copy de las
   capas, que ya es público en el sitio de documentación). La página consigue su credencial
   del ``localStorage`` de la consola —mismo origen: Caddy en prod, el proxy de
   ``vite.config.ts`` en dev— y sin sesión no muestra tráfico sino cómo conseguirla. Si se
   prefiere cerrar también el cascarón, es mover ``_SESION`` al ``APIRouter``: una línea, y
   la vitrina standalone deja de existir.

1. **Fix de XSS (independiente de la 027, pero éste es el archivo).** El mapeo del feed
   interpolaba ``tenant``, ``tool``, ``client``, ``model``, el ``compliance_status`` y las
   entidades enmascaradas **crudos** dentro de ``innerHTML``; sólo ``masked_preview``
   pasaba por ``escapeHtml``. Todos esos campos vienen del tráfico: el ``tool``/``model``
   los elige quien hace el pedido y el ``tenant`` es un slug provisionado. Un valor con
   ``<img onerror=…>`` ejecutaba script **en la pantalla del Admin**, que es exactamente
   quien mira esta página. Ahora **todo** valor del evento pasa por ``esc()`` antes de
   entrar al HTML, y lo que va a un atributo ``class`` pasa además por ``cls()``, que
   recorta a ``[A-Za-z0-9_-]``: escapar no alcanza en contexto de atributo si el atributo
   se arma sin comillas o si el valor puede cerrar la comilla.
2. **Atribución por capa** (contrato ``evento-monitor-atribucion.md`` §8): el evento suma
   ``applied_layers`` y ``blocked_by_layer``, y la vitrina los lee para que un bloqueo se
   vea **atribuido a la capa que lo produjo** en vez de aparecer como un "BLOQUEADO"
   anónimo. Los eventos sin esos campos (productores previos a la 027) se marcan como
   *sin registro de capas* — no como "ninguna capa actuó": ausencia de dato y ausencia de
   protección son cosas distintas y confundirlas es la mentira que la feature borra.
3. **Los diccionarios del render no heredan de ``Object.prototype``** (segundo hallazgo de la
   misma verificación): las cuatro tablas de copy se indexan con valores que vienen del
   evento, y un objeto literal responde ``'toString'`` con una función. En el caso de
   ``STATUS`` eso rompía el destructuring y dejaba la vitrina en blanco: un pedido con
   ``compliance_status='toString'`` tumbaba la pantalla del Admin. Ver ``tabla()`` abajo.
4. **Un bloqueo del plano chat NO se veía como bloqueo** (residual de US2). ``chat.py``
   publica tres estados que la tabla ``STATUS`` no conocía —``blocked_by_policy``
   (``chat.py:694``, bloqueo por guardián: secreto o PII), ``blocked_residency``
   (``chat.py:805``, residencia de datos del proyecto)— y el gateway publica un cuarto,
   ``upstream_error`` (``gateway.py:829``). Los tres caían en el mismo fallback: **chip
   gris con la etiqueta cruda**. O sea que el pedido donde el firewall hizo su trabajo se
   pintaba como un evento neutro, indistinguible de uno que pasó. Pintar un bloqueo de
   gris es exactamente la clase de deshonestidad que la 027 existe para borrar — la misma
   familia del ``guardian_events`` fijo que decía ``PROXY`` pasara lo que pasara (D6).

   **El arreglo no es agregar tres filas a la tabla**, porque eso deja intacto el
   mecanismo que produjo el bug: una tabla que enumera valores y un fallback neutro para
   todo lo demás garantiza que el próximo call-site de bloqueo vuelva a nacer gris, y
   nadie se entera hasta la demo. Ahora la **familia visual** (``pass``/``blocked``/
   ``flag``/``error``) se deriva del nombre del estado —cualquier ``blocked_*``, conocido
   o no, se pinta como bloqueo— y la tabla solo aporta la **etiqueta legible**. El default
   deja de ser "neutro" y pasa a ser "lo que el nombre afirma". Ver ``estado()``.

   Contracara: ``blocked_guardian`` sigue en la tabla y **no lo emite ningún productor
   vivo** — se conserva porque el ring es efímero pero de 300 s, así que puede haber
   eventos de un despliegue anterior; borrar el copy los mandaría al fallback.

Constitución VII: el copy de las capas nombra **lo que protegen**, nunca el guardrail ni
el proveedor que las implementa; la clave que viaja en el evento es el ``layer_key`` del
registry (identidad estable), jamás ``guardian.name`` (editable por el cliente).
"""
import json

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from ..auth.rbac import require_role
from ..services.governance_catalog import LAYER_KEYS
from ..services.redis_client import get_redis

# Sesión exigida en TODO endpoint que devuelva datos del feed (hoy ``/events``; ver el punto 0
# del docstring para por qué no está en el ``APIRouter``, que es el patrón normal del repo).
#
# Los dos roles son los que el nav ya le da a la página "Firewall en vivo" (``App.tsx:29``), y
# ``compliance_officer`` está a propósito: mirar qué se bloqueó y por qué **es** su trabajo, y
# dejarlo afuera lo empujaría a pedir una cuenta admin —peor para la seguridad real que el
# permiso que se le negó—. No se usa ``require_authenticated()`` (el patrón de
# ``analytics.py:31``) porque el feed es **un ring compartido, sin filtro por tenant**: hasta
# que eso se scopee, cualquier sesión leería tráfico de organizaciones ajenas.
_SESION = [Depends(require_role("admin", "compliance_officer"))]

router = APIRouter(prefix="/gw", tags=["Monitor"])

_MONITOR_KEY = "basa:gw:events"


# ── Copy de capas para la vitrina (Constitución VII) ──────────────────────────────
# Claves = ``layer_key`` del registry (identidad estable que viaja en ``applied_layers``);
# valores = nombre legible del producto. El nombre vive acá y no en el registry porque es
# white-label —el cliente puede querer otro copy— mientras la clave no cambia jamás. Y no
# se lee de ``guardians.name``: ese nombre es editable, así que un rename del cliente
# reescribiría la lectura de eventos históricos.
#
# El diccionario se **valida contra el registry** al importar (abajo): una capa nueva sin
# copy tiene que fallar acá, en el arranque, y no aparecer como un código pelado en la
# pantalla de una demo.
LAYER_LABELS = {
    "interception_audit": "Intercepción y registro",
    "pii_detection": "Detección de datos personales",
    "secret_detection": "Bloqueo de secretos",
    "ai_act_evaluation": "Evaluación de cumplimiento AI-Act",
    "pii_masking": "Enmascarado de datos personales",
    "sensitive_routing": "Reruteo de prompts sensibles",
    "content_moderation": "Moderación de contenido",
    "prompt_injection": "Defensa anti-inyección de prompts",
    "content_safety": "Seguridad de contenido por severidad",
    "provider_guardrails": "Guardarraíles de plataforma en la nube",
}

_faltantes = [k for k in LAYER_KEYS if k not in LAYER_LABELS]
if _faltantes:  # pragma: no cover — invariante de import, no rama de runtime
    raise RuntimeError(f"monitor: capas del registry sin copy legible: {_faltantes}")

# Qué DECIDIÓ la capa sobre el pedido, y qué le pasó A LA CAPA: dos ejes separados, como
# en la columna durable (data-model §3.1). Reconflarlos en un solo texto es justo lo que
# hacía ilegible el ``action`` del legado.
_DECISION_LABELS = {
    "allow": "permitió",
    "mask": "enmascaró",
    "flag": "marcó",
    "block": "bloqueó",
}
_STATUS_LABELS = {
    "applied": "aplicada",
    "skipped": "omitida por configuración",
    "not_configured": "sin configurar",
    "requires_credential": "requiere credencial",
    "delegated": "delegada al servicio upstream",
    "degraded": "degradada",
}


def _js(value) -> str:
    """Constante JS embebida en la página. ``</script>`` dentro de un literal cerraría el
    bloque aunque el JSON sea válido, así que se escapa el ``<`` — el copy de hoy no lo
    lleva, pero la protección no debe depender de que nadie edite el copy."""
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c")


@router.get("/events", dependencies=_SESION)
def monitor_events(limit: int = 50):
    """Últimos eventos del firewall (metadata-only, preview enmascarado). **Exige sesión.**

    Sin ``Authorization`` válido responde 401; con un rol sin permiso, 403. Hasta la 027
    respondía 200 a cualquiera — ver el punto 0 del docstring del módulo.
    """
    client = get_redis()
    if client is None:
        return {"events": [], "detail": "feed no disponible (Redis)"}
    raw = client.lrange(_MONITOR_KEY, 0, max(0, limit - 1))
    events = []
    for item in raw:
        try:
            events.append(json.loads(item))
        except (ValueError, TypeError):
            continue
    return {"events": events}


_MONITOR_TEMPLATE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Basa Gateway — Monitor en vivo</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: dark; }
  body { margin:0; background:#0b0f14; color:#e6edf3; font:14px/1.5 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif; }
  header { padding:16px 20px; border-bottom:1px solid #1c2531; display:flex; align-items:center; gap:12px; }
  header h1 { font-size:16px; margin:0; font-weight:600; }
  .dot { width:8px; height:8px; border-radius:50%; background:#3fb950; box-shadow:0 0 8px #3fb950; }
  .muted { color:#7d8590; font-size:12px; }
  main { padding:16px 20px; display:flex; flex-direction:column; gap:10px; max-width:1100px; }
  .row { border:1px solid #1c2531; border-radius:10px; padding:12px 14px; background:#0f1620; }
  /* El resaltado de la fila cuelga de la FAMILIA del estado (`blocked`/`flag`/`error`), no
     del `compliance_status` crudo: enumerar los valores acá era la otra mitad del bug del
     bloqueo gris — `blocked_by_policy` no matcheaba ningún selector y la fila de un pedido
     bloqueado salía con el borde neutro de una que pasó. */
  .row.blocked { border-color:#f8514933; background:#f851490d; }
  .row.flag { border-color:#d2992233; background:#d299220d; }
  .row.error { border-color:#8b949e33; background:#8b949e0d; }
  .top { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .tag { font-size:11px; padding:2px 8px; border-radius:999px; background:#1c2531; color:#adbac7; }
  .tag.tenant { background:#1f2d3d; color:#79c0ff; }
  .tag.pass { background:#193c2a; color:#3fb950; }
  .tag.blocked { background:#3d1f22; color:#f85149; }
  .tag.flag { background:#3d341f; color:#d29922; }
  /* `upstream_error` NO es un verdicto del firewall: el pedido pasó las capas y falló el
     servicio de destino. Se pinta neutro a propósito — ni verde (no se completó) ni rojo
     (nadie lo bloqueó). */
  .tag.error { background:#232a33; color:#8b949e; }
  .preview { margin-top:8px; color:#adbac7; font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
             white-space:pre-wrap; word-break:break-word; }
  .ent { color:#79c0ff; }
  .empty { color:#7d8590; padding:40px; text-align:center; }
  /* Atribución por capa (spec 027): qué capa actuó sobre este pedido. */
  .capas { margin-top:8px; display:flex; gap:6px; flex-wrap:wrap; align-items:center; }
  .capa { font-size:11px; padding:2px 8px; border-radius:6px; background:#161d27;
          color:#adbac7; border:1px solid #1c2531; }
  .capa.block { background:#3d1f22; color:#f85149; border-color:#f8514933; font-weight:600; }
  .capa.mask { background:#193c2a; color:#3fb950; border-color:#3fb95033; }
  /* Capas que corrieron y no encontraron nada: verde apagado. Un `allow` confirmado es una
     buena noticia, pero no del mismo peso que un enmascarado efectivo. */
  .capa.ok { color:#3fb950; border-color:#3fb95033; }
  .capa.flag { background:#3d341f; color:#d29922; border-color:#d2992233; }
  .capa.inerte { color:#7d8590; }
  .capa.sinregistro { color:#7d8590; font-style:italic; }
</style></head>
<body>
<header><span class="dot"></span><h1>Basa Gateway — Monitor en vivo</h1>
  <span class="muted" id="status">conectando…</span></header>
<main id="feed"><div class="empty">Esperando tráfico… enviá una request por el gateway.</div></main>
<script>
const feed = document.getElementById('feed');
const statusEl = document.getElementById('status');

// tabla(): diccionario SIN prototipo. Todas las tablas de acá se indexan con un valor que
// viene del evento (``compliance_status``, ``layer_code``, ``decision``, ``status``), y un
// objeto literal hereda de ``Object.prototype``: con ``compliance_status='toString'`` el
// lookup NO devuelve undefined sino una función, y el destructuring de STATUS —que espera un
// array— tira ``is not iterable``, revienta el render entero y deja la vitrina en blanco. Un
// pedido con un campo elegido a mano tumbaba la pantalla del Admin (DoS del feed). Con
// prototipo nulo, ``'toString'`` es una clave ausente como cualquier otra y cae en el
// fallback. Se arregla en la construcción y no en cada lectura: un ``hasOwnProperty`` por
// sitio de uso se olvida en el próximo lookup que alguien agregue.
function tabla(obj){ return Object.assign(Object.create(null), obj); }

// STATUS: sólo la ETIQUETA legible de cada `compliance_status`. El color ya no sale de acá
// —sale de estado(), abajo— así que una entrada que falte degrada el copy, nunca el verdicto.
// Los tres planos productores y sus estados (barrido completo, residual US2):
//   gateway/inspect → passed · flagged_high_risk · blocked_prohibited · blocked_secret ·
//                     upstream_error        (gateway.py:262-275, :829)
//   motor           → passed · flagged_high_risk · blocked_prohibited
//                     (basa_guardian_policy.evaluate_ai_act, vía basa_compliance.status)
//   chat            → blocked_prohibited · blocked_by_policy · blocked_residency
//                     (chat.py:566, :694, :805)
const STATUS = tabla({
  passed:['pass','OK'],
  flagged_high_risk:['flag','ALTO RIESGO'],
  blocked_prohibited:['blocked','BLOQUEADO'],
  blocked_secret:['blocked','SECRETO BLOQUEADO'],
  blocked_guardian:['blocked','BLOQUEADO'],
  // Bloqueo del plano chat por un guardián de la postura (secreto o dato personal). Se
  // nombra por la POLÍTICA, no por el guardián: el nombre del guardián es editable por el
  // cliente y white-label (D6/Principio VII).
  blocked_by_policy:['blocked','BLOQUEADO POR POLÍTICA'],
  // Residencia de datos del proyecto de cumplimiento. NO es una capa del registry, así que
  // este evento viene con `blocked_by_layer` en null a propósito (chat.py:797-805).
  blocked_residency:['blocked','BLOQUEADO POR RESIDENCIA'],
  // El firewall dejó pasar el pedido y falló el servicio de destino. Es lo contrario de un
  // bloqueo y se dice distinto.
  upstream_error:['error','ERROR UPSTREAM'],
});

// estado(): familia visual + etiqueta de un `compliance_status`. La familia se DERIVA del
// nombre cuando la tabla no lo conoce: un estado nuevo que se llama `blocked_*` es un
// bloqueo y se pinta como bloqueo, aunque nadie haya tocado esta página. El fallback viejo
// —chip gris con la etiqueta cruda— convertía cada call-site de bloqueo nuevo en un evento
// que se leía como neutro; el default correcto no es "no sé", es "lo que el nombre afirma".
function estado(s){
  const conocido = STATUS[s];
  if(conocido) return conocido;
  const raw = String(s === undefined || s === null || s === '' ? '—' : s);
  if(raw.indexOf('blocked') === 0) return ['blocked', raw.toUpperCase()];
  if(raw.indexOf('flagged') === 0) return ['flag', raw.toUpperCase()];
  if(raw.indexOf('error') !== -1) return ['error', raw.toUpperCase()];
  return ['', raw.toUpperCase()];
}
// Copy de capas y de los dos ejes de la atribución (spec 027). Se inyecta desde el
// backend, que lo valida contra el registry: la vitrina no inventa nombres.
const LAYER_LABELS = tabla(__LAYER_LABELS__);
const DECISION_LABELS = tabla(__DECISION_LABELS__);
const STATUS_LABELS = tabla(__STATUS_LABELS__);

// esc(): TODO valor del evento pasa por acá antes de tocar innerHTML. Incluye comillas
// porque varios de estos valores terminan dentro de un atributo (title/class): escapar
// sólo &<> deja abierto el `" onmouseover=…` clásico.
function esc(s){
  return String(s === undefined || s === null ? '' : s)
    .replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
// cls(): el valor va a un atributo `class` y de ahí a un selector CSS. Se recorta a un
// token seguro en vez de escaparlo — un `class` no tiene por qué aceptar nada más.
function cls(s){ return String(s || '').replace(/[^A-Za-z0-9_-]/g, ''); }
// Nombre legible de la capa; si el código no está en el catálogo (productor más nuevo que
// esta página) se muestra el código tal cual, escapado: preferible a inventar un nombre.
function layerName(code){ return LAYER_LABELS[code] || code || '—'; }

// Atribución del pedido: qué capa actuó y, si hubo bloqueo, cuál lo produjo (FR-009).
// `familia` es la del `compliance_status` (ver estado()): hace falta para detectar el
// bloqueo SIN capa, que es un caso real y no un dato faltante.
function atribucion(e, familia){
  const capas = Array.isArray(e.applied_layers) ? e.applied_layers.filter(l => l && typeof l === 'object') : [];
  const bloqueo = e.blocked_by_layer;
  if(!capas.length && !bloqueo){
    // Evento anterior a la atribución: "no hay registro" ≠ "no actuó ninguna capa".
    return '<div class="capas"><span class="capa sinregistro">sin registro de capas</span></div>';
  }
  const chips = [];
  if(bloqueo){
    chips.push(`<span class="capa block">Bloqueado por: ${esc(layerName(bloqueo))}</span>`);
  } else if(familia === 'blocked'){
    // Bloqueo cuya causa NO es una capa del catálogo — hoy, la residencia de datos del
    // proyecto (chat.py:797-805). Sin esta línea el pedido sale con el chip rojo arriba y
    // debajo sólo las capas que permitieron: se lee como "lo bloquearon y ninguna capa
    // bloqueó", que es la contradicción exacta que la atribución vino a resolver.
    // Adjudicárselo a una capa para tapar el hueco sería falsear el registro.
    chips.push('<span class="capa block" title="El bloqueo lo produjo una política que no'
               + ' está en el catálogo de capas gobernables (p. ej. residencia de datos).'
               + ' Ninguna capa se lo atribuye porque ninguna lo produjo.">'
               + 'Bloqueado fuera del catálogo de capas</span>');
  }
  capas.filter(l => l.status === 'applied' && l.decision && l.decision !== 'allow'
                    && l.layer_code !== bloqueo)
       .forEach(l => {
         const verbo = DECISION_LABELS[l.decision] || l.decision;
         const n = Number.isFinite(l.count) ? ` (${esc(l.count)})` : '';
         chips.push(`<span class="capa ${cls(l.decision)}">${esc(layerName(l.layer_code))}: `
                    + `${esc(verbo)}${n}</span>`);
       });
  // Las que corrieron sin encontrar nada también son parte de la respuesta a "¿qué me
  // cubrió este pedido?": sin ellas, un pedido limpio se ve igual que uno sin protección.
  // Van agregadas —una fila con diez chips verdes no se lee— con los nombres en el tooltip.
  const limpias = capas.filter(l => l.status === 'applied'
                                    && (!l.decision || l.decision === 'allow')
                                    && l.layer_code !== bloqueo);
  if(limpias.length){
    const detalle = limpias.map(l => layerName(l.layer_code)).join(' · ');
    chips.push(`<span class="capa ok" title="${esc(detalle)}">`
               + `${esc(limpias.length)} capa(s) aplicadas sin hallazgos</span>`);
  }
  // Las que NO corrieron van juntas, con el detalle en el tooltip: apagada, sin credencial
  // o delegada son estados distintos y ninguno significa "no pasó nada".
  const inertes = capas.filter(l => l.status && l.status !== 'applied');
  if(inertes.length){
    const detalle = inertes.map(l => `${layerName(l.layer_code)}: `
                                     + `${STATUS_LABELS[l.status] || l.status}`).join(' · ');
    chips.push(`<span class="capa inerte" title="${esc(detalle)}">`
               + `${esc(inertes.length)} capa(s) sin aplicar</span>`);
  }
  return `<div class="capas">${chips.join('')}</div>`;
}

function render(events){
  if(!events.length){ feed.innerHTML = '<div class="empty">Esperando tráfico…</div>'; return; }
  feed.innerHTML = events.map(e => {
    const [estadoCls,label] = estado(e.compliance_status);
    const ents = (Array.isArray(e.masked_entities) ? e.masked_entities : [])
      .filter(x => x && typeof x === 'object')
      .map(x => `<span class="ent">${esc(x.count)}× ${esc(x.type)}</span>`).join(' ');
    return `<div class="row ${cls(estadoCls)}">
      <div class="top">
        <span class="tag tenant">${esc(e.tenant || '—')}</span>
        <strong>${esc(e.tool || '—')}</strong>
        <span class="muted">${esc(e.client || 'anónimo')}</span>
        <span class="tag ${cls(estadoCls)}">${esc(label)}</span>
        <span class="muted">${esc(e.model)}</span>
        ${ents ? '<span class="muted">·</span> '+ents : ''}
        <span class="muted" style="margin-left:auto">${esc(String(e.ts || '').replace('T',' ').slice(0,19))}</span>
      </div>
      ${atribucion(e, estadoCls)}
      ${e.masked_preview ? `<div class="preview">${esc(e.masked_preview)}</div>` : ''}
    </div>`;
  }).join('');
}
// El feed exige sesión (hallazgo A1). Esta página no tiene login propio a propósito —no hace
// falta otro—: toma el token que la consola guarda en el localStorage del MISMO origen. En
// prod el ingress Caddy sirve consola y API bajo un solo dominio, y en dev el proxy de
// vite.config.ts hace lo mismo con /api y /gw, así que abrir la vitrina por el origen de la
// consola alcanza. Abrirla por el puerto del backend es OTRO origen: ahí no hay token, y el
// mensaje lo dice en vez de mostrar un feed vacío que parece "no hay tráfico".
const TOKEN_KEY = 'basa_session_token';   // espejo de frontend/src/services/auth.ts
function sesion(){ try { return localStorage.getItem(TOKEN_KEY) || ''; } catch(e){ return ''; } }

function sinSesion(mensaje){
  statusEl.textContent = mensaje;
  feed.innerHTML = '<div class="empty">Esta vista muestra tráfico real, así que pide sesión.<br>'
    + 'Iniciá sesión en la consola y abrí esta página desde el mismo origen '
    + '(la consola tiene la misma vitrina en <strong>Firewall en vivo</strong>).</div>';
}

async function tick(){
  const token = sesion();
  if(!token){ sinSesion('sin sesión'); return; }
  try {
    const r = await fetch('events?limit=50', { headers: { 'Authorization': 'Bearer ' + token } });
    if(r.status === 401 || r.status === 403){
      sinSesion(r.status === 401 ? 'sesión expirada' : 'esta cuenta no puede ver el firewall');
      return;
    }
    const d = await r.json();
    render(d.events||[]); statusEl.textContent = (d.events||[]).length + ' eventos · actualiza cada 2s';
  } catch(e){ statusEl.textContent = 'feed no disponible'; }
}
tick(); setInterval(tick, 2000);
</script></body></html>"""


# El copy se inyecta por sustitución de marcadores y no con ``str.format``: la plantilla
# está llena de ``${...}`` de template-literals y de llaves de CSS, que ``format``
# interpretaría. Se resuelve una sola vez al importar — la página es constante.
_MONITOR_HTML = (
    _MONITOR_TEMPLATE
    .replace("__LAYER_LABELS__", _js(LAYER_LABELS))
    .replace("__DECISION_LABELS__", _js(_DECISION_LABELS))
    .replace("__STATUS_LABELS__", _js(_STATUS_LABELS))
)


@router.get("/monitor", response_class=HTMLResponse)
def monitor_page():
    return HTMLResponse(_MONITOR_HTML)
