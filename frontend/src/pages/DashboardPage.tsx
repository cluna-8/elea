import React, { useState, useEffect, useCallback } from "react";
import { api } from "../services/api";

type Range = "day" | "week" | "month";

const RANGE_LABELS: Record<Range, string> = {
  day: "Hoy",
  week: "Semana",
  month: "Mes",
};

function KpiCard({
  label,
  value,
  sub,
  color = "text-white",
}: {
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="bg-panel border border-slate-700/40 rounded-lg p-5 space-y-1">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-text-secondary">{label}</p>
      <p className={`text-3xl font-bold leading-none ${color}`}>{value}</p>
      {sub && <p className="text-[10px] text-text-secondary">{sub}</p>}
    </div>
  );
}

function StatusDot({ online }: { online: boolean }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full mr-2 ${online ? "bg-success" : "bg-danger"}`}
    />
  );
}

export const DashboardPage: React.FC = () => {
  const [range, setRange] = useState<Range>("week");
  const [summary, setSummary] = useState<any>(null);
  const [engineStatus, setEngineStatus] = useState<"online" | "offline" | null>(null);
  const [guardians, setGuardians] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async (r: Range) => {
    setLoading(true);
    setError(null);
    try {
      const [summaryData, statusData, guardiansData] = await Promise.all([
        api.getAnalyticsSummary(r),
        api.getEngineStatus(),
        api.getGuardians(),
      ]);
      setSummary(summaryData);
      setEngineStatus(statusData.status);
      setGuardians(guardiansData);
    } catch (e: any) {
      setError("No se pudieron cargar las métricas. Verifique la conexión con el servidor.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(range);
  }, [range, fetchData]);

  const activeGuardians = guardians.filter((g) => g.is_active).length;
  const guardianEvents = summary?.guardian_activations?.by_guardian || {};
  const guardianEntries = Object.entries(guardianEvents) as [string, number][];
  const maxActivations = guardianEntries.length > 0 ? Math.max(...guardianEntries.map(([, v]) => v)) : 1;

  return (
    <div className="space-y-6 p-6 max-w-5xl mx-auto pb-16">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 pb-4 border-b border-slate-700/30">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Panel Principal</h1>
          <p className="text-xs text-text-secondary mt-1">
            Métricas de uso, costos e incidentes de seguridad del gateway.
          </p>
        </div>
        <div className="flex gap-1 bg-background/60 border border-slate-700/40 rounded-lg p-1">
          {(["day", "week", "month"] as Range[]).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`px-3 py-1.5 rounded text-xs font-semibold transition-all ${
                range === r
                  ? "bg-primary text-background"
                  : "text-text-secondary hover:text-white"
              }`}
            >
              {RANGE_LABELS[r]}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="bg-danger/10 border border-danger/20 text-danger px-4 py-3 rounded-lg text-xs">
          {error}
        </div>
      )}

      {loading ? (
        <div className="py-16 text-center text-xs font-mono text-text-secondary">
          Cargando métricas...
        </div>
      ) : (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <KpiCard
              label="Peticiones"
              value={summary?.total_requests ?? 0}
              sub={`Promedio ${summary?.total_requests ? Math.round(summary.total_requests / (range === "day" ? 1 : range === "week" ? 7 : 30)) : 0}/día`}
            />
            <KpiCard
              label="Costo Total"
              value={`$${Number(summary?.total_cost_usd ?? 0).toFixed(4)}`}
              sub={`${summary?.total_prompt_tokens ?? 0} prompt + ${summary?.total_completion_tokens ?? 0} compl. tokens`}
              color="text-success"
            />
            <KpiCard
              label="Incidentes PII"
              value={summary?.pii_incidents ?? 0}
              sub="Datos enmascarados antes del modelo"
              color={summary?.pii_incidents > 0 ? "text-warning" : "text-white"}
            />
            <KpiCard
              label="Bloqueos de Guardianes"
              value={summary?.guardian_activations?.total ?? 0}
              sub={`${summary?.compliance_blocked ?? 0} bloqueos AI Act`}
              color={summary?.guardian_activations?.total > 0 ? "text-danger" : "text-white"}
            />
          </div>

          {/* Middle row: Top Models + System Status */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Top Models */}
            <div className="bg-panel border border-slate-700/40 rounded-lg p-5 space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
                Top Modelos
              </h3>
              {summary?.models?.length > 0 ? (
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-text-secondary border-b border-slate-700/30">
                      <th className="text-left py-1">Modelo</th>
                      <th className="text-right py-1">Peticiones</th>
                      <th className="text-right py-1">Costo</th>
                    </tr>
                  </thead>
                  <tbody className="text-white font-mono divide-y divide-slate-700/20">
                    {summary.models.slice(0, 5).map((m: any) => (
                      <tr key={m.model}>
                        <td className="py-1.5 font-medium truncate max-w-[140px]">{m.model}</td>
                        <td className="py-1.5 text-right text-text-secondary">{m.requests}</td>
                        <td className="py-1.5 text-right text-success">${Number(m.cost_usd).toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-xs text-text-secondary py-4">Sin peticiones en el período.</p>
              )}
            </div>

            {/* System Status */}
            <div className="bg-panel border border-slate-700/40 rounded-lg p-5 space-y-3">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
                Estado del Sistema
              </h3>
              <div className="space-y-3 text-xs">
                <div className="flex items-center justify-between">
                  <span className="text-text-secondary">Motor de IA</span>
                  <span className={`font-semibold flex items-center ${engineStatus === "online" ? "text-success" : "text-danger"}`}>
                    <StatusDot online={engineStatus === "online"} />
                    {engineStatus === "online" ? "Online" : "Offline"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-secondary">Guardianes activos</span>
                  <span className="font-semibold text-white font-mono">
                    {activeGuardians} / {guardians.length}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-secondary">Latencia media</span>
                  <span className="font-semibold text-warning font-mono">
                    {summary?.avg_latency_ms ?? 0}ms
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-secondary">Tokens optimizados</span>
                  <span className="font-semibold text-sky-400 font-mono">
                    {summary?.tokens_saved_by_optimization ?? 0}
                  </span>
                </div>
                <div className="pt-2 border-t border-slate-700/30">
                  <div className="flex justify-between text-[10px] text-text-secondary">
                    <span>AI Act: {summary?.compliance_passed ?? 0} correctas</span>
                    <span className={summary?.compliance_blocked > 0 ? "text-danger" : ""}>
                      {summary?.compliance_blocked ?? 0} bloqueadas
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Guardian Activations */}
          <div className="bg-panel border border-slate-700/40 rounded-lg p-5 space-y-4">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">
              Activaciones de Guardianes
            </h3>
            {guardianEntries.length > 0 ? (
              <div className="space-y-3">
                {guardianEntries.map(([name, count]) => (
                  <div key={name} className="space-y-1">
                    <div className="flex justify-between text-xs">
                      <span className="text-text-secondary">{name}</span>
                      <span className="text-white font-mono font-semibold">{count}</span>
                    </div>
                    <div className="w-full bg-background rounded-full h-1.5">
                      <div
                        className="bg-primary h-1.5 rounded-full transition-all duration-500"
                        style={{ width: `${Math.round((count / maxActivations) * 100)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-text-secondary py-2">
                Sin activaciones de guardianes en el período seleccionado.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default DashboardPage;
