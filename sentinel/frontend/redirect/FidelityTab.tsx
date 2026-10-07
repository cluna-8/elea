// Pestaña «Fidelidad»: prueba de un destino con conversaciones sintéticas de cada herramienta
// (FR-031). No envía datos de nadie; gasta un presupuesto propio, no el de ninguna llave.
import React, { useCallback, useEffect, useState } from "react";
import { Button, Card, Field, StatusBadge } from "../../../frontend/src/components/ui";
import { CAPABILITY_LABELS, KIT_TOOLS, KIT_TOOL_LABELS, KitTool, VERDICT_LABELS } from "./catalog";
import { Destination, Permissions } from "./helpers";
import { RedirectApiError, us5Api } from "./api";
import { detailLabel, FidelityReport, formatUsd, us5ErrorMessage } from "./insights";
import { EmptyRow, Notice, SelectField, tableClass, tdClass, thClass } from "./ui";

const VERDICT_TONE = { apto: "ok", no_apto: "danger", incompleto: "warn" } as const;

const ReportView: React.FC<{ report: FidelityReport }> = ({ report }) => (
  <Card title={`Informe · ${KIT_TOOL_LABELS[report.tool as KitTool] ?? report.tool}${report.tool_version ? ` ${report.tool_version}` : ""}`} className="mb-4">
    <div className="flex flex-wrap items-center gap-3 text-sm mb-3">
      <StatusBadge tone={VERDICT_TONE[report.verdict] ?? "neutral"} dot>{VERDICT_LABELS[report.verdict] ?? report.verdict}</StatusBadge>
      <span>Aprobado: <b>{Math.round(report.pass_rate * 100)} %</b></span>
      <span>Costo de la prueba: <b>{formatUsd(report.cost)}</b></span>
      <span className="text-text-tertiary">Corpus {report.corpus_version}</span>
    </div>
    {report.regressions && report.regressions.length > 0 && (
      <Notice tone="error">
        Regresión respecto de la corrida anterior{report.compared_with?.tool_version ? ` (${report.compared_with.tool_version})` : ""}:{" "}
        {report.regressions.map(r => CAPABILITY_LABELS[r.capability] ?? r.capability).join(", ")}.
      </Notice>
    )}
    <table className={tableClass}>
      <thead><tr><th className={thClass}>Función</th><th className={thClass}>Resultado</th><th className={thClass}>Detalle</th></tr></thead>
      <tbody>
        {report.results.map(r => (
          <tr key={r.name}>
            <td className={tdClass}>{CAPABILITY_LABELS[r.capability] ?? r.capability}</td>
            <td className={tdClass}>
              <StatusBadge tone={r.passed ? "ok" : "danger"} dot>{r.passed ? "Aprobado" : "Fallado"}</StatusBadge>
              {r.silent && <span className="ml-2 text-xs text-danger">en silencio</span>}
            </td>
            <td className={tdClass}>{detailLabel(r.detail_code)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </Card>
);

export const FidelityTab: React.FC<{ perms: Permissions; destinations: Destination[] }> = ({ perms, destinations }) => {
  const usable = destinations.filter(d => d.status === "active");
  const [dest, setDest] = useState("");
  const [tool, setTool] = useState<KitTool>("claude_code");
  const [version, setVersion] = useState("");
  const [report, setReport] = useState<FidelityReport | null>(null);
  const [history, setHistory] = useState<FidelityReport[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const name = (id: string) => destinations.find(d => d.id === id)?.name ?? "(destino)";

  const loadHistory = useCallback(async () => {
    try { setHistory(await us5Api.fidelityRuns()); } catch { setHistory([]); }
  }, []);
  useEffect(() => { void loadHistory(); }, [loadHistory]);

  const run = async () => {
    if (!dest) { setErr("Elegí el destino a probar."); return; }
    setBusy(true); setErr(null); setReport(null);
    try {
      setReport(await us5Api.runFidelity({ destination_id: dest, tool, ...(version.trim() ? { tool_version: version.trim() } : {}) }));
      await loadHistory();
    } catch (e) {
      const status = e instanceof RedirectApiError ? e.status : undefined;
      setErr(us5ErrorMessage(status, (e as Error).message, "Ese destino no está disponible para esta organización."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <Notice tone="info">
        La prueba reproduce conversaciones sintéticas de la herramienta contra el destino y dice qué funciona:
        conversación, herramientas, streaming largo, errores y contexto. No usa datos de ningún usuario, solo
        corre contra destinos de tu catálogo y respeta tu residencia. Repetila al actualizar una herramienta:
        las regresiones se ven antes de que lleguen a los usuarios.
      </Notice>
      {perms.canAdmin && (
        <Card title="Probar un destino" className="mb-6">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <SelectField label="Destino" value={dest} onChange={setDest} placeholder="Elegí…"
              options={usable.map(d => ({ value: d.id, label: d.name }))} />
            <SelectField label="Herramienta" value={tool} onChange={v => setTool(v as KitTool)}
              options={KIT_TOOLS.map(t => ({ value: t, label: KIT_TOOL_LABELS[t] }))} />
            <Field label="Versión de la herramienta (opcional)" value={version} onChange={e => setVersion(e.target.value)} />
          </div>
          <div className="flex justify-end mt-4"><Button onClick={run} disabled={busy}>{busy ? "Probando…" : "Ejecutar prueba"}</Button></div>
        </Card>
      )}
      {err && <Notice tone="error" onClose={() => setErr(null)}>{err}</Notice>}
      {report && <ReportView report={report} />}
      <Card title="Corridas anteriores">
        <table className={tableClass}>
          <thead><tr><th className={thClass}>Destino</th><th className={thClass}>Herramienta</th><th className={thClass}>Versión</th><th className={thClass}>Veredicto</th><th className={thClass}>Fecha</th></tr></thead>
          <tbody>
            {history.length === 0 && <EmptyRow cols={5}>Todavía no se corrió ninguna prueba.</EmptyRow>}
            {history.map(h => (
              <tr key={h.id}>
                <td className={tdClass}>{name(h.destination_id)}</td>
                <td className={tdClass}>{KIT_TOOL_LABELS[h.tool as KitTool] ?? h.tool}</td>
                <td className={tdClass}>{h.tool_version ?? "—"}</td>
                <td className={tdClass}><StatusBadge tone={VERDICT_TONE[h.verdict] ?? "neutral"} dot>{VERDICT_LABELS[h.verdict]?.split(" (")[0] ?? h.verdict}</StatusBadge></td>
                <td className={tdClass}>{new Date(h.run_at).toLocaleString("es")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
};
