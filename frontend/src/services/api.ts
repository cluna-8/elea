import { authStorage } from "./auth";

// Ruta RELATIVA al mismo origen: el ingress (Caddy) proxya /api/* al backend.
// Un host:puerto absoluto rompe HTTPS (mixed content) y ata el deploy a un
// puerto publicado — fix portado del install real del VPS (issue #35).
const API_BASE = "/api/v1";

function authHeaders(): Record<string, string> {
  const token = authStorage.getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function jsonHeaders(): Record<string, string> {
  return { "Content-Type": "application/json", ...authHeaders() };
}

function handleExpiredSession(res: Response): void {
  if (res.status === 401) {
    authStorage.clear();
    window.location.reload();
  }
}

export interface Group {
  id: string;
  name: string;
  description?: string;
  engine_team_id?: string;
  created_at: string;
}

export interface SpendInfo {
  spend_usd: number | null;
  max_budget: number | null;
  remaining: number | null;
}

export interface User {
  id: string;
  username: string;
  email: string;
  role: string;
  group_id?: string;
  engine_user_id?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  // Contexto legal por persona (spec 013 FR-016: la gobernanza legal vive a nivel Client,
  // no en la Connection). UsersPage ya los mandaba en el alta; faltaban en el tipo, y sin
  // chequeo de tipos en el build nadie lo notó.
  legal_basis?: string;
  risk_level?: string;
  compliance_project_id?: string;
  // Spec 043 (US4/US5): distingue cuentas de servicio (`account_type: "service"`) de
  // personas reales — `GET /users` las excluye por default (`?include_service=true` las
  // trae, con `purpose`). `deactivated_at`/`deactivated_reason` quedan pobladas cuando se
  // dio de baja (`DELETE /{user_id}`, no borra físicamente — ver `UsersPage.tsx` T041).
  account_type?: "human" | "service";
  purpose?: string;
  deactivated_at?: string | null;
  deactivated_reason?: string | null;
}

/** Actualización parcial de persona (spec 043 US5, contrato `PATCH /users/{id}`) — solo se
 *  envían los campos tocados, a diferencia de `updateUser` (reemplazo completo vía `PUT`,
 *  que se mantiene por compatibilidad hacia atrás). */
export interface UserPatch {
  username?: string;
  email?: string;
  role?: string;
  group_id?: string | null;
  is_active?: boolean;
  legal_basis?: string;
  risk_level?: string;
  compliance_project_id?: string | null;
}

/** Espacio de Eleia Hub heredado de una migración, sin dueño todavía (spec 043 US1,
 *  contrato 1: `WorkspaceUnassignedOut`) — sin `role`, porque nadie es miembro aún. */
export interface WorkspaceUnassigned {
  id: string;
  engine_slug: string;
  display_name: string;
  status: "unassigned";
}

export interface Budget {
  id: string;
  user_id?: string;
  group_id?: string;
  max_spend_usd: number;
  current_spend_usd: number;
  max_tokens: number;
  current_tokens: number;
  reset_period: string;
  last_reset_at: string;
  created_at: string;
  updated_at: string;
}

export interface ModelPricing {
  model_name: string;
  input_cost_per_million: number;
  output_cost_per_million: number;
  max_tokens?: number | null;
  max_input_tokens?: number | null;
}

/** Estado del supervisor del motor (spec 033, `GET /chat/models/status`). Contrato
 *  200-nunca-500: `state` puede ser `"unknown"` con `ts`/`config_hash` en `null` — no son
 *  opcionales por descuido de tipado, son un valor real que la UI tiene que sobrevivir. */
export interface EngineApplyStatus {
  state: "idle" | "applying" | "error" | "unknown";
  ts: number | null;
  last_error: string | null;
  config_hash: string | null;
}

export interface CostModelBreakdown {
  model: string;
  cost_usd: number;
  requests: number;
  tokens_saved: number;
}

export interface CostEntityBreakdown {
  name: string;
  cost_usd: number;
  requests: number;
  tokens_saved: number;
  cost_saved_usd?: number;
}

/** Protección de documentos por persona (spec 044 US2, T025) — separado de `by_user`
 *  a propósito: cuenta DOCUMENTOS enmascarados (contrato 3 de la 043: varios chunks
 *  comparten un `document_group_id`), nunca cuestiones con costo/modelo real. Mezclar
 *  ambos infla el "gasto por usuario" con operaciones que nunca llaman a un modelo. */
export interface MaskingEntityBreakdown {
  name: string;
  documents: number;
  sin_document_id: number;
}

export interface CostSummary {
  range: string;
  total_cost_usd: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  tokens_saved: number;
  cost_saved_usd: number;
  total_requests: number;
  cost_saved_estimate_usd: number | null;
  top_models: CostModelBreakdown[];
  by_user: CostEntityBreakdown[];
  by_group: CostEntityBreakdown[];
  masking_by_user: MaskingEntityBreakdown[];
}

export interface CostConfig {
  enabled: boolean;
  default_strategy: string;
  default_threshold: number;
  default_aggressiveness: string;
}

export interface GroupCompressionConfig {
  group_id: string;
  group_name: string;
  mode: "off" | "deterministic" | "headroom";
  strategy: "deterministic" | "headroom";
  threshold_tokens: number | null;
  aggressiveness: "low" | "medium" | "high";
  cache_enabled: boolean;
}

export type CompressionVeredicto = "conviene" | "no_conviene" | "usd_no_disponible";

export interface CompressionAnalysis {
  tokens_original: number;
  tokens_compressed: number;
  tokens_saved: number;
  cost_saved_usd: number | null;
  would_compress: boolean;
  veredicto: CompressionVeredicto;
  ratio: number;
  threshold: number;
  model: string | null;
  aggressiveness: string;
  strategy: string;
  strategy_applied?: string;
}

export interface SecurityPolicy {
  id?: string;
  name: string;
  is_active: boolean;
  entity_configs: Record<string, "MASK" | "BLOCK" | "ALLOW">;
  gdpr_mode: boolean;
  ai_act_mode: boolean;
  headroom_mode: boolean;
}

// ── Gobernanza (spec 027) ────────────────────────────────────────────────────────
// Los dos ejes que el producto confundía y que la 027 separa: `decision_resuelta` es
// el DESEO del admin y `estado_efectivo` es la ejecución REAL (contrato
// api-gobernanza.md, garantía (c): son independientes — una capa `on` puede estar
// `no_disponible`). Ningún componente puede volver a derivar "activo" de un deseo:
// esa derivación es exactamente la mentira que esta feature elimina (FR-001).

export type GovernanceTier = "floor" | "optional";
export type GovernanceDecision = "on" | "off";
export type GovernanceOrigin =
  | "floor" | "connection" | "surface" | "connection_mode" | "tenant_default" | "product_default";
export type GovernanceEffectiveState =
  | "aplicandose" | "requiere_credencial" | "delegada" | "no_disponible" | "degradada";

export interface GovernanceLayerStatus {
  layer_key: string;
  tier: GovernanceTier;
  planes: string[];
  decision_resuelta: GovernanceDecision;
  origen: GovernanceOrigin;
  estado_efectivo: GovernanceEffectiveState;
  /** Obligatorio cuando `estado_efectivo != aplicandose` (FR-013): el copy que distingue
   *  "no la aplicamos nosotros" de "estás desprotegido". Sale de un catálogo cerrado del
   *  backend, nunca de una excepción del motor. */
  motivo: string;
}

/** Estado normalizado para la UI. `porModo` responde SC-002 ("qué protege el tráfico de
 *  suscripción y qué el de modelos de la pasarela") de un vistazo. */
export interface GovernanceStatus {
  layers: GovernanceLayerStatus[];
  porModo: Record<string, GovernanceLayerStatus[]>;
}

export const CONNECTION_MODES = ["subscription", "gateway-models"] as const;
export type ConnectionMode = (typeof CONNECTION_MODES)[number];

/** Superficies configurables: espejo EXACTO del CHECK `ck_api_keys_tool_type` de la
 *  Connection (data-model §1.2). Jamás una señal de User-Agent: la superficie que habilita
 *  una relajación es el `tool_type` que el admin provisionó, no algo que el cliente diga de
 *  sí mismo. Si el enum crece (issue #28), crece acá y en los dos CHECKs, en la misma
 *  migración. */
export const GOVERNANCE_SURFACES = [
  "claude-code", "copilot", "cursor", "claude-desktop", "chatgpt", "chat-ui",
] as const;
export type GovernanceSurface = (typeof GOVERNANCE_SURFACES)[number];

/** Los tres ejes de alcance del enum cerrado de `governance_profiles.scope_type` (D2). */
export type GovernanceScopeType = "tenant_default" | "connection_mode" | "surface";

/** Una fila de decisión del tenant. **La ausencia de fila es "heredar"** (D2): el backend no
 *  fabrica filas implícitas ni completa el catálogo, así que la UI tampoco puede inventarlas
 *  — "heredado" se representa por la falta de fila, nunca por un `decision: "inherit"` que no
 *  existe en el dominio. */
export interface GovernanceProfileRow {
  scope_type: GovernanceScopeType;
  scope_value: string;
  layer_key: string;
  decision: GovernanceDecision;
  updated_by?: string;
  updated_at?: string;
}

/** Resultado de una mutación de decisión (PUT o DELETE).
 *
 *  **Es la verdad recalculada, no un eco del valor enviado** (contrato api-gobernanza, PUT
 *  garantía (d)): activar una capa cuyo guardrail no está cargado responde 200 con
 *  `estado_efectivo: no_disponible`. La UI setea su estado desde acá y NUNCA desde el valor
 *  optimista — si lo hiciera, volvería a pintar de verde un deseo, que es exactamente la
 *  mentira que la 027 elimina.
 *
 *  `row = null` es el resultado de un DELETE (volver a heredar) y también de un 204 sin
 *  cuerpo: no hay fila, y eso ES el estado, no un fallo. */
export interface GovernanceDecisionResult {
  row: GovernanceProfileRow | null;
  /** Colapso fail-closed de `porModo`: si la capa no se aplica en alguno de los modos del
   *  alcance, el escalar reporta ESE caso y nunca el optimista. */
  estado_efectivo: GovernanceEffectiveState | null;
  /** Copy del catálogo cerrado del backend. Para una relajación por superficie explica el
   *  alcance real ("aplica solo a Connections con esta herramienta declarada", D5 refinada):
   *  se muestra tal cual para que el admin no crea que apagó más de lo que apagó. */
  motivo: string;
  origen: GovernanceOrigin | null;
  /** Estado recomputado por modo de conexión. Un alcance transversal (la organización, una
   *  superficie) cruza los dos modos y puede resolver distinto en cada uno; mostrar solo el
   *  escalar escondería esa diferencia. */
  porModo: { mode: string; estado_efectivo: GovernanceEffectiveState; motivo: string }[];
  /** Honestidad sobre la propagación al motor: `confirmada` es lo que el producto puede
   *  AFIRMAR, no lo que le gustaría. Se muestra cuando no está confirmada — un cambio que
   *  todavía no se sabe si viajó no puede presentarse como aplicado en todos lados. */
  propagacion: { confirmada: boolean; motivo: string } | null;
}

/** Error de API que conserva el status HTTP. Sin esto la UI no puede distinguir
 *  "no tenés permiso" (403) de "no se pudo contactar al servidor" (fallo de red), y las
 *  dos terminan pintando una pantalla vacía que el usuario lee como un bug del producto
 *  — el patrón del `catch { // silent }` de SecurityPage que la 027 viene a corregir.
 *  `status = 0` significa que nunca hubo respuesta. */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    // Necesario porque el target de compilación puede degradar `extends Error` y romper
    // el instanceof; sin esto el llamador no puede ramificar por tipo.
    Object.setPrototypeOf(this, ApiError.prototype);
  }

  get isForbidden(): boolean { return this.status === 403; }
  get isNetwork(): boolean { return this.status === 0; }

  /** ¿Se puede AFIRMAR que el servidor no escribió? Solo los 4xx lo garantizan: son
   *  veredictos deliberados emitidos antes de tocar la base (403 de rol, 404 de recurso,
   *  422 del piso o del enum). Todo lo demás deja el resultado **indeterminado**:
   *  `status = 0` (el `fetch` rechazó — timeout, corte de red, la respuesta se perdió a
   *  mitad de camino) o un 5xx de un intermediario o del propio backend pueden ocurrir
   *  DESPUÉS de que la escritura commiteó.
   *
   *  Hallazgo (verificación adversarial US2, MEDIA): el autosave de gobernanza revertía el
   *  control en cualquier `catch`, así que un corte posterior al commit dejaba la pantalla
   *  mostrando "Apagada" mientras en la base había quedado "Encendida" — o al revés. En una
   *  superficie de gobernanza, creer que una capa está encendida cuando está apagada es el
   *  peor error posible; el llamador tiene que poder distinguir "lo rechazaron" de "no sé
   *  qué pasó" y actuar distinto en cada caso. */
  get isDeterminate(): boolean { return this.status >= 400 && this.status < 500; }
  get isIndeterminate(): boolean { return !this.isDeterminate; }
}

// Aplana el `detail` de un error de la API: string → tal cual; objeto estructurado
// (p.ej. el 503 de saturación {code, message}) → su `.message`; ausente → fallback.
// Sin esto, un `detail` objeto se interpola como `[object Object]` en el Error (#185).
function detailToMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && typeof (detail as any).message === "string") {
    return (detail as any).message;
  }
  return fallback;
}

function asLayers(value: any): GovernanceLayerStatus[] {
  // Solo entra lo que tiene identidad de capa: un envoltorio inesperado produce lista
  // vacía (y la UI lo dice), nunca objetos a medio formar renderizados como capas.
  //
  // El `tier` se NORMALIZA además de exigirse, y eso es una decisión de seguridad, no de
  // prolijidad: SecurityPage decide con él si el interruptor de una capa se puede tocar
  // (el piso no se apaga desde ahí). Una capa que llegara sin `tier` —o con uno fuera del
  // enum— caía a `undefined`, `undefined !== "floor"`, y el candado del piso se abría solo.
  // Ante la duda se asume `floor`: negar el apagado de una capa opcional es un incordio;
  // permitir el de una de piso rompe SC-004.
  return Array.isArray(value)
    ? value
        .filter((l) => l && typeof l.layer_key === "string")
        .map((l) => ({ ...l, tier: l.tier === "optional" ? "optional" : "floor" }))
    : [];
}

/** Normaliza la respuesta de `/governance/status`. El contrato fija el shape POR CAPA y
 *  sus invariantes; el envoltorio de agrupación queda "refinable en implementación"
 *  (api-gobernanza.md, encabezado), así que se aceptan las formas razonables del bloque
 *  por modo en vez de acoplar la UI a una sola. Si no viene agrupado, la página pide modo
 *  por modo: SC-002 no puede depender de un detalle de serialización. */
function normalizeGovernanceStatus(raw: any): GovernanceStatus {
  const porModo: Record<string, GovernanceLayerStatus[]> = {};
  const grouped = raw?.by_mode ?? raw?.por_modo ?? raw?.modes ?? raw?.modos;

  if (Array.isArray(grouped)) {
    for (const entry of grouped) {
      const mode = entry?.mode ?? entry?.modo ?? entry?.connection_mode;
      if (typeof mode === "string") porModo[mode] = asLayers(entry?.layers ?? entry?.capas);
    }
  } else if (grouped && typeof grouped === "object") {
    for (const [mode, entry] of Object.entries<any>(grouped)) {
      porModo[mode] = asLayers(Array.isArray(entry) ? entry : entry?.layers ?? entry?.capas);
    }
  }

  let layers = asLayers(Array.isArray(raw) ? raw : raw?.layers ?? raw?.capas);
  if (layers.length === 0) {
    // Un payload que solo trae la agrupación sigue siendo respondible: el detalle por capa
    // se lee del primer modo disponible en vez de mostrar la página vacía.
    const first = Object.values(porModo).find((l) => l.length > 0);
    if (first) layers = first;
  }
  return { layers, porModo };
}

const SCOPE_TYPES: readonly string[] = ["tenant_default", "connection_mode", "surface"];

function asProfileRow(value: any): GovernanceProfileRow | null {
  // Una fila solo cuenta si trae los cuatro campos de su clave natural con valores del
  // dominio. Un objeto a medio formar NO se renderiza como decisión: mostrar "apagada" por
  // un `decision` basura sería afirmar una postura que el tenant no tomó.
  if (!value || typeof value !== "object") return null;
  const { scope_type, scope_value, layer_key, decision } = value;
  if (typeof scope_value !== "string" || typeof layer_key !== "string") return null;
  if (!SCOPE_TYPES.includes(scope_type)) return null;
  if (decision !== "on" && decision !== "off") return null;
  return {
    scope_type, scope_value, layer_key, decision,
    updated_by: typeof value.updated_by === "string" ? value.updated_by : undefined,
    updated_at: typeof value.updated_at === "string" ? value.updated_at : undefined,
  };
}

/** El envoltorio de la lista es refinable en implementación (encabezado del contrato); la
 *  fila NO. Se aceptan las formas razonables y se descarta lo que no sea una decisión. */
function normalizeProfileRows(raw: any): GovernanceProfileRow[] {
  const lista = Array.isArray(raw)
    ? raw
    : raw?.rows ?? raw?.profile ?? raw?.decisions ?? raw?.items ?? raw?.filas ?? raw?.decisiones;
  if (!Array.isArray(lista)) return [];
  return lista.map(asProfileRow).filter((r): r is GovernanceProfileRow => r !== null);
}

const ESTADOS_EFECTIVOS: readonly string[] = [
  "aplicandose", "requiere_credencial", "delegada", "no_disponible", "degradada",
];

/** Normaliza la respuesta de una mutación. Fail-closed en el estado: un `estado_efectivo`
 *  ausente o fuera del enum cerrado queda `null` ("todavía no se sabe") y la UI NO pinta
 *  nada como aplicándose — jamás se asume verde por defecto (D4). */
function normalizeDecisionResult(raw: any): GovernanceDecisionResult {
  const anidado = raw?.row ?? raw?.profile ?? raw?.fila ?? raw?.decision_row;
  const row = asProfileRow(anidado) ?? asProfileRow(raw);

  const estadoRaw =
    raw?.estado_efectivo ??
    raw?.estado?.estado_efectivo ?? raw?.status?.estado_efectivo ?? raw?.layer?.estado_efectivo ??
    (typeof raw?.estado === "string" ? raw.estado : undefined);
  const origenRaw =
    raw?.origen ?? raw?.estado?.origen ?? raw?.status?.origen ?? raw?.layer?.origen;
  const motivoRaw =
    raw?.motivo ?? raw?.estado?.motivo ?? raw?.status?.motivo ?? raw?.layer?.motivo;

  const porModoRaw = raw?.por_modo ?? raw?.by_mode ?? raw?.modes ?? raw?.modos;
  const porModo = Array.isArray(porModoRaw)
    ? porModoRaw
        .filter((m) => m && typeof m.mode === "string" && ESTADOS_EFECTIVOS.includes(m.estado_efectivo))
        .map((m) => ({
          mode: m.mode as string,
          estado_efectivo: m.estado_efectivo as GovernanceEffectiveState,
          motivo: typeof m.motivo === "string" ? m.motivo : "",
        }))
    : [];

  const prop = raw?.propagacion ?? raw?.propagation;
  const propagacion =
    prop && typeof prop === "object"
      ? { confirmada: prop.confirmada === true, motivo: typeof prop.motivo === "string" ? prop.motivo : "" }
      : null;

  return {
    row,
    estado_efectivo: ESTADOS_EFECTIVOS.includes(estadoRaw)
      ? (estadoRaw as GovernanceEffectiveState)
      : null,
    motivo: typeof motivoRaw === "string" ? motivoRaw : "",
    origen: typeof origenRaw === "string" ? (origenRaw as GovernanceOrigin) : null,
    porModo,
    propagacion,
  };
}

/** El `detail` del backend ES el mensaje que la UI muestra en el rollback (contrato,
 *  invariante 6). FastAPI lo devuelve como string en los errores de negocio (422 del piso,
 *  403 de rol) y como lista de objetos en los de validación del modelo: aplanar la lista
 *  evita el "[object Object]" que deja al admin sin saber qué rechazó el producto. */
function detailMessage(err: any, fallback: string): string {
  const detail = err?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const partes = detail
      .map((d) => (typeof d === "string" ? d : typeof d?.msg === "string" ? d.msg : ""))
      .filter(Boolean);
    if (partes.length > 0) return partes.join(" · ");
  }
  return fallback;
}

/** Fetch del bloque Governance con el manejo de error que el contrato exige en TODAS sus
 *  funciones: sin respuesta ⇒ `ApiError(…, 0)` (fallo de red, distinguible del 403),
 *  `handleExpiredSession` SIEMPRE antes de evaluar `res.ok` —el olvido del bloque Security
 *  Policy deja al usuario con sesión vencida mirando un error genérico en vez de
 *  re-loguearse— y el `detail` del backend propagado con su status. */
async function governanceFetch(path: string, init: RequestInit, fallback: string): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/governance${path}`, init);
  } catch {
    throw new ApiError("No se pudo contactar al servidor de gobernanza.", 0);
  }
  handleExpiredSession(res);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new ApiError(detailMessage(err, fallback), res.status);
  }
  return res;
}

export interface AuditLog {
  id: string;
  timestamp: string;
  user_id?: string;
  api_key_id?: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  pii_detected: boolean;
  masked_entities?: Array<{ type: string; count: number }>;
  compliance_status: string;
  latency_ms: number;
  tokens_saved_by_optimization: number;
  /** Código de la capa que bloqueó (registry 027). Sólo viene en filas de bloqueo, y sólo
   *  si el endpoint de listado lo expone: la UI lo muestra si está y lo omite si no —
   *  nunca inventa la capa a partir del estado (spec 031, contrato §Fila de bloqueo). */
  blocked_by_layer?: string | null;
}

/** Bloque `audit` del health (spec 031, contrato §GET /health). Ausente en instalaciones
 *  anteriores a la 031 —y también para quien no sea admin/compliance_officer, porque los
 *  números viajan sólo al tier detallado—: por eso todo es opcional.
 *
 *  `lost_events: null` NO es cero: es "el contador no se pudo leer" (Redis caído o valor
 *  ilegible). El backend los distingue a propósito y la UI tiene que respetarlo — decir
 *  "cero pérdidas" sin haber podido mirar es la mentira que la 031 borra. */
export interface AuditHealth {
  mode?: "open" | "closed" | string;
  lost_events?: number | null;
  last_failure_at?: string | null;
}

/** Bloque `nlp` del health (issue #63). Ausente en instalaciones anteriores al fix y para
 *  quien no sea admin/compliance_officer: todo opcional.
 *
 *  Los tres `status` NO son intercambiables y la UI no puede colapsarlos:
 *  - `not_configured` — no hay motor NLP cableado. Modo de desarrollo por patrones: es una
 *    elección de despliegue, no una avería. Se informa, no se alarma.
 *  - `ok` — configurado y respondiendo.
 *  - `unreachable` — configurado y CAÍDO. Según `fail_mode_efectivo`, el tráfico se está
 *    rechazando (`block`) o sirviendo con cobertura reducida (`degrade`). Esto sí alarma. */
export interface NlpHealth {
  configured?: boolean;
  status?: "ok" | "unreachable" | "not_configured" | string;
  /** Instante de la PRIMERA request degradada de la racha actual (ISO), o null. */
  degraded_since?: string | null;
  /** Cuántas se sirvieron con patrones. `null` = no se pudo leer el contador, NO cero. */
  degraded_requests?: number | null;
  fail_mode_efectivo?: "block" | "degrade" | string | null;
}

export interface SystemHealth {
  status?: "healthy" | "degraded" | string;
  service?: string;
  version?: string;
  audit?: AuditHealth;
  nlp?: NlpHealth;
  /** Motivo de la degradación (auditoría no escribible con `audit_fail=closed`, y/o motor
   *  de detección NLP caído — pueden venir los dos concatenados con " | "). */
  reason?: string | null;
}

/** Piso de longitud que exige el backend (auth/passwords.py MIN_PASSWORD_LEN). Está
 *  duplicado a propósito: el cliente valida para poder decirlo en el campo, en español y
 *  antes del viaje, pero el que MANDA sigue siendo el servidor. Si allá sube, subir acá. */
export const MIN_PASSWORD_LEN = 12;

/** Devuelve el mensaje a mostrar si la contraseña no sirve, o `null` si pasa. */
export function validarPassword(raw: string | undefined | null): string | null {
  if (!raw) return "Escriba una contraseña para esta persona.";
  if (raw.length < MIN_PASSWORD_LEN) {
    return `La contraseña debe tener al menos ${MIN_PASSWORD_LEN} caracteres.`;
  }
  return null;
}

/** POST de contraseña con el trato de error que estas pantallas necesitan: el `detail` del
 *  backend ES el mensaje que se muestra (viene en español) y el status se conserva.
 *  `sesionVencidaEn401` distingue los dos significados que tiene un 401 acá: en el reseteo
 *  del administrador sólo puede ser la sesión vencida (hay que echar y recargar), pero en el
 *  cambio propio es "la contraseña actual no coincide" — cerrarle la sesión a alguien por un
 *  error de tipeo le haría perder el formulario y parecería un bug del producto. */
async function passwordFetch(
  path: string,
  body: unknown,
  fallback: string,
  sesionVencidaEn401: boolean
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError("No se pudo contactar al servidor.", 0);
  }
  if (sesionVencidaEn401) handleExpiredSession(res);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new ApiError(detailMessage(err, fallback), res.status);
  }
}

/** Ruta semántica del auto-router (spec 030, data-model §1). `target_ok` es COMPUTADO por
 *  el GET contra el catálogo real del motor: no vive en disco y no se manda en el PUT. */
export interface RouterRoute {
  name: string;
  description?: string;
  target_model: string;
  score_threshold: number;
  /** Etiqueta cosmética (premium/economy/local) — sólo badge en el panel. */
  tier?: string;
  utterances: string[];
  /** false = ruta rota: el modelo destino ya no está en el catálogo. */
  target_ok?: boolean;
}

/** Config caliente del auto-router. Los tres `*_ok`/`config_error` son computados del GET
 *  (contrato `router-config-api.md`): se muestran, nunca se persisten. */
export interface RouterConfig {
  enabled: boolean;
  default_model: string;
  timeout_seconds: number;
  embedding_model: string;
  routes: RouterRoute[];
  default_model_ok?: boolean;
  embedding_model_ok?: boolean;
  /** true = el fichero de disco falta o está corrupto y se están mostrando defaults. */
  config_error?: boolean;
}

/** Cuerpo del PUT: la config SIN los campos computados (contrato §PUT).
 *
 *  Se construye por lista blanca en vez de borrar claves del objeto del GET por dos
 *  motivos: los computados nunca se cuelan aunque el panel los arrastre, y los opcionales
 *  vacíos (`description`, `tier`) se OMITEN en lugar de viajar como cadena vacía o null —
 *  una clave presente con valor nulo rompe a los consumidores que hacen `.get(campo,
 *  default)` del lado backend. */
function routerConfigPayload(cfg: RouterConfig): Record<string, unknown> {
  return {
    enabled: !!cfg.enabled,
    default_model: cfg.default_model ?? "",
    timeout_seconds: cfg.timeout_seconds,
    embedding_model: cfg.embedding_model ?? "",
    routes: (cfg.routes || []).map((ruta) => {
      const salida: Record<string, unknown> = {
        name: ruta.name ?? "",
        target_model: ruta.target_model ?? "",
        score_threshold: ruta.score_threshold,
        utterances: ruta.utterances || [],
      };
      if (ruta.description) salida.description = ruta.description;
      if (ruta.tier) salida.tier = ruta.tier;
      return salida;
    }),
  };
}

export const api = {
  // --- Auth ---
  login: async (username: string, password: string): Promise<{ access_token: string; user: any }> => {
    const res = await fetch(`${API_BASE}/users/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(detailToMessage(e.detail, "Credenciales incorrectas.")); }
    return res.json();
  },

  // --- SSO (spec 017 US2, contrato specs/017-auth-rbac-sso/contracts/proveedor-sso.md) ---

  /** ¿Mostrar «Entrar con Microsoft»? Fail-closed por contrato (FR-010): 200 con
   *  `enabled:true` es el ÚNICO caso que muestra el botón. Un 403 (licencia sin SSO), un
   *  200 con `enabled:false` (tenant sin configurar), cualquier otro status, o un fallo de
   *  red colapsan al mismo resultado — "no mostrar". Nunca lanza: el llamador (LoginPage)
   *  no puede tener un `catch` que bloquee el formulario local por esto. */
  getSsoAvailable: async (): Promise<{ enabled: boolean; provider_type: string | null }> => {
    try {
      const res = await fetch(`${API_BASE}/auth/sso/available`);
      if (!res.ok) return { enabled: false, provider_type: null };
      const data = await res.json().catch(() => ({}));
      return {
        enabled: data?.enabled === true,
        provider_type: typeof data?.provider_type === "string" ? data.provider_type : null,
      };
    } catch {
      return { enabled: false, provider_type: null };
    }
  },

  /** Arranca el flujo SSO con una navegación REAL del navegador, no un `fetch`: el backend
   *  responde 302 al IdP y deja una cookie de state en el mismo origen — un `fetch` seguiría
   *  ese redirect por XHR y moriría en CORS contra Microsoft (contrato, paso 2). */
  startSsoLogin: (): void => {
    window.location.assign(`${API_BASE}/auth/sso/login`);
  },

  /** Callback del IdP: cambia `code`+`state` por la sesión. Mismo cuerpo que
   *  `POST /users/login` (contrato): `{access_token, token_type, user}`. El `detail` de los
   *  4xx (400 state inválido/ausente, 401 identidad no verificada, 403 usuario dado de baja)
   *  se propaga tal cual — es el texto que la pantalla de retorno muestra. */
  exchangeSsoCallback: async (code: string, state: string): Promise<{ access_token: string; token_type: string; user: any }> => {
    let res: Response;
    try {
      const qs = new URLSearchParams({ code, state });
      res = await fetch(`${API_BASE}/auth/sso/callback?${qs.toString()}`);
    } catch {
      throw new ApiError("No se pudo contactar al servidor.", 0);
    }
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new ApiError(
        detailToMessage(err.detail, "No se pudo completar el inicio de sesión con Microsoft."),
        res.status
      );
    }
    return res.json();
  },

  // --- Users & Groups ---
  // `includeService` (spec 043 US4, T045 del lado backend): por default el backend excluye
  // las cuentas de servicio de la lista (dejaban de aparecer entre las personas reales);
  // pedirlas explícitamente las trae con su `purpose`, para la sección plegada de
  // "Cuentas de servicio" (T042), nunca en la tabla principal.
  getUsers: async ({ includeService = false }: { includeService?: boolean } = {}): Promise<User[]> => {
    const qs = includeService ? "?include_service=true" : "";
    const res = await fetch(`${API_BASE}/users${qs}`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch users");
    return res.json();
  },

  /** La contraseña es obligatoria y NO tiene valor por defecto. El relleno anterior
   *  ("defaultpass123") le daba a cada persona registrada la misma credencial conocida, así
   *  que un alta silenciosa era una cuenta abierta: si falta, esto revienta acá y no manda
   *  nada. */
  createUser: async (user: Omit<User, "id" | "created_at" | "updated_at"> & { password: string }): Promise<User> => {
    const invalida = validarPassword(user.password);
    if (invalida) throw new ApiError(invalida, 422);
    const res = await fetch(`${API_BASE}/users`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(user),
    });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new ApiError(detailMessage(e, "No se pudo registrar al usuario."), res.status);
    }
    return res.json();
  },

  /** Cambio de la propia contraseña. Su 401 es "la contraseña actual no coincide", así que
   *  NO se trata como sesión vencida. */
  changeOwnPassword: async (currentPassword: string, newPassword: string): Promise<void> => {
    const invalida = validarPassword(newPassword);
    if (invalida) throw new ApiError(invalida, 422);
    await passwordFetch(
      "/users/me/password",
      { current_password: currentPassword, new_password: newPassword },
      "La contraseña actual no es correcta.",
      false
    );
  },

  /** Reseteo del administrador sobre otra persona: no pide la contraseña actual, porque el
   *  administrador no la conoce (ni debería). */
  resetUserPassword: async (userId: string, newPassword: string): Promise<void> => {
    const invalida = validarPassword(newPassword);
    if (invalida) throw new ApiError(invalida, 422);
    await passwordFetch(
      `/users/${userId}/password`,
      { new_password: newPassword },
      "No se pudo cambiar la contraseña.",
      true
    );
  },

  updateUser: async (userId: string, current: User, patch: { group_id?: string | null; role?: string; compliance_project_id?: string | null }): Promise<User> => {
    const body = { username: current.username, email: current.email, role: current.role, is_active: current.is_active, ...patch };
    const res = await fetch(`${API_BASE}/users/${userId}`, {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error("Failed to update user");
    return res.json();
  },

  /** Actualización parcial (spec 043 US5, T052) — solo manda los campos tocados, a
   *  diferencia de `updateUser` (que siempre reenvía `username`/`email`/`role`/`is_active`
   *  completos vía `PUT`). Usar esta para ediciones puntuales (solo rol, solo email). */
  patchUser: async (userId: string, patch: UserPatch): Promise<User> => {
    const res = await fetch(`${API_BASE}/users/${userId}`, {
      method: "PATCH",
      headers: jsonHeaders(),
      body: JSON.stringify(patch),
    });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new ApiError(detailMessage(e, "No se pudo actualizar el usuario."), res.status);
    }
    return res.json();
  },

  /** Baja definitiva (spec 043 US5, T053-T055): no borra físicamente — desactiva, revoca
   *  llaves y libera sus espacios propios a "sin asignar". El backend impide auto-baja y
   *  baja del último admin activo del tenant (409 en ambos casos); la UI (T041) MUST
   *  repetir esas dos validaciones localmente antes de llamar, para no depender solo del
   *  mensaje del backend. */
  deleteUser: async (userId: string): Promise<{ status: string; id: string; workspaces_unassigned: number }> => {
    const res = await fetch(`${API_BASE}/users/${userId}`, {
      method: "DELETE",
      headers: jsonHeaders(),
    });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new ApiError(detailMessage(e, "No se pudo dar de baja al usuario."), res.status);
    }
    return res.json();
  },

  /** Espacios de Eleia Hub heredados de una migración, sin dueño (spec 043 US1/US4,
   *  contrato 1) — solo admins; el backend exige el rol server-side, esto no depende de
   *  qué rol crea que tiene el que llama. */
  getUnassignedWorkspaces: async (): Promise<WorkspaceUnassigned[]> => {
    const res = await fetch(`${API_BASE}/workspaces?status_filter=unassigned`, { headers: authHeaders() });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new ApiError(detailMessage(e, "No se pudieron consultar los espacios sin asignar."), res.status);
    }
    const data = await res.json();
    return data.workspaces ?? data;
  },

  /** Asigna el primer miembro (dueño) a un espacio "sin asignar" (spec 043 US1, T044/T018
   *  de la 044) — mismo endpoint de miembros que un espacio ya asignado; el backend lo
   *  permite para un admin aunque no sea miembro (`add_member(..., is_admin=...)`). */
  assignWorkspaceMember: async (workspaceId: string, username: string): Promise<{ user_id: string; role: string }> => {
    const res = await fetch(`${API_BASE}/workspaces/${workspaceId}/members`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ username }),
    });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new ApiError(detailMessage(e, "No se pudo asignar el espacio."), res.status);
    }
    return res.json();
  },

  getGroups: async (): Promise<Group[]> => {
    const res = await fetch(`${API_BASE}/users/groups`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch groups");
    return res.json();
  },

  createGroup: async (group: Omit<Group, "id" | "created_at">): Promise<Group> => {
    const res = await fetch(`${API_BASE}/users/groups`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(group),
    });
    if (!res.ok) throw new Error("Failed to create group");
    return res.json();
  },

  // --- Budgets ---
  getBudgets: async (): Promise<Budget[]> => {
    const res = await fetch(`${API_BASE}/budgets`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch budgets");
    return res.json();
  },

  createBudget: async (budget: Omit<Budget, "id" | "current_spend_usd" | "current_tokens" | "last_reset_at" | "created_at" | "updated_at">): Promise<Budget> => {
    const res = await fetch(`${API_BASE}/budgets`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(budget),
    });
    if (!res.ok) throw new Error("Failed to create budget");
    return res.json();
  },

  updateBudget: async (budgetId: string, patch: { max_spend_usd?: number; max_tokens?: number; reset_period?: string; user_id?: string; group_id?: string }): Promise<Budget> => {
    const res = await fetch(`${API_BASE}/budgets/${budgetId}`, {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error("Failed to update budget");
    return res.json();
  },

  deleteBudget: async (budgetId: string): Promise<void> => {
    const res = await fetch(`${API_BASE}/budgets/${budgetId}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error("Failed to delete budget");
  },

  // --- Security Policy ---
  getSecurityPolicy: async (): Promise<SecurityPolicy> => {
    const res = await fetch(`${API_BASE}/security/policy`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch security policy");
    return res.json();
  },

  updateSecurityPolicy: async (policy: SecurityPolicy): Promise<SecurityPolicy> => {
    const res = await fetch(`${API_BASE}/security/policy`, {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify(policy),
    });
    if (!res.ok) throw new Error("Failed to update security policy");
    return res.json();
  },

  getPolicies: async (): Promise<SecurityPolicy[]> => {
    const res = await fetch(`${API_BASE}/security/policies`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch policies");
    return res.json();
  },

  createPolicy: async (policy: Omit<SecurityPolicy, "id" | "created_at" | "updated_at">): Promise<SecurityPolicy> => {
    const res = await fetch(`${API_BASE}/security/policies`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(policy),
    });
    if (!res.ok) throw new Error("Failed to create policy");
    return res.json();
  },

  updatePolicyById: async (id: string, policy: SecurityPolicy): Promise<SecurityPolicy> => {
    const res = await fetch(`${API_BASE}/security/policies/${id}`, {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify(policy),
    });
    if (!res.ok) throw new Error("Failed to update policy");
    return res.json();
  },

  deletePolicy: async (id: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/security/policies/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error("Failed to delete policy");
    return res.json();
  },

  // --- Audit Logs ---
  getAuditLogs: async (params?: {
    limit?: number;
    offset?: number;
    pii_detected?: string;
    /** Estado exacto (igualdad). Sirve para un motivo concreto: `blocked_prohibited`. */
    compliance_status?: string;
    /** Familia de estados (spec 031, FR-006). Hoy: `bloqueados` → LIKE 'blocked%' en el
     *  backend. Es un filtro APARTE de `compliance_status` a propósito: «bloqueado» no es
     *  un valor de la columna sino un conjunto de motivos (blocked_prohibited,
     *  blocked_secret, blocked_guardian, blocked_residency, ...), y el officer filtra por
     *  el conjunto. Los dos no se mandan juntos (la UI manda uno u otro). */
    estado?: string;
    from_date?: string;
    to_date?: string;
  }): Promise<{ total: number; logs: AuditLog[] }> => {
    const qs = new URLSearchParams();
    if (params?.limit != null) qs.append("limit", String(params.limit));
    if (params?.offset != null) qs.append("offset", String(params.offset));
    if (params?.pii_detected) qs.append("pii_detected", params.pii_detected);
    if (params?.compliance_status) qs.append("compliance_status", params.compliance_status);
    if (params?.estado) qs.append("estado", params.estado);
    if (params?.from_date) qs.append("from_date", params.from_date);
    if (params?.to_date) qs.append("to_date", params.to_date);
    const query = qs.toString();
    const res = await fetch(`${API_BASE}/audit-logs${query ? `?${query}` : ""}`, { headers: authHeaders() });
    handleExpiredSession(res);
    if (!res.ok) throw new Error("Failed to fetch audit logs");
    return res.json();
  },

  // --- Chat / Playground ---
  sendChatMessage: async (
    message: string, 
    model: string, 
    virtualKey?: string,
    overrides?: {
      override_pii_masking?: boolean;
      override_gdpr_mode?: boolean;
      override_ai_act_mode?: boolean;
      override_headroom_mode?: boolean;
    }
  ): Promise<any> => {
    const headers: Record<string, string> = { "Content-Type": "application/json", ...authHeaders() };
    if (virtualKey) {
      headers["Authorization"] = `Bearer ${virtualKey}`;
    }
    const res = await fetch(`${API_BASE}/chat/completions`, {
      method: "POST",
      headers,
      body: JSON.stringify({ message, model, ...overrides }),
    });
    handleExpiredSession(res);
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(detailToMessage(errData.detail, "Failed to send chat message"));
    }
    return res.json();
  },

  getModels: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/chat/models`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch models");
    return res.json();
  },

  createModel: async (model: { model_name: string; provider: string; model_id: string; api_key?: string; api_base?: string }): Promise<any> => {
    const res = await fetch(`${API_BASE}/chat/models`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(model),
    });
    if (!res.ok) throw new Error("Failed to create model");
    return res.json();
  },

  deleteModel: async (modelName: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/chat/models/${modelName}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error("Failed to delete model");
    return res.json();
  },

  // Spec 043/044 (US5, contrato 6, T051): el backend ahora acepta `engine_params` como
  // nombre primario (con `litellm_params` mantenido como alias `deprecated` durante la
  // migración — nunca expone "litellm" en la respuesta). El cliente ya manda el nuevo.
  updateModelCredential: async (modelName: string, engineParams: Record<string, string>): Promise<void> => {
    const res = await fetch(`${API_BASE}/chat/models/${modelName}`, {
      method: "PATCH",
      headers: jsonHeaders(),
      body: JSON.stringify({ engine_params: engineParams }),
    });
    if (!res.ok) throw new Error("Failed to update model credential");
  },

  getFallbacks: async (): Promise<Record<string, string>> => {
    const res = await fetch(`${API_BASE}/chat/fallbacks`, { headers: authHeaders() });
    if (!res.ok) return {};
    return res.json();
  },

  setFallback: async (modelName: string, fallbackModel: string | null): Promise<void> => {
    await fetch(`${API_BASE}/chat/fallbacks/${modelName}`, {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify({ fallback_model: fallbackModel }),
    });
  },

  getModelsPricing: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/chat/models/pricing`, { headers: authHeaders() });
    if (!res.ok) return [];
    return res.json();
  },

  // --- Motor IA: estado del supervisor + botón "Aplicar cambios" (spec 033) ---

  /** Gate del backend: `admin` + `compliance_officer` (NO `developer`, aunque el nav de
   *  `models` sea admin+developer — mismatch abierto en #245). Un rol sin permiso da 403 acá
   *  y la página tiene que mostrarlo tal cual, no romperse: por eso se propaga con `ApiError`
   *  como el resto del panel, en vez de devolver un estado sintético. */
  getEngineApplyStatus: async (): Promise<EngineApplyStatus> => {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/chat/models/status`, { headers: authHeaders() });
    } catch {
      throw new ApiError("No se pudo contactar al servidor.", 0);
    }
    handleExpiredSession(res);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new ApiError(
        detailMessage(err, "No se pudo consultar el estado del motor IA."),
        res.status
      );
    }
    return res.json();
  },

  /** Dispara un ciclo nuevo de aplicación (gate: sólo `admin`). El resultado no viaja en la
   *  respuesta — se consulta con `getEngineApplyStatus`, por eso el llamador arranca el
   *  polling apenas esto resuelve. */
  applyEngineChanges: async (reason?: string): Promise<{ status: string; ts: number }> => {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/chat/models/apply`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify(reason?.trim() ? { reason: reason.trim() } : {}),
      });
    } catch {
      throw new ApiError("No se pudo contactar al servidor.", 0);
    }
    handleExpiredSession(res);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new ApiError(
        detailMessage(err, "No se pudo disparar la aplicación de cambios del motor IA."),
        res.status
      );
    }
    return res.json();
  },

  // --- Auto-router semántico (spec 030) ---

  /** Config del ruteo + los computados del catálogo. El backend garantiza 200 aunque el
   *  fichero de disco falte o esté corrupto (`config_error: true`), así que un error acá
   *  es sesión/rol/red — no una config rota. */
  getRouterConfig: async (): Promise<RouterConfig> => {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/chat/router-config`, { headers: authHeaders() });
    } catch {
      throw new ApiError("No se pudo contactar al servidor.", 0);
    }
    handleExpiredSession(res);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new ApiError(
        detailMessage(err, "No se pudo cargar la configuración del ruteo inteligente."),
        res.status
      );
    }
    return res.json();
  },

  /** Guarda la config completa y devuelve la RELEÍDA de disco (con computados frescos).
   *  El 422 del backend trae la lista de errores de validación por campo: se propaga tal
   *  cual porque es el texto que el panel muestra. */
  putRouterConfig: async (cfg: RouterConfig): Promise<RouterConfig> => {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/chat/router-config`, {
        method: "PUT",
        headers: jsonHeaders(),
        body: JSON.stringify(routerConfigPayload(cfg)),
      });
    } catch {
      throw new ApiError("No se pudo contactar al servidor.", 0);
    }
    handleExpiredSession(res);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new ApiError(
        detailMessage(err, "No se pudo guardar la configuración del ruteo inteligente."),
        res.status
      );
    }
    return res.json();
  },

  /** Redacta frases de ejemplo para una ruta con el modelo local, a partir de su nombre y
   *  descripción (US2: «ruteo automático» significa que el admin NO carga frases a mano).
   *
   *  Manda las frases actuales en `existing` para que el backend no repita lo que ya hay; el
   *  merge sin duplicados lo hace igual el panel, porque el modelo puede devolver variantes.
   *  El `detail` del backend se propaga tal cual (p.ej. «no hay modelo local disponible»):
   *  es el texto que el panel muestra, y una causa inventada acá mandaría al admin a buscar
   *  el problema donde no está. */
  generateUtterances: async (
    name: string,
    description: string,
    existing: string[] = []
  ): Promise<string[]> => {
    let res: Response;
    try {
      res = await fetch(`${API_BASE}/chat/router-config/generate-utterances`, {
        method: "POST",
        headers: jsonHeaders(),
        body: JSON.stringify({ name, description, existing }),
      });
    } catch {
      throw new ApiError("No se pudo contactar al servidor.", 0);
    }
    handleExpiredSession(res);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new ApiError(
        detailMessage(err, "No se pudieron generar frases de ejemplo."),
        res.status
      );
    }
    const datos = await res.json().catch(() => ({}));
    return Array.isArray(datos?.utterances)
      ? datos.utterances
          .filter((u: any) => typeof u === "string" && u.trim())
          .map((u: string) => u.trim())
      : [];
  },

  // --- Virtual Keys ---
  getKeys: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/keys`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch keys");
    return res.json();
  },

  createKey: async (key: {
    name: string;
    user_id?: string;
    group_id?: string;
    max_budget?: number;
    budget_duration?: string;
    models?: string[];
    expires_at?: string;
    rpm_limit?: number;
    tpm_limit?: number;
    compliance_project_id?: string;
  }): Promise<any> => {
    const res = await fetch(`${API_BASE}/keys`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(key),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      // ApiError (no Error pelado) para que quien llame pueda ramificar por status:
      // el 402 de seats agotados necesita otro texto que un 503 del motor.
      throw new ApiError(detailMessage(err, "No se pudo generar la llave virtual."), res.status);
    }
    return res.json();
  },

  deleteKey: async (id: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/keys/${id}`, { method: "DELETE", headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to revoke key");
    return res.json();
  },

  getKeySpend: async (keyId: string): Promise<SpendInfo> => {
    const res = await fetch(`${API_BASE}/keys/${keyId}/spend`, { headers: authHeaders() });
    if (!res.ok) return { spend_usd: null, max_budget: null, remaining: null };
    return res.json();
  },

  getGroupSpend: async (groupId: string): Promise<SpendInfo> => {
    const res = await fetch(`${API_BASE}/users/groups/${groupId}/spend`, { headers: authHeaders() });
    if (!res.ok) return { spend_usd: null, max_budget: null, remaining: null };
    return res.json();
  },

  getUserSpend: async (userId: string): Promise<SpendInfo> => {
    const res = await fetch(`${API_BASE}/users/${userId}/spend`, { headers: authHeaders() });
    if (!res.ok) return { spend_usd: null, max_budget: null, remaining: null };
    return res.json();
  },

  // --- Security Guardians ---
  getGuardians: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/guardians`, { headers: authHeaders() });
    handleExpiredSession(res);
    if (!res.ok) throw new Error("Failed to fetch guardians");
    return res.json();
  },

  updateGuardian: async (id: string, guardian: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/guardians/${id}`, {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify(guardian),
    });
    if (!res.ok) {
      // El `detail` del backend ES el mensaje para el admin (mismo patrón que testGuardian):
      // el 409 de FR-007 explica que el guardián es del catálogo incoming, y tragarlo detrás
      // de un "Failed to update guardian" dejaba el rechazo honesto sin destinatario.
      const err = await res.json().catch(() => ({}));
      throw new Error(detailToMessage(err.detail, "No se pudo guardar el guardián."));
    }
    return res.json();
  },

  testGuardian: async (id: string, text: string): Promise<{ blocked: boolean; reason: string | null }> => {
    const res = await fetch(`${API_BASE}/guardians/${id}/test`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(detailToMessage(err.detail, "Error al ejecutar el test del guardián."));
    }
    return res.json();
  },

  // --- Governance ---
  // Router admin-only (`require_role("admin")` en el APIRouter): un rol insuficiente
  // recibe 403 y la UI lo dice con todas las letras. `handleExpiredSession(res)` va en
  // TODAS las funciones del bloque — el olvido del bloque Security Policy (arriba) deja
  // al usuario con sesión vencida mirando un error genérico en vez de re-loguearse.
  getGovernanceStatus: async (params?: { mode?: string; surface?: string }): Promise<GovernanceStatus> => {
    const qs = new URLSearchParams();
    if (params?.mode) qs.append("mode", params.mode);
    if (params?.surface) qs.append("surface", params.surface);
    const query = qs.toString();

    let res: Response;
    try {
      res = await fetch(`${API_BASE}/governance/status${query ? `?${query}` : ""}`, {
        headers: authHeaders(),
      });
    } catch {
      // Sin respuesta no hay status: se marca como fallo de red (0) para que la página
      // no lo confunda con "no tenés permiso".
      throw new ApiError("No se pudo contactar al servidor de gobernanza.", 0);
    }
    handleExpiredSession(res);
    if (!res.ok) {
      // El `detail` del backend es el mensaje que la UI muestra (patrón de testGuardian):
      // el catálogo cerrado de motivos vive allá, no acá.
      const err = await res.json().catch(() => ({}));
      throw new ApiError(detailToMessage(err.detail, "No se pudo obtener el estado de gobernanza."), res.status);
    }
    return normalizeGovernanceStatus(await res.json());
  },

  /** Las decisiones EXPLÍCITAS del tenant. Lo que no está en esta lista se hereda: el
   *  endpoint no fabrica filas implícitas (D2), así que la UI distingue "decidido acá" de
   *  "heredado" por presencia/ausencia, sin un tercer valor inventado. */
  getGovernanceProfile: async (): Promise<GovernanceProfileRow[]> => {
    const res = await governanceFetch(
      "/profile",
      { headers: authHeaders() },
      "No se pudo obtener la configuración de gobernanza."
    );
    return normalizeProfileRows(await res.json());
  },

  /** Upsert de UNA decisión por su clave natural (scope_type, scope_value, layer_key).
   *
   *  Devuelve la fila persistida **y el estado recalculado**: el llamador debe setear su
   *  estado desde acá, nunca desde el valor que envió (contrato PUT (d), D7). Un
   *  `layer_key` del piso responde 422 con su `detail` — el rechazo se muestra como lo que
   *  es, y del lado del backend queda registrado el intento (FR-003/SC-004). */
  putGovernanceDecision: async (input: {
    scope_type: GovernanceScopeType;
    scope_value: string;
    layer_key: string;
    decision: GovernanceDecision;
  }): Promise<GovernanceDecisionResult> => {
    const res = await governanceFetch(
      "/profile",
      { method: "PUT", headers: jsonHeaders(), body: JSON.stringify(input) },
      "No se pudo guardar la decisión de gobernanza."
    );
    return normalizeDecisionResult(await res.json().catch(() => ({})));
  },

  /** Volver a HEREDAR: borra la fila de decisión. Idempotente por contrato (una fila
   *  inexistente responde 204 igual: "heredar" ya es el estado resultante), así que un
   *  doble click no es un error que mostrarle a nadie. Un 204 sin cuerpo devuelve
   *  `row: null` y `estado_efectivo: null` — la página refresca el estado real desde el
   *  servidor en vez de suponerlo. */
  deleteGovernanceDecision: async (
    scope_type: GovernanceScopeType,
    scope_value: string,
    layer_key: string
  ): Promise<GovernanceDecisionResult> => {
    const path =
      `/profile/${encodeURIComponent(scope_type)}` +
      `/${encodeURIComponent(scope_value)}/${encodeURIComponent(layer_key)}`;
    const res = await governanceFetch(
      path,
      { method: "DELETE", headers: authHeaders() },
      "No se pudo volver a heredar esta capa."
    );
    if (res.status === 204) {
      return { row: null, estado_efectivo: null, motivo: "", origen: null, porModo: [], propagacion: null };
    }
    return normalizeDecisionResult(await res.json().catch(() => ({})));
  },

  // --- Analytics ---
  getAnalyticsSummary: async (range: "day" | "week" | "month"): Promise<any> => {
    const res = await fetch(`${API_BASE}/analytics/summary?range=${range}`, { headers: authHeaders() });
    handleExpiredSession(res);
    if (!res.ok) throw new Error("Failed to fetch analytics summary");
    return res.json();
  },

  getEngineStatus: async (): Promise<{ status: "online" | "offline"; checked_at: string }> => {
    const res = await fetch(`${API_BASE}/analytics/engine-status`, { headers: authHeaders() });
    handleExpiredSession(res);
    if (!res.ok) return { status: "offline", checked_at: new Date().toISOString() };
    return res.json();
  },

  /** Health de PRODUCTO (`GET /api/v1/health`, spec 031 §health). No confundir con el
   *  `/health` de la raíz: ése es el probe barato del contenedor (healthcheck de compose)
   *  y no lleva el bloque `audit`.
   *
   *  Va con credenciales porque el bloque `audit` (contador de pérdidas y hora del último
   *  fallo) sólo viaja a admin/compliance_officer — los mismos roles que pueden entrar a
   *  Logs de Auditoría. Sin sesión, la respuesta llega sin `audit` y el aviso no aparece.
   *
   *  Devuelve `null` ante CUALQUIER problema (red, 5xx, cuerpo que no es JSON). Es
   *  deliberado: alimenta un aviso secundario de la página y un aviso que no se puede
   *  leer nunca debe tumbar la pantalla de Logs. `null` = "no sé", y "no sé" se pinta como
   *  nada, jamás como "todo bien". */
  getSystemHealth: async (): Promise<SystemHealth | null> => {
    try {
      const res = await fetch(`${API_BASE}/health`, {
        headers: { Accept: "application/json", ...authHeaders() },
      });
      if (!res.ok) return null;
      if (!(res.headers.get("Content-Type") || "").includes("application/json")) return null;
      return (await res.json()) as SystemHealth;
    } catch {
      return null;
    }
  },

  exportAuditLogs: async (filters: {
    pii_detected?: boolean;
    compliance_status?: string;
    /** Mismo filtro de familia que el listado: el CSV exportado tiene que ser LO QUE SE VE
     *  en pantalla. Si el backend no conociera el parámetro, FastAPI lo ignora y el CSV
     *  saldría más ancho que la tabla — por eso el backend lo cablea en `_build_query`,
     *  que es el helper compartido por listado y export. */
    estado?: string;
    from_date?: string;
    to_date?: string;
  }): Promise<void> => {
    const params = new URLSearchParams();
    if (filters.pii_detected !== undefined) params.append("pii_detected", String(filters.pii_detected));
    if (filters.compliance_status) params.append("compliance_status", filters.compliance_status);
    if (filters.estado) params.append("estado", filters.estado);
    if (filters.from_date) params.append("from_date", filters.from_date);
    if (filters.to_date) params.append("to_date", filters.to_date);

    const res = await fetch(`${API_BASE}/audit-logs/export?${params.toString()}`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to export audit logs");

    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="(.+?)"/);
    const filename = match ? match[1] : "audit_export.csv";

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  // --- Compliance ---
  getComplianceProjects: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/compliance/projects`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch compliance projects");
    return res.json();
  },

  createComplianceProject: async (project: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/projects`, {
      method: "POST", headers: jsonHeaders(), body: JSON.stringify(project),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(detailToMessage(e.detail, "Error al crear proyecto")); }
    return res.json();
  },

  updateComplianceProject: async (id: string, project: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/projects/${id}`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify(project),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(detailToMessage(e.detail, "Error al actualizar proyecto")); }
    return res.json();
  },

  deleteComplianceProject: async (id: string): Promise<void> => {
    await fetch(`${API_BASE}/compliance/projects/${id}`, { method: "DELETE", headers: authHeaders() });
  },

  getDPAs: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/compliance/dpas`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch DPAs");
    return res.json();
  },

  createDPA: async (dpa: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/dpas`, {
      method: "POST", headers: jsonHeaders(), body: JSON.stringify(dpa),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(detailToMessage(e.detail, "Error al registrar DPA")); }
    return res.json();
  },

  updateDPA: async (id: string, dpa: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/dpas/${id}`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify(dpa),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(detailToMessage(e.detail, "Error al actualizar DPA")); }
    return res.json();
  },

  deleteDPA: async (id: string): Promise<void> => {
    await fetch(`${API_BASE}/compliance/dpas/${id}`, { method: "DELETE", headers: authHeaders() });
  },

  getDSRs: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/compliance/dsr`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch DSRs");
    return res.json();
  },

  createDSR: async (dsr: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/dsr`, {
      method: "POST", headers: jsonHeaders(), body: JSON.stringify(dsr),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(detailToMessage(e.detail, "Error al crear solicitud")); }
    return res.json();
  },

  updateDSR: async (id: string, update: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/dsr/${id}`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify(update),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(detailToMessage(e.detail, "Error al actualizar solicitud")); }
    return res.json();
  },

  searchDSR: async (subjectId: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/dsr/search?subject_id=${encodeURIComponent(subjectId)}`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to search DSR");
    return res.json();
  },

  getRetentionPolicies: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/compliance/retention`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch retention policies");
    return res.json();
  },

  updateRetentionPolicies: async (policies: any[]): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/compliance/retention`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify(policies),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(detailToMessage(e.detail, "Error al guardar retención")); }
    return res.json();
  },

  getComplianceDashboard: async (): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/dashboard`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch compliance dashboard");
    return res.json();
  },

  // --- Groups compliance ---
  getGroupsCompliance: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/groups`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch groups");
    return res.json();
  },

  updateGroupCompliance: async (groupId: string, data: { default_legal_basis?: string; default_risk_level?: string; compliance_project_id?: string | null }): Promise<any> => {
    const res = await fetch(`${API_BASE}/groups/${groupId}/compliance`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify(data),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(detailToMessage(e.detail, "Error al actualizar perfil de compliance")); }
    return res.json();
  },

  assignUserGroup: async (userId: string, groupId: string | null): Promise<any> => {
    const res = await fetch(`${API_BASE}/groups/users/${userId}/group`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify({ group_id: groupId }),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(detailToMessage(e.detail, "Error al asignar grupo")); }
    return res.json();
  },

  // --- Consent ---
  getUserConsents: async (userId: string): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/compliance/consent/${userId}`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch consents");
    return res.json();
  },

  recordConsent: async (data: { user_id: string; consent_type: string; version?: string; notes?: string }): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/consent`, {
      method: "POST", headers: jsonHeaders(), body: JSON.stringify(data),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(detailToMessage(e.detail, "Error al registrar consentimiento")); }
    return res.json();
  },

  revokeConsent: async (consentId: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/consent/${consentId}`, { method: "DELETE", headers: authHeaders() });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(detailToMessage(e.detail, "Error al revocar consentimiento")); }
    return res.json();
  },

  getAllConsents: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/compliance/consent`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch consents");
    return res.json();
  },

  // --- Reports (GDPR Art. 30 / Audit Export) ---
  exportRAT: async (): Promise<void> => {
    const res = await fetch(`${API_BASE}/reports/rat`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Error al exportar el RAT");
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="(.+?)"/);
    const filename = match ? match[1] : "RAT_Art30_GDPR.csv";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  exportDSAR: async (subjectIdentifier: string): Promise<void> => {
    const res = await fetch(`${API_BASE}/reports/dsar/${encodeURIComponent(subjectIdentifier)}`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Error al exportar el DSAR");
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="(.+?)"/);
    const filename = match ? match[1] : "DSAR_export.csv";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  exportHumanReviewLog: async (): Promise<void> => {
    const res = await fetch(`${API_BASE}/reports/human-review-log`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Error al exportar revisiones");
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="(.+?)"/);
    const filename = match ? match[1] : "Revisiones_Humanas.csv";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  getExecutiveSummary: async (): Promise<any> => {
    const res = await fetch(`${API_BASE}/reports/executive`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch executive summary");
    return res.json();
  },

  // --- Human Review Queue ---
  getPendingReviews: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/compliance/review/pending`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch pending reviews");
    return res.json();
  },

  submitReview: async (token: string, data: { reviewer_id?: string; action: string; notes?: string }): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/review/${token}`, {
      method: "POST", headers: jsonHeaders(), body: JSON.stringify(data),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(detailToMessage(e.detail, "Error al procesar la revisión")); }
    return res.json();
  },

  // --- Costs (Ahorro de Costes IA) ---
  getCostsSummary: async (range: "day" | "week" | "month"): Promise<CostSummary> => {
    const res = await fetch(`${API_BASE}/costs/summary?range=${range}`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch costs summary");
    return res.json();
  },

  calculateCompression: async (req: {
    prompt: string;
    model?: string | null;
    threshold?: number | null;
    aggressiveness?: string;
    strategy?: string;
  }): Promise<CompressionAnalysis> => {
    const res = await fetch(`${API_BASE}/costs/calculator`, {
      method: "POST", headers: jsonHeaders(), body: JSON.stringify(req),
    });
    if (!res.ok) throw new Error("Failed to run compression calculator");
    return res.json();
  },

  // --- Costs config (US4) ---
  getCostConfig: async (): Promise<CostConfig> => {
    const res = await fetch(`${API_BASE}/costs/config`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch cost config");
    return res.json();
  },

  updateCostConfig: async (enabled: boolean): Promise<{ enabled: boolean }> => {
    const res = await fetch(`${API_BASE}/costs/config`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify({ enabled }),
    });
    if (!res.ok) throw new Error("Failed to update cost config");
    return res.json();
  },

  getGroupCompression: async (groupId: string): Promise<GroupCompressionConfig> => {
    const res = await fetch(`${API_BASE}/costs/groups/${groupId}/compression`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch group compression config");
    return res.json();
  },

  updateGroupCompression: async (groupId: string, cfg: Omit<GroupCompressionConfig, "group_id" | "group_name">): Promise<GroupCompressionConfig> => {
    const res = await fetch(`${API_BASE}/costs/groups/${groupId}/compression`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify(cfg),
    });
    if (!res.ok) throw new Error("Failed to update group compression config");
    return res.json();
  },
};
