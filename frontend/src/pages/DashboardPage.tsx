import React, { useState, useEffect, useCallback } from "react";
import { api, GovernanceLayerStatus, NlpHealth } from "../services/api";
import {
  Card,
  PageHeader,
  StatusBadge,
  Table,
  TableColumn,
  cn,
} from "../components/ui";

type Range = "day" | "week" | "month";

/** Aviso PERSISTENTE del estado de la detección de datos personales (issue #63).
 *
 *  Existe porque el producto podía estar detectando PII con patrones de desarrollo —o
 *  rechazando tráfico— sin que ninguna pantalla lo dijera. Un firewall que degrada su capa
 *  más importante en silencio es peor que uno que no la tiene: el operador cree que está
 *  protegido. Por eso el aviso no se puede cerrar y vive en el panel principal, no escondido
 *  en una pantalla de configuración.
 *
 *  Tres formas distintas para tres hechos distintos — colapsarlos sería reintroducir el bug:
 *  - `unreachable` → ROJO. El motor está caído y hay consecuencia AHORA (según la política:
 *    tráfico rechazado o servido con cobertura reducida).
 *  - `not_configured` → INFORMATIVO. No hay motor cableado: es el modo de desarrollo, una
 *    decisión de despliegue. Se dice, no se alarma.
 *  - `ok` (o sin dato) → nada. "No sé" se pinta como nada, jamás como "todo bien". */
function AvisoNlp({ nlp }: { nlp: NlpHealth | null }) {
  if (!nlp || nlp.status === "ok") return null;

  if (nlp.status === "not_configured") {
    return (
      <div
        role="status"
        className="bg-surface-2 border border-border text-text-secondary px-4 py-3 rounded-md text-sm"
      >
        <span className="font-semibold text-text-primary">
          Detección NLP: no configurada — modo regex de desarrollo.
        </span>{" "}
        Los datos personales se detectan con patrones locales, que cubren menos casos que el
        motor de lenguaje (nombres sin tratamiento previo, móviles sin prefijo internacional).
        No utilice esta instalación con datos reales de pacientes o clientes.
      </div>
    );
  }

  if (nlp.status !== "unreachable") return null;

  const degradando = nlp.fail_mode_efectivo === "degrade";
  return (
    <div
      role="alert"
      className="bg-danger-bg border border-danger text-danger px-4 py-3 rounded-md text-sm space-y-1"
    >
      <p className="font-semibold">
        Detección NLP: el motor de detección de datos personales no responde.
      </p>
      <p>
        {degradando
          ? "La política de esta instalación es continuar (degradar): las peticiones se están " +
            "sirviendo con detección por patrones y la cobertura de datos personales es MENOR " +
            "de la habitual."
          : "La política de esta instalación es bloquear: las peticiones con enmascarado activo " +
            "se están rechazando hasta que el motor vuelva."}
      </p>
      {degradando && nlp.degraded_since && (
        <p className="text-xs">
          Desde {new Date(nlp.degraded_since).toLocaleString("es-ES")}
          {typeof nlp.degraded_requests === "number" && nlp.degraded_requests > 0
            ? ` · ${nlp.degraded_requests} peticiones servidas con patrones`
            : ""}
          .
        </p>
      )}
      <p className="text-xs">
        Revise el servicio de detección con el administrador del sistema. La postura ante esta
        caída se configura en Seguridad → Enmascaramiento de datos.
      </p>
    </div>
  );
}

const RANGE_LABELS: Record<Range, string> = {
  day: "Hoy",
  week: "Semana",
  month: "Mes",
};

function KpiCard({
  label,
  value,
  sub,
  color = "text-text-primary",
}: {
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
}) {
  return (
    <Card>
      <div className="space-y-1">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-text-secondary">
          {label}
        </p>
        <p className={cn("text-3xl font-bold leading-none", color)}>{value}</p>
        {sub && <p className="text-[10px] text-text-secondary">{sub}</p>}
      </div>
    </Card>
  );
}

export const DashboardPage: React.FC = () => {
  const [range, setRange] = useState<Range>("week");
  const [summary, setSummary] = useState<any>(null);
  const [engineStatus, setEngineStatus] = useState<"online" | "offline" | null>(null);
  // Capas de gobernanza con su estado REAL (spec 027). Reemplaza el conteo de guardianes
  // por `is_active`, que contaba DESEOS: mostrar "N activos" a partir de una intención es
  // la misma mentira que la 027 elimina, y en el panel principal es la más visible.
  const [layers, setLayers] = useState<GovernanceLayerStatus[] | null>(null);
  // Estado de la detección de datos personales (issue #63). `null` = no se pudo leer, y se
  // pinta como nada: nunca como "todo bien".
  const [nlp, setNlp] = useState<NlpHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async (r: Range) => {
    setLoading(true);
    setError(null);
    try {
      const [summaryData, statusData] = await Promise.all([
        api.getAnalyticsSummary(r),
        api.getEngineStatus(),
      ]);
      setSummary(summaryData);
      setEngineStatus(statusData.status);
    } catch (e: any) {
      setError("No se pudieron cargar las métricas. Revise la conexión con el servidor.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(range);
  }, [range, fetchData]);

  useEffect(() => {
    // Consulta aparte: el estado de gobernanza es admin-only, y este panel lo ven todos los
    // roles. Si no se puede leer, la fila muestra "sin dato" — nunca un número inventado.
    (async () => {
      try {
        // Se consulta UN modo (`gateway-models`), no el resumen sin params: éste devuelve la unión
        // de los dos modos (cada capa repetida → contador N/20). `gateway-models` es el modo
        // conservador —somos la única protección, sin upstream que delegue—, así el número del panel
        // es el más honesto: cuántas de NUESTRAS capas corren de verdad.
        setLayers((await api.getGovernanceStatus({ mode: "gateway-models" })).layers);
      } catch {
        setLayers(null);
      }
    })();
  }, []);

  useEffect(() => {
    // Health de producto, por separado de las métricas: si el health no responde, el panel
    // se dibuja igual (mismo criterio que el aviso de pérdidas de auditoría en Logs). El
    // bloque `nlp` sólo viaja a admin/compliance_officer; para el resto llega ausente y el
    // aviso simplemente no aparece.
    (async () => {
      const health = await api.getSystemHealth();
      setNlp(health?.nlp ?? null);
    })();
  }, []);

  const capasAplicandose = layers ? layers.filter((l) => l.estado_efectivo === "aplicandose").length : null;
  const guardianEvents = summary?.guardian_activations?.by_guardian || {};
  const guardianEntries = Object.entries(guardianEvents) as [string, number][];
  const maxActivations = guardianEntries.length > 0 ? Math.max(...guardianEntries.map(([, v]) => v)) : 1;

  const modelColumns: TableColumn<any>[] = [
    {
      key: "model",
      header: "Modelo",
      render: (m) => (
        <span className="font-mono font-medium truncate block max-w-[180px]">{m.model}</span>
      ),
    },
    {
      key: "requests",
      header: "Peticiones",
      align: "right",
      render: (m) => <span className="text-text-secondary">{m.requests}</span>,
    },
    {
      key: "cost",
      header: "Costo",
      align: "right",
      render: (m) => (
        <span className="font-mono text-ok">${Number(m.cost_usd).toFixed(4)}</span>
      ),
    },
  ];

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <PageHeader
        className="mb-0"
        title="Panel Principal"
        subtitle="Métricas de uso, costos e incidentes de seguridad del gateway."
        actions={
          <div className="inline-flex gap-1 bg-surface border border-border rounded-md p-1">
            {(["day", "week", "month"] as Range[]).map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => setRange(r)}
                className={cn(
                  "px-3 py-1.5 rounded text-xs font-semibold transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary",
                  range === r
                    ? "bg-primary text-white"
                    : "text-text-secondary hover:text-text-primary hover:bg-surface-2"
                )}
              >
                {RANGE_LABELS[r]}
              </button>
            ))}
          </div>
        }
      />

      {/* Aviso de estado de la detección NLP: va ANTES del error de métricas y fuera del
          `loading`, porque es lo que el operador tiene que ver aunque las métricas no
          carguen — y no depende de ellas. */}
      <AvisoNlp nlp={nlp} />

      {error && (
        <div className="bg-danger-bg text-danger px-4 py-3 rounded-md text-sm">
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
              color="text-ok"
            />
            <KpiCard
              label="Incidentes PII"
              value={summary?.pii_incidents ?? 0}
              sub="Datos enmascarados antes del modelo"
              color={summary?.pii_incidents > 0 ? "text-warn" : "text-text-primary"}
            />
            <KpiCard
              label="Bloqueos de Guardianes"
              value={summary?.guardian_activations?.total ?? 0}
              sub={`${summary?.compliance_blocked ?? 0} bloqueos AI Act`}
              color={summary?.guardian_activations?.total > 0 ? "text-danger" : "text-text-primary"}
            />
          </div>

          {/* Middle row: Top Models + System Status */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Top Models */}
            <Card title="Top Modelos" noPadding>
              <Table
                columns={modelColumns}
                rows={(summary?.models?.slice(0, 5) ?? []) as any[]}
                rowKey={(m) => m.model}
                emptyLabel="Sin peticiones en el período."
                wrapperClassName="border-0 rounded-none"
              />
            </Card>

            {/* System Status */}
            <Card title="Estado del Sistema">
              <div className="space-y-3 text-sm">
                <div className="flex items-center justify-between">
                  <span className="text-text-secondary">Motor de IA</span>
                  <StatusBadge tone={engineStatus === "online" ? "ok" : "danger"} dot>
                    {engineStatus === "online" ? "Online" : "Offline"}
                  </StatusBadge>
                </div>
                <div className="flex items-center justify-between">
                  <span
                    className="text-text-secondary"
                    title="Capas de protección que se están aplicando ahora mismo."
                  >
                    Capas aplicándose
                  </span>
                  {capasAplicandose !== null && layers ? (
                    <span className="font-semibold text-text-primary font-mono">
                      {capasAplicandose} / {layers.length}
                    </span>
                  ) : (
                    <span
                      className="font-semibold text-text-tertiary font-mono"
                      title="No se pudo consultar el estado de las capas con esta sesión."
                    >
                      sin dato
                    </span>
                  )}
                </div>
                <div className="flex items-center justify-between">
                  <span
                    className="text-text-secondary"
                    title="Motor de detección de datos personales (NLP). Sin él, la detección es por patrones locales."
                  >
                    Detección NLP
                  </span>
                  {nlp?.status === "ok" ? (
                    <StatusBadge tone="ok" dot>
                      Activa
                    </StatusBadge>
                  ) : nlp?.status === "unreachable" ? (
                    <StatusBadge tone="danger" dot>
                      No responde
                    </StatusBadge>
                  ) : nlp?.status === "not_configured" ? (
                    <StatusBadge tone="warn" dot>
                      No configurada
                    </StatusBadge>
                  ) : (
                    <span
                      className="font-semibold text-text-tertiary font-mono text-xs"
                      title="No se pudo consultar el estado del motor NLP con esta sesión."
                    >
                      sin dato
                    </span>
                  )}
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-secondary">Latencia media</span>
                  <span className="font-semibold text-warn font-mono">
                    {summary?.avg_latency_ms ?? 0}ms
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-secondary">Tokens optimizados</span>
                  <span className="font-semibold text-info font-mono">
                    {summary?.tokens_saved_by_optimization ?? 0}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-text-secondary">Ahorro de Costes IA</span>
                  <span className="font-semibold text-ok font-mono">
                    ${Number(summary?.cost_saved_usd ?? 0).toFixed(4)}
                  </span>
                </div>
                <div className="pt-2 border-t border-border">
                  <div className="flex justify-between text-xs text-text-secondary">
                    <span>AI Act: {summary?.compliance_passed ?? 0} correctas</span>
                    <span className={summary?.compliance_blocked > 0 ? "text-danger" : ""}>
                      {summary?.compliance_blocked ?? 0} bloqueadas
                    </span>
                  </div>
                </div>
              </div>
            </Card>
          </div>

          {/* Guardian Activations */}
          <Card title="Activaciones de Guardianes">
            {guardianEntries.length > 0 ? (
              <div className="space-y-3">
                {guardianEntries.map(([name, count]) => (
                  <div key={name} className="space-y-1">
                    <div className="flex justify-between text-sm">
                      <span className="text-text-secondary">{name}</span>
                      <span className="text-text-primary font-mono font-semibold">{count}</span>
                    </div>
                    <div className="w-full bg-surface-2 rounded-full h-1.5">
                      <div
                        className="bg-primary h-1.5 rounded-full transition-all duration-500"
                        style={{ width: `${Math.round((count / maxActivations) * 100)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-text-tertiary py-2">
                Sin activaciones de guardianes en el período seleccionado.
              </p>
            )}
          </Card>
        </>
      )}
    </div>
  );
};

export default DashboardPage;
