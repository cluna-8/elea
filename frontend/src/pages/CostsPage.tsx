import React, { useState, useEffect, useCallback } from "react";
import { api } from "../services/api";
import type { CostSummary, CompressionAnalysis, ModelPricing, CostConfig, GroupCompressionConfig, Group } from "../services/api";

type Range = "day" | "week" | "month";

const RANGE_LABELS: Record<Range, string> = {
  day: "Hoy",
  week: "Semana",
  month: "Mes",
};

const VEREDICTO_LABELS: Record<string, { label: string; cls: string }> = {
  conviene: { label: "Conviene activar", cls: "text-success bg-success/10 border-success/40" },
  no_conviene: { label: "No conviene", cls: "text-warning bg-warning/10 border-warning/40" },
  usd_no_disponible: { label: "Conviene (USD no disponible)", cls: "text-text-secondary bg-surface-2 border-border" },
};

const fmtUsd = (v: number | null | undefined) =>
  v == null ? "—" : `$${Number(v).toFixed(4)}`;

const STRATEGY_APPLIED_LABELS: Record<string, string> = {
  headroom: "Headroom (local)",
  deterministic: "Determinista",
  none: "Sin comprimir",
};

function KpiCard({
  label, value, sub, color = "text-text-primary",
}: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <div className="bg-surface border border-border rounded-lg p-5 space-y-1">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-text-secondary">{label}</p>
      <p className={`text-3xl font-bold leading-none ${color}`}>{value}</p>
      {sub && <p className="text-[10px] text-text-secondary">{sub}</p>}
    </div>
  );
}

function BreakdownTable({
  title, rows, nameKey, emptyText, loading,
}: {
  title: string;
  rows: { name: string; cost_usd: number; requests: number; tokens_saved: number }[];
  nameKey: string;
  emptyText: string;
  loading: boolean;
}) {
  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h2 className="text-sm font-bold text-text-primary mb-4">{title}</h2>
      {loading ? (
        <p className="text-xs text-text-secondary">Cargando…</p>
      ) : !rows?.length ? (
        <p className="text-xs text-text-secondary">{emptyText}</p>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-text-secondary text-left border-b border-border">
              <th className="pb-2 font-medium">{nameKey}</th>
              <th className="pb-2 font-medium text-right">Gasto</th>
              <th className="pb-2 font-medium text-right">Requests</th>
              <th className="pb-2 font-medium text-right">Ahorrado</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.name + i} className="border-b border-border">
                <td className="py-2 font-mono text-text-secondary truncate max-w-[140px]">{r.name}</td>
                <td className="py-2 text-right text-danger">{fmtUsd(r.cost_usd)}</td>
                <td className="py-2 text-right">{r.requests}</td>
                <td className="py-2 text-right text-success">{r.tokens_saved.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export const CostsPage: React.FC = () => {
  const [range, setRange] = useState<Range>("week");
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [pricing, setPricing] = useState<ModelPricing[]>([]);
  const [loading, setLoading] = useState(true);

  // Calculator state
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState<string>("");
  const [strategy, setStrategy] = useState<"deterministic" | "headroom">("deterministic");
  const [aggressiveness, setAggressiveness] = useState<"low" | "medium" | "high">("medium");
  const [analysis, setAnalysis] = useState<CompressionAnalysis | null>(null);
  const [calcLoading, setCalcLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Compression config (US4)
  const [costConfig, setCostConfig] = useState<CostConfig | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [groupConfigs, setGroupConfigs] = useState<Record<string, GroupCompressionConfig>>({});
  const [configSaving, setConfigSaving] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, p, cfg, grps] = await Promise.all([
        api.getCostsSummary(range),
        api.getModelsPricing(),
        api.getCostConfig().catch(() => null),
        api.getGroups().catch(() => [] as Group[]),
      ]);
      setSummary(s as CostSummary);
      setPricing((p as ModelPricing[]) || []);
      if (cfg) setCostConfig(cfg);
      setGroups(grps as Group[]);
      if (!model && (p as ModelPricing[]).length) setModel((p as ModelPricing[])[0].model_name);
      // Cargar config de compresión por grupo (paralelo, fail-open)
      const gc = await Promise.all(
        (grps as Group[]).map((g) => api.getGroupCompression(g.id).catch(() => null).then((c) => [g.id, c] as const))
      );
      const map: Record<string, GroupCompressionConfig> = {};
      gc.forEach(([id, c]) => { if (c) map[id] = c; });
      setGroupConfigs(map);
    } catch (e: any) {
      setError(e.message || "Error al cargar costes");
    } finally {
      setLoading(false);
    }
  }, [range, model]);

  const toggleGlobal = async (enabled: boolean) => {
    setConfigSaving("global");
    try {
      await api.updateCostConfig(enabled);
      setCostConfig((c) => (c ? { ...c, enabled } : c));
    } catch (e: any) {
      setError(e.message || "Error al guardar config global");
    } finally {
      setConfigSaving(null);
    }
  };

  const updateGroup = async (groupId: string, patch: Partial<GroupCompressionConfig>) => {
    const cur = groupConfigs[groupId];
    if (!cur) return;
    const next = { ...cur, ...patch };
    setGroupConfigs((m) => ({ ...m, [groupId]: next }));
    setConfigSaving(groupId);
    try {
      const saved = await api.updateGroupCompression(groupId, {
        mode: next.mode, strategy: next.strategy, threshold_tokens: next.threshold_tokens,
        aggressiveness: next.aggressiveness, cache_enabled: next.cache_enabled,
      });
      setGroupConfigs((m) => ({ ...m, [groupId]: saved }));
    } catch (e: any) {
      setError(e.message || "Error al guardar config del grupo");
    } finally {
      setConfigSaving(null);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line */ }, [range]);

  const calculate = async () => {
    setCalcLoading(true);
    setError(null);
    try {
      const res = await api.calculateCompression({
        prompt,
        model: model || null,
        aggressiveness,
        strategy,
      });
      setAnalysis(res);
    } catch (e: any) {
      setError(e.message || "Error en la calculadora");
    } finally {
      setCalcLoading(false);
    }
  };

  const pct = (r: number) => `${Math.round(r * 100)}%`;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Costos</h1>
          <p className="text-xs text-text-secondary">
            Visualiza el gasto y calcula si te conviene activar la compresión de tokens (Ahorro de Costes IA).
          </p>
        </div>
        <div className="flex gap-1 bg-surface border border-border rounded-lg p-1">
          {(Object.keys(RANGE_LABELS) as Range[]).map((r) => (
            <button
              key={r}
              onClick={() => setRange(r)}
              className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                range === r ? "bg-primary text-background" : "text-text-secondary hover:text-text-primary"
              }`}
            >
              {RANGE_LABELS[r]}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="bg-danger/10 border border-danger/40 text-danger text-sm rounded-lg p-3">
          {error}
        </div>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-4 gap-4">
        <KpiCard label="Gasto total" value={fmtUsd(summary?.total_cost_usd)} sub="USD" color="text-danger" />
        <KpiCard label="Requests" value={summary?.total_requests ?? "—"} sub={RANGE_LABELS[range]} />
        <KpiCard
          label="Tokens ahorrados"
          value={summary?.tokens_saved?.toLocaleString() ?? "—"}
          sub="por compresión"
          color="text-success"
        />
        <KpiCard
          label="Ahorro real"
          value={fmtUsd(summary?.cost_saved_usd)}
          sub="USD (por compresión)"
          color="text-success"
        />
      </div>

      {/* Config de compresión — US4 (global + por grupo) */}
      <div className="bg-surface border border-border rounded-lg p-5 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-bold text-text-primary">Configuración de compresión</h2>
            <p className="text-[10px] text-text-secondary">
              Activa la compresión globalmente y configura la estrategia por grupo. El motor headroom
              comprime contenido estructurado (JSON/RAG/arrays) sin gastar tokens.
            </p>
          </div>
          <label className="flex items-center gap-2 cursor-pointer">
            <span className="text-xs text-text-secondary">Global</span>
            <button
              onClick={() => toggleGlobal(!costConfig?.enabled)}
              disabled={configSaving === "global"}
              className={`relative w-11 h-6 rounded-full transition-all ${costConfig?.enabled ? "bg-primary" : "bg-border-strong"}`}
            >
              <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-surface rounded-full transition-all ${costConfig?.enabled ? "translate-x-5" : ""}`} />
            </button>
            <span className="text-xs font-semibold text-text-primary">{costConfig?.enabled ? "ON" : "OFF"}</span>
          </label>
        </div>

        {groups.length > 0 ? (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-text-secondary text-left border-b border-border">
                <th className="pb-2 font-medium">Grupo</th>
                <th className="pb-2 font-medium">Modo</th>
                <th className="pb-2 font-medium">Estrategia</th>
                <th className="pb-2 font-medium">Umbral (tokens)</th>
                <th className="pb-2 font-medium">Agresividad</th>
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => {
                const c = groupConfigs[g.id];
                return (
                  <tr key={g.id} className="border-b border-border">
                    <td className="py-2 font-mono text-text-secondary truncate max-w-[140px]">{g.name}</td>
                    <td className="py-2">
                      <select
                        value={c?.mode ?? "off"}
                        onChange={(e) => updateGroup(g.id, { mode: e.target.value as any })}
                        className="bg-surface border border-border rounded px-2 py-1 text-text-primary"
                      >
                        <option value="off">Off</option>
                        <option value="deterministic">Determinista</option>
                        <option value="headroom">Headroom</option>
                      </select>
                    </td>
                    <td className="py-2">
                      <select
                        value={c?.strategy ?? "deterministic"}
                        onChange={(e) => updateGroup(g.id, { strategy: e.target.value as any })}
                        className="bg-surface border border-border rounded px-2 py-1 text-text-primary"
                      >
                        <option value="deterministic">Determinista</option>
                        <option value="headroom">Headroom</option>
                      </select>
                    </td>
                    <td className="py-2">
                      <input
                        type="number"
                        value={c?.threshold_tokens ?? ""}
                        placeholder="default"
                        onChange={(e) => updateGroup(g.id, { threshold_tokens: e.target.value ? Number(e.target.value) : null })}
                        className="w-20 bg-surface border border-border rounded px-2 py-1 text-text-primary"
                      />
                    </td>
                    <td className="py-2">
                      <select
                        value={c?.aggressiveness ?? "medium"}
                        onChange={(e) => updateGroup(g.id, { aggressiveness: e.target.value as any })}
                        className="bg-surface border border-border rounded px-2 py-1 text-text-primary"
                      >
                        <option value="low">Baja</option>
                        <option value="medium">Media</option>
                        <option value="high">Alta</option>
                      </select>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <p className="text-xs text-text-secondary">No hay grupos. Crea grupos desde Usuarios &amp; Equipos.</p>
        )}
      </div>

      {/* Breakdown tables: modelos / usuarios / grupos */}
      <div className="grid grid-cols-3 gap-6">
        <BreakdownTable
          title="Top modelos por gasto"
          nameKey="Modelo"
          rows={(summary?.top_models ?? []).map((m) => ({ name: m.model, ...m }))}
          emptyText="Sin datos de gasto en este período."
          loading={loading}
        />
        <BreakdownTable
          title="Gasto por usuario"
          nameKey="Usuario"
          rows={summary?.by_user ?? []}
          emptyText="Sin datos de usuarios en este período."
          loading={loading}
        />
        <BreakdownTable
          title="Gasto por grupo"
          nameKey="Grupo"
          rows={summary?.by_group ?? []}
          emptyText="Sin datos de grupos en este período."
          loading={loading}
        />
      </div>

      {/* Calculator */}
      <div className="bg-surface border border-border rounded-lg p-5 space-y-4">
        <div>
          <h2 className="text-sm font-bold text-text-primary">Calculadora de compresión</h2>
          <p className="text-[10px] text-text-secondary">
            Pega un prompt, elige modelo y mira cuántos tokens ahorrarías y si conviene activar.
          </p>
        </div>

          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="Pega aquí un prompt de ejemplo…"
            className="w-full h-28 bg-surface border border-border rounded-lg p-3 text-sm text-text-primary placeholder:text-text-secondary focus:outline-none focus:ring-1 focus:ring-primary resize-none"
          />

          <div className="grid grid-cols-3 gap-3">
            <div>
              <label className="text-[10px] uppercase tracking-wider text-text-secondary">Estrategia</label>
              <select
                value={strategy}
                onChange={(e) => setStrategy(e.target.value as any)}
                className="w-full mt-1 bg-surface border border-border rounded-lg p-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="deterministic">Determinista (prosa, local)</option>
                <option value="headroom">Headroom (estructurado, local · sin tokens)</option>
              </select>
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-text-secondary">Modelo</label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="w-full mt-1 bg-surface border border-border rounded-lg p-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-primary"
              >
                {!pricing.length && <option value="">— sin modelos —</option>}
                {pricing.map((p) => (
                  <option key={p.model_name} value={p.model_name}>
                    {p.model_name} (${p.input_cost_per_million}/M)
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[10px] uppercase tracking-wider text-text-secondary">Agresividad</label>
              <select
                value={aggressiveness}
                onChange={(e) => setAggressiveness(e.target.value as any)}
                className="w-full mt-1 bg-surface border border-border rounded-lg p-2 text-sm text-text-primary focus:outline-none focus:ring-1 focus:ring-primary"
              >
                <option value="low">Baja</option>
                <option value="medium">Media</option>
                <option value="high">Alta</option>
              </select>
            </div>
          </div>

          {strategy === "headroom" && (
            <p className="text-[10px] text-text-secondary">
              El módulo headroom (SmartCrusher, Rust) comprime contenido estructurado (JSON, logs,
              tool outputs, RAG, arrays) de forma local — <span className="text-success">sin gastar tokens</span> ni
              llamar a ningún LLM. Para prosa libre cae al determinista. Pega un JSON/array para ver el ahorro real.
            </p>
          )}

          <button
            onClick={calculate}
            disabled={!prompt.trim() || calcLoading}
            className="w-full bg-primary text-background font-semibold text-sm py-2.5 rounded-lg hover:opacity-90 transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {calcLoading ? "Calculando…" : "Calcular ahorro"}
          </button>

          {analysis && (
            <div className="border-t border-border pt-4 space-y-3">
              <div className="grid grid-cols-3 gap-2 text-center">
                <div className="bg-background/40 rounded-lg p-2">
                  <p className="text-[9px] uppercase text-text-secondary">Tokens originales</p>
                  <p className="text-lg font-bold text-text-primary">{analysis.tokens_original.toLocaleString()}</p>
                </div>
                <div className="bg-background/40 rounded-lg p-2">
                  <p className="text-[9px] uppercase text-text-secondary">Tras compresión</p>
                  <p className="text-lg font-bold text-text-primary">{analysis.tokens_compressed.toLocaleString()}</p>
                </div>
                <div className="bg-background/40 rounded-lg p-2">
                  <p className="text-[9px] uppercase text-text-secondary">Ahorro</p>
                  <p className="text-lg font-bold text-success">{analysis.tokens_saved.toLocaleString()}</p>
                </div>
              </div>

              <div className="flex items-center justify-between text-sm">
                <span className="text-text-secondary">% de ahorro</span>
                <span className="text-text-primary font-semibold">{pct(analysis.ratio)}</span>
              </div>
              <div className="flex items-center justify-between text-sm">
                <span className="text-text-secondary">Ahorro USD (estimado)</span>
                <span className="text-success font-semibold">{fmtUsd(analysis.cost_saved_usd)}</span>
              </div>

              <div className={`text-center text-sm font-semibold rounded-lg border px-3 py-2 ${VEREDICTO_LABELS[analysis.veredicto].cls}`}>
                {VEREDICTO_LABELS[analysis.veredicto].label}
              </div>

              {analysis.strategy === "headroom" && (
                <div className="flex flex-wrap gap-2 justify-center text-[10px]">
                  <span className="px-2 py-1 rounded-md bg-surface-2 border border-border text-text-secondary">
                    Aplicado: <span className="text-text-primary font-semibold">{STRATEGY_APPLIED_LABELS[analysis.strategy_applied ?? "none"]}</span>
                  </span>
                  {analysis.strategy_applied === "headroom" && (
                    <span className="px-2 py-1 rounded-md bg-success/10 border border-success/40 text-success">
                      Sin gastar tokens · 100% local
                    </span>
                  )}
                </div>
              )}

              {!analysis.would_compress && (
                <p className="text-[10px] text-text-secondary text-center">
                  Por debajo del umbral ({analysis.threshold} tokens) o sin ahorro — no se comprimiría.
                </p>
              )}
            </div>
          )}
        </div>
    </div>
  );
};