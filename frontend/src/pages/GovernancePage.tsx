import React, { useCallback, useEffect, useState } from "react";
import {
  api,
  ApiError,
  CONNECTION_MODES,
  GovernanceEffectiveState,
  GovernanceLayerStatus,
  GovernanceOrigin,
  GovernanceStatus,
} from "../services/api";

/**
 * Página "Gobernanza" (spec 027, US1 — T017).
 *
 * Muestra el estado REAL de cada capa de protección: lo que se está aplicando de verdad,
 * no lo que alguien deseó (FR-001). Es página propia de primer nivel y no una pestaña
 * dentro de Seguridad (D7): SecurityPage no tiene shell de pestañas y heredaría su botón
 * "Guardar Cambios" global, que ES el bug de los toggles que se pierden al desmontar.
 *
 * Vista de solo lectura a propósito: US1 entrega confianza ("lo que la UI muestra es lo que
 * corre") sin ninguna capacidad de configuración nueva. Los controles de decisión llegan en
 * la US2, con autosave por control y rollback desde la respuesta del servidor.
 *
 * Constitución VII: ningún nombre de proveedor externo en el copy. Las capas se nombran por
 * lo que protegen; la delegación se explica como "servicio upstream", nunca por su marca.
 */

// Copy por capa. Las claves son los `layer_key` del registry (identidad estable que viaja a
// applied_layers); el nombre de display vive acá porque es white-label y editable, mientras
// la clave no cambia jamás.
const LAYER_COPY: Record<string, { name: string; que_protege: string }> = {
  interception_audit: {
    name: "Intercepción y registro",
    que_protege: "Cada pedido se intercepta y queda registrado con su atribución. Es lo que hace del producto un firewall y no un proxy.",
  },
  pii_detection: {
    name: "Detección de datos personales",
    que_protege: "Detecta datos personales en el texto aunque el enmascarado esté apagado: el pedido nunca queda sin relato.",
  },
  secret_detection: {
    name: "Bloqueo de secretos",
    que_protege: "Detecta claves y tokens antes de que salgan de la organización.",
  },
  ai_act_evaluation: {
    name: "Evaluación de cumplimiento AI-Act",
    que_protege: "Evalúa cada pedido contra la política de cumplimiento y lo deja registrado.",
  },
  pii_masking: {
    name: "Enmascarado de datos personales",
    que_protege: "Transforma lo detectado antes de que salga. Se puede apagar por alcance (en herramientas de código el enmascarado rompe el código); apagarlo no apaga la detección.",
  },
  sensitive_routing: {
    name: "Reruteo de prompts sensibles",
    que_protege: "Envía los prompts con términos sensibles a un modelo local, de forma transparente.",
  },
  content_moderation: {
    name: "Moderación de contenido",
    que_protege: "Clasifica y frena contenido de categorías dañinas.",
  },
  prompt_injection: {
    name: "Defensa anti-inyección de prompts",
    que_protege: "Frena intentos de jailbreak e inyección de instrucciones adversarias.",
  },
  content_safety: {
    name: "Seguridad de contenido por severidad",
    que_protege: "Clasificación de contenido inapropiado por nivel de severidad.",
  },
  provider_guardrails: {
    name: "Guardarraíles de plataforma en la nube",
    que_protege: "Temas restringidos y filtros corporativos aplicados en la plataforma de nube.",
  },
};

// Los 5 estados deben distinguirse de un golpe de vista: color + FORMA, nunca solo texto
// (data-model §4, FR-001). El `resumen` es el copy que separa "no la aplicamos nosotros" de
// "estás desprotegido" (FR-013) — el `motivo` concreto llega del backend por capa.
const ESTADO_UI: Record<
  GovernanceEffectiveState,
  { label: string; glyph: string; text: string; border: string; bg: string; resumen: string }
> = {
  aplicandose: {
    label: "Aplicándose",
    glyph: "●",
    text: "text-success",
    border: "border-success/30",
    bg: "bg-success/10",
    resumen: "Corre sobre el tráfico de este alcance, confirmado — no es una intención declarada.",
  },
  delegada: {
    label: "Delegada al servicio upstream",
    glyph: "◐",
    text: "text-primary",
    border: "border-primary/30",
    bg: "bg-primary/10",
    resumen: "No la aplicamos nosotros: la aporta el servicio upstream en su propio extremo. El tráfico NO queda desprotegido — el piso se sigue aplicando.",
  },
  requiere_credencial: {
    label: "Requiere credencial",
    glyph: "▲",
    text: "text-warning",
    border: "border-warning/30",
    bg: "bg-warning/10",
    resumen: "Está deseada pero le falta la credencial: no se está aplicando y no se cuenta como protección.",
  },
  degradada: {
    label: "Degradada",
    glyph: "◆",
    text: "text-danger",
    border: "border-danger/30",
    bg: "bg-danger/10",
    resumen: "Venía aplicándose y dejó de confirmarse. Se reporta degradada, jamás activa.",
  },
  no_disponible: {
    label: "No disponible",
    glyph: "○",
    text: "text-text-secondary",
    border: "border-slate-700/40",
    bg: "bg-slate-800/40",
    resumen: "No se está aplicando en este alcance. Es el estado por defecto: sin confirmación, no se afirma nada.",
  },
};

// Orden de lectura: primero lo que protege, al final lo que no. Es el orden en que un admin
// responde "¿qué me está cubriendo hoy?".
const ESTADO_ORDER: GovernanceEffectiveState[] = [
  "aplicandose",
  "delegada",
  "requiere_credencial",
  "degradada",
  "no_disponible",
];

const MODE_COPY: Record<string, { title: string; subtitle: string }> = {
  subscription: {
    title: "Tráfico de suscripción",
    subtitle: "Pedidos que viajan contra la suscripción de la propia organización. El servicio upstream aporta parte de las protecciones.",
  },
  "gateway-models": {
    title: "Modelos de la pasarela",
    subtitle: "Pedidos hacia modelos administrados por la pasarela (incluidos los locales). Acá no hay nadie más protegiendo: solo lo que aplica el producto.",
  },
};

const ORIGEN_LABELS: Record<GovernanceOrigin, string> = {
  floor: "Piso del producto",
  connection: "Conexión (clave)",
  surface: "Superficie / herramienta",
  connection_mode: "Modo de conexión",
  tenant_default: "Default de la organización",
  product_default: "Default del producto",
};

/** Se exporta —igual que `EstadoBadge`— porque el vocabulario de estados es el contrato de
 *  honestidad de la 027: si Seguridad y el Panel se pintaran su propia versión, el mismo
 *  estado terminaría dicho de dos formas distintas y volvería la ambigüedad que la spec
 *  elimina. Una sola fuente de copy y color para las tres vistas. */
export function estadoUi(estado: GovernanceEffectiveState) {
  // Un estado fuera del enum cerrado NO se pinta como algo bueno: cae al fail-closed.
  return ESTADO_UI[estado] || ESTADO_UI.no_disponible;
}

function layerCopy(layerKey: string): { name: string; que_protege: string } {
  return (
    LAYER_COPY[layerKey] || {
      name: layerKey,
      que_protege: "Capa declarada por el catálogo del producto.",
    }
  );
}

export function EstadoBadge({ estado }: { estado: GovernanceEffectiveState }) {
  const ui = estadoUi(estado);
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-[10px] font-bold whitespace-nowrap ${ui.border} ${ui.bg} ${ui.text}`}
    >
      <span aria-hidden="true" className="text-[11px] leading-none">{ui.glyph}</span>
      {ui.label}
    </span>
  );
}

/** Tarjeta de un modo de conexión: agrupa las capas por estado para que "qué protege este
 *  tráfico" se responda de un vistazo, sin leer capa por capa (SC-002). */
function ModeCard({ mode, layers }: { mode: string; layers: GovernanceLayerStatus[] }) {
  const copy = MODE_COPY[mode] || { title: mode, subtitle: "Alcance de tráfico." };
  const aplicandose = layers.filter((l) => l.estado_efectivo === "aplicandose").length;

  return (
    <div className="bg-panel border border-slate-700/40 rounded-lg p-5 space-y-4">
      <div className="space-y-1">
        <h3 className="text-sm font-bold text-white">{copy.title}</h3>
        <p className="text-[11px] text-text-secondary leading-relaxed">{copy.subtitle}</p>
      </div>

      <div className="bg-background/40 border border-slate-700/30 rounded px-3 py-2 text-xs">
        <span className="text-text-secondary">Aplicándose ahora: </span>
        <span className="font-mono font-bold text-success">
          {aplicandose} / {layers.length}
        </span>
        <span className="text-text-secondary"> capas del catálogo</span>
      </div>

      <div className="space-y-3">
        {ESTADO_ORDER.map((estado) => {
          const grupo = layers.filter((l) => l.estado_efectivo === estado);
          if (grupo.length === 0) return null;
          const ui = estadoUi(estado);
          return (
            <div key={estado} className="space-y-1.5">
              <div className={`flex items-center gap-1.5 text-[11px] font-bold ${ui.text}`}>
                <span aria-hidden="true">{ui.glyph}</span>
                <span>{ui.label}</span>
                <span className="text-text-secondary font-mono font-normal">({grupo.length})</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {grupo.map((l) => (
                  <span
                    key={l.layer_key}
                    title={l.motivo || undefined}
                    className={`px-1.5 py-0.5 rounded border text-[10px] ${ui.border} ${ui.bg} text-white`}
                  >
                    {layerCopy(l.layer_key).name}
                    {l.tier === "floor" && (
                      <span className="ml-1 text-text-secondary font-mono">piso</span>
                    )}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
        {layers.length === 0 && (
          <p className="text-xs text-text-secondary">Sin capas reportadas para este modo.</p>
        )}
      </div>
    </div>
  );
}

/** Fila de detalle de una capa: estado real + de dónde viene la decisión + motivo. */
/** Una entrada del catálogo deduplicado: los campos estáticos de la capa (invariantes al modo) +
 *  su estado efectivo en cada modo de conexión. El estado depende del modo, así que la tarjeta
 *  nunca colapsa dos modos en un solo badge. */
type CatalogEntry = {
  base: GovernanceLayerStatus;
  porModo: { mode: string; estado: GovernanceEffectiveState; motivo: string }[];
};

const MODE_LABELS: Record<string, string> = {
  subscription: "Suscripción",
  "gateway-models": "Modelos de la pasarela",
};

function LayerRow({ entry }: { entry: CatalogEntry }) {
  const layer = entry.base;
  const copy = layerCopy(layer.layer_key);
  const esPiso = layer.tier === "floor";
  // Cuando se consultó un modo puntual (sin agrupación) `porModo` viene vacío: la tarjeta cae al
  // estado único de `base`, como antes.
  const estados = entry.porModo.length > 0
    ? entry.porModo
    : [{ mode: "", estado: layer.estado_efectivo, motivo: layer.motivo }];
  const aplicandoseEnAlguno = estados.some((e) => e.estado === "aplicandose");
  // El borde de la tarjeta refleja el estado MÁS protegido de los modos (el más verde), para no
  // pintar de rojo una capa que sí corre en un modo; el detalle por modo va adentro.
  const borde = estadoUi(aplicandoseEnAlguno ? "aplicandose" : estados[0].estado).border;

  return (
    <div className={`border rounded-lg p-4 space-y-2.5 ${borde} ${aplicandoseEnAlguno ? "bg-success/5" : "bg-background/10"}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-white text-xs">{copy.name}</span>
            {esPiso ? (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold border border-primary/20 bg-primary/10 text-primary">
                Piso · siempre activo
              </span>
            ) : (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold border border-slate-700 bg-slate-800 text-text-secondary">
                Gobernable
              </span>
            )}
          </div>
          <p className="text-[11px] text-text-secondary leading-relaxed">{copy.que_protege}</p>
        </div>
      </div>

      {/* Estado POR MODO: una fila por modo de conexión con su badge y, si no aplica, su motivo. */}
      <div className="space-y-1.5">
        {estados.map((e) => {
          const ui = estadoUi(e.estado);
          const aplicandose = e.estado === "aplicandose";
          return (
            <div key={e.mode || "único"} className="space-y-0.5">
              <div className="flex items-center justify-between gap-3">
                {e.mode && (
                  <span className="text-[10px] font-mono text-text-secondary">
                    {MODE_LABELS[e.mode] || e.mode}
                  </span>
                )}
                <EstadoBadge estado={e.estado} />
              </div>
              {!aplicandose && (
                <p className={`text-[11px] leading-relaxed border-l-2 pl-2.5 ${ui.border} ${ui.text}`}>
                  {e.motivo || ui.resumen}
                </p>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-text-secondary font-mono pt-1 border-t border-slate-700/20">
        <span>
          {/* `decision_resuelta` es el DESEO, y se rotula como tal: nunca como estado. */}
          Deseado:{" "}
          <span className={layer.decision_resuelta === "on" ? "text-white" : "text-text-secondary"}>
            {esPiso ? "siempre activo (no configurable)" : layer.decision_resuelta === "on" ? "activo" : "apagado"}
          </span>
        </span>
        {layer.planes?.length > 0 && (
          <span>
            Planos: <span className="text-white">{layer.planes.join(" · ")}</span>
          </span>
        )}
      </div>
    </div>
  );
}

export const GovernancePage: React.FC = () => {
  const [status, setStatus] = useState<GovernanceStatus | null>(null);
  const [loading, setLoading] = useState(true);
  // Error TIPADO: 403 y fallo de red se cuentan distinto. Pintar la página vacía ante un
  // 403 —el `catch { // silent }` de SecurityPage— hace que un problema de permisos parezca
  // un producto roto.
  const [error, setError] = useState<{ kind: "forbidden" | "network" | "other"; message: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resumen = await api.getGovernanceStatus();
      let porModo = resumen.porModo;
      if (Object.keys(porModo).length === 0) {
        // El resumen agrupado es parte del contrato, pero su envoltorio es refinable en
        // implementación: si no vino agrupado se pide modo por modo. SC-002 no puede
        // depender de un detalle de serialización.
        const porModoFetched = await Promise.all(
          CONNECTION_MODES.map(async (mode) => [mode, (await api.getGovernanceStatus({ mode })).layers] as const)
        );
        porModo = Object.fromEntries(porModoFetched);
      }
      setStatus({ layers: resumen.layers, porModo });
    } catch (e: any) {
      const apiError = e instanceof ApiError ? e : null;
      if (apiError?.isForbidden) {
        setError({
          kind: "forbidden",
          message:
            e.message ||
            "Esta vista es solo para administradores. Tu sesión no tiene permiso para consultar el estado de gobernanza.",
        });
      } else if (apiError?.isNetwork) {
        setError({
          kind: "network",
          message:
            "No se pudo contactar al servidor. El estado de gobernanza no se puede afirmar sin respuesta: no se muestra nada como activo.",
        });
      } else {
        // Se muestra el código HTTP además del detalle: un 404 (la sección todavía no está
        // disponible en este servidor) y un 500 se leen muy distinto, y sin el código el
        // usuario no puede reportar nada útil.
        const detalle = e?.message || "El servidor no devolvió un motivo.";
        setError({
          kind: "other",
          message: apiError ? `No se pudo obtener el estado de gobernanza (HTTP ${apiError.status}): ${detalle}` : detalle,
        });
      }
      setStatus(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const modos = status ? CONNECTION_MODES.filter((m) => status.porModo[m]) : [];
  const modosExtra = status
    ? Object.keys(status.porModo).filter((m) => !(CONNECTION_MODES as readonly string[]).includes(m))
    : [];

  // El detalle por capa es un CATÁLOGO deduplicado por `layer_key`, no la unión plana de
  // `status.layers` (que trae cada capa una vez POR MODO — 10 capas × 2 modos = 20). Consumir la
  // unión como si fuera una-entrada-por-capa producía claves React duplicadas, tarjetas repetidas
  // con estados contradictorios y un contador N/20. El estado efectivo depende del modo, así que
  // cada tarjeta muestra su estado POR MODO (ver `LayerRow`); los campos estáticos (tier, planos,
  // deseo, copy) son invariantes al modo y se toman de la primera aparición.
  const todosLosModos = status ? [...modos, ...modosExtra] : [];
  const catalogo: CatalogEntry[] = [];
  if (status) {
    const porClave = new Map<string, CatalogEntry>();
    const fuente = todosLosModos.length > 0
      ? todosLosModos.flatMap((m) => status.porModo[m].map((l) => [m, l] as const))
      : status.layers.map((l) => [null as string | null, l] as const);
    for (const [modo, l] of fuente) {
      let entry = porClave.get(l.layer_key);
      if (!entry) {
        entry = { base: l, porModo: [] };
        porClave.set(l.layer_key, entry);
        catalogo.push(entry);
      }
      if (modo) entry.porModo.push({ mode: modo, estado: l.estado_efectivo, motivo: l.motivo });
    }
  }
  const piso = catalogo.filter((c) => c.base.tier === "floor");
  const gobernables = catalogo.filter((c) => c.base.tier !== "floor");

  return (
    <div className="space-y-8 pb-16">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 pb-4 border-b border-slate-700/30">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Gobernanza</h1>
          <p className="text-xs text-text-secondary mt-1">
            Estado real de cada capa de protección: lo que se aplica de verdad sobre el tráfico, no lo que
            está declarado. Una capa que no corre nunca aparece como activa.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="bg-primary hover:bg-primary/90 disabled:opacity-40 text-background font-semibold px-5 py-2 rounded-lg text-xs transition-all"
        >
          {loading ? "Consultando..." : "Actualizar estado"}
        </button>
      </div>

      {error && (
        <div
          className={`px-4 py-3 rounded-lg text-xs border space-y-1 ${
            error.kind === "forbidden"
              ? "bg-warning/10 border-warning/20 text-warning"
              : "bg-danger/10 border-danger/20 text-danger"
          }`}
        >
          <p className="font-bold">
            {error.kind === "forbidden"
              ? "Sin permiso para ver la gobernanza"
              : error.kind === "network"
              ? "Sin conexión con el servidor"
              : "No se pudo leer el estado de gobernanza"}
          </p>
          <p className="font-normal">{error.message}</p>
        </div>
      )}

      {loading && !status && (
        <div className="py-16 text-center text-xs font-mono text-text-secondary">
          Consultando estado de gobernanza...
        </div>
      )}

      {status && (
        <>
          {/* ── Resumen por modo de conexión (FR-010 / SC-002) ── */}
          <div className="space-y-4">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
                Resumen por modo de conexión
              </h2>
              <p className="text-[11px] text-text-secondary">
                Qué protege hoy al tráfico de suscripción y qué al tráfico hacia modelos de la pasarela.
              </p>
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {modos.map((mode) => (
                <ModeCard key={mode} mode={mode} layers={status.porModo[mode]} />
              ))}
              {modosExtra.map((mode) => (
                <ModeCard key={mode} mode={mode} layers={status.porModo[mode]} />
              ))}
            </div>
            {modos.length === 0 && modosExtra.length === 0 && (
              <p className="text-xs text-text-secondary">
                El servidor no devolvió el resumen por modo. El detalle por capa de abajo sigue siendo el
                estado real consultado.
              </p>
            )}
          </div>

          {/* ── Leyenda de estados ── */}
          <div className="bg-panel border border-slate-700/40 rounded-lg p-5 space-y-3">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
              Cómo leer los estados
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {ESTADO_ORDER.map((estado) => {
                const ui = estadoUi(estado);
                return (
                  <div key={estado} className="flex items-start gap-2.5">
                    <span aria-hidden="true" className={`text-sm leading-none mt-0.5 ${ui.text}`}>
                      {ui.glyph}
                    </span>
                    <div className="space-y-0.5">
                      <p className={`text-[11px] font-bold ${ui.text}`}>{ui.label}</p>
                      <p className="text-[11px] text-text-secondary leading-relaxed">{ui.resumen}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* ── Piso no negociable ── */}
          <div className="space-y-4">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
                Piso no negociable
              </h2>
              <p className="text-[11px] text-text-secondary">
                Interceptar y registrar todo el tráfico, detectar datos personales y bloquear secretos. Es la
                promesa del producto: se aplica siempre, en todos los modos y superficies, y ninguna
                configuración puede apagarlo — por eso no hay controles acá.
              </p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {piso.map((c) => (
                <LayerRow key={c.base.layer_key} entry={c} />
              ))}
            </div>
            {piso.length === 0 && (
              <p className="text-xs text-text-secondary">Sin capas de piso reportadas.</p>
            )}
          </div>

          {/* ── Capas gobernables ── */}
          <div className="space-y-4">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
                Capas gobernables
              </h2>
              <p className="text-[11px] text-text-secondary">
                Protecciones que se configuran por alcance. Su estado real es independiente de la decisión:
                una capa deseada activa puede no estar aplicándose, y en ese caso acá se dice por qué.
              </p>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {gobernables.map((c) => (
                <LayerRow key={c.base.layer_key} entry={c} />
              ))}
            </div>
            {gobernables.length === 0 && (
              <p className="text-xs text-text-secondary">Sin capas gobernables reportadas.</p>
            )}
          </div>

          {/* ── Nota honesta (FR-013) ── */}
          <div className="bg-background/40 border border-slate-700/30 rounded-lg p-4 text-[11px] text-text-secondary leading-relaxed">
            <span className="font-semibold text-white">Una capa que no aplicamos no es tráfico desprotegido.</span>{" "}
            Cuando una capa figura como <span className="text-primary">delegada</span>, la protección la aporta
            el servicio upstream en su propio extremo. Cuando figura como{" "}
            <span className="text-text-secondary">no disponible</span> o{" "}
            <span className="text-warning">requiere credencial</span>, esa protección concreta no se está
            ejecutando — y el piso se sigue aplicando igual, en los dos casos.
          </div>
        </>
      )}
    </div>
  );
};

export default GovernancePage;
