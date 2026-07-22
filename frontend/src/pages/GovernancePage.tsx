import React, { useCallback, useEffect, useState } from "react";
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

/** Se exporta por el mismo motivo que `estadoUi`: el nombre legible de una capa es
 *  vocabulario de producto, y el "Firewall en vivo" tiene que nombrar la capa que bloqueó
 *  un pedido EXACTAMENTE igual que Gobernanza nombra esa capa. Dos tablas de copy = el
 *  mismo `layer_key` con dos nombres en dos pantallas, que es la ambigüedad que la 027
 *  borra. Un `layerKey` fuera del catálogo devuelve el código crudo a propósito: preferible
 *  a inventarle un nombre (y jamás `guardian.name`, que es editable — D6/Principio VII). */
export function layerCopy(layerKey: string): { name: string; que_protege: string } {
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
  /** `origen` y `decision` viajan además del estado porque la sección de configuración los
   *  necesita para hacer la precedencia CONSULTABLE (FR-006): sin el origen, un admin no
   *  puede saber si lo que ve viene de su decisión de modo, del default de la organización o
   *  del default del producto — y "determinista" que no se puede mirar no sirve de nada. */
  porModo: {
    mode: string;
    estado: GovernanceEffectiveState;
    motivo: string;
    origen: GovernanceOrigin;
    decision: GovernanceDecision;
  }[];
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

// ── Configuración (US2 — T030) ───────────────────────────────────────────────────────────
//
// Alcances configurables, en el orden de la cascada de menor a mayor especificidad. El nivel
// Connection (el toggle por clave) NO está acá a propósito: no es una fila de
// `governance_profiles`, es el `redact_enabled` de la Connection (D8), y ofrecerlo en esta
// tabla haría creer que se edita desde el mismo lugar.
type ConfigScope = {
  scope_type: GovernanceScopeType;
  scope_value: string;
  label: string;
  hint: string;
};

const SCOPE_TENANT: ConfigScope = {
  scope_type: "tenant_default",
  scope_value: "*",
  label: "Toda la organización",
  hint: "La postura base. Aplica a todo el tráfico que no tenga una decisión más específica por modo, por superficie o en la propia Conexión.",
};

const SCOPE_MODES: ConfigScope[] = [
  {
    scope_type: "connection_mode",
    scope_value: "subscription",
    label: "Tráfico de suscripción",
    hint: "Pedidos que viajan contra la suscripción de la organización. Parte de las protecciones las aporta el servicio upstream en su propio extremo.",
  },
  {
    scope_type: "connection_mode",
    scope_value: "gateway-models",
    label: "Modelos de la pasarela",
    hint: "Pedidos hacia modelos administrados por la pasarela, incluidos los locales. Acá no hay nadie más protegiendo: solo lo que aplica el producto.",
  },
];

// Copy de superficie: neutro y funcional. El identificador crudo se muestra aparte porque es
// el valor que el admin eligió al provisionar la Connection (`tool_type`, dato del cliente
// que la API de Connections ya expone) y sin él no puede emparejar la configuración con sus
// conexiones reales; el copy del producto, en cambio, no nombra marcas (Constitución VII).
const SURFACE_COPY: Record<string, string> = {
  "claude-code": "Asistente de código en terminal",
  copilot: "Asistente de código en el editor",
  cursor: "Editor con asistente integrado",
  "claude-desktop": "Aplicación de escritorio de chat",
  chatgpt: "Chat en el navegador",
  "chat-ui": "Interfaz de chat del producto",
};

const SCOPE_SURFACES: ConfigScope[] = GOVERNANCE_SURFACES.map((s) => ({
  scope_type: "surface" as const,
  scope_value: s,
  label: SURFACE_COPY[s] || s,
  hint: "Decisión por herramienta declarada en la Conexión. Es el alcance más fino que ofrece esta pantalla.",
}));

const scopeKey = (s: ConfigScope, layerKey: string) =>
  `${s.scope_type}|${s.scope_value}|${layerKey}`;

/** Estado de guardado POR CONTROL. No hay banner global ni botón "Guardar Cambios" (D7): el
 *  bug de los toggles de Seguridad es exactamente eso — el estado vive en memoria hasta
 *  pulsar el botón, y al cambiar de sección la página se desmonta y se pierde sin aviso.
 *  Acá cada control persiste solo y cuenta su propia historia. */
type SaveStrip = {
  saving: boolean;
  savedAt?: string;
  error?: string | null;
  errorStatus?: number;
  /** Estado recalculado por el servidor tras la escritura. Fuente única: si esto se pintara
   *  desde el valor optimista, activar una capa no cargada se vería verde y volveríamos a la
   *  mentira que la 027 elimina. */
  estado?: GovernanceEffectiveState | null;
  motivo?: string;
  /** Estado recomputado POR MODO. Un alcance transversal (la organización, una superficie)
   *  cruza los dos modos de conexión y puede resolver distinto en cada uno; el escalar de
   *  arriba es el colapso fail-closed y por sí solo escondería esa diferencia. */
  porModo?: { mode: string; estado_efectivo: GovernanceEffectiveState; motivo: string }[];
  /** Propagación al motor no confirmada: se dice, no se calla. */
  propagacion?: { confirmada: boolean; motivo: string } | null;
  /** True tras un DELETE 204 (sin cuerpo): la decisión volvió a heredarse y el estado real
   *  se re-consulta al servidor en vez de suponerse. */
  recalculando?: boolean;
  /** Fallo **INDETERMINADO**: no se puede afirmar que el servidor NO haya escrito (el
   *  `fetch` rechazó por timeout o corte, o respondió un 5xx de un intermediario — todos
   *  posibles DESPUÉS del commit). Mientras esté en true no se afirma ningún estado y el
   *  control avisa que hay que reconfirmar contra el servidor.
   *
   *  Hallazgo (verificación adversarial US2, MEDIA): antes el `catch` revertía el control
   *  siempre, así que un corte posterior al commit mostraba "Apagada" con la capa apagada
   *  de verdad en la base — o al revés. Creer que una capa está encendida cuando está
   *  apagada es el peor error posible en esta pantalla, y el rollback ciego lo producía
   *  justo cuando el admin menos podía sospecharlo. */
  incierto?: boolean;
  /** Re-lectura del perfil en curso para cerrar esa incertidumbre. */
  reconciliando?: boolean;
  /** Hora en que el control quedó re-sincronizado con el valor real del servidor. */
  reconciliadoAt?: string;
};

const DECISION_OPTIONS: { value: GovernanceDecision | null; label: string; help: string }[] = [
  {
    value: null,
    label: "Heredar",
    help: "Sin decisión propia en este alcance: vale lo que resuelva el nivel de abajo de la cascada.",
  },
  { value: "on", label: "Activa", help: "Decisión explícita: aplicar esta capa en este alcance." },
  { value: "off", label: "Apagada", help: "Decisión explícita: no aplicar esta capa en este alcance." },
];

/** Un control de decisión + su strip de estado. Tres estados posibles y ninguno inventado:
 *  heredar (ausencia de fila), on y off. No existe `decision='inherit'` en el dominio. */
function DecisionRow({
  entry,
  scope,
  decision,
  strip,
  resuelto,
  onChange,
  onReconsultar,
}: {
  entry: CatalogEntry;
  scope: ConfigScope;
  decision: GovernanceDecision | null;
  strip?: SaveStrip;
  resuelto?: { estado: GovernanceEffectiveState; motivo: string; origen: GovernanceOrigin; decision: GovernanceDecision };
  onChange: (next: GovernanceDecision | null) => void;
  onReconsultar: () => void;
}) {
  const copy = layerCopy(entry.base.layer_key);
  const explicita = decision !== null;
  // Con la escritura en estado INDETERMINADO no se afirma NADA: ni el estado recalculado
  // (no llegó) ni el del último resumen (quedó viejo en el instante en que la escritura
  // pudo haberse aplicado). El badge desaparece y en su lugar habla el aviso de abajo —
  // pintar un "Aplicándose" heredado del resumen anterior sería exactamente la mentira que
  // el hallazgo describe.
  const incierto = strip?.incierto === true;
  // El estado que se muestra es SIEMPRE del servidor: el recalculado que devolvió la última
  // escritura, o el del resumen consultado. Nunca se deriva de la decisión elegida.
  const estado = incierto ? null : strip?.estado ?? resuelto?.estado ?? null;
  const motivo = incierto ? "" : strip?.motivo || resuelto?.motivo || "";
  const relajaSuperficie = scope.scope_type === "surface" && decision === "off";

  return (
    <div
      className={`rounded-lg border p-4 space-y-3 ${
        explicita ? "border-primary/30 bg-primary/5" : "border-dashed border-slate-700/50 bg-background/10"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-white text-xs">{copy.name}</span>
            {/* "Heredado" y "decidido acá" son la semántica de la AUSENCIA de fila (D2): se
                distinguen visualmente porque son cosas distintas, no dos formas de lo mismo. */}
            {explicita ? (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold border border-primary/30 bg-primary/10 text-primary">
                Decidido en este alcance
              </span>
            ) : (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold border border-slate-700 bg-slate-800/60 text-text-secondary">
                Heredado
              </span>
            )}
          </div>
          <p className="text-[11px] text-text-secondary leading-relaxed">{copy.que_protege}</p>
        </div>
        {estado && <EstadoBadge estado={estado} />}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {DECISION_OPTIONS.map((opt) => {
          const activo = decision === opt.value;
          return (
            <button
              key={opt.label}
              type="button"
              title={opt.help}
              aria-pressed={activo}
              disabled={strip?.saving}
              onClick={() => onChange(opt.value)}
              className={`px-2.5 py-1 rounded text-[11px] font-semibold border transition-colors disabled:opacity-40 disabled:cursor-wait ${
                activo
                  ? opt.value === "off"
                    ? "border-warning/40 bg-warning/15 text-warning"
                    : opt.value === "on"
                    ? "border-success/40 bg-success/15 text-success"
                    : "border-slate-600 bg-slate-700/60 text-white"
                  : "border-slate-700/60 bg-background/40 text-text-secondary hover:text-white hover:border-slate-500"
              }`}
            >
              {opt.label}
            </button>
          );
        })}
      </div>

      {/* Precedencia consultable (FR-006): de dónde sale hoy lo que se aplica en este alcance.
          Se calla mientras la escritura esté indeterminada: "Resuelto hoy" sería una
          afirmación sobre un estado que justo ahora no se puede afirmar. */}
      {resuelto && !incierto && (
        <p className="text-[10px] font-mono text-text-secondary">
          Resuelto hoy: <span className="text-white">{resuelto.decision === "on" ? "activa" : "apagada"}</span>
          {" · origen: "}
          <span className="text-white">{ORIGEN_LABELS[resuelto.origen] || resuelto.origen}</span>
        </p>
      )}

      {motivo && (
        <p className="text-[11px] leading-relaxed text-text-secondary border-l-2 border-slate-700/60 pl-2.5">
          {motivo}
        </p>
      )}

      {/* Recomputación por modo: un alcance transversal puede resolver distinto en cada modo
          de conexión, y el escalar de arriba lo colapsa fail-closed. Acá se abre. */}
      {(strip?.porModo?.length ?? 0) > 1 && (
        <div className="space-y-1 border-t border-slate-700/20 pt-2">
          {strip!.porModo!.map((m) => (
            <div key={m.mode} className="flex items-center justify-between gap-2">
              <span className="text-[10px] font-mono text-text-secondary">
                {MODE_LABELS[m.mode] || m.mode}
              </span>
              <EstadoBadge estado={m.estado_efectivo} />
            </div>
          ))}
        </div>
      )}

      {/* Propagación no confirmada: el cambio quedó escrito, pero el producto no puede
          afirmar todavía que el plano de ejecución lo esté usando. Se dice con todas las
          letras en vez de dejar un "Guardado" que el admin leería como "ya rige". */}
      {strip?.propagacion && !strip.propagacion.confirmada && strip.propagacion.motivo && (
        <p className="text-[11px] leading-relaxed text-text-secondary border-l-2 border-slate-700/60 pl-2.5">
          {strip.propagacion.motivo}
        </p>
      )}

      {/* Honestidad de alcance de la relajación por superficie (D5 refinada): que el admin no
          crea que apagó más de lo que apagó. El motivo concreto lo escribe el backend
          (arriba); esta nota es la regla del producto, y se muestra aunque la escritura de
          esta sesión ya haya terminado. */}
      {relajaSuperficie && (
        <p className="text-[11px] leading-relaxed text-warning/90 border-l-2 border-warning/40 pl-2.5">
          Esta relajación alcanza solo al tráfico cuya herramienta está declarada en la Conexión. El
          tráfico cuya superficie se deduce del cliente (dato que el cliente puede falsear) no se relaja
          nunca: para ese tráfico esta decisión se ignora y vale el nivel de abajo.
        </p>
      )}

      {/* Fallo INDETERMINADO: la escritura pudo haberse aplicado igual. NO se revierte el
          control a ciegas —revertir sería afirmar que no se guardó, y eso es justo lo que no
          se sabe—: se declara la incertidumbre y se re-lee del servidor. */}
      {incierto && (
        <div className="space-y-1.5 border-l-2 border-warning/40 pl-2.5">
          <p className="text-[11px] font-bold text-warning">Estado incierto: recargá para confirmar</p>
          <p className="text-[11px] leading-relaxed text-warning/90">
            No hubo respuesta del servidor, así que no se puede afirmar si el cambio quedó aplicado o no.
            Este control <span className="font-semibold">no</span> se revirtió: mostrarlo como antes daría
            por seguro que no se guardó. Hasta reconfirmar contra el servidor, no se afirma ningún estado
            para esta capa.
          </p>
          <button
            type="button"
            onClick={onReconsultar}
            disabled={strip?.reconciliando}
            className="px-2.5 py-1 rounded text-[11px] font-semibold border border-warning/40 bg-warning/10 text-warning hover:bg-warning/20 disabled:opacity-40 disabled:cursor-wait transition-colors"
          >
            {strip?.reconciliando ? "Re-consultando…" : "Re-consultar al servidor"}
          </button>
        </div>
      )}

      {/* Strip POR FILA. Sin banner global: cada control informa lo suyo, donde ocurrió. */}
      <div className="text-[10px] font-mono min-h-[14px]">
        {strip?.saving && <span className="text-text-secondary">Guardando…</span>}
        {!strip?.saving && strip?.reconciliando && (
          <span className="text-text-secondary">Re-consultando el valor real al servidor…</span>
        )}
        {/* La incertidumbre gana al error: el mensaje de red ya se muestra arriba con su
            consecuencia, y repetirlo acá como "Error" sugeriría que no pasó nada. */}
        {!strip?.saving && !strip?.reconciliando && incierto && strip?.error && (
          <span className="text-warning">Sin confirmación: {strip.error}</span>
        )}
        {!strip?.saving && !strip?.reconciliando && !incierto && strip?.error && (
          <span className="text-danger">
            {strip.errorStatus === 422 ? "Rechazado por el producto: " : "Error: "}
            {strip.error}
          </span>
        )}
        {!strip?.saving && !strip?.reconciliando && !incierto && !strip?.error && strip?.reconciliadoAt && (
          <span className="text-text-secondary">
            Valor re-leído del servidor {strip.reconciliadoAt}
          </span>
        )}
        {!strip?.saving && !strip?.reconciliando && !incierto && !strip?.error && !strip?.reconciliadoAt && strip?.savedAt && (
          <span className="text-success">
            Guardado {strip.savedAt}
            {strip.recalculando && (
              <span className="text-text-secondary"> · el estado real se re-consulta al servidor</span>
            )}
          </span>
        )}
      </div>
    </div>
  );
}

/** Sección de configuración: qué capas opcionales aplican por modo de conexión y por
 *  superficie (FR-004/FR-005), con autosave por control y rollback (D7). */
function ConfiguracionGobernanza({
  gobernables,
  piso,
  onCambio,
}: {
  gobernables: CatalogEntry[];
  piso: CatalogEntry[];
  onCambio: () => void;
}) {
  const [scope, setScope] = useState<ConfigScope>(SCOPE_MODES[0]);
  const [decisions, setDecisions] = useState<Record<string, GovernanceDecision | null>>({});
  const [strips, setStrips] = useState<Record<string, SaveStrip>>({});
  const [cargando, setCargando] = useState(true);
  const [errorCarga, setErrorCarga] = useState<{ status: number; message: string } | null>(null);

  /** Lee las decisiones del servidor y las hace mandar en la pantalla. Devuelve si la
   *  lectura tuvo éxito: el modo `silent` (re-sincronización tras una escritura
   *  indeterminada) necesita saberlo para cerrar —o mantener— la incertidumbre de la fila,
   *  y no desmonta la grilla con el spinner de carga para no llevarse los strips. */
  const cargarPerfil = useCallback(async (opts?: { silent?: boolean }): Promise<boolean> => {
    if (!opts?.silent) {
      setCargando(true);
      setErrorCarga(null);
    }
    try {
      const filas = await api.getGovernanceProfile();
      const mapa: Record<string, GovernanceDecision | null> = {};
      for (const f of filas) {
        mapa[`${f.scope_type}|${f.scope_value}|${f.layer_key}`] = f.decision;
      }
      // Reemplazo, no merge: lo que el servidor no trae ya NO está decidido. Un merge dejaría
      // viva en pantalla una fila borrada por otro admin.
      setDecisions(mapa);
      setErrorCarga(null);
      return true;
    } catch (e: any) {
      const apiError = e instanceof ApiError ? e : null;
      // En modo `silent` NO se levanta el banner de carga: ese banner oculta la grilla
      // entera, y con ella el aviso de "estado incierto" de la fila que justo estamos
      // tratando de reconfirmar — el admin se quedaría sin la única señal que le dice que su
      // último cambio no está confirmado. La incertidumbre se cuenta por fila.
      if (!opts?.silent) {
        setErrorCarga({
          status: apiError?.status ?? 0,
          message: e?.message || "No se pudo leer la configuración de gobernanza.",
        });
      }
      return false;
    } finally {
      if (!opts?.silent) setCargando(false);
    }
  }, []);

  useEffect(() => {
    cargarPerfil();
  }, [cargarPerfil]);

  /** Cierra una incertidumbre re-leyendo el perfil del servidor. Si la lectura vuelve, el
   *  control queda con el valor REAL (`cargarPerfil` reemplaza el mapa entero) y el aviso se
   *  apaga solo; si tampoco vuelve, la fila sigue marcada incierta — que es la verdad. */
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
            ? {
                saving: false,
                reconciliando: false,
                incierto: false,
                error: null,
                reconciliadoAt: new Date().toLocaleTimeString(),
              }
            : { ...previo, reconciliando: false, incierto: true },
        };
      });
      // El resumen de arriba también dejó de ser confiable: si la escritura se aplicó, el
      // estado efectivo cambió. Se refresca en silencio.
      if (ok) onCambio();
    },
    [cargarPerfil, onCambio]
  );

  /** Autosave optimista con rollback POR CONTROL (D7):
   *  1. valor optimista para que el control responda al toque;
   *  2. `await` a la escritura;
   *  3. estado desde la RESPUESTA DEL SERVIDOR —fila persistida y estado recalculado—,
   *     jamás desde el valor optimista;
   *  4. en el `catch`, **según si el fallo es determinado o no** (ver abajo).
   *  No queda estado sin guardar que perder al desmontar: esa clase de bug no existe acá.
   *
   *  El paso 4 se partió en dos por el hallazgo de la verificación adversarial (MEDIA): el
   *  rollback era ciego. Un `fetch` puede rechazar DESPUÉS de que el servidor commiteó
   *  (timeout, corte en la respuesta, 502 de un proxy), y en ese caso revertir el control
   *  mostraba "Apagada" con la capa encendida en la base — o al revés. Solo un 4xx permite
   *  afirmar que no se escribió (`ApiError.isDeterminate`): es un veredicto deliberado del
   *  backend emitido antes de tocar la base. Todo lo demás es INDETERMINADO y se trata como
   *  tal: sin rollback, sin estado afirmado, y re-lectura del servidor. */
  const aplicar = async (s: ConfigScope, layerKey: string, next: GovernanceDecision | null) => {
    const key = scopeKey(s, layerKey);
    const previa = decisions[key] ?? null;
    if (previa === next) return;

    setDecisions((d) => ({ ...d, [key]: next }));
    setStrips((st) => ({ ...st, [key]: { saving: true, error: null, estado: st[key]?.estado } }));

    try {
      const res =
        next === null
          ? await api.deleteGovernanceDecision(s.scope_type, s.scope_value, layerKey)
          : await api.putGovernanceDecision({
              scope_type: s.scope_type,
              scope_value: s.scope_value,
              layer_key: layerKey,
              decision: next,
            });

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
          // Un DELETE responde 204 sin cuerpo: no hay estado que copiar y no se inventa uno.
          recalculando: res.estado_efectivo === null,
        },
      }));
      // El resumen por modo de arriba deja de ser cierto tras una escritura: se re-consulta
      // en silencio, sin desmontar esta sección ni perder los strips.
      onCambio();
    } catch (e: any) {
      const apiError = e instanceof ApiError ? e : null;
      // Sin `ApiError` no hay status que mirar (p. ej. la respuesta llegó 200 y falló al
      // parsearse: la escritura SÍ ocurrió). Ante la duda, indeterminado.
      const determinado = apiError?.isDeterminate === true;

      if (determinado) {
        // El servidor rechazó y no escribió (403 de rol, 404, 422 del piso/enum): revertir es
        // afirmar algo cierto. Se muestra el `detail` del backend, que es el mensaje del
        // producto (contrato, invariante 6).
        setDecisions((d) => ({ ...d, [key]: previa }));
        setStrips((st) => ({
          ...st,
          [key]: {
            saving: false,
            error: e?.message || "No se pudo guardar la decisión.",
            errorStatus: apiError?.status,
            estado: st[key]?.estado,
          },
        }));
        return;
      }

      // INDETERMINADO: no se revierte (revertir afirmaría que no se guardó) y no se afirma
      // ningún estado efectivo. La verdad la tiene el servidor, así que se le pregunta.
      setStrips((st) => ({
        ...st,
        [key]: {
          saving: false,
          incierto: true,
          error: e?.message || "No hubo respuesta del servidor al guardar la decisión.",
          errorStatus: apiError?.status,
          estado: null,
        },
      }));
      void reconciliar(key);
    }
  };

  const resueltoDe = (entry: CatalogEntry) =>
    scope.scope_type === "connection_mode"
      ? entry.porModo.find((p) => p.mode === scope.scope_value)
      : undefined;

  const scopeGroups: { title: string; scopes: ConfigScope[] }[] = [
    { title: "Organización", scopes: [SCOPE_TENANT] },
    { title: "Modo de conexión", scopes: SCOPE_MODES },
    { title: "Superficie / herramienta", scopes: SCOPE_SURFACES },
  ];

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
          Configuración de la gobernanza
        </h2>
        <p className="text-[11px] text-text-secondary leading-relaxed">
          Qué capas opcionales aplican para cada alcance. Cada control se guarda solo, al instante: no
          hay botón de guardar y no queda nada pendiente que se pierda al salir de la pantalla.
        </p>
      </div>

      {/* Precedencia canónica, escrita donde se configura (FR-006). */}
      <div className="bg-background/40 border border-slate-700/30 rounded-lg p-4 space-y-2">
        <p className="text-[11px] font-semibold text-white">Orden de resolución</p>
        <p className="text-[11px] text-text-secondary font-mono leading-relaxed">
          Conexión (clave) → Superficie / herramienta → Modo de conexión → Toda la organización → Default
          del producto
        </p>
        <p className="text-[11px] text-text-secondary leading-relaxed">
          Gana siempre el alcance más específico que tenga una decisión propia. Un alcance en{" "}
          <span className="text-white">Heredar</span> no decide nada: cede al siguiente de la lista. El
          piso no participa de este orden — se aplica siempre.
        </p>
      </div>

      {/* Selector de alcance */}
      <div className="bg-panel border border-slate-700/40 rounded-lg p-4 space-y-3">
        {scopeGroups.map((g) => (
          <div key={g.title} className="space-y-1.5">
            <p className="text-[10px] font-bold uppercase tracking-wider text-text-secondary">{g.title}</p>
            <div className="flex flex-wrap gap-1.5">
              {g.scopes.map((s) => {
                const activo = s.scope_type === scope.scope_type && s.scope_value === scope.scope_value;
                const decididas = gobernables.filter(
                  (c) => (decisions[scopeKey(s, c.base.layer_key)] ?? null) !== null
                ).length;
                return (
                  <button
                    key={`${s.scope_type}|${s.scope_value}`}
                    type="button"
                    onClick={() => setScope(s)}
                    className={`px-2.5 py-1.5 rounded text-[11px] font-semibold border transition-colors ${
                      activo
                        ? "border-primary/50 bg-primary/15 text-primary"
                        : "border-slate-700/60 bg-background/40 text-text-secondary hover:text-white hover:border-slate-500"
                    }`}
                  >
                    {s.label}
                    {decididas > 0 && (
                      <span className="ml-1.5 font-mono text-[10px] opacity-80">{decididas}</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {/* Alcance seleccionado */}
      <div className="bg-panel border border-slate-700/40 rounded-lg p-5 space-y-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-sm font-bold text-white">{scope.label}</h3>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-mono border border-slate-700 bg-slate-800/60 text-text-secondary">
              {scope.scope_type === "tenant_default" ? "toda la organización" : scope.scope_value}
            </span>
          </div>
          <p className="text-[11px] text-text-secondary leading-relaxed">{scope.hint}</p>
        </div>

        {cargando && (
          <p className="text-xs font-mono text-text-secondary py-6 text-center">
            Leyendo la configuración…
          </p>
        )}

        {errorCarga && (
          <div className="px-3 py-2.5 rounded border text-[11px] bg-warning/10 border-warning/20 text-warning space-y-1">
            <p className="font-bold">
              {errorCarga.status === 404
                ? "La configuración todavía no está disponible en este servidor"
                : "No se pudo leer la configuración"}
            </p>
            {/* Se dice el motivo real: una pantalla de configuración vacía sin explicación se
                lee como "no hay nada configurado", que es una afirmación distinta. */}
            <p className="font-normal">{errorCarga.message}</p>
          </div>
        )}

        {!cargando && !errorCarga && (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
            {gobernables.map((entry) => {
              const key = scopeKey(scope, entry.base.layer_key);
              return (
                <DecisionRow
                  key={key}
                  entry={entry}
                  scope={scope}
                  decision={decisions[key] ?? null}
                  strip={strips[key]}
                  resuelto={resueltoDe(entry)}
                  onChange={(next) => aplicar(scope, entry.base.layer_key, next)}
                  onReconsultar={() => reconciliar(key)}
                />
              );
            })}
            {gobernables.length === 0 && (
              <p className="text-xs text-text-secondary">Sin capas gobernables en el catálogo.</p>
            )}
          </div>
        )}

        {/* El piso, en la misma pantalla y SIN controles: no es un toggle deshabilitado, es una
            capa que no tiene control porque no es configurable (SC-004 estructural). Un switch
            en gris insinuaría que existe una forma de apagarlo. */}
        <div className="border-t border-slate-700/30 pt-4 space-y-2">
          <p className="text-[11px] font-semibold text-white">Piso no negociable — sin controles</p>
          <p className="text-[11px] text-text-secondary leading-relaxed">
            Estas capas se aplican siempre, en este y en todos los alcances. No hay configuración que las
            desactive: cualquier intento se rechaza y queda registrado.
          </p>
          <div className="flex flex-wrap gap-1.5">
            {piso.map((c) => (
              <span
                key={c.base.layer_key}
                className="inline-flex items-center gap-1.5 px-2 py-1 rounded border border-primary/20 bg-primary/10 text-primary text-[10px] font-bold"
              >
                <span aria-hidden="true">■</span>
                {layerCopy(c.base.layer_key).name}
              </span>
            ))}
            {piso.length === 0 && (
              <span className="text-[11px] text-text-secondary">Sin capas de piso reportadas.</span>
            )}
          </div>
        </div>
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

  // `silent` re-consulta el estado sin vaciar la pantalla: tras guardar una decisión el
  // resumen por modo deja de ser cierto y hay que refrescarlo, pero un spinner a pantalla
  // completa desmontaría la sección de configuración y se llevaría los strips de guardado
  // ("Guardado 14:32:07") que son la única evidencia de que la escritura ocurrió.
  const load = useCallback(async (opts?: { silent?: boolean }) => {
    if (!opts?.silent) setLoading(true);
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
      // En el refresco silencioso se conserva el último estado conocido: vaciar la pantalla
      // por un refresco fallido borraría la sección de configuración y sus strips, y el admin
      // no sabría si su cambio se guardó. El banner de error de arriba ya lo dice.
      if (!opts?.silent) setStatus(null);
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
      if (modo)
        entry.porModo.push({
          mode: modo,
          estado: l.estado_efectivo,
          motivo: l.motivo,
          origen: l.origen,
          decision: l.decision_resuelta,
        });
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
          onClick={() => load()}
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

          {/* ── Configuración por alcance (US2 — FR-004/FR-005) ── */}
          <ConfiguracionGobernanza
            gobernables={gobernables}
            piso={piso}
            onCambio={() => load({ silent: true })}
          />

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
