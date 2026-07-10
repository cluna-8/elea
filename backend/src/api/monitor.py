"""Monitor en vivo del firewall (spec 014 US3, FR-017) — la vitrina de las demos.

Sirve el feed efímero que el ``BasaAuditLogger`` (extensión del motor) publica en
Redis por request: qué herramienta/cliente/tenant, verdicto de compliance, entidades
enmascaradas y un preview **ya enmascarado** (lo que vio el upstream). Nada de PII
cruda (Constitución VIII: animación cosmética, datos reales; C1: sin texto sensible).

- ``GET /gw/monitor``  → página HTML autocontenida que refresca el feed.
- ``GET /gw/events``   → JSON del ring (para la página y para integraciones).
"""
import json

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from ..services.redis_client import get_redis

router = APIRouter(prefix="/gw", tags=["Monitor"])

_MONITOR_KEY = "basa:gw:events"


@router.get("/events")
def monitor_events(limit: int = 50):
    """Últimos eventos del firewall (metadata-only, preview enmascarado)."""
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


_MONITOR_HTML = """<!doctype html>
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
  .row.blocked_prohibited, .row.blocked_secret, .row.blocked_guardian { border-color:#f8514933; background:#f851490d; }
  .row.flagged_high_risk { border-color:#d2992233; background:#d299220d; }
  .top { display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
  .tag { font-size:11px; padding:2px 8px; border-radius:999px; background:#1c2531; color:#adbac7; }
  .tag.tenant { background:#1f2d3d; color:#79c0ff; }
  .tag.pass { background:#193c2a; color:#3fb950; }
  .tag.blocked { background:#3d1f22; color:#f85149; }
  .tag.flag { background:#3d341f; color:#d29922; }
  .preview { margin-top:8px; color:#adbac7; font:12px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
             white-space:pre-wrap; word-break:break-word; }
  .ent { color:#79c0ff; }
  .empty { color:#7d8590; padding:40px; text-align:center; }
</style></head>
<body>
<header><span class="dot"></span><h1>Basa Gateway — Monitor en vivo</h1>
  <span class="muted" id="status">conectando…</span></header>
<main id="feed"><div class="empty">Esperando tráfico… enviá una request por el gateway.</div></main>
<script>
const feed = document.getElementById('feed');
const statusEl = document.getElementById('status');
const STATUS = { passed:['pass','OK'], blocked_prohibited:['blocked','BLOQUEADO'],
  blocked_secret:['blocked','SECRETO BLOQUEADO'], blocked_guardian:['blocked','BLOQUEADO'],
  flagged_high_risk:['flag','ALTO RIESGO'] };
function render(events){
  if(!events.length){ feed.innerHTML = '<div class="empty">Esperando tráfico…</div>'; return; }
  feed.innerHTML = events.map(e => {
    const [cls,label] = STATUS[e.compliance_status] || ['', e.compliance_status||''];
    const ents = (e.masked_entities||[]).map(x => `<span class="ent">${x.count}× ${x.type}</span>`).join(' ');
    return `<div class="row ${e.compliance_status||''}">
      <div class="top">
        <span class="tag tenant">${e.tenant||'—'}</span>
        <strong>${e.tool||'—'}</strong>
        <span class="muted">${e.client||'anónimo'}</span>
        <span class="tag ${cls}">${label}</span>
        <span class="muted">${e.model||''}</span>
        ${ents ? '<span class="muted">·</span> '+ents : ''}
        <span class="muted" style="margin-left:auto">${(e.ts||'').replace('T',' ').slice(0,19)}</span>
      </div>
      ${e.masked_preview ? `<div class="preview">${escapeHtml(e.masked_preview)}</div>` : ''}
    </div>`;
  }).join('');
}
function escapeHtml(s){ return (s||'').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
async function tick(){
  try {
    const r = await fetch('events?limit=50'); const d = await r.json();
    render(d.events||[]); statusEl.textContent = (d.events||[]).length + ' eventos · actualiza cada 2s';
  } catch(e){ statusEl.textContent = 'feed no disponible'; }
}
tick(); setInterval(tick, 2000);
</script></body></html>"""


@router.get("/monitor", response_class=HTMLResponse)
def monitor_page():
    return HTMLResponse(_MONITOR_HTML)
