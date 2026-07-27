import React, { useState, useEffect } from "react";
import { api } from "../services/api";

interface AuditLog {
  id: string;
  timestamp: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  pii_detected: boolean;
  compliance_status: string;
  latency_ms: number;
  cost_usd: number;
  tokens_saved_by_optimization: number;
  masked_entities?: Array<{ type: string; count: number }>;
  guardian_events?: any[];
}

export const AuditPage: React.FC = () => {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  // Filters
  const [piiFilter, setPiiFilter] = useState<string>("all");
  const [complianceFilter, setComplianceFilter] = useState<string>("all");
  const [fromDate, setFromDate] = useState<string>("");
  const [toDate, setToDate] = useState<string>("");
  const [limit] = useState(15);
  const [offset, setOffset] = useState(0);

  const fetchLogs = async () => {
    try {
      setLoading(true);
      const data = await api.getAuditLogs({
        limit,
        offset,
        pii_detected: piiFilter !== "all" ? piiFilter : undefined,
        compliance_status: complianceFilter !== "all" ? complianceFilter : undefined,
        from_date: fromDate ? new Date(fromDate).toISOString() : undefined,
        to_date: toDate ? new Date(toDate + "T23:59:59").toISOString() : undefined,
      });
      setLogs(data.logs);
      setTotal(data.total);
    } catch (err) {
      console.error("Error fetching audit logs:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, [piiFilter, complianceFilter, fromDate, toDate, offset]);

  const handleExport = async () => {
    setExporting(true);
    try {
      await api.exportAuditLogs({
        pii_detected: piiFilter !== "all" ? piiFilter === "true" : undefined,
        compliance_status: complianceFilter !== "all" ? complianceFilter : undefined,
        from_date: fromDate ? new Date(fromDate).toISOString() : undefined,
        to_date: toDate ? new Date(toDate + "T23:59:59").toISOString() : undefined,
      });
    } catch (e) {
      alert("Error al exportar. Intente nuevamente.");
    } finally {
      setExporting(false);
    }
  };

  const formatTimestamp = (isoString: string) => {
    try {
      return new Date(isoString).toLocaleString("es-AR", {
        day: "2-digit", month: "2-digit", year: "numeric",
        hour: "2-digit", minute: "2-digit", second: "2-digit",
      });
    } catch { return isoString; }
  };

  const toggleExpand = (id: string) => {
    setExpandedRow((prev) => (prev === id ? null : id));
  };

  const complianceLabel = (status: string) => {
    switch (status) {
      case "blocked_prohibited": return { label: "Bloqueado (AI Act)", cls: "text-danger font-bold" };
      case "blocked_by_policy": return { label: "Bloqueado (Política)", cls: "text-danger font-bold" };
      case "flagged_high_risk": return { label: "Riesgo alto (AI Act)", cls: "text-warning font-semibold" };
      default: return { label: "Cumple", cls: "text-success font-semibold" };
    }
  };

  return (
    <div className="space-y-6 p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex justify-between items-center pb-4 border-b border-border">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-text-primary">Logs de Auditoría</h1>
          <p className="text-xs text-text-secondary mt-1">
            Registro inmutable de transacciones para control de cumplimiento y costos. No se almacena PII.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleExport}
            disabled={exporting}
            className="bg-surface-2 hover:bg-border disabled:opacity-50 text-text-primary font-medium px-4 py-2 rounded-lg text-xs transition-colors border border-border"
          >
            {exporting ? "Exportando..." : "Exportar CSV"}
          </button>
          <button
            onClick={fetchLogs}
            className="bg-surface-2 hover:bg-border text-text-primary font-medium px-4 py-2 rounded-lg text-xs transition-colors border border-border"
          >
            {loading ? "Actualizando..." : "Actualizar"}
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-surface border border-border rounded-lg p-4 flex flex-wrap gap-3 items-center">
        <span className="text-xs text-text-secondary font-semibold uppercase tracking-wider">Filtrar:</span>

        <select
          value={piiFilter}
          onChange={(e) => { setPiiFilter(e.target.value); setOffset(0); }}
          className="bg-surface border border-border rounded px-3 py-1.5 text-xs text-text-primary"
        >
          <option value="all">Privacidad: Todos</option>
          <option value="true">Con PII detectado</option>
          <option value="false">Sin PII</option>
        </select>

        <select
          value={complianceFilter}
          onChange={(e) => { setComplianceFilter(e.target.value); setOffset(0); }}
          className="bg-surface border border-border rounded px-3 py-1.5 text-xs text-text-primary"
        >
          <option value="all">Cumplimiento: Todos</option>
          <option value="allowed">Permitidos</option>
          <option value="blocked_prohibited">Bloqueados (AI Act)</option>
        </select>

        <div className="flex items-center gap-2">
          <span className="text-xs text-text-secondary">Desde:</span>
          <input
            type="date"
            value={fromDate}
            onChange={(e) => { setFromDate(e.target.value); setOffset(0); }}
            className="bg-surface border border-border rounded px-2 py-1.5 text-xs text-text-primary"
          />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-secondary">Hasta:</span>
          <input
            type="date"
            value={toDate}
            onChange={(e) => { setToDate(e.target.value); setOffset(0); }}
            className="bg-surface border border-border rounded px-2 py-1.5 text-xs text-text-primary"
          />
        </div>

        <div className="ml-auto text-xs text-text-secondary">
          Total: <span className="text-text-primary font-bold">{total}</span> registros
        </div>
      </div>

      {/* Table */}
      <div className="bg-surface border border-border rounded-lg p-5">
        {loading && logs.length === 0 ? (
          <div className="py-12 text-center text-xs font-mono text-text-secondary">Cargando registros...</div>
        ) : logs.length === 0 ? (
          <div className="py-12 text-center text-xs text-text-secondary">No se encontraron registros.</div>
        ) : (
          <div className="space-y-4">
            <div className="border border-border rounded overflow-hidden">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-background/40 border-b border-border text-xs text-text-secondary font-semibold">
                    <th className="p-3">Fecha y Hora</th>
                    <th className="p-3">Modelo</th>
                    <th className="p-3">Tokens (P/R)</th>
                    <th className="p-3">Privacidad</th>
                    <th className="p-3">AI Act</th>
                    <th className="p-3">Guardianes</th>
                    <th className="p-3">Latencia</th>
                    <th className="p-3 text-right">Costo</th>
                  </tr>
                </thead>
                <tbody className="text-text-primary text-xs font-mono">
                  {logs.map((log) => {
                    const isExpanded = expandedRow === log.id;
                    const guardianCount = log.guardian_events?.length ?? 0;
                    const { label: complianceLbl, cls: complianceCls } = complianceLabel(log.compliance_status);
                    return (
                      <React.Fragment key={log.id}>
                        <tr
                          onClick={() => toggleExpand(log.id)}
                          className="border-b border-border hover:bg-background/30 transition-colors cursor-pointer"
                        >
                          <td className="p-3 text-text-secondary">{formatTimestamp(log.timestamp)}</td>
                          <td className="p-3 font-bold">{log.model}</td>
                          <td className="p-3">
                            {log.prompt_tokens} / {log.completion_tokens}
                            <span className="text-[10px] text-text-secondary ml-1">tokens</span>
                          </td>
                          <td className="p-3">
                            {log.pii_detected ? (
                              <span className="text-warning font-semibold">[PII]</span>
                            ) : (
                              <span className="text-text-tertiary">Limpio</span>
                            )}
                          </td>
                          <td className={`p-3 ${complianceCls}`}>{complianceLbl}</td>
                          <td className="p-3">
                            {guardianCount > 0 ? (
                              <span className="bg-warning/10 text-warning border border-warning/20 px-1.5 py-0.5 rounded text-[10px] font-semibold">
                                {guardianCount} evento{guardianCount > 1 ? "s" : ""}
                              </span>
                            ) : (
                              <span className="text-text-tertiary">—</span>
                            )}
                          </td>
                          <td className="p-3 text-warning">{log.latency_ms}ms</td>
                          <td className="p-3 text-right text-success font-bold">${Number(log.cost_usd).toFixed(6)}</td>
                        </tr>
                        {isExpanded && (
                          <tr className="bg-background/30 border-b border-border">
                            <td colSpan={8} className="p-4">
                              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                                {/* Left: token detail */}
                                <div className="space-y-2">
                                  <h4 className="text-[10px] font-semibold uppercase tracking-wider text-text-secondary">Detalle de la transacción</h4>
                                  <div className="space-y-1 text-text-secondary">
                                    <div className="flex justify-between">
                                      <span>Tokens de prompt:</span>
                                      <span className="text-text-primary font-mono">{log.prompt_tokens}</span>
                                    </div>
                                    <div className="flex justify-between">
                                      <span>Tokens de respuesta:</span>
                                      <span className="text-text-primary font-mono">{log.completion_tokens}</span>
                                    </div>
                                    <div className="flex justify-between">
                                      <span>Tokens optimizados:</span>
                                      <span className="text-primary font-mono">{log.tokens_saved_by_optimization}</span>
                                    </div>
                                    <div className="flex justify-between">
                                      <span>Latencia:</span>
                                      <span className="text-warning font-mono">{log.latency_ms}ms</span>
                                    </div>
                                    <div className="flex justify-between">
                                      <span>Costo:</span>
                                      <span className="text-success font-mono">${Number(log.cost_usd).toFixed(6)}</span>
                                    </div>
                                  </div>
                                  {log.pii_detected && log.masked_entities && log.masked_entities.length > 0 && (
                                    <div className="mt-2 pt-2 border-t border-border">
                                      <p className="text-[10px] text-text-secondary font-semibold uppercase mb-1">Entidades PII enmascaradas</p>
                                      <div className="flex flex-wrap gap-1">
                                        {log.masked_entities.map((e, i) => (
                                          <span key={i} className="bg-warning/10 text-warning border border-warning/20 px-1.5 py-0.5 rounded text-[10px]">
                                            {e.type}: {e.count}
                                          </span>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                </div>

                                {/* Right: guardian events */}
                                <div className="space-y-2">
                                  <h4 className="text-[10px] font-semibold uppercase tracking-wider text-text-secondary">Eventos de guardianes</h4>
                                  {log.guardian_events && log.guardian_events.length > 0 ? (
                                    <div className="space-y-1">
                                      {log.guardian_events.map((ev: any, i: number) => (
                                        <div key={i} className="bg-background/40 border border-border rounded p-2 text-[10px] text-text-secondary">
                                          <span className="text-text-primary font-semibold">
                                            {ev.guardrail_name || ev.guardian || "Guardián de seguridad"}
                                          </span>
                                          {ev.action && <span className="ml-2 text-warning">[{ev.action}]</span>}
                                          {ev.detail && <span className="ml-2">{ev.detail}</span>}
                                        </div>
                                      ))}
                                    </div>
                                  ) : (
                                    <p className="text-text-secondary">Sin eventos de guardianes en esta petición.</p>
                                  )}
                                  <div className="mt-2 pt-2 border-t border-border">
                                    <p className="text-[10px] text-text-secondary">
                                      Estado AI Act: <span className={complianceCls}>{complianceLbl}</span>
                                    </p>
                                  </div>
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <div className="flex justify-between items-center pt-2">
              <button
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - limit))}
                className="bg-surface-2 hover:bg-border disabled:opacity-50 text-text-primary px-3 py-1.5 rounded text-xs transition-colors"
              >
                Anterior
              </button>
              <span className="text-xs text-text-secondary">
                Página <span className="text-text-primary font-bold">{Math.floor(offset / limit) + 1}</span> de{" "}
                <span className="text-text-primary font-bold">{Math.ceil(total / limit) || 1}</span>
              </span>
              <button
                disabled={offset + limit >= total}
                onClick={() => setOffset(offset + limit)}
                className="bg-surface-2 hover:bg-border disabled:opacity-50 text-text-primary px-3 py-1.5 rounded text-xs transition-colors"
              >
                Siguiente
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default AuditPage;
