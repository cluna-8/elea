import React, { useState, useEffect, useRef } from "react";
import { authStorage } from "../services/auth";
import { GovernanceEffectiveState } from "../services/api";
import { estadoUi, layerCopy } from "./GovernancePage";
import { Button, Card, PageHeader, StatusBadge, type BadgeTone } from "../components/ui";

// Firewall en vivo — feed del gateway (coding tools / browser) migrado en spec 019.
// Consume /api/v1/gw/events (metadata-only: sin texto de prompt crudo ni PII cruda).
//
// **El feed dejó de ser público (spec 027, hallazgo A1).** Era un endpoint sin sesión, y con
// la 027 el evento pasó a llevar la atribución por capa —qué capa bloqueó cada pedido y
// cuáles no corrieron, o sea la postura de seguridad del tenant—. Ahora `/gw/events` exige
// sesión (admin o compliance_officer, los mismos roles que el nav le da a esta página en
// App.tsx:29), así que este fetch manda el token como cualquier otra llamada de la consola.
// El 401 se trata como en `api.ts:17-22`: sesión muerta → limpiar y volver al login, no
// reintentar cada 2 s contra un endpoint que ya nos dijo que no.
//
// **Residuales de US2 cerrados acá (dos, y los dos son de honestidad):**
//
// 1. **Un bloqueo no se veía como bloqueo.** `STATUS_META` enumeraba cinco valores y todo lo
//    demás caía en un chip GRIS con la etiqueta cruda. El plano chat publica tres estados
//    que no estaban en esa lista —`blocked_by_policy` (chat.py:694), `blocked_residency`
//    (chat.py:805)— y el gateway un cuarto, `upstream_error` (gateway.py:829). Resultado: el
//    pedido donde el firewall SÍ actuó se pintaba como un evento neutro. El arreglo no es
//    agregar tres filas —eso deja vivo el mecanismo, y el próximo call-site de bloqueo nace
//    gris otra vez— sino **derivar la familia visual del nombre del estado**: cualquier
//    `blocked_*`, conocido o no, se pinta como bloqueo (ver `estadoEvento`).
//
// 2. **La atribución de US2 no llegaba al cliente.** `applied_layers`/`blocked_by_layer` ni
//    siquiera estaban declarados en `GwEvent`: toda la feature vivía sólo en `/gw/monitor`,
//    la vitrina standalone que se usa en demos. O sea que construimos "qué capa bloqueó" y
//    la consola real —la que el cliente abre— no lo mostraba. Ahora se renderiza acá, y el
//    vocabulario NO se reescribe: el nombre de cada capa sale de `layerCopy` y el color de
//    cada estado de `estadoUi`, ambos de GovernancePage. Si Gobernanza y el Firewall
//    pintaran su propia versión del mismo estado, tendríamos dos verdades sobre el mismo
//    hecho — que es justo lo que la 027 elimina.

interface MaskedEntity { type: string; count: number; }
/** Elemento de atribución — las CUATRO claves del contrato (evento-monitor-atribucion §1),
 *  serializadas sin transformar desde el resolutor. `decision` es null cuando la capa no
 *  corrió (`status != applied`): no decidió nada, y afirmar `allow` ahí sería inventar. */
interface GwLayer {
  layer_code: string;
  status: string;
  decision: string | null;
  count?: number;
}
/** Decisión del auto-router proyectada al feed (spec 030, contrato §evento de vitrina).
 *  Es un SUBCONJUNTO del objeto decisión: `requested` y `reason` se quedan en el Debugger
 *  Técnico y en la columna durable, no en la vitrina. */
interface GwRouting {
  route?: string | null;
  score?: number | null;
  model_selected?: string | null;
  degraded?: boolean;
}
interface GwEvent {
  tenant?: string;
  tool?: string;
  client?: string;
  model?: string;
  compliance_status?: string;
  masked_entities?: MaskedEntity[];
  masked_preview?: string;
  ts?: string;
  /** null (no `[]`) en eventos sin atribución: productores pre-027 o emisores que no la
   *  llevan. Ausencia de dato ≠ ausencia de protección — el render lo dice distinto. */
  applied_layers?: GwLayer[] | null;
  blocked_by_layer?: string | null;
  /** Campo OPCIONAL del contrato: lo emite UN solo productor (el plano chat, y sólo
   *  cuando el usuario pidió «auto»). Su ausencia es lo normal y no se pinta nada. */
  routing?: GwRouting | null;
}

// Familias visuales. El color cuelga de la familia, nunca del `compliance_status` crudo.
type Familia = "pass" | "blocked" | "flag" | "error" | "otro";

const FAMILIA_CLS: Record<Familia, string> = {
  pass: "bg-ok-bg text-ok border-ok/30",
  blocked: "bg-danger-bg text-danger border-danger/40",
  flag: "bg-warn-bg text-warn border-warn/40",
  // `upstream_error` no es un verdicto del firewall: el pedido pasó las capas y falló el
  // servicio de destino. Neutro a propósito — ni verde (no se completó) ni rojo (nadie lo
  // bloqueó). Constitución VII: "servicio upstream", jamás la marca del proveedor.
  error: "bg-surface-2 text-text-secondary border-border",
  otro: "bg-surface-2 text-text-secondary border-border",
};

// La pill de estado superior de cada evento usa el kit (StatusBadge): la familia visual
// mapea al tono semántico del componente para no duplicar la escala de color.
const FAMILIA_TONE: Record<Familia, BadgeTone> = {
  pass: "ok",
  blocked: "danger",
  flag: "warn",
  error: "neutral",
  otro: "neutral",
};

// Sólo la ETIQUETA de cada estado; el color sale de la familia. Barrido completo de los
// valores que los tres planos publican al feed (residual US2):
//   gateway/inspect → passed · flagged_high_risk · blocked_prohibited · blocked_secret ·
//                     upstream_error                       (gateway.py:262-275, :829)
//   motor           → passed · flagged_high_risk · blocked_prohibited
//   chat            → blocked_prohibited · blocked_by_policy · blocked_residency
//                                                          (chat.py:566, :694, :805)
// `blocked_guardian` no lo emite ningún productor vivo; se conserva porque el ring dura
// 300 s y puede traer eventos de un despliegue anterior.
const STATUS_LABEL: Record<string, string> = {
  passed: "PERMITIDO",
  flagged_high_risk: "ALTO RIESGO",
  blocked_prohibited: "BLOQUEADO",
  blocked_secret: "SECRETO BLOQUEADO",
  blocked_guardian: "BLOQUEADO",
  // Se nombra por la POLÍTICA y no por el guardián que la aplicó: el nombre del guardián lo
  // edita el cliente y es white-label (D6 / Principio VII).
  blocked_by_policy: "BLOQUEADO POR POLÍTICA",
  // Residencia de datos del proyecto: NO es capa del registry, así que este evento viene con
  // `blocked_by_layer` en null a propósito (chat.py:797-805).
  blocked_residency: "BLOQUEADO POR RESIDENCIA",
  upstream_error: "ERROR UPSTREAM",
};

/** Familia + etiqueta de un `compliance_status`. La familia se DERIVA del nombre cuando la
 *  tabla no lo conoce: un estado nuevo llamado `blocked_*` es un bloqueo y se pinta como
 *  bloqueo aunque nadie haya tocado este archivo. El default no es "no sé" (gris, que se lee
 *  como neutro) sino "lo que el nombre afirma". */
function estadoEvento(status?: string): { label: string; familia: Familia } {
  const raw = status || "";
  const familia: Familia = raw.startsWith("blocked")
    ? "blocked"
    : raw.startsWith("flagged")
    ? "flag"
    : raw === "passed"
    ? "pass"
    : raw.includes("error")
    ? "error"
    : "otro";
  return { label: STATUS_LABEL[raw] || (raw || "—").toUpperCase(), familia };
}

// ── Vocabulario de la atribución (spec 027) ───────────────────────────────────────────
// Qué le pasó A LA CAPA en este pedido, traducido al estado que Gobernanza ya pinta, para
// tomar de ahí color y forma. Se toma el COLOR de `estadoUi` y no la etiqueta porque los dos
// ejes miran cosas distintas: Gobernanza describe una CONFIGURACIÓN vigente ("Aplicándose"),
// el feed describe UN PEDIDO que ya ocurrió ("aplicada"). Y `skipped` (apagada por decisión)
// y `not_configured` (sin información) comparten color pero JAMÁS etiqueta: colapsarlos en
// un solo texto sería volver a confundir "no la aplicamos" con "no sabemos", que es el
// error que la 027 borra.
const LAYER_STATUS_STATE: Record<string, GovernanceEffectiveState> = {
  applied: "aplicandose",
  delegated: "delegada",
  requires_credential: "requiere_credencial",
  degraded: "degradada",
  skipped: "no_disponible",
  not_configured: "no_disponible",
};
// Mismas cadenas que sirve `/gw/monitor` (backend/src/api/monitor.py, `_STATUS_LABELS` /
// `_DECISION_LABELS`): las dos vitrinas leen el MISMO evento y tienen que nombrarlo igual.
// Lo que sí difiere es la DENSIDAD, y a propósito: la standalone es una tira compacta de
// demo y agrega las capas inertes en un chip con tooltip; ésta es la consola del cliente,
// donde "qué me cubrió y qué no" se responde sin pasar el mouse por encima.
const LAYER_STATUS_LABEL: Record<string, string> = {
  applied: "aplicada",
  skipped: "omitida por configuración",
  not_configured: "sin configurar",
  requires_credential: "requiere credencial",
  delegated: "delegada al servicio upstream",
  degraded: "degradada",
};
const DECISION_LABEL: Record<string, string> = {
  allow: "permitió",
  mask: "enmascaró",
  flag: "marcó",
  block: "bloqueó",
};

const CHIP = "inline-flex items-center gap-1.5 px-2 py-0.5 rounded border text-[10px] font-semibold whitespace-nowrap";

/** Atribución por pedido: qué capa bloqueó (destacado), qué capas corrieron y cuáles no.
 *  `familia` viene del `compliance_status` porque hace falta para distinguir el bloqueo SIN
 *  capa —un caso real— de un dato faltante. */
const Atribucion: React.FC<{ e: GwEvent; familia: Familia }> = ({ e, familia }) => {
  const capas = Array.isArray(e.applied_layers)
    ? e.applied_layers.filter((l): l is GwLayer => !!l && typeof l === "object")
    : [];
  const bloqueo = e.blocked_by_layer;

  if (!capas.length && !bloqueo) {
    // Evento sin atribución (productor pre-027). "No hay registro" ≠ "no actuó ninguna
    // capa": el piso corre siempre, así que afirmar lo segundo sería mentir hacia el lado
    // que asusta, igual que afirmar cobertura sería mentir hacia el lado que tranquiliza.
    return (
      <div className="flex items-center gap-2 mt-3 flex-wrap">
        <span className={`${CHIP} border-border bg-surface-2 text-text-tertiary italic font-normal`}>
          sin registro de capas
        </span>
      </div>
    );
  }

  const conDecision = capas.filter(
    (l) => l.status === "applied" && l.decision && l.decision !== "allow" && l.layer_code !== bloqueo,
  );
  const limpias = capas.filter(
    (l) => l.status === "applied" && (!l.decision || l.decision === "allow") && l.layer_code !== bloqueo,
  );
  const inertes = capas.filter((l) => l.status && l.status !== "applied");

  const uiAplicada = estadoUi("aplicandose");

  return (
    <div className="flex items-center gap-2 mt-3 flex-wrap">
      {bloqueo ? (
        <span className={`${CHIP} font-bold ${FAMILIA_CLS.blocked}`}>
          <span aria-hidden="true">■</span> Bloqueado por: {layerCopy(bloqueo).name}
        </span>
      ) : familia === "blocked" ? (
        // Bloqueo cuya causa NO es una capa del catálogo — hoy, la residencia de datos del
        // proyecto (chat.py:797-805). Sin este chip el pedido sale con "BLOQUEADO" arriba y
        // debajo sólo las capas que permitieron: se lee como "lo bloquearon y ninguna capa
        // bloqueó". Adjudicárselo a una capa para tapar el hueco sería falsear el registro,
        // que es exactamente lo que esta spec vino a terminar.
        <span
          className={`${CHIP} font-bold ${FAMILIA_CLS.blocked}`}
          title="El bloqueo lo produjo una política que no está en el catálogo de capas gobernables (por ejemplo, residencia de datos). Ninguna capa se lo atribuye porque ninguna lo produjo."
        >
          <span aria-hidden="true">■</span> Bloqueado fuera del catálogo de capas
        </span>
      ) : null}

      {conDecision.map((l) => (
        <span
          key={l.layer_code}
          className={`${CHIP} ${uiAplicada.border} ${uiAplicada.bg} ${uiAplicada.text}`}
        >
          <span aria-hidden="true">{uiAplicada.glyph}</span>
          {layerCopy(l.layer_code).name}: {DECISION_LABEL[l.decision || ""] || l.decision}
          {typeof l.count === "number" ? ` (${l.count})` : ""}
        </span>
      ))}

      {/* Las que corrieron sin encontrar nada también responden "¿qué me cubrió este
          pedido?": sin ellas, un pedido limpio se ve igual que uno sin protección. Van
          agregadas —diez chips verdes no se leen— con los nombres en el tooltip. */}
      {limpias.length > 0 && (
        <span
          className={`${CHIP} ${uiAplicada.border} bg-transparent ${uiAplicada.text} font-normal`}
          title={limpias.map((l) => layerCopy(l.layer_code).name).join(" · ")}
        >
          <span aria-hidden="true">{uiAplicada.glyph}</span>
          {limpias.length} capa(s) aplicadas sin hallazgos
        </span>
      )}

      {/* Las que NO corrieron: apagada por configuración, sin credencial, delegada y
          degradada son estados distintos y ninguno significa "no pasó nada". Cada una lleva
          su color de Gobernanza; el tooltip dice cuál es cuál. */}
      {inertes.map((l) => {
        const ui = estadoUi(LAYER_STATUS_STATE[l.status] || "no_disponible");
        return (
          <span
            key={l.layer_code}
            className={`${CHIP} font-normal ${ui.border} ${ui.bg} ${ui.text}`}
            title={`${layerCopy(l.layer_code).name}: ${LAYER_STATUS_LABEL[l.status] || l.status}`}
          >
            <span aria-hidden="true">{ui.glyph}</span>
            {layerCopy(l.layer_code).name}: {LAYER_STATUS_LABEL[l.status] || l.status}
          </span>
        );
      })}
    </div>
  );
};

/** Ruteo automático (spec 030, FR-006): a qué modelo mandó el pedido el router y por qué.
 *
 *  Va en su propia fila y NO mezclado con la atribución de capas, a propósito: el ruteo no
 *  es una capa del firewall, no protege nada, y meterlo entre los chips de capas lo haría
 *  leer como un verdicto de seguridad.
 *
 *  El campo es OPCIONAL en el contrato del evento y hoy lo emite un solo productor —el
 *  plano chat, sólo en peticiones «auto»—, así que su AUSENCIA es lo normal y no se dibuja
 *  nada: "sin chip" significa "este pedido no pasó por el router", no "el router no
 *  eligió". Misma distinción que `sin registro de capas`. El vocabulario es el mismo que
 *  sirve la vitrina standalone (backend/src/api/monitor.py, `ruteo()`): las dos leen el
 *  MISMO evento y tienen que nombrarlo igual. */
const Ruteo: React.FC<{ e: GwEvent }> = ({ e }) => {
  const r = e.routing;
  if (!r || typeof r !== "object" || Array.isArray(r)) return null;

  const destino = r.model_selected ? ` → ${r.model_selected}` : "";
  const score =
    typeof r.score === "number" && isFinite(r.score) ? ` (${r.score.toFixed(2)})` : "";
  // Sin ruta ganadora se DICE «modelo por defecto» en vez de omitirlo: "el router corrió y
  // nada superó el umbral" es un dato, no un hueco.
  const texto = r.route ? `${r.route}${score}${destino}` : `modelo por defecto${destino}`;
  // Degradado ≠ pedido fallido: se respondió igual, pero la decisión no se pudo tomar
  // (embeddings caídos, timeout o configuración inválida). Decirlo es el requisito —
  // FR-004: la degradación jamás es silenciosa. Por eso el chip cambia de familia visual.
  const titulo = r.degraded
    ? "El ruteo no pudo decidir (modelo de embeddings caído, timeout o configuración inválida) y el pedido se sirvió por el modelo por defecto. Se respondió igual."
    : "Modelo elegido automáticamente por similitud semántica con los ejemplos de la ruta.";

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <span
        className={`${CHIP} ${
          r.degraded ? FAMILIA_CLS.flag : "border-border bg-primary-tint text-primary"
        }`}
        title={titulo}
      >
        <span aria-hidden="true">🧭</span>
        {texto}
        {r.degraded ? " · ruteo degradado" : ""}
      </span>
    </div>
  );
};

// Timestamp naive (UTC sin 'Z') -> forzar UTC para que el browser lo muestre en hora local.
function fmtTime(iso?: string): string {
  if (!iso) return "";
  const utc = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + "Z";
  const d = new Date(utc);
  return isNaN(d.getTime()) ? iso : d.toLocaleString("es-ES", { hour12: false });
}

export const FirewallMonitorPage: React.FC = () => {
  const [events, setEvents] = useState<GwEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const [denegado, setDenegado] = useState(false);
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      if (pausedRef.current) return;
      try {
        const token = authStorage.getToken();
        const r = await fetch("/api/v1/gw/events?limit=50", {
          headers: {
            Accept: "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
        });
        if (r.status === 401) {
          // Mismo trato que `handleExpiredSession`: la sesión murió, no es un feed caído.
          authStorage.clear();
          window.location.reload();
          return;
        }
        if (r.status === 403) {
          // El nav no debería traer acá a un rol sin permiso, pero el gate real es el router:
          // si alguna vez discrepan, la pantalla lo dice en vez de mostrar "sin tráfico".
          if (alive) { setDenegado(true); setConnected(false); }
          return;
        }
        const d = await r.json();
        if (!alive) return;
        setEvents(Array.isArray(d.events) ? d.events : []);
        setConnected(true);
        setDenegado(false);
      } catch {
        if (alive) setConnected(false);
      }
    };
    tick();
    const id = setInterval(tick, 2000);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const total = events.length;
  const blocked = events.filter((e) => (e.compliance_status || "").startsWith("blocked")).length;
  const allowed = total - blocked;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title={
          <span className="flex items-center gap-3">
            Conexiones en vivo
            <span className="flex items-center gap-1.5 text-xs font-semibold text-ok">
              <span className="h-2 w-2 rounded-full bg-ok animate-pulse" />
              EN VIVO
            </span>
          </span>
        }
        // El feed dejó de ser sólo del gateway: con la 030 el plano chat publica también
        // sus peticiones servidas (antes sólo los bloqueos), que es de donde salen los
        // eventos con ruteo automático. Nombrar sólo las coding tools acá dejaría al
        // usuario buscando en la pantalla equivocada el pedido que acaba de mandar.
        subtitle="Tráfico de coding tools (Claude Code, Cursor…), del navegador y del chat de la consola. Auditado sin texto de prompt ni PII cruda."
        actions={
          <>
            <Button variant="secondary" size="sm" onClick={() => setPaused((p) => !p)}>
              {paused ? "Reanudar" : "Pausar"}
            </Button>
            <Button variant="secondary" size="sm" onClick={() => setEvents([])}>
              Limpiar
            </Button>
          </>
        }
      />

      {/* Banda de contexto. Decía, en verde y sin condiciones: "Redacción activa… el modelo
          nunca ve el dato real". Es una afirmación que esta misma pantalla contradice dos
          centímetros más abajo: con la atribución renderizada, un evento puede mostrar
          "Enmascarado de datos personales: omitida por configuración" —que es una postura
          LEGÍTIMA y frecuente (D8: en herramientas de código el enmascarado rompe el
          código)— debajo de un cartel que promete lo contrario. Afirmar cobertura que no se
          verificó es el mismo pecado que pintar un bloqueo de gris, sólo que hacia el lado
          que tranquiliza. Ahora la banda explica dónde mirar y no promete nada. */}
      <div className="flex items-start gap-2 rounded-card border border-border bg-primary-tint px-4 py-3 text-sm text-text-secondary">
        <span aria-hidden="true">🔒</span>
        <span>
          Qué protege cada pedido lo decide la postura de la organización, y cambia por
          alcance. Cada evento de abajo lleva las capas que se aplicaron <strong>de verdad</strong>{" "}
          y las que no; la configuración vigente se ve en <strong>Gobernanza</strong>.
        </span>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[
          { n: total, label: "peticiones", color: "text-text-primary" },
          { n: allowed, label: "permitidas", color: "text-ok" },
          { n: blocked, label: "bloqueadas", color: "text-danger" },
        ].map((s) => (
          <Card key={s.label}>
            <div className={`text-4xl font-bold ${s.color}`}>{s.n}</div>
            <div className="mt-1 text-sm text-text-secondary">{s.label}</div>
          </Card>
        ))}
      </div>

      {/* Feed */}
      {total === 0 ? (
        <div className="rounded-card border border-dashed border-border bg-surface py-16 text-center text-text-secondary">
          {denegado
            ? "Esta cuenta no tiene permiso para ver el firewall en vivo. Se necesita un rol de administración o de cumplimiento."
            : connected
            ? "Esperando tráfico… enviá una request por el gateway (Claude Code, VS Code o el browser)."
            : "Conectando con el feed del gateway…"}
        </div>
      ) : (
        <div className="space-y-3">
          {events.map((e, i) => {
            const { label, familia } = estadoEvento(e.compliance_status);
            // El borde de la tarjeta también cuelga de la familia: un bloqueo se distingue
            // del resto del feed antes de leer una sola palabra.
            const borde =
              familia === "blocked"
                ? "border-danger/40"
                : familia === "flag"
                ? "border-warn/40"
                : "border-border";
            return (
              <div key={i} className={`rounded-card border ${borde} bg-surface px-5 py-4 shadow-card`}>
                <div className="flex flex-wrap items-center gap-3">
                  <StatusBadge tone={FAMILIA_TONE[familia]}>{label}</StatusBadge>
                  <span className="rounded-md border border-border bg-primary-tint px-2.5 py-0.5 text-xs font-medium text-primary">
                    ▸ {e.tenant || "—"}
                  </span>
                  <strong className="text-text-primary">{e.tool || "—"}</strong>
                  <span className="text-sm text-text-secondary">· {e.client || "anónimo"}</span>
                  {e.model && <span className="font-mono text-xs text-text-secondary">{e.model}</span>}
                  <span className="ml-auto font-mono text-xs text-text-tertiary">{fmtTime(e.ts)}</span>
                </div>

                <Atribucion e={e} familia={familia} />

                <Ruteo e={e} />

                {e.masked_entities && e.masked_entities.length > 0 && (
                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <span className="text-xs text-text-secondary">PII enmascarada:</span>
                    {e.masked_entities.map((x, j) => (
                      <span key={j} className="rounded border border-border bg-primary-tint px-2 py-0.5 font-mono text-[11px] text-primary">
                        {x.count}× {x.type}
                      </span>
                    ))}
                  </div>
                )}

                {e.masked_preview && (
                  <div className="mt-3 whitespace-pre-wrap break-words rounded-md border border-border bg-surface-2 px-3 py-2 font-mono text-xs text-text-secondary">
                    {e.masked_preview}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
