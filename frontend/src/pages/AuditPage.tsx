import React, { useState, useEffect } from "react";

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
}

export const AuditPage: React.FC = () => {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  
  // Filtering & Pagination
  const [piiFilter, setPiiFilter] = useState<string>("all");
  const [complianceFilter, setComplianceFilter] = useState<string>("all");
  const [limit] = useState(15);
  const [offset, setOffset] = useState(0);

  const fetchLogs = async () => {
    try {
      setLoading(true);
      let url = `http://localhost:8081/api/v1/audit-logs?limit=${limit}&offset=${offset}`;
      if (piiFilter !== "all") url += `&pii_detected=${piiFilter === "true"}`;
      if (complianceFilter !== "all") url += `&compliance_status=${complianceFilter}`;

      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        setLogs(data.logs);
        setTotal(data.total);
      }
    } catch (err) {
      console.error("Error fetching audit logs:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, [piiFilter, complianceFilter, offset]);

  const handlePageChange = (newOffset: number) => {
    setOffset(newOffset);
  };

  const formatTimestamp = (isoString: string) => {
    try {
      const date = new Date(isoString);
      return date.toLocaleString("es-AR", {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch (e) {
      return isoString;
    }
  };

  return (
    <div className="space-y-8 p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex justify-between items-center pb-4 border-b border-slate-700/30">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Logs de Auditoría
          </h1>
          <p className="text-xs text-text-secondary mt-1">
            Registro inmutable de transacciones para control de cumplimiento y costos. No se almacena PII.
          </p>
        </div>
        <button
          onClick={fetchLogs}
          className="bg-slate-800 hover:bg-slate-700 text-white font-medium px-4 py-2 rounded-lg text-xs transition-colors border border-slate-700"
        >
          {loading ? "Actualizando..." : "Actualizar"}
        </button>
      </div>

      {/* Filters Bar */}
      <div className="bg-panel border border-slate-700/40 rounded-lg p-4 flex flex-wrap gap-4 items-center justify-between">
        <div className="flex flex-wrap gap-4 items-center">
          <span className="text-xs text-text-secondary font-semibold uppercase tracking-wider">Filtrar por:</span>

          {/* PII Filter */}
          <select
            value={piiFilter}
            onChange={(e) => { setPiiFilter(e.target.value); setOffset(0); }}
            className="bg-background border border-slate-700 rounded px-3 py-1.5 text-xs text-white"
          >
            <option value="all">Privacidad: Todos</option>
            <option value="true">Con PII detectado</option>
            <option value="false">Sin PII</option>
          </select>

          {/* Compliance Filter */}
          <select
            value={complianceFilter}
            onChange={(e) => { setComplianceFilter(e.target.value); setOffset(0); }}
            className="bg-background border border-slate-700 rounded px-3 py-1.5 text-xs text-white"
          >
            <option value="all">Cumplimiento: Todos</option>
            <option value="allowed">Permitidos (AI Act)</option>
            <option value="blocked_prohibited">Bloqueados (AI Act)</option>
          </select>
        </div>

        <div className="text-xs text-text-secondary">
          Total: <span className="text-white font-bold">{total}</span> registros
        </div>
      </div>

      {/* Logs Table */}
      <div className="bg-panel border border-slate-700/40 rounded-lg p-5">
        {loading && logs.length === 0 ? (
          <div className="py-12 text-center text-xs font-mono text-text-secondary">
            Cargando registros...
          </div>
        ) : logs.length === 0 ? (
          <div className="py-12 text-center text-xs text-text-secondary">
            No se encontraron transacciones en los logs.
          </div>
        ) : (
          <div className="space-y-4">
            <div className="border border-slate-700/30 rounded overflow-hidden">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-background/40 border-b border-slate-700/50 text-xs text-text-secondary font-semibold">
                    <th className="p-3">Fecha y Hora</th>
                    <th className="p-3">Modelo</th>
                    <th className="p-3">Longitud (P/R)</th>
                    <th className="p-3">Privacidad</th>
                    <th className="p-3">AI Act Status</th>
                    <th className="p-3">Latencia</th>
                    <th className="p-3">Optimiz.</th>
                    <th className="p-3 text-right">Costo</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/30 text-white text-xs font-mono">
                  {logs.map((log) => (
                    <tr key={log.id} className="hover:bg-background/20 transition-colors">
                      <td className="p-3 text-text-secondary">{formatTimestamp(log.timestamp)}</td>
                      <td className="p-3 font-bold">{log.model}</td>
                      <td className="p-3">
                        {log.prompt_tokens} / {log.completion_tokens} <span className="text-[10px] text-text-secondary">tokens</span>
                      </td>
                      <td className="p-3">
                        {log.pii_detected ? (
                          <span className="text-warning font-semibold">[PII ENMASCARADO]</span>
                        ) : (
                          <span className="text-slate-500">Limpio</span>
                        )}
                      </td>
                      <td className="p-3">
                        {log.compliance_status === "blocked_prohibited" ? (
                          <span className="text-danger font-bold">[BLOQUEADO]</span>
                        ) : (
                          <span className="text-success font-semibold">Cumple</span>
                        )}
                      </td>
                      <td className="p-3 text-warning">{log.latency_ms}ms</td>
                      <td className="p-3 text-sky-400">
                        {log.tokens_saved_by_optimization > 0 ? `+${log.tokens_saved_by_optimization}t` : "0"}
                      </td>
                      <td className="p-3 text-right text-success font-bold">${Number(log.cost_usd).toFixed(6)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            <div className="flex justify-between items-center pt-2">
              <button
                disabled={offset === 0}
                onClick={() => handlePageChange(Math.max(0, offset - limit))}
                className="bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-white px-3 py-1.5 rounded text-xs transition-colors"
              >
                Anterior
              </button>
              <span className="text-xs text-text-secondary">
                Página <span className="text-white font-bold">{Math.floor(offset / limit) + 1}</span> de{" "}
                <span className="text-white font-bold">{Math.ceil(total / limit) || 1}</span>
              </span>
              <button
                disabled={offset + limit >= total}
                onClick={() => handlePageChange(offset + limit)}
                className="bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-white px-3 py-1.5 rounded text-xs transition-colors"
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
