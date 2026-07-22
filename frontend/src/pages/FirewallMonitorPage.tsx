import React, { useState, useEffect, useRef } from "react";

// Firewall en vivo — feed del gateway (coding tools / browser) migrado en spec 019.
// Consume /api/v1/gw/events (metadata-only: sin texto de prompt crudo ni PII cruda).
// Endpoint público (el monitor standalone /gw/monitor lo fetchea sin auth).

interface MaskedEntity { type: string; count: number; }
interface GwEvent {
  tenant?: string;
  tool?: string;
  client?: string;
  model?: string;
  compliance_status?: string;
  masked_entities?: MaskedEntity[];
  masked_preview?: string;
  ts?: string;
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  passed: { label: "PERMITIDO", cls: "bg-success/15 text-success border-success/30" },
  blocked_prohibited: { label: "BLOQUEADO", cls: "bg-danger/15 text-danger border-danger/30" },
  blocked_secret: { label: "SECRETO BLOQUEADO", cls: "bg-danger/15 text-danger border-danger/30" },
  blocked_guardian: { label: "BLOQUEADO", cls: "bg-danger/15 text-danger border-danger/30" },
  flagged_high_risk: { label: "ALTO RIESGO", cls: "bg-warning/15 text-warning border-warning/30" },
};

// Timestamp naive (UTC sin 'Z') -> forzar UTC para que el browser lo muestre en hora local.
function fmtTime(iso?: string): string {
  if (!iso) return "";
  const utc = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + "Z";
  const d = new Date(utc);
  return isNaN(d.getTime()) ? iso : d.toLocaleString("es-ES", { hour12: false });
}

export const FirewallMonitorPage: React.FC = () => {
  const [events, setEvents] = useState<GwEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      if (pausedRef.current) return;
      try {
        const r = await fetch("/api/v1/gw/events?limit=50", { headers: { Accept: "application/json" } });
        const d = await r.json();
        if (!alive) return;
        setEvents(Array.isArray(d.events) ? d.events : []);
        setConnected(true);
      } catch {
        if (alive) setConnected(false);
      }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const total = events.length;
  const blocked = events.filter((e) => (e.compliance_status || "").startsWith("blocked")).length;
  const allowed = total - blocked;

  return (
    <div className="p-8 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between gap-4 mb-2 flex-wrap">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-text-primary">Firewall en vivo</h1>
          <span className="flex items-center gap-1.5 text-xs font-semibold text-success">
            <span className="w-2 h-2 rounded-full bg-success animate-pulse shadow-[0_0_8px_#06d6a0]" />
            EN VIVO
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setPaused((p) => !p)}
            className="px-4 py-2 rounded-lg text-sm font-medium border border-slate-700/50 text-text-secondary hover:text-white hover:bg-slate-800/40 transition"
          >
            {paused ? "Reanudar" : "Pausar"}
          </button>
          <button
            onClick={() => setEvents([])}
            className="px-4 py-2 rounded-lg text-sm font-medium border border-slate-700/50 text-text-secondary hover:text-white hover:bg-slate-800/40 transition"
          >
            Limpiar
          </button>
        </div>
      </div>
      <p className="text-sm text-text-secondary mb-4">
        Tráfico de coding tools (Claude Code, Cursor…) y browser atravesando el gateway.
        Auditado sin texto de prompt ni PII cruda.
      </p>

      {/* Redaction banner */}
      <div className="flex items-center gap-2 mb-6 px-4 py-3 rounded-lg bg-success/10 border border-success/20 text-sm text-success">
        <span>🔒</span>
        <span>Redacción activa: la PII se enmascara antes de llegar al modelo y se des-enmascara en la respuesta. El modelo nunca ve el dato real.</span>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-6">
        {[
          { n: total, label: "peticiones", color: "text-text-primary" },
          { n: allowed, label: "permitidas", color: "text-success" },
          { n: blocked, label: "bloqueadas", color: "text-danger" },
        ].map((s) => (
          <div key={s.label} className="bg-panel border border-slate-700/50 rounded-xl px-6 py-5">
            <div className={`text-4xl font-bold ${s.color}`}>{s.n}</div>
            <div className="text-sm text-text-secondary mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Feed */}
      {total === 0 ? (
        <div className="text-center py-16 text-text-secondary border border-dashed border-slate-700/40 rounded-xl">
          {connected
            ? "Esperando tráfico… enviá una request por el gateway (Claude Code, VS Code o el browser)."
            : "Conectando con el feed del gateway…"}
        </div>
      ) : (
        <div className="space-y-3">
          {events.map((e, i) => {
            const meta = STATUS_META[e.compliance_status || ""] || {
              label: (e.compliance_status || "—").toUpperCase(),
              cls: "bg-slate-700/30 text-text-secondary border-slate-600/40",
            };
            return (
              <div key={i} className="bg-panel border border-slate-700/50 rounded-xl px-5 py-4">
                <div className="flex items-center gap-3 flex-wrap">
                  <span className={`text-[11px] font-semibold px-2.5 py-1 rounded-full border ${meta.cls}`}>
                    {meta.label}
                  </span>
                  <span className="text-xs px-2.5 py-1 rounded-full bg-primary/10 text-primary border border-primary/20">
                    ▸ {e.tenant || "—"}
                  </span>
                  <strong className="text-text-primary">{e.tool || "—"}</strong>
                  <span className="text-sm text-text-secondary">· {e.client || "anónimo"}</span>
                  {e.model && <span className="text-xs font-mono text-text-secondary">{e.model}</span>}
                  <span className="text-xs text-text-secondary ml-auto font-mono">{fmtTime(e.ts)}</span>
                </div>

                {e.masked_entities && e.masked_entities.length > 0 && (
                  <div className="flex items-center gap-2 mt-3 flex-wrap">
                    <span className="text-xs text-text-secondary">PII enmascarada:</span>
                    {e.masked_entities.map((x, j) => (
                      <span key={j} className="text-[11px] px-2 py-0.5 rounded bg-primary/10 text-primary border border-primary/20 font-mono">
                        {x.count}× {x.type}
                      </span>
                    ))}
                  </div>
                )}

                {e.masked_preview && (
                  <div className="mt-3 px-3 py-2 rounded-lg bg-background/60 border border-slate-700/40 font-mono text-xs text-text-secondary whitespace-pre-wrap break-words">
                    {e.masked_preview}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
