// Pestaña «Consumo» de «Modelos» (US9): cuánto se usó cada modelo o destino en un período, con
// totales, tabla ordenable y barras proporcionales (CSS, sin librería de gráficos). Solo cifras de
// la organización de la sesión; jamás contenido de pedidos. La «tarifa plana» no se mide por token:
// se marca aparte para no confundirla con costo medido.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Card, StatusBadge, cn } from "../../../frontend/src/components/ui";
import { Notice } from "../redirect/ui";
import { fetchUsage, UsageGroup, UsageReport, UsageRow } from "./usageApi";
import {
  barPct, fmtInt, fmtMs, fmtUsd, Period, PERIODS, periodRange, SortDir, SortKey, sortRows, tokensOf,
} from "./usageHelpers";

const Kpi: React.FC<{ label: string; value: string; sub?: string }> = ({ label, value, sub }) => (
  <div className="bg-surface border border-border rounded-lg p-5 space-y-1">
    <p className="text-[10px] font-semibold uppercase tracking-wider text-text-secondary">{label}</p>
    <p className="text-3xl font-bold leading-none text-text-primary">{value}</p>
    {sub && <p className="text-[10px] text-text-secondary">{sub}</p>}
  </div>
);

const Bar: React.FC<{ pct: number; tone?: "primary" | "muted" }> = ({ pct, tone = "primary" }) => (
  <div aria-hidden="true" className="h-1.5 w-full rounded-full bg-surface-2">
    <div className={cn("h-1.5 rounded-full", tone === "primary" ? "bg-primary" : "bg-text-tertiary")} style={{ width: `${pct}%` }} />
  </div>
);

const COLUMNS: { key: SortKey; label: string; right: boolean }[] = [
  { key: "name", label: "", right: false },
  { key: "requests", label: "Pedidos", right: true },
  { key: "tokens", label: "Tokens", right: true },
  { key: "cost_usd", label: "Costo", right: true },
  { key: "latency_avg_ms", label: "Latencia media", right: true },
  { key: "latency_p95_ms", label: "Latencia p95", right: true },
];

export const UsageTab: React.FC = () => {
  const [days, setDays] = useState<Period>(30);
  const [group, setGroup] = useState<UsageGroup>("model");
  const [report, setReport] = useState<UsageReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: "cost_usd", dir: "desc" });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { from, to } = periodRange(days);
      setReport(await fetchUsage(from, to, group));
    } catch (e) {
      setReport(null);
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [days, group]);
  useEffect(() => { void load(); }, [load]);

  const rows: UsageRow[] = useMemo(() => sortRows(report?.data ?? [], sort.key, sort.dir), [report, sort]);
  const maxCost = Math.max(0, ...rows.map(r => r.cost_usd));
  const maxReq = Math.max(0, ...rows.map(r => r.requests));
  const flatCount = rows.filter(r => r.billing === "flat").length;
  const groupLabel = group === "model" ? "Modelo" : "Destino";

  const toggleSort = (key: SortKey) =>
    setSort(s => (s.key === key ? { key, dir: s.dir === "asc" ? "desc" : "asc" } : { key, dir: key === "name" ? "asc" : "desc" }));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <div role="group" aria-label="Período" className="flex gap-1">
          {PERIODS.map(p => (
            <button
              key={p} type="button" aria-pressed={days === p} onClick={() => setDays(p)}
              className={cn("rounded-md border px-3 py-1.5 text-xs font-semibold",
                days === p ? "border-primary bg-primary-tint text-text-primary" : "border-border text-text-secondary")}
            >
              {p} días
            </button>
          ))}
        </div>
        <div role="group" aria-label="Agrupar por" className="flex gap-1">
          {([["model", "Por modelo"], ["destination", "Por destino"]] as const).map(([g, label]) => (
            <button
              key={g} type="button" aria-pressed={group === g} onClick={() => setGroup(g)}
              className={cn("rounded-md border px-3 py-1.5 text-xs font-semibold",
                group === g ? "border-primary bg-primary-tint text-text-primary" : "border-border text-text-secondary")}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <Notice tone="error">
          {error}{" "}
          <button type="button" className="underline" onClick={() => void load()}>Reintentar</button>
        </Notice>
      )}

      {loading ? (
        <p role="status" className="text-sm text-text-tertiary">Cargando consumo…</p>
      ) : report && (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi label="Pedidos" value={fmtInt(report.totals.requests)} />
            <Kpi label="Tokens de entrada" value={fmtInt(report.totals.prompt_tokens)} />
            <Kpi label="Tokens de salida" value={fmtInt(report.totals.completion_tokens)} />
            <Kpi label="Costo medido" value={fmtUsd(report.totals.cost_usd)}
              sub={flatCount ? "Los de tarifa plana no se miden por token" : undefined} />
          </div>

          <Card title={`Consumo por ${groupLabel.toLowerCase()}`} noPadding>
            {rows.length === 0 ? (
              <p className="px-5 py-8 text-center text-sm text-text-secondary">
                Todavía no hay consumo en este período. Cuando haya pedidos, los vas a ver acá.
              </p>
            ) : (
              <div className="w-full overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-border text-left text-text-secondary">
                      {COLUMNS.map(c => (
                        <th
                          key={c.key} scope="col" className={cn("px-4 py-2 font-medium", c.right && "text-right")}
                          aria-sort={sort.key === c.key ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
                        >
                          <button type="button" onClick={() => toggleSort(c.key)} className="font-medium hover:text-text-primary">
                            {c.label || groupLabel}{sort.key === c.key ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
                          </button>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(r => (
                      <tr key={r.key} className="border-b border-border align-top">
                        <td className="px-4 py-2 font-mono text-text-primary">{r.name}</td>
                        <td className="min-w-[8rem] px-4 py-2 text-right">
                          {fmtInt(r.requests)}
                          <Bar pct={barPct(r.requests, maxReq)} tone="muted" />
                        </td>
                        <td className="px-4 py-2 text-right">{fmtInt(tokensOf(r))}</td>
                        <td className="min-w-[9rem] px-4 py-2 text-right">
                          {r.billing === "flat" ? (
                            <StatusBadge tone="neutral">Tarifa plana</StatusBadge>
                          ) : (
                            <>
                              {fmtUsd(r.cost_usd)}
                              <Bar pct={barPct(r.cost_usd, maxCost)} />
                            </>
                          )}
                        </td>
                        <td className="px-4 py-2 text-right">{fmtMs(r.latency_avg_ms)}</td>
                        <td className="px-4 py-2 text-right">{fmtMs(r.latency_p95_ms)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
          {flatCount > 0 && (
            <p className="text-xs text-text-secondary">
              «Tarifa plana»: el proveedor cobra un monto fijo, no por token, así que no hay costo medido por token para ese modelo.
            </p>
          )}
          <p className="text-xs text-text-tertiary">Solo cifras de uso: nunca se muestra el contenido de los pedidos.</p>
        </>
      )}
    </div>
  );
};

export default UsageTab;
