import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  ApiError,
  CONNECTION_MODES,
  GOVERNANCE_SURFACES,
  GovernanceDecision,
  GovernanceEffectiveState,
  GovernanceLayerStatus,
  GovernanceOrigin,
  GovernanceScopeType,
  GovernanceStatus,
} from "../services/api";

/**
 * Página "Gobernanza" (spec 027).
 *
 * El eje real del producto son DOS modos de conexión: o el tráfico va contra la suscripción de
 * la organización, o va contra un modelo propio administrado por el gateway. La pantalla se
 * organiza por esos dos modos: UNA fila por capa de protección, y dos columnas —Suscripción y
 * Modelo propio— donde se ve el estado real y se configura el control por modo, con autosave.
 *
 * Los ajustes por herramienta (superficie) NO son un tercer modo: son una excepción fina —en
 * herramientas de código el enmascarado rompe el código— y viven plegados en "Avanzado".
 *
 * Lo que se conserva del motor honesto ya verificado y NO se toca: los ejes separados
 * `decision_resuelta` (deseo) vs `estado_efectivo` (ejecución real), la máquina de 5 estados
 * fail-closed, y el autosave por control con rollback determinado/indeterminado (`aplicar`,
 * `reconciliar`). Cada control persiste solo; no hay botón "Guardar" global (el save global es
 * justamente el bug que esta pantalla elimina).
 *
 * Constitución VII (white-label): ningún nombre de proveedor externo en el copy —ni en
 * tooltips—. Las capas se nombran por lo que protegen; la delegación se explica por rol
 * ("proveedor del modelo"), nunca por marca.
 */

// Copy por capa. Las claves son los `layer_key` del registry (identidad estable que viaja a
// applied_layers); el nombre de display vive acá porque es white-label. `que_protege` se
// muestra SOLO en la fila-detalle expandible, nunca en reposo.
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
    name: "Evaluación de cumplimiento",
    que_protege: "Evalúa cada pedido contra la política de cumplimiento y lo deja registrado.",
  },
  pii_masking: {
    name: "Enmascarado de datos personales",
    que_protege: "Transforma lo detectado antes de que salga. Se puede apagar por herramienta (en herramientas de código el enmascarado rompe el código); apagarlo no apaga la detección.",
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
    name: "Guardarraíles de la plataforma",
    que_protege: "Temas restringidos y filtros corporativos aplicados en la plataforma que aloja el modelo.",
  },
};

// Orden canónico (orden de declaración). Se usa para que las filas NO salten al recalcularse un
// estado tras guardar: el orden se fija por catálogo, no por estado en vivo. Gobernables
// primero (lo que el admin toca), piso al final.
const LAYER_ORDER = Object.keys(LAYER_COPY);

// Los 5 estados se distinguen por color + FORMA, nunca solo texto. El `resumen` separa "no la
// aplicamos nosotros" de "estás desprotegido"; se muestra en tooltips y en la fila-detalle,
// nunca como párrafo fijo.
const ESTADO_UI: Record<
  GovernanceEffectiveState,
  { label: string; glyph: string; text: string; border: string; bg: string; resumen: string }
> = {
  aplicandose: {
    label: "Aplicándose",
    glyph: "●",
    text: "text-ok",
    border: "border-ok/30",
    bg: "bg-ok-bg",
    resumen: "Corre sobre el tráfico de este modo, confirmado — no es una intención declarada.",
  },
  delegada: {
    label: "Delegada",
    glyph: "◐",
    text: "text-info",
    border: "border-info/30",
    bg: "bg-info-bg",
    resumen: "No la aplicamos nosotros: la aporta el proveedor del modelo en su propio extremo. El tráfico no queda desprotegido — la protección base se sigue aplicando.",
  },
  requiere_credencial: {
    label: "Requiere credencial",
    glyph: "▲",
    text: "text-warn",
    border: "border-warn/30",
    bg: "bg-warn-bg",
    resumen: "Está deseada pero le falta la credencial: no se está aplicando y no se cuenta como protección.",
  },
  degradada: {
    label: "Degradada",
    glyph: "◆",
    text: "text-danger",
    border: "border-danger/30",
    bg: "bg-danger-bg",
    resumen: "Venía aplicándose y dejó de confirmarse. Se reporta degradada, jamás activa.",
  },
  no_disponible: {
    label: "No disponible",
    glyph: "○",
    text: "text-text-tertiary",
    border: "border-border",
    bg: "bg-surface-2",
    resumen: "No se está aplicando en este modo. Es el estado por defecto: sin confirmación, no se afirma nada.",
  },
};

const ESTADO_ORDER: GovernanceEffectiveState[] = [
  "aplicandose",
  "delegada",
  "requiere_credencial",
  "degradada",
  "no_disponible",
];

// Estados que "gritan" un problema: se marcan con un glyph de alerta en la fila colapsada.
const ESTADO_PROBLEMA: GovernanceEffectiveState[] = ["requiere_credencial", "degradada"];

// Nombres de los dos modos. "Modelo propio" es el término que el producto ya usa (docs de
// integraciones) para los modelos administrados por el motor del gateway, incluidos los locales.
const MODE_SHORT: Record<string, string> = {
  subscription: "Suscripción",
  "gateway-models": "Modelo propio",
};
const MODE_LONG: Record<string, string> = {
  subscription: "Tráfico contra la suscripción de la organización. El proveedor del modelo aporta parte de las protecciones en su propio extremo.",
  "gateway-models": "Tráfico contra un modelo propio administrado por el gateway (incluidos los locales). Acá solo protege lo que aplica el producto.",
};

// Precedencia traducida a copy de usuario (sin la palabra "origen", sin "default").
const ORIGEN_LABELS: Record<GovernanceOrigin, string> = {
  floor: "Siempre activa",
  connection: "la Conexión (fuera de esta pantalla)",
  surface: "un ajuste por herramienta",
  connection_mode: "este modo",
  tenant_default: "toda la organización",
  product_default: "el valor por defecto",
};

/** Se exporta —igual que `EstadoBadge`— porque el vocabulario de estados es el contrato de
 *  honestidad de la 027: si Seguridad y el Firewall se pintaran su propia versión, el mismo
 *  estado terminaría dicho de dos formas y volvería la ambigüedad que la spec elimina. */
export function estadoUi(estado: GovernanceEffectiveState) {
  return ESTADO_UI[estado] || ESTADO_UI.no_disponible;
}

/** Se exporta por el mismo motivo que `estadoUi`: el "Firewall en vivo" tiene que nombrar la
 *  capa que bloqueó un pedido EXACTO igual que Gobernanza. Un `layerKey` fuera del catálogo
 *  devuelve el código crudo a propósito (jamás `guardian.name`, que es editable — Principio VII). */
export function layerCopy(layerKey: string): { name: string; que_protege: string } {
  return (
    LAYER_COPY[layerKey] || {
      name: layerKey,
      que_protege: "Capa declarada por el catálogo del producto.",
    }
  );
}

/** Badge de estado completo (glyph + label). Se usa en la fila-detalle y lo consume el
 *  Firewall en vivo. */
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

/** Estado efectivo de una capa en cada modo, más los ejes que la fila-detalle necesita
 *  (origen y decisión resuelta) para hacer la precedencia consultable sin colapsar los modos. */
type CatalogEntry = {
  base: GovernanceLayerStatus;
  porModo: {
    mode: string;
    estado: GovernanceEffectiveState;
    motivo: string;
    origen: GovernanceOrigin;
    decision: GovernanceDecision;
  }[];
};

// Alcance mínimo para reusar `aplicar`/`scopeKey`. No es una fila de UI: es la clave natural
// (scope_type, scope_value) de la decisión.
type Scope = { scope_type: GovernanceScopeType; scope_value: string };
const modeScope = (mode: string): Scope => ({ scope_type: "connection_mode", scope_value: mode });
const surfaceScope = (surface: string): Scope => ({ scope_type: "surface", scope_value: surface });
const scopeKey = (s: Scope, layerKey: string) => `${s.scope_type}|${s.scope_value}|${layerKey}`;

// Copy de superficie: neutro y funcional (Constitución VII — sin marcas).
const SURFACE_COPY: Record<string, string> = {
  "claude-code": "Asistente de código en terminal",
  copilot: "Asistente de código en el editor",
  cursor: "Editor con asistente integrado",
  "claude-desktop": "Aplicación de escritorio de chat",
  chatgpt: "Chat en el navegador",
  "chat-ui": "Interfaz de chat del producto",
};

/** Estado de guardado POR CONTROL. */
type SaveStrip = {
  saving: boolean;
  savedAt?: string;
  error?: string | null;
  errorStatus?: number;
  estado?: GovernanceEffectiveState | null;
  motivo?: string;
  porModo?: { mode: string; estado_efectivo: GovernanceEffectiveState; motivo: string }[];
  propagacion?: { confirmada: boolean; motivo: string } | null;
  recalculando?: boolean;
  /** Fallo INDETERMINADO: no se puede afirmar que el servidor NO haya escrito. No se revierte
   *  el control a ciegas; se declara la incertidumbre y se re-lee del servidor. */
  incierto?: boolean;
  reconciliando?: boolean;
  reconciliadoAt?: string;
};

const DECISION_OPTIONS: { value: GovernanceDecision | null; label: string; help: string }[] = [
  { value: "on", label: "Activa", help: "Aplicar esta capa en este modo." },
  { value: "off", label: "Apagada", help: "No aplicar esta capa en este modo." },
  { value: null, label: "Heredar", help: "Sin decisión propia: vale el valor por defecto (o lo que decida la organización)." },
];

// ── Átomos ──────────────────────────────────────────────────────────────────────────────────

/** Badge compacto: glyph siempre visible, label solo desde `sm`. */
function ModeBadge({ estado, motivo }: { estado: GovernanceEffectiveState; motivo?: string }) {
  const ui = estadoUi(estado);
  return (
    <span
      title={motivo ? `${ui.label} — ${motivo}` : `${ui.label} — ${ui.resumen}`}
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded border text-[10px] font-semibold whitespace-nowrap ${ui.border} ${ui.bg} ${ui.text}`}
    >
      <span aria-hidden="true" className="text-[11px] leading-none">{ui.glyph}</span>
      <span className="hidden sm:inline">{ui.label}</span>
    </span>
  );
}

/** Micro-indicador de autosave: 1 carácter. */
function SaveIndicator({ strip }: { strip?: SaveStrip }) {
  if (!strip) return <span className="inline-block w-4" />;
  if (strip.saving || strip.reconciliando)
    return <span title="Guardando…" className="text-text-secondary animate-pulse">⟳</span>;
  if (strip.incierto) return <span title="Sin confirmar — expandí para reconsultar" className="text-warning">⚠</span>;
  if (strip.error) return <span title={strip.error} className="text-danger">✕</span>;
  if (strip.savedAt) return <span title={`Guardado ${strip.savedAt}`} className="text-success">✓</span>;
  return <span className="inline-block w-4" />;
}

/** Segmentado [Activa · Apagada · Heredar]. Un punto lleno marca "definido aquí"; "heredar"
 *  activo se ve punteado/fantasma. */
function SegmentedControl({
  decision,
  saving,
  onChange,
}: {
  decision: GovernanceDecision | null;
  saving?: boolean;
  onChange: (next: GovernanceDecision | null) => void;
}) {
  const explicita = decision !== null;
  return (
    <div className="inline-flex items-center gap-1.5">
      <span
        title={explicita ? "Definido en este modo" : "Heredado"}
        className={`w-1.5 h-1.5 rounded-full shrink-0 ${explicita ? "bg-primary" : "bg-transparent border border-border"}`}
        aria-hidden="true"
      />
      <div className="inline-flex rounded-md border border-border overflow-hidden">
        {DECISION_OPTIONS.map((opt) => {
          const activo = decision === opt.value;
          const base = "px-2 py-1 text-[11px] font-semibold border-r border-border last:border-r-0 transition-colors disabled:opacity-40 disabled:cursor-wait";
          const estilo = activo
            ? opt.value === "on"
              ? "bg-success/20 text-success"
              : opt.value === "off"
              ? "bg-warning/20 text-warning"
              : "bg-surface-2 text-text-primary border-dashed"
            : opt.value === null
            ? "bg-background/40 text-text-secondary border-dashed hover:text-text-primary"
            : "bg-background/40 text-text-secondary hover:text-text-primary";
          return (
            <button
              key={opt.label}
              type="button"
              title={opt.help}
              aria-pressed={activo}
              disabled={saving}
              onClick={() => onChange(opt.value)}
              className={`${base} ${estilo}`}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

/** Pill de piso: siempre activa, sin control. */
function LockPill() {
  return (
    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md border border-primary/20 bg-primary/10 text-primary text-[11px] font-semibold whitespace-nowrap">
      <span aria-hidden="true">🔒</span> Siempre activa
    </span>
  );
}

/** Popover "?" con la leyenda de estados y el orden de resolución. */
function HelpPopover() {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="w-6 h-6 rounded-full border border-border text-text-secondary hover:text-text-primary hover:border-border text-xs font-bold transition-colors"
        title="Cómo leer los estados"
      >
        ?
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} aria-hidden="true" />
          <div className="absolute right-0 mt-2 w-[22rem] max-w-[90vw] z-30 bg-surface border border-border rounded-lg shadow-xl p-4 space-y-4">
            <div className="space-y-2">
              <p className="text-[11px] font-bold uppercase tracking-wider text-text-secondary">Los estados</p>
              {ESTADO_ORDER.map((estado) => {
                const ui = estadoUi(estado);
                return (
                  <div key={estado} className="flex items-start gap-2">
                    <span aria-hidden="true" className={`text-sm leading-none mt-0.5 ${ui.text}`}>{ui.glyph}</span>
                    <div className="space-y-0.5">
                      <p className={`text-[11px] font-bold ${ui.text}`}>{ui.label}</p>
                      <p className="text-[11px] text-text-secondary leading-relaxed">{ui.resumen}</p>
                    </div>
                  </div>
                );
              })}
            </div>
            <div className="space-y-1 border-t border-border pt-3">
              <p className="text-[11px] font-bold uppercase tracking-wider text-text-secondary">Heredar</p>
              <p className="text-[11px] text-text-secondary leading-relaxed">
                Un control en <span className="text-text-primary">Heredar</span> no decide por ese modo: cede al valor
                por defecto (o a lo que fije la organización). La protección base va siempre, fuera de este orden.
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

/** Fila-detalle: el ÚNICO lugar con párrafos. Colapsada por defecto; un estado incierto la
 *  fuerza abierta. */
function LayerDetailRow({
  entry,
  perMode,
  onReconsultar,
}: {
  entry: CatalogEntry;
  perMode: { mode: string; strip?: SaveStrip }[];
  onReconsultar: (mode: string) => void;
}) {
  const copy = layerCopy(entry.base.layer_key);
  const esPiso = entry.base.tier === "floor";
  const hayDelegadaODisponible = entry.porModo.some((m) =>
    ["delegada", "no_disponible", "requiere_credencial"].includes(m.estado)
  );
  const stripDe = (mode: string) => perMode.find((p) => p.mode === mode)?.strip;

  return (
    <div className="bg-background/40 border-t border-border px-3 sm:px-4 py-3 space-y-3">
      <p className="text-[11px] text-text-secondary leading-relaxed">{copy.que_protege}</p>

      <div className="space-y-2">
        {entry.porModo.map((m) => {
          const ui = estadoUi(m.estado);
          const strip = stripDe(m.mode);
          return (
            <div key={m.mode} className="space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[11px] font-semibold text-text-primary min-w-[6.5rem]">{MODE_SHORT[m.mode] || m.mode}</span>
                <EstadoBadge estado={m.estado} />
                <span className="text-[10px] text-text-secondary">
                  Se resuelve en: <span className="text-text-primary">{ORIGEN_LABELS[m.origen] || m.origen}</span>
                </span>
              </div>
              {m.estado !== "aplicandose" && (m.motivo || ui.resumen) && (
                <p className={`text-[11px] leading-relaxed border-l-2 pl-2.5 ${ui.border} text-text-secondary`}>
                  {m.motivo || ui.resumen}
                </p>
              )}
              {(strip?.porModo?.length ?? 0) > 1 && (
                <p className="text-[10px] text-text-secondary pl-2.5">Recalculado tras tu cambio.</p>
              )}
              {strip?.incierto && (
                <div className="space-y-1.5 border-l-2 border-warning/40 pl-2.5">
                  <p className="text-[11px] font-bold text-warning">Estado incierto: reconfirmá contra el servidor</p>
                  <p className="text-[11px] leading-relaxed text-warning/90">
                    No hubo respuesta al guardar, así que no se puede afirmar si el cambio quedó aplicado. Este
                    control <span className="font-semibold">no</span> se revirtió: hasta reconfirmar, no se afirma
                    ningún estado para esta capa en este modo.
                  </p>
                  <button
                    type="button"
                    onClick={() => onReconsultar(m.mode)}
                    disabled={strip?.reconciliando}
                    className="px-2.5 py-1 rounded text-[11px] font-semibold border border-warning/40 bg-warning/10 text-warning hover:bg-warning/20 disabled:opacity-40 disabled:cursor-wait transition-colors"
                  >
                    {strip?.reconciliando ? "Re-consultando…" : "Re-consultar al servidor"}
                  </button>
                </div>
              )}
              {strip?.propagacion && !strip.propagacion.confirmada && strip.propagacion.motivo && (
                <p className="text-[11px] leading-relaxed text-text-secondary border-l-2 border-border pl-2.5">
                  {strip.propagacion.motivo}
                </p>
              )}
            </div>
          );
        })}
        {entry.porModo.length === 0 && (
          <div className="flex items-center gap-2">
            <EstadoBadge estado={entry.base.estado_efectivo} />
            {entry.base.motivo && <span className="text-[11px] text-text-secondary">{entry.base.motivo}</span>}
          </div>
        )}
      </div>

      {esPiso && (
        <p className="text-[11px] text-primary/90 leading-relaxed border-l-2 border-primary/40 pl-2.5">
          Se aplica siempre, en los dos modos. No se puede desactivar: cualquier intento se rechaza y queda
          registrado.
        </p>
      )}

      {hayDelegadaODisponible && !esPiso && (
        <p className="text-[11px] text-text-secondary leading-relaxed">
          Una capa <span className="text-primary">delegada</span> no es tráfico desprotegido: la aporta el
          proveedor del modelo en su extremo. Si figura <span className="text-text-secondary">no disponible</span> o{" "}
          <span className="text-warning">requiere credencial</span>, esa protección concreta no corre — y la
          protección base se sigue aplicando igual.
        </p>
      )}
    </div>
  );
}

/** Una fila de la matriz: nombre + candado(piso)/alerta, y por cada modo un badge de estado +
 *  su control. */
function LayerMatrixRow({
  entry,
  decisions,
  strips,
  expanded,
  onToggle,
  onChange,
  onReconsultar,
}: {
  entry: CatalogEntry;
  decisions: Record<string, GovernanceDecision | null>;
  strips: Record<string, SaveStrip>;
  expanded: boolean;
  onToggle: () => void;
  onChange: (mode: string, next: GovernanceDecision | null) => void;
  onReconsultar: (mode: string) => void;
}) {
  const copy = layerCopy(entry.base.layer_key);
  const esPiso = entry.base.tier === "floor";
  const estadoDe = (mode: string): { estado: GovernanceEffectiveState; motivo: string } => {
    const m = entry.porModo.find((p) => p.mode === mode);
    return m ? { estado: m.estado, motivo: m.motivo } : { estado: entry.base.estado_efectivo, motivo: entry.base.motivo };
  };
  const stripDe = (mode: string) => strips[scopeKey(modeScope(mode), entry.base.layer_key)];
  const decisionDe = (mode: string) => decisions[scopeKey(modeScope(mode), entry.base.layer_key)] ?? null;

  const algunIncierto = CONNECTION_MODES.some((m) => stripDe(m)?.incierto === true);
  const problema = entry.porModo.find((m) => ESTADO_PROBLEMA.includes(m.estado))?.estado ?? null;
  const alerta = algunIncierto ? { g: "⚠", c: "text-warning" } : problema ? { g: estadoUi(problema).glyph, c: estadoUi(problema).text } : null;
  const abierto = expanded || algunIncierto;

  const nameCell = (
    <div className="flex items-center gap-2 min-w-0">
      <button type="button" onClick={onToggle} aria-expanded={abierto} className="flex items-center gap-2 min-w-0 text-left group">
        <span aria-hidden="true" className="text-text-secondary text-[10px] w-3 shrink-0 group-hover:text-text-primary transition-colors">{abierto ? "▾" : "▸"}</span>
        {esPiso && <span aria-hidden="true" title="Siempre activa; no se puede desactivar" className="text-text-secondary text-[11px] shrink-0">🔒</span>}
        <span className="text-text-primary text-xs font-semibold truncate group-hover:text-primary transition-colors">{copy.name}</span>
      </button>
      {alerta && (
        <span aria-hidden="true" title="Requiere atención — expandí para el detalle" className={`text-[11px] shrink-0 ${alerta.c}`}>{alerta.g}</span>
      )}
    </div>
  );

  const modeCell = (mode: string) => {
    const s = estadoDe(mode);
    return (
      <div className="flex flex-col gap-2 items-start">
        <ModeBadge estado={s.estado} motivo={s.motivo} />
        {esPiso ? (
          <LockPill />
        ) : (
          <div className="flex items-center gap-2">
            <SegmentedControl decision={decisionDe(mode)} saving={stripDe(mode)?.saving} onChange={(next) => onChange(mode, next)} />
            <SaveIndicator strip={stripDe(mode)} />
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="border-b border-border hover:bg-border transition-colors">
      {/* Desktop */}
      <div className="hidden md:grid md:grid-cols-[minmax(0,1.4fr)_1fr_1fr] md:gap-4 px-3 py-3 items-start">
        <div className="pt-1">{nameCell}</div>
        {modeCell("subscription")}
        {modeCell("gateway-models")}
      </div>
      {/* Móvil */}
      <div className="md:hidden flex flex-col gap-3 px-3 py-3">
        {nameCell}
        {CONNECTION_MODES.map((mode) => (
          <div key={mode} className="pl-5 flex flex-col gap-1.5">
            <span className="text-[10px] text-text-secondary uppercase tracking-wider">{MODE_SHORT[mode]}</span>
            {modeCell(mode)}
          </div>
        ))}
      </div>

      {abierto && (
        <LayerDetailRow
          entry={entry}
          perMode={CONNECTION_MODES.map((mode) => ({ mode, strip: stripDe(mode) }))}
          onReconsultar={onReconsultar}
        />
      )}
    </div>
  );
}

/** "Avanzado": apagar una capa solo en una herramienta (superficie). Plegado por defecto; en la
 *  demo no se abre. Es una relajación fina, no un tercer modo. */
function AdvancedSection({
  gobernables,
  decisions,
  strips,
  onChange,
}: {
  gobernables: CatalogEntry[];
  decisions: Record<string, GovernanceDecision | null>;
  strips: Record<string, SaveStrip>;
  onChange: (scope: Scope, layerKey: string, next: GovernanceDecision | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const [surface, setSurface] = useState<string>(GOVERNANCE_SURFACES[0]);

  return (
    <div className="border border-dashed border-border rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="w-full flex items-center gap-2 px-4 py-3 text-left text-text-secondary hover:text-text-primary transition-colors"
      >
        <span aria-hidden="true" className="text-[10px]">{open ? "▾" : "▸"}</span>
        <span className="text-xs font-semibold">Avanzado — apagar una capa solo en una herramienta</span>
        <span className="text-[10px] text-text-secondary ml-auto">código, chat, editor…</span>
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-3 border-t border-border pt-3">
          <p className="text-[11px] text-text-secondary leading-relaxed">
            Ajuste fino por herramienta declarada en la Conexión (por ejemplo, apagar el enmascarado solo en
            herramientas de código, donde rompe el código). Refina el modo; el efecto real se ve arriba, en la
            columna del modo. El tráfico cuya herramienta se deduce del cliente no se relaja nunca.
          </p>

          <label className="flex items-center gap-2 text-xs">
            <span className="text-text-secondary">Herramienta:</span>
            <select
              value={surface}
              onChange={(e) => setSurface(e.target.value)}
              className="bg-surface border border-border rounded-md px-2.5 py-1.5 text-text-primary text-xs font-semibold focus:outline-none focus:ring-1 focus:ring-primary"
            >
              {GOVERNANCE_SURFACES.map((s) => (
                <option key={s} value={s}>{SURFACE_COPY[s] || s}</option>
              ))}
            </select>
          </label>

          <div className="space-y-1.5">
            {gobernables.map((entry) => {
              const key = scopeKey(surfaceScope(surface), entry.base.layer_key);
              const strip = strips[key];
              return (
                <div key={entry.base.layer_key} className="flex items-center justify-between gap-3 py-1.5 border-b border-border last:border-b-0">
                  <span className="text-[11px] text-text-primary truncate">{layerCopy(entry.base.layer_key).name}</span>
                  <div className="flex items-center gap-2 shrink-0">
                    <SegmentedControl
                      decision={decisions[key] ?? null}
                      saving={strip?.saving}
                      onChange={(next) => onChange(surfaceScope(surface), entry.base.layer_key, next)}
                    />
                    <SaveIndicator strip={strip} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Página ────────────────────────────────────────────────────────────────────────────────

export const GovernancePage: React.FC = () => {
  const [status, setStatus] = useState<GovernanceStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [leidoAt, setLeidoAt] = useState<string>("");
  const [error, setError] = useState<{ kind: "forbidden" | "network" | "other"; message: string } | null>(null);

  const [decisions, setDecisions] = useState<Record<string, GovernanceDecision | null>>({});
  const [strips, setStrips] = useState<Record<string, SaveStrip>>({});
  const [errorPerfil, setErrorPerfil] = useState<{ status: number; message: string } | null>(null);

  const [expandido, setExpandido] = useState<Record<string, boolean>>({});
  const ordenRef = useRef<string[]>([]);

  const load = useCallback(async (opts?: { silent?: boolean }) => {
    if (!opts?.silent) setLoading(true);
    setError(null);
    try {
      const resumen = await api.getGovernanceStatus();
      let porModo = resumen.porModo;
      if (Object.keys(porModo).length === 0) {
        const porModoFetched = await Promise.all(
          CONNECTION_MODES.map(async (mode) => [mode, (await api.getGovernanceStatus({ mode })).layers] as const)
        );
        porModo = Object.fromEntries(porModoFetched);
      }
      setStatus({ layers: resumen.layers, porModo });
      setLeidoAt(new Date().toLocaleTimeString());
    } catch (e: any) {
      const apiError = e instanceof ApiError ? e : null;
      if (apiError?.isForbidden) {
        setError({ kind: "forbidden", message: e.message || "Esta vista es solo para administradores. Tu sesión no tiene permiso para consultar el estado de gobernanza." });
      } else if (apiError?.isNetwork) {
        setError({ kind: "network", message: "No se pudo contactar al servidor. El estado no se puede afirmar sin respuesta: no se muestra nada como activo." });
      } else {
        const detalle = e?.message || "El servidor no devolvió un motivo.";
        setError({ kind: "other", message: apiError ? `No se pudo obtener el estado (HTTP ${apiError.status}): ${detalle}` : detalle });
      }
      if (!opts?.silent) setStatus(null);
    } finally {
      setLoading(false);
    }
  }, []);

  const cargarPerfil = useCallback(async (opts?: { silent?: boolean }): Promise<boolean> => {
    if (!opts?.silent) setErrorPerfil(null);
    try {
      const filas = await api.getGovernanceProfile();
      const mapa: Record<string, GovernanceDecision | null> = {};
      for (const f of filas) mapa[`${f.scope_type}|${f.scope_value}|${f.layer_key}`] = f.decision;
      setDecisions(mapa);
      setErrorPerfil(null);
      return true;
    } catch (e: any) {
      const apiError = e instanceof ApiError ? e : null;
      if (!opts?.silent) setErrorPerfil({ status: apiError?.status ?? 0, message: e?.message || "No se pudo leer la configuración." });
      return false;
    }
  }, []);

  useEffect(() => {
    load();
    cargarPerfil();
  }, [load, cargarPerfil]);

  const reconciliar = useCallback(
    async (key: string) => {
      setStrips((st) => ({ ...st, [key]: { ...(st[key] ?? { saving: false }), reconciliando: true } }));
      const ok = await cargarPerfil({ silent: true });
      setStrips((st) => {
        const previo = st[key];
        if (!previo) return st;
        return {
          ...st,
          [key]: ok
            ? { saving: false, reconciliando: false, incierto: false, error: null, reconciliadoAt: new Date().toLocaleTimeString() }
            : { ...previo, reconciliando: false, incierto: true },
        };
      });
      if (ok) load({ silent: true });
    },
    [cargarPerfil, load]
  );

  /** Autosave optimista con rollback POR CONTROL. El estado sale SIEMPRE del servidor (fila
   *  persistida + recalculado), nunca del valor optimista. En el catch se distingue fallo
   *  determinado (4xx: se revierte) de indeterminado (se declara incierto y se re-lee). */
  const aplicar = async (s: Scope, layerKey: string, next: GovernanceDecision | null) => {
    const key = scopeKey(s, layerKey);
    const previa = decisions[key] ?? null;
    if (previa === next) return;

    setDecisions((d) => ({ ...d, [key]: next }));
    setStrips((st) => ({ ...st, [key]: { saving: true, error: null, estado: st[key]?.estado } }));

    try {
      const res =
        next === null
          ? await api.deleteGovernanceDecision(s.scope_type, s.scope_value, layerKey)
          : await api.putGovernanceDecision({ scope_type: s.scope_type, scope_value: s.scope_value, layer_key: layerKey, decision: next });

      setDecisions((d) => ({ ...d, [key]: res.row ? res.row.decision : null }));
      setStrips((st) => ({
        ...st,
        [key]: {
          saving: false,
          savedAt: new Date().toLocaleTimeString(),
          error: null,
          estado: res.estado_efectivo,
          motivo: res.motivo,
          porModo: res.porModo,
          propagacion: res.propagacion,
          recalculando: res.estado_efectivo === null,
        },
      }));
      load({ silent: true });
    } catch (e: any) {
      const apiError = e instanceof ApiError ? e : null;
      const determinado = apiError?.isDeterminate === true;

      if (determinado) {
        setDecisions((d) => ({ ...d, [key]: previa }));
        setStrips((st) => ({ ...st, [key]: { saving: false, error: e?.message || "No se pudo guardar la decisión.", errorStatus: apiError?.status, estado: st[key]?.estado } }));
        return;
      }

      setStrips((st) => ({ ...st, [key]: { saving: false, incierto: true, error: e?.message || "No hubo respuesta del servidor al guardar.", errorStatus: apiError?.status, estado: null } }));
      setExpandido((ex) => ({ ...ex, [layerKey]: true }));
      void reconciliar(key);
    }
  };

  const catalogo: CatalogEntry[] = useMemo(() => {
    if (!status) return [];
    const modos = Object.keys(status.porModo);
    const porClave = new Map<string, CatalogEntry>();
    const out: CatalogEntry[] = [];
    const fuente = modos.length > 0
      ? modos.flatMap((m) => status.porModo[m].map((l) => [m, l] as const))
      : status.layers.map((l) => [null as string | null, l] as const);
    for (const [modo, l] of fuente) {
      let entry = porClave.get(l.layer_key);
      if (!entry) {
        entry = { base: l, porModo: [] };
        porClave.set(l.layer_key, entry);
        out.push(entry);
      }
      if (modo) entry.porModo.push({ mode: modo, estado: l.estado_efectivo, motivo: l.motivo, origen: l.origen, decision: l.decision_resuelta });
    }
    return out;
  }, [status]);

  if (catalogo.length > 0 && ordenRef.current.length === 0) {
    const idx = (k: string) => { const i = LAYER_ORDER.indexOf(k); return i === -1 ? 999 : i; };
    ordenRef.current = [...catalogo]
      .sort((a, b) => {
        const pisoA = a.base.tier === "floor" ? 1 : 0;
        const pisoB = b.base.tier === "floor" ? 1 : 0;
        if (pisoA !== pisoB) return pisoA - pisoB;
        return idx(a.base.layer_key) - idx(b.base.layer_key);
      })
      .map((e) => e.base.layer_key);
  }
  const ordenado = useMemo(() => {
    const pos = (k: string) => { const i = ordenRef.current.indexOf(k); return i === -1 ? 999 : i; };
    return [...catalogo].sort((a, b) => pos(a.base.layer_key) - pos(b.base.layer_key));
  }, [catalogo]);

  const gobernables = useMemo(() => ordenado.filter((e) => e.base.tier !== "floor"), [ordenado]);

  return (
    <div className="pb-16">
      {/* Barra de operación */}
      <div className="sticky top-0 z-10 -mx-6 px-6 py-4 bg-background/95 backdrop-blur border-b border-border">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-text-primary">Gobernanza</h1>
            <p className="text-xs text-text-secondary mt-0.5">
              Lo que protege de verdad a cada tipo de tráfico. Una capa que no corre nunca figura activa.
            </p>
          </div>
          <div className="flex items-center gap-3 flex-wrap">
            <HelpPopover />
            <button
              onClick={() => { load(); cargarPerfil(); }}
              disabled={loading}
              className="bg-primary hover:bg-primary/90 disabled:opacity-40 text-background font-semibold px-4 py-2 rounded-lg text-xs transition-all whitespace-nowrap"
            >
              {loading ? "Consultando…" : "Actualizar"}
            </button>
            {leidoAt && <span className="text-[10px] text-text-secondary font-mono">Leído {leidoAt}</span>}
          </div>
        </div>
      </div>

      <div className="space-y-5 pt-6">
        {error && (
          <div className={`px-4 py-3 rounded-lg text-xs border space-y-1 ${error.kind === "forbidden" ? "bg-warning/10 border-warning/20 text-warning" : "bg-danger/10 border-danger/20 text-danger"}`}>
            <p className="font-bold">
              {error.kind === "forbidden" ? "Sin permiso para ver la gobernanza" : error.kind === "network" ? "Sin conexión con el servidor" : "No se pudo leer el estado"}
            </p>
            <p className="font-normal">{error.message}</p>
          </div>
        )}

        {loading && !status && (
          <div className="py-16 text-center text-xs font-mono text-text-secondary">Consultando estado…</div>
        )}

        {errorPerfil && (
          <div className="px-3 py-2.5 rounded border text-[11px] bg-warning/10 border-warning/20 text-warning space-y-1">
            <p className="font-bold">{errorPerfil.status === 404 ? "La configuración todavía no está disponible en este servidor" : "No se pudo leer la configuración"}</p>
            <p className="font-normal">{errorPerfil.message}</p>
          </div>
        )}

        {status && (
          <>
            {/* La matriz: una capa por fila, dos modos. */}
            <div className="bg-surface border border-border rounded-lg overflow-hidden">
              <div className="hidden md:grid md:grid-cols-[minmax(0,1.4fr)_1fr_1fr] md:gap-4 px-3 py-2 border-b border-border bg-background/30">
                <span className="text-[10px] font-bold uppercase tracking-wider text-text-secondary">Capa</span>
                <span title={MODE_LONG.subscription} className="text-[10px] font-bold uppercase tracking-wider text-text-secondary cursor-help">Suscripción</span>
                <span title={MODE_LONG["gateway-models"]} className="text-[10px] font-bold uppercase tracking-wider text-text-secondary cursor-help">Modelo propio</span>
              </div>

              {ordenado.map((entry) => (
                <LayerMatrixRow
                  key={entry.base.layer_key}
                  entry={entry}
                  decisions={decisions}
                  strips={strips}
                  expanded={expandido[entry.base.layer_key] === true}
                  onToggle={() => setExpandido((ex) => ({ ...ex, [entry.base.layer_key]: !ex[entry.base.layer_key] }))}
                  onChange={(mode, next) => aplicar(modeScope(mode), entry.base.layer_key, next)}
                  onReconsultar={(mode) => reconciliar(scopeKey(modeScope(mode), entry.base.layer_key))}
                />
              ))}

              {ordenado.length === 0 && (
                <p className="px-4 py-8 text-center text-xs text-text-secondary">El servidor no devolvió capas.</p>
              )}
            </div>

            {/* Avanzado (superficies), plegado. */}
            {gobernables.length > 0 && (
              <AdvancedSection
                gobernables={gobernables}
                decisions={decisions}
                strips={strips}
                onChange={(scope, layerKey, next) => aplicar(scope, layerKey, next)}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default GovernancePage;
