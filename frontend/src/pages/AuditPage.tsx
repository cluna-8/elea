import React, { useState, useEffect } from "react";
import { api, AuditHealth } from "../services/api";
import { StatusBadge, BadgeTone } from "../components/ui";

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
  /** Capa del registry 027 que produjo el bloqueo (la expone el listado desde la 031).
   *  `null` = bloqueo real SIN capa del catálogo (p. ej. residencia de datos, que no es
   *  una capa del registry); clave ausente = backend anterior a la 031, que no manda el
   *  dato. Los dos casos se dicen distinto en el detalle: "no hay registro" no es "no
   *  actuó ninguna capa". */
  blocked_by_layer?: string | null;
}

type FamiliaEstado = "bloqueado" | "riesgo" | "cumple" | "error" | "desconocido";

const TONO_POR_FAMILIA: Record<FamiliaEstado, BadgeTone> = {
  bloqueado: "danger",
  riesgo: "warn",
  cumple: "ok",
  error: "neutral",
  desconocido: "neutral",
};

/** Etiquetas legibles de `compliance_status`, alineadas con la vitrina «Conexiones en
 *  vivo» (monitor.py:279) para que el mismo evento no se cuente de dos maneras.
 *
 *  Es un `Map` y no un objeto literal por la misma razón que la vitrina usa prototipo
 *  nulo: el valor viene del servidor y un `compliance_status = "toString"` en un objeto
 *  literal NO devuelve `undefined` sino una función heredada de `Object.prototype` — el
 *  destructuring posterior revienta y deja la página en blanco. Con `Map`, cualquier
 *  clave ajena es simplemente una clave ausente. */
const ETIQUETAS_ESTADO = new Map<string, [FamiliaEstado, string]>([
  ["passed", ["cumple", "Cumple"]],
  // Valor legado: ningún plano lo escribe hoy, pero hay filas viejas y analytics lo cuenta
  // junto a `passed` (analytics.py:212). Se etiqueta igual para no partir la historia.
  ["allowed", ["cumple", "Cumple"]],
  ["flagged_high_risk", ["riesgo", "Riesgo alto (AI Act)"]],
  ["blocked_prohibited", ["bloqueado", "Bloqueado (AI Act)"]],
  ["blocked_secret", ["bloqueado", "Bloqueado (secreto)"]],
  ["blocked_guardian", ["bloqueado", "Bloqueado (guardián)"]],
  ["blocked_by_policy", ["bloqueado", "Bloqueado (política)"]],
  ["blocked_residency", ["bloqueado", "Bloqueado (residencia)"]],
  ["blocked_entity", ["bloqueado", "Bloqueado (dato personal)"]],
  // Rechazo por capacidad (tope de admisión del motor, #135): no lo impidió una política
  // —por eso no es familia «bloqueado»— pero el officer tiene que poder explicar por qué el
  // pedido no salió sin leer el literal interno. Mismo evento y texto que en la vitrina.
  ["rejected_saturated", ["error", "Rechazado por capacidad"]],
  ["upstream_error", ["error", "Error del proveedor"]],
]);

/** Familia + etiqueta + tono de un `compliance_status`.
 *
 *  La familia se DERIVA del nombre cuando la tabla no conoce el valor: un estado nuevo que
 *  se llama `blocked_*` ES un bloqueo y se pinta como bloqueo aunque nadie haya tocado
 *  esta página. El default anterior era "Cumple" en verde, así que `blocked_secret`,
 *  `blocked_guardian` y `blocked_residency` —tres motivos que el producto YA escribe— se
 *  leían como transacciones correctas en la pantalla que audita bloqueos (FR-006). El
 *  default correcto no es "no sé", es lo que el nombre del estado afirma. */
export const estadoDeCumplimiento = (
  status: string
): { familia: FamiliaEstado; etiqueta: string; tono: BadgeTone; esBloqueo: boolean } => {
  const raw = String(status ?? "").trim();
  const conocido = ETIQUETAS_ESTADO.get(raw);
  const [familia, etiqueta] = conocido
    ? conocido
    : raw.startsWith("blocked")
    ? (["bloqueado", `Bloqueado (${raw})`] as [FamiliaEstado, string])
    : raw.startsWith("flagged")
    ? (["riesgo", raw] as [FamiliaEstado, string])
    : raw.startsWith("rejected")
    ? (["error", raw] as [FamiliaEstado, string])
    : raw.includes("error")
    ? (["error", raw] as [FamiliaEstado, string])
    : (["desconocido", raw || "sin estado"] as [FamiliaEstado, string]);
  return {
    familia,
    etiqueta,
    tono: TONO_POR_FAMILIA[familia],
    esBloqueo: familia === "bloqueado",
  };
};

/** Opciones del filtro de cumplimiento.
 *
 *  `bloqueados` / `permitidos` son FAMILIAS (parámetro `estado` del endpoint, spec 031
 *  FR-006): el officer aísla TODOS los intentos impedidos —vengan del Playground, del
 *  motor por byok o del passthrough— sin tener que conocer de memoria los motivos. Las
 *  otras dos opciones son motivos exactos (`compliance_status`).
 *
 *  La opción anterior «Permitidos» mandaba `compliance_status=allowed`, un valor que
 *  NINGÚN plano escribe (los tres escriben `passed`): devolvía siempre cero registros.
 *  Ahora la resuelve el backend como complemento exacto de «bloqueados». */
type OpcionCumplimiento =
  | "todos"
  | "bloqueados"
  | "permitidos"
  | "blocked_prohibited"
  | "flagged_high_risk";

const OPCIONES_CUMPLIMIENTO: Array<{ valor: OpcionCumplimiento; etiqueta: string }> = [
  { valor: "todos", etiqueta: "Cumplimiento: Todos" },
  { valor: "bloqueados", etiqueta: "Solo bloqueados" },
  { valor: "permitidos", etiqueta: "Solo permitidos" },
  { valor: "blocked_prohibited", etiqueta: "Bloqueados (AI Act)" },
  { valor: "flagged_high_risk", etiqueta: "Riesgo alto (AI Act)" },
];

/** Traduce la opción elegida a los parámetros del endpoint: `estado` (familia, resuelta
 *  con `LIKE 'blocked%'` del lado del servidor) o `compliance_status` (igualdad exacta).
 *  Nunca se mandan los dos juntos. */
export const parametrosDeCumplimiento = (
  opcion: OpcionCumplimiento
): { estado?: string; compliance_status?: string } => {
  if (opcion === "todos") return {};
  if (opcion === "bloqueados" || opcion === "permitidos") return { estado: opcion };
  return { compliance_status: opcion };
};

/** Hora local de un timestamp del backend. Los `timestamp` de las filas son naive (UTC sin
 *  'Z') y los del health vienen con offset: se normaliza igual que `fmtTime` del monitor
 *  para que Auditoría y «Conexiones en vivo» muestren la MISMA hora del mismo evento. */
const aFechaLocal = (isoString: string): Date | null => {
  try {
    const utc = /[zZ]|[+-]\d{2}:?\d{2}$/.test(isoString) ? isoString : isoString + "Z";
    const d = new Date(utc);
    return isNaN(d.getTime()) ? null : d;
  } catch {
    return null;
  }
};

/** Momento legible del último fallo: «las 14:32» si fue hoy, «el 27/07 a las 14:32» si no.
 *  El contrato pide «desde HH:MM», pero un contador sin TTL puede tener días: la hora sola
 *  haría creer que la pérdida fue hace un rato. */
const momentoLocal = (iso: string, ahora: Date): string | null => {
  const d = aFechaLocal(iso);
  if (!d) return null;
  // `hour12: false` explícito: el contrato pide «desde HH:MM» y hay entornos (según la
  // versión de ICU) donde es-AR resuelve a 12 h y devuelve «09:32 a. m.».
  const hora = d.toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit", hour12: false });
  const mismoDia =
    d.getFullYear() === ahora.getFullYear() &&
    d.getMonth() === ahora.getMonth() &&
    d.getDate() === ahora.getDate();
  if (mismoDia) return `las ${hora}`;
  // DD/MM armado a mano: con el esqueleto día+mes hay ICUs que devuelven «26/7», y en la
  // misma pantalla la tabla escribe «26/07/2026». El formato del aviso no depende de eso.
  const dia = String(d.getDate()).padStart(2, "0");
  const mes = String(d.getMonth() + 1).padStart(2, "0");
  return `el ${dia}/${mes} a las ${hora}`;
};

/** Texto del aviso de eventos no registrados (spec 031, T010) o `null` si no hay nada que
 *  avisar. Se lee del bloque `audit` del health: `lost_events` es el contador
 *  `basa:audit:lost` de Redis, que sube cuando el escritor agota sus reintentos.
 *
 *  Casos que NO muestran aviso: health ilegible (`null`), contador en cero, o un contador
 *  que no es un número. Un aviso es una afirmación fuerte —«su registro está incompleto»—
 *  y no se hace sobre un dato que no se pudo leer. El caso inverso sí se cubre: si hay
 *  pérdidas pero no hay timestamp, se avisa igual, sin la hora. */
export const avisoDePerdidas = (
  audit: AuditHealth | null | undefined,
  ahora: Date = new Date()
): string | null => {
  const n = Number(audit?.lost_events ?? 0);
  if (!Number.isFinite(n) || n <= 0) return null;
  const plural = n === 1 ? "" : "s";
  const cuando = audit?.last_failure_at ? momentoLocal(audit.last_failure_at, ahora) : null;
  return `${n} evento${plural} no registrado${plural}${cuando ? ` desde ${cuando}` : ""}`;
};

export const AuditPage: React.FC = () => {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  // Bloque `audit` del health (spec 031 §GET /health): pérdidas de escritura de auditoría.
  // `null` = no se pudo leer → no se afirma nada (ni bien ni mal).
  const [auditHealth, setAuditHealth] = useState<AuditHealth | null>(null);

  // Filters
  const [piiFilter, setPiiFilter] = useState<string>("all");
  const [complianceFilter, setComplianceFilter] = useState<OpcionCumplimiento>("todos");
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
        ...parametrosDeCumplimiento(complianceFilter),
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

  /** Lectura del health para el aviso de eventos perdidos. Va por separado de los logs a
   *  propósito: si el health no responde, la tabla de auditoría se muestra igual. */
  const fetchAuditHealth = async () => {
    const health = await api.getSystemHealth();
    setAuditHealth(health?.audit ?? null);
  };

  useEffect(() => {
    fetchLogs();
  }, [piiFilter, complianceFilter, fromDate, toDate, offset]);

  useEffect(() => {
    fetchAuditHealth();
  }, []);

  const refrescar = () => {
    fetchLogs();
    fetchAuditHealth();
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      await api.exportAuditLogs({
        pii_detected: piiFilter !== "all" ? piiFilter === "true" : undefined,
        ...parametrosDeCumplimiento(complianceFilter),
        from_date: fromDate ? new Date(fromDate).toISOString() : undefined,
        to_date: toDate ? new Date(toDate + "T23:59:59").toISOString() : undefined,
      });
    } catch (e) {
      alert("No se pudo exportar. Intente nuevamente.");
    } finally {
      setExporting(false);
    }
  };

  const formatTimestamp = (isoString: string) => {
    const d = aFechaLocal(isoString);
    if (!d) return isoString;
    return d.toLocaleString("es-AR", {
      day: "2-digit", month: "2-digit", year: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit",
    });
  };

  const toggleExpand = (id: string) => {
    setExpandedRow((prev) => (prev === id ? null : id));
  };

  // Aviso de eventos no registrados (spec 031, T010): `null` = nada que avisar.
  const aviso = avisoDePerdidas(auditHealth);

  return (
    <div className="space-y-6 p-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex justify-between items-center pb-4 border-b border-border">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-text-primary">Logs de Auditoría</h1>
          <p className="text-xs text-text-secondary mt-1">
            Registro de cada transacción para control de cumplimiento y costos. No se guarda el texto de los prompts.
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
            onClick={refrescar}
            className="bg-surface-2 hover:bg-border text-text-primary font-medium px-4 py-2 rounded-lg text-xs transition-colors border border-border"
          >
            {loading ? "Actualizando..." : "Actualizar"}
          </button>
        </div>
      </div>

      {/* Aviso de pérdidas: sólo aparece si el health cuenta eventos no registrados. Es la
          señal que convierte un agujero silencioso en un hecho visible (spec 031, US2). */}
      {aviso && (
        <div
          role="status"
          className="bg-warn-bg border border-warn/30 rounded-lg px-4 py-3 flex items-start gap-3"
        >
          <span aria-hidden="true" className="text-warn font-bold leading-5">!</span>
          <div className="space-y-1">
            <p className="text-xs font-semibold text-warn">{aviso}</p>
            <p className="text-[11px] text-text-secondary">
              Esas peticiones no se pudieron guardar, así que el registro de abajo está incompleto.
              Avise a quien opera la instalación.
            </p>
          </div>
        </div>
      )}

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
          onChange={(e) => { setComplianceFilter(e.target.value as OpcionCumplimiento); setOffset(0); }}
          className="bg-surface border border-border rounded px-3 py-1.5 text-xs text-text-primary"
        >
          {OPCIONES_CUMPLIMIENTO.map((o) => (
            <option key={o.valor} value={o.valor}>{o.etiqueta}</option>
          ))}
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
          <div className="py-12 text-center text-xs text-text-secondary">
            {complianceFilter === "bloqueados"
              ? "No hay intentos bloqueados en el período seleccionado."
              : "No se encontraron registros."}
          </div>
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
                    <th className="p-3">Estado</th>
                    <th className="p-3">Guardianes</th>
                    <th className="p-3">Latencia</th>
                    <th className="p-3 text-right">Costo</th>
                  </tr>
                </thead>
                <tbody className="text-text-primary text-xs font-mono">
                  {logs.map((log) => {
                    const isExpanded = expandedRow === log.id;
                    const guardianCount = log.guardian_events?.length ?? 0;
                    const estado = estadoDeCumplimiento(log.compliance_status);
                    return (
                      <React.Fragment key={log.id}>
                        <tr
                          onClick={() => toggleExpand(log.id)}
                          className="border-b border-border hover:bg-background/30 transition-colors cursor-pointer"
                        >
                          <td
                            className={`p-3 text-text-secondary ${estado.esBloqueo ? "border-l-2 border-l-danger" : ""}`}
                          >
                            {formatTimestamp(log.timestamp)}
                          </td>
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
                          <td className="p-3">
                            <StatusBadge tone={estado.tono}>{estado.etiqueta}</StatusBadge>
                            {/* La capa va bajo el badge y no sólo en el detalle: SC-005
                                pide quién/qué/cuándo/qué capa de un vistazo. */}
                            {estado.esBloqueo && log.blocked_by_layer && (
                              <div className="text-[10px] text-text-tertiary mt-1">{log.blocked_by_layer}</div>
                            )}
                          </td>
                          <td className="p-3">
                            {guardianCount > 0 ? (
                              <span className="bg-warning/10 text-warning border border-warning/20 px-1.5 py-0.5 rounded text-[10px] font-semibold">
                                {guardianCount} evento{guardianCount > 1 ? "s" : ""}
                              </span>
                            ) : (
                              <span className="text-text-tertiary">sin eventos</span>
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
                                  <div className="mt-2 pt-2 border-t border-border space-y-1.5">
                                    <p className="text-[10px] text-text-secondary flex items-center gap-2">
                                      Estado:
                                      <StatusBadge tone={estado.tono}>{estado.etiqueta}</StatusBadge>
                                    </p>
                                    {estado.esBloqueo && (
                                      <p className="text-[10px] text-text-secondary">
                                        Capa que bloqueó:{" "}
                                        {log.blocked_by_layer ? (
                                          <span className="text-text-primary font-mono">{log.blocked_by_layer}</span>
                                        ) : "blocked_by_layer" in log ? (
                                          // Bloqueo real sin capa del catálogo (p. ej. residencia de
                                          // datos, que no es una capa del registry 027).
                                          <span className="text-text-tertiary">sin capa asociada</span>
                                        ) : (
                                          // El listado no trae el dato: "no hay registro" ≠ "no actuó
                                          // ninguna capa". No se afirma lo que no se sabe.
                                          <span className="text-text-tertiary">sin dato</span>
                                        )}
                                      </p>
                                    )}
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
