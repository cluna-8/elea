// Pestaña «Costos»: lo que costó el tráfico redirigido y lo que habría costado con el modelo
// pedido (FR-032). Los dos importes salen de la misma fuente de precios que los presupuestos.
import React, { useState } from "react";
import { Button, Card, Field } from "../../../frontend/src/components/ui";
import { SCOPE_TYPE_LABELS, ScopeType } from "./catalog";
import { Lookups, scopeLabel } from "./helpers";
import { us5Api } from "./api";
import { CostComparison, CostLine, defaultPeriod, formatUsd, periodQuery, scopeParam } from "./insights";
import { EmptyRow, Notice, ScopePicker, tableClass, tdClass, thClass } from "./ui";

const Stat: React.FC<{ label: string; value: string; hint?: string }> = ({ label, value, hint }) => (
  <div className="rounded-md border border-border p-3">
    <div className="text-xs uppercase tracking-wide text-text-secondary">{label}</div>
    <div className="text-lg font-semibold text-text-primary">{value}</div>
    {hint && <div className="text-xs text-text-tertiary">{hint}</div>}
  </div>
);

const Cells: React.FC<{ line: CostLine }> = ({ line }) => (
  <>
    <td className={tdClass}>{line.requests}</td>
    <td className={tdClass}>{formatUsd(line.cost_real)}</td>
    <td className={tdClass}>{formatUsd(line.cost_hypothetical)}</td>
    <td className={tdClass}>{formatUsd(line.savings)}</td>
  </>
);

export const CostsTab: React.FC<{ lookups: Lookups }> = ({ lookups }) => {
  const [period, setPeriod] = useState(() => defaultPeriod(new Date()));
  const [scope, setScope] = useState<{ type: ScopeType; value: string }>({ type: "tenant", value: "" });
  const [data, setData] = useState<CostComparison | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const q = periodQuery(period.from, period.to);
    if (!q) { setErr("El período no es válido: la fecha final no puede ser anterior a la inicial."); return; }
    if (scope.type !== "tenant" && !scope.value) { setErr("Elegí a quién aplica el filtro."); return; }
    setBusy(true); setErr(null);
    try { setData(await us5Api.costs({ ...q, scope: scopeParam(scope.type, scope.value) })); }
    catch (e) { setErr((e as Error).message); setData(null); }
    finally { setBusy(false); }
  };

  const t = data?.totals;
  return (
    <div>
      <Notice tone="info">
        Costo real = lo que costó servir el tráfico con el destino elegido. Costo hipotético = lo que habría
        costado con el modelo pedido (en Claude y Codex) o con el modelo de referencia que definas en el id
        publicado (en alias propios). Sin modelo de referencia no se inventa una cifra.
      </Notice>
      <Card title="Período" className="mb-6">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
          <Field label="Desde" type="date" value={period.from} onChange={e => setPeriod({ ...period, from: e.target.value })} />
          <Field label="Hasta" type="date" value={period.to} onChange={e => setPeriod({ ...period, to: e.target.value })} />
        </div>
        <ScopePicker type={scope.type} value={scope.value} lookups={lookups}
          onChange={(type, value) => setScope({ type, value })} />
        <div className="flex justify-end mt-4"><Button onClick={load} disabled={busy}>{busy ? "Calculando…" : "Comparar"}</Button></div>
      </Card>
      {err && <Notice tone="error" onClose={() => setErr(null)}>{err}</Notice>}
      {data && t && (
        <div>
          {data.truncated && <Notice tone="info">El período tiene más pedidos de los que se pueden sumar de una vez: acortalo para ver cifras completas.</Notice>}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <Stat label="Pedidos redirigidos" value={String(t.requests)} />
            <Stat label="Costo real" value={formatUsd(t.cost_real)}
              hint={t.estimated_real ? `${t.estimated_real} estimados con el precio del modelo real` : undefined} />
            <Stat label="Costo hipotético" value={formatUsd(t.cost_hypothetical)}
              hint={t.without_reference ? `${t.without_reference} sin modelo de referencia` : undefined} />
            <Stat label="Diferencia" value={formatUsd(t.savings)} hint="hipotético − real, en los pedidos comparables" />
          </div>
          <Card title="Por destino" className="mb-6">
            <table className={tableClass}>
              <thead><tr><th className={thClass}>Destino</th><th className={thClass}>Pedidos</th><th className={thClass}>Real</th><th className={thClass}>Hipotético</th><th className={thClass}>Diferencia</th></tr></thead>
              <tbody>
                {data.by_destination.length === 0 && <EmptyRow cols={5}>No hay tráfico redirigido en el período.</EmptyRow>}
                {data.by_destination.map(d => (
                  <tr key={d.destination_id}><td className={tdClass}>{d.destination_name ?? "(destino dado de baja)"}</td><Cells line={d} /></tr>
                ))}
              </tbody>
            </table>
          </Card>
          <Card title="Por alcance">
            <table className={tableClass}>
              <thead><tr><th className={thClass}>Alcance</th><th className={thClass}>Pedidos</th><th className={thClass}>Real</th><th className={thClass}>Hipotético</th><th className={thClass}>Diferencia</th></tr></thead>
              <tbody>
                {data.by_scope.length === 0 && <EmptyRow cols={5}>No hay tráfico redirigido en el período.</EmptyRow>}
                {data.by_scope.map(s => (
                  <tr key={`${s.scope_type}:${s.scope_value}`}>
                    <td className={tdClass}>{s.scope_type === "tenant" ? SCOPE_TYPE_LABELS.tenant : scopeLabel(s.scope_type, s.scope_value, lookups)}</td>
                    <Cells line={s} />
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}
    </div>
  );
};
