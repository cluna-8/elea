// Funciones puras de la pantalla de redirección: formulario → cuerpo de la API, forma de la
// credencial por proveedor, etiquetas de alcance, permisos por rol y errores en castellano.
// Sin React ni fetch: se testean solas (sentinel/frontend/redirect/__tests__/helpers.test.ts).
import {
  CREDENTIAL_FIELD_LABELS, CREDENTIAL_SHAPES, DEFAULT_API_BASE, ENV_NAME_PREFIX, ENV_NAME_RE,
  ENV_PREFIX, Face, FamilyTier, LabelMode, PolicyState, PostureMode, Provider, ProtocolFamily,
  REQUIRES_API_BASE, RequestClass, SCOPE_TYPE_LABELS, SECRET_FIELDS, ScopeType, SUGGESTED_PROTOCOL,
} from "./catalog";

// ── tipos de la API (contracts/admin-api.md) ────────────────────────────────

export interface Destination {
  id: string;
  level: "installation" | "tenant";
  tenant_id: string | null;
  name: string;
  provider: Provider;
  real_model: string;
  protocol_family: ProtocolFamily;
  inference_jurisdiction: string | null;
  entity_jurisdiction: string | null;
  blocked_by_default: boolean;
  enabled_at: string | null;
  enable_reason: string | null;
  has_credential: boolean;
  api_base: string | null;
  status: "active" | "inactive" | "revoked";
  context_window?: number | null;
  max_output?: number | null;
  price_override?: Price | null;
  capability_profile?: Record<string, unknown> | null;
  /** Id público de la entrada del catálogo (069 E3: el destino ES la entrada). */
  public_id?: string;
  /** Parámetros del pedido que el modelo no acepta (los quita la pasarela); viene de la ficha. */
  unsupported_params?: string[];
}

/** Precio del destino en USD por millón de tokens (D23 de la 069). Sin precio propio, el motor usa
 *  su mapa de precios si conoce el modelo; si no, el gasto no se descuenta del presupuesto. */
export interface Price {
  input_per_mtok: number; output_per_mtok: number;
  /** Precio de lectura y escritura de caché (057 FR-046), opcionales: sin ellos la caché se cobra a precio de entrada. */
  cache_read_per_mtok?: number; cache_write_per_mtok?: number;
}

export interface PublishedModel {
  id: string;
  face: Face;
  public_id: string;
  family_tier: FamilyTier | null;
  is_family_default: boolean;
  label: string | null;
  label_mode: LabelMode;
  scope_type: ScopeType;
  scope_value: string;
  reference_model: string | null;
}

export interface Rule {
  id: string;
  published_model_id: string | null;
  family_tier: FamilyTier | null;
  request_class: RequestClass | null;
  scope_type: ScopeType;
  scope_value: string;
  targets: string[];
  /** Estrategia de elección entre los destinos elegibles (069 US10); filas viejas: "order". */
  strategy?: "order" | "cheapest";
  /** Avisos derivados por el backend: destinos de la regla que ya no se pueden usar (FR-005b / 069 E3). */
  warnings?: RuleWarning[];
}

export interface RuleWarning {
  code: "offer_withdrawn" | "destination_unavailable" | string;
  destination_id: string;
}

export interface PolicyRow {
  id: string;
  scope_type: ScopeType;
  scope_value: string;
  state: PolicyState;
  reason: string | null;
  changed_at: string | null;
}

export interface PostureRow {
  id: string;
  scope_type: ScopeType;
  scope_value: string;
  mode: PostureMode;
  jurisdictions: string[];
  accept_foreign_entity: boolean;
  reason: string;
  created_by_role: string | null;
  created_at: string | null;
}

export interface Lookups {
  groups: { id: string; name: string }[];
  users: { id: string; username: string }[];
  keys: { id: string; name: string }[];
}

export type FieldErrors = Record<string, string>;
export type Built<T> = { payload: T; errors: FieldErrors } | { payload: null; errors: FieldErrors };

// ── roles ───────────────────────────────────────────────────────────────────

/** Rol canónico de la sesión. La consola guarda el rol ya normalizado (super_admin y
 *  tenant_admin se ven como `admin`), pero la pantalla necesita distinguir super_admin
 *  (destinos de instalación, ofertas): se lee del token de sesión. Solo decide qué botones se
 *  muestran — el backend aplica los permisos igual. */
export function sessionRole(token: string | null, storedRole: string | undefined): string {
  if (token) {
    try {
      const part = token.split(".")[1];
      if (part) {
        const json = JSON.parse(atob(part.replace(/-/g, "+").replace(/_/g, "/")));
        if (typeof json?.role === "string" && json.role) return json.role;
      }
    } catch {
      /* token opaco: se usa el rol guardado */
    }
  }
  return storedRole ?? "";
}

export interface Permissions {
  isSuper: boolean;
  /** Destinos de tenant, ids publicados, reglas, estado de política. */
  canAdmin: boolean;
  /** Habilitar destinos bloqueados por defecto. */
  canEnable: boolean;
  /** Agregar filas de postura. */
  canAddPosture: boolean;
  /** Editar/borrar posturas y aceptar entidades de otra jurisdicción. */
  canManagePosture: boolean;
  /** Cambiar la postura por defecto de la región y crear o revocar relajaciones por destino (057 FR-023, FR-031a):
   *  solo el rol REAL de cumplimiento o super-admin; el tenant operador por entorno no lo da. */
  canManageRegion: boolean;
}

/** `operator`: la sesión es del tenant operador de la instalación (`GET /redirect/capabilities`,
 *  variable REDIRECT_OPERATOR_TENANT del servidor) — equivale a super_admin para la redirección. */
export function permissionsFor(role: string, operator = false, managesRegions?: boolean | null): Permissions {
  const isSuper = role === "super_admin" || operator;
  const canAdmin = isSuper || role === "tenant_admin" || role === "admin";
  const compliance = role === "compliance_officer";
  return {
    isSuper,
    canAdmin,
    canEnable: isSuper || compliance,
    canAddPosture: canAdmin || compliance,
    canManagePosture: isSuper || compliance,
    // `managesRegions` lo informa el servidor (`GET /redirect/capabilities`); sin él, decide el rol de la sesión
    canManageRegion: managesRegions ?? (role === "super_admin" || compliance),
  };
}

// ── alcances ────────────────────────────────────────────────────────────────

export function scopeValueFor(type: ScopeType, value: string): string {
  return type === "tenant" ? "*" : value;
}

const shortId = (id: string) => (id.length > 8 ? `${id.slice(0, 8)}…` : id);

/** «Grupo: Ventas» — con el nombre si está en los listados, o un id corto si no (p. ej. un
 *  grupo dado de baja): nunca se muestra vacío. */
export function scopeLabel(type: ScopeType, value: string, lookups: Lookups): string {
  if (type === "tenant") return SCOPE_TYPE_LABELS.tenant;
  let name: string | undefined;
  if (type === "group") name = lookups.groups.find(g => g.id === value)?.name;
  if (type === "user") name = lookups.users.find(u => u.id === value)?.username;
  if (type === "connection") name = lookups.keys.find(k => k.id === value)?.name;
  return `${SCOPE_TYPE_LABELS[type] ?? type}: ${name ?? `(${shortId(value)})`}`;
}

function checkScope(type: ScopeType, value: string, errors: FieldErrors): string {
  if (type !== "tenant" && !value) errors.scope_value = "Elegí a quién aplica.";
  return scopeValueFor(type, value);
}

// ── credenciales ────────────────────────────────────────────────────────────

export interface CredentialFieldSpec {
  name: string;
  label: string;
  required: boolean;
  secret: boolean;
  multiline: boolean;
}

export function credentialFields(provider: Provider): CredentialFieldSpec[] {
  const [required, optional] = CREDENTIAL_SHAPES[provider] ?? [[], []];
  return [...required.map(n => [n, true] as const), ...optional.map(n => [n, false] as const)].map(
    ([name, req]) => ({
      name,
      label: CREDENTIAL_FIELD_LABELS[name] ?? name,
      required: req,
      secret: SECRET_FIELDS.has(name),
      multiline: name === "vertex_credentials",
    }),
  );
}

export interface CredentialForm {
  /** `values`: secretos tipeados; `env`: referencia del servidor (solo nivel instalación). */
  mode: "values" | "env";
  values: Record<string, string>;
}

export const emptyCredential = (): CredentialForm => ({ mode: "values", values: {} });

/** Arma la credencial write-only. Devuelve `null` si no hay nada que mandar (proveedor sin
 *  secreto o reemplazo sin tocar). En modo `env` cada campo lleva el sufijo del nombre de la
 *  variable del servidor: `env:REDIRECT_CRED_<SUFIJO>`. */
export function buildCredential(
  provider: Provider, form: CredentialForm, level: "installation" | "tenant",
): { credential: Record<string, unknown> | null; errors: FieldErrors } {
  const errors: FieldErrors = {};
  const out: Record<string, unknown> = {};
  const fields = credentialFields(provider);
  const useEnv = form.mode === "env";
  if (useEnv && level !== "installation") {
    errors.credential = "Las referencias del servidor solo valen para destinos de instalación.";
    return { credential: null, errors };
  }
  for (const f of fields) {
    const raw = (form.values[f.name] ?? "").trim();
    if (!raw) {
      if (f.required) errors[`cred.${f.name}`] = "Obligatorio.";
      continue;
    }
    if (useEnv) {
      // Se acepta la referencia completa (`env:REDIRECT_CRED_X`), el nombre o solo el sufijo.
      const bare = raw.replace(/^env:/i, "").toUpperCase();
      const name = bare.startsWith(ENV_NAME_PREFIX) ? bare : `${ENV_NAME_PREFIX}${bare}`;
      if (!ENV_NAME_RE.test(name)) {
        errors[`cred.${f.name}`] = "Nombre de variable inválido (letras, números y _).";
        continue;
      }
      out[f.name] = `${ENV_PREFIX}${name}`;
    } else if (f.name === "vertex_credentials") {
      try {
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error();
        out[f.name] = parsed;
      } catch {
        errors[`cred.${f.name}`] = "Pegá el JSON completo de la cuenta de servicio.";
      }
    } else {
      out[f.name] = raw;
    }
  }
  if (Object.keys(errors).length) return { credential: null, errors };
  return { credential: Object.keys(out).length ? out : null, errors };
}

// ── destinos ────────────────────────────────────────────────────────────────

export interface DestinationForm {
  level: "installation" | "tenant";
  name: string;
  provider: Provider;
  real_model: string;
  protocol_family: ProtocolFamily;
  inference_jurisdiction: string;
  entity_jurisdiction: string;
  api_base: string;
  context_window: string;
  max_output: string;
  price_input: string;
  price_output: string;
  accepts_images?: boolean;
  accepts_pdf?: boolean;
  credential: CredentialForm;
}

export function newDestinationForm(provider: Provider = "openai_compatible"): DestinationForm {
  return {
    level: "tenant", name: "", provider, real_model: "", protocol_family: SUGGESTED_PROTOCOL[provider],
    inference_jurisdiction: "", entity_jurisdiction: "", api_base: DEFAULT_API_BASE[provider] ?? "",
    context_window: "", max_output: "", price_input: "", price_output: "", credential: emptyCredential(),
  };
}

/** Cambiar de proveedor re-sugiere la familia y la base, y descarta lo tipeado de credencial
 *  (otra forma de campos). */
export function withProvider(form: DestinationForm, provider: Provider): DestinationForm {
  const prevDefault = DEFAULT_API_BASE[form.provider] ?? "";
  return {
    ...form, provider, protocol_family: SUGGESTED_PROTOCOL[provider],
    api_base: !form.api_base || form.api_base === prevDefault ? DEFAULT_API_BASE[provider] ?? "" : form.api_base,
    credential: { mode: form.credential.mode, values: {} },
  };
}

/** Tokens opcionales (ventana, salida máxima): vacío = sin declarar; si no, entero positivo. */
export function parseTokens(text: string): { value: number | null; error?: string } {
  const t = text.trim().replace(/[.\s_]/g, "");
  if (!t) return { value: null };
  if (!/^\d+$/.test(t) || Number(t) < 1) return { value: null, error: "Un número entero de tokens, p. ej. 128000." };
  return { value: Number(t) };
}

/** Cuerpo del PATCH de ventana/salida: solo lo declarado (la API no borra con null). */
export function buildWindowPatch(window: string, maxOutput: string): Built<Record<string, number>> {
  const w = parseTokens(window), o = parseTokens(maxOutput);
  const errors: FieldErrors = {};
  if (w.error) errors.context_window = w.error;
  if (o.error) errors.max_output = o.error;
  if (!w.error && !o.error && w.value === null && o.value === null) errors.context_window = "Indicá al menos la ventana.";
  if (Object.keys(errors).length) return { payload: null, errors };
  const payload: Record<string, number> = {};
  if (w.value !== null) payload.context_window = w.value;
  if (o.value !== null) payload.max_output = o.value;
  return { payload, errors };
}

/** USD por millón de tokens: vacío = sin precio propio; acepta coma o punto decimal. */
export function parsePrice(text: string): { value: number | null; error?: string } {
  const t = text.trim().replace(",", ".");
  if (!t) return { value: null };
  if (!/^\d+(\.\d+)?$/.test(t)) return { value: null, error: "Un número en USD por millón de tokens, p. ej. 0,29." };
  return { value: Number(t) };
}

/** Los dos precios o ninguno (ninguno = precio automático del motor). */
export function buildPrice(input: string, output: string): Built<Price | null> {
  const i = parsePrice(input), o = parsePrice(output);
  const errors: FieldErrors = {};
  if (i.error) errors.price_input = i.error;
  if (o.error) errors.price_output = o.error;
  if (!i.error && !o.error && (i.value === null) !== (o.value === null)) {
    errors[i.value === null ? "price_input" : "price_output"] = "Completá también este precio (o dejá los dos vacíos).";
  }
  if (Object.keys(errors).length) return { payload: null, errors } as Built<Price | null>;
  return { payload: i.value === null ? null : { input_per_mtok: i.value, output_per_mtok: o.value as number }, errors };
}

const usd = (n: number) => n.toLocaleString("es", { maximumFractionDigits: 4 });

export function priceLabel(d: Destination): string {
  return d.price_override
    ? `Precio: ${usd(d.price_override.input_per_mtok)} / ${usd(d.price_override.output_per_mtok)} USD por millón (entrada / salida)`
    : "Precio: automático (si el motor conoce el modelo)";
}

// ── caché del proveedor (057 FR-043, FR-044, FR-046) ──────────────────────────
// `cache_control`: las marcas de caché de la herramienta se reenvían al destino (FR-044). `session_affinity`: el destino agrupa
// por sesión y recibe un identificador estable derivado con la clave del servidor (FR-043); sin declarar, OpenRouter lo tiene
// encendido (lo mismo que decide el servidor).

export interface CacheFlags { cache_control: boolean; session_affinity: boolean }

export function cacheFlags(d: { provider?: string; capability_profile?: Record<string, unknown> | null }): CacheFlags {
  const p = d.capability_profile ?? {};
  return {
    cache_control: p.cache_control === true,
    session_affinity: typeof p.session_affinity === "boolean" ? p.session_affinity : d.provider === "openrouter",
  };
}

/** El PATCH de `features` reemplaza el perfil entero: se fusiona con el que ya tiene para no borrar otras claves. */
export function buildCacheFeatures(prev: Record<string, unknown> | null | undefined,
  patch: Partial<CacheFlags>): Record<string, unknown> {
  return { ...(prev ?? {}), ...patch };
}

/** Texto del precio de caché: lectura y escritura si el destino los tiene; si no, el aviso de que se cobra a precio de entrada. */
export function cachePriceLabel(d: Destination): string | null {
  const p = d.price_override;
  if (!p) return null;
  const has = (n?: number) => typeof n === "number";
  if (!has(p.cache_read_per_mtok) && !has(p.cache_write_per_mtok)) {
    return "Sin precio de caché: se cobra a precio de entrada";
  }
  const part = (n?: number) => (has(n) ? usd(n as number) : "—");
  return `Precio de caché: lectura ${part(p.cache_read_per_mtok)} / escritura ${part(p.cache_write_per_mtok)} USD por millón`;
}

/** USD por millón → USD por token (lo que guarda el catálogo). Vacío = no cambia. */
export function parseCachePrice(text: string): { perToken: number | null; error?: string } {
  const r = parsePrice(text);
  return r.error ? { perToken: null, error: r.error } : { perToken: r.value === null ? null : r.value / 1e6 };
}

// ── capacidades del destino ─────────────────────────────────────────────────
// Claves de `capability_profile` que ya lee la cara Claude (sentinel/redirect/faces/claude.py).
// Sin declarar = no acepta: un adjunto de la persona se rechaza y lo que devuelve una herramienta
// (la captura de Cowork) se reemplaza por una nota.

export interface CapabilityFlags { images: boolean; documents_pdf: boolean }

export function capabilityFlags(d: { capability_profile?: Record<string, unknown> | null }): CapabilityFlags {
  const p = d.capability_profile ?? {};
  return { images: p.images === true, documents_pdf: p.documents_pdf === true };
}

/** El PATCH reemplaza el perfil entero: se fusiona con el que ya tiene para no borrar otras
 *  claves (cache_control, thinking…) cargadas por API. */
export function buildCapabilityProfile(prev: Record<string, unknown> | null | undefined,
  flags: CapabilityFlags): Record<string, unknown> {
  return { ...(prev ?? {}), images: flags.images, documents_pdf: flags.documents_pdf };
}

export function capabilityLabel(d: { capability_profile?: Record<string, unknown> | null }): string {
  const f = capabilityFlags(d);
  const parts = [f.images && "imágenes", f.documents_pdf && "PDF"].filter(Boolean);
  return `Acepta: ${parts.length ? parts.join(" y ") : "solo texto"}`;
}

export const needsApiBase = (p: Provider) => REQUIRES_API_BASE.includes(p);

export function buildDestinationPayload(form: DestinationForm): Built<Record<string, unknown>> {
  const errors: FieldErrors = {};
  if (!form.name.trim()) errors.name = "Poné un nombre.";
  if (!form.real_model.trim()) errors.real_model = "Indicá el modelo real del proveedor.";
  const apiBase = form.api_base.trim();
  if (needsApiBase(form.provider) && !apiBase) errors.api_base = "Este proveedor necesita la dirección base.";
  if (apiBase && !/^https?:\/\//i.test(apiBase)) errors.api_base = "La dirección debe empezar con http:// o https://.";
  const win = parseTokens(form.context_window ?? ""), out = parseTokens(form.max_output ?? "");
  const price = buildPrice(form.price_input ?? "", form.price_output ?? "");
  Object.assign(errors, price.errors);
  if (win.error) errors.context_window = win.error;
  if (out.error) errors.max_output = out.error;
  const cred = buildCredential(form.provider, form.credential, form.level);
  Object.assign(errors, cred.errors);
  if (Object.keys(errors).length) return { payload: null, errors };
  const payload: Record<string, unknown> = {
    level: form.level,
    name: form.name.trim(),
    provider: form.provider,
    real_model: form.real_model.trim(),
    protocol_family: form.protocol_family,
    inference_jurisdiction: form.inference_jurisdiction || null,
    entity_jurisdiction: form.entity_jurisdiction || null,
    api_base: apiBase || null,
  };
  if (win.value !== null) payload.context_window = win.value;
  if (out.value !== null) payload.max_output = out.value;
  if (price.payload) payload.price_override = price.payload;
  if (form.accepts_images || form.accepts_pdf) {
    payload.capability_profile = { images: !!form.accepts_images, documents_pdf: !!form.accepts_pdf };
  }
  if (cred.credential) payload.credential = cred.credential;
  return { payload, errors };
}

export function destinationStatus(d: Destination): { label: string; tone: "ok" | "warn" | "danger" | "neutral" } {
  if (d.status === "revoked") return { label: "Revocado", tone: "danger" };
  if (d.blocked_by_default && !d.enabled_at) return { label: "Bloqueado por defecto", tone: "warn" };
  if (d.status === "inactive") return { label: "Inactivo", tone: "neutral" };
  return { label: "Activo", tone: "ok" };
}

/** Lista de tenants para la oferta: `*` o UUIDs separados por coma/espacio/línea. */
export function parseOfferTenants(text: string): { tenants: string[] | null; error?: string } {
  const parts = text.split(/[\s,;]+/).map(s => s.trim()).filter(Boolean);
  if (!parts.length) return { tenants: [] };
  if (parts.includes("*")) return { tenants: ["*"] };
  const bad = parts.find(p => !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(p));
  if (bad) return { tenants: null, error: `Identificador de organización inválido: ${bad}` };
  return { tenants: parts };
}

// ── ids publicados ──────────────────────────────────────────────────────────

export interface PublishedForm {
  face: Face;
  public_id: string;
  family_tier: FamilyTier | "";
  is_family_default: boolean;
  label_mode: LabelMode;
  label: string;
  scope_type: ScopeType;
  scope_value: string;
  reference_model: string;
}

export const newPublishedForm = (): PublishedForm => ({
  face: "openai_generic", public_id: "", family_tier: "", is_family_default: false,
  label_mode: "destination", label: "", scope_type: "tenant", scope_value: "", reference_model: "",
});

export function buildPublishedPayload(form: PublishedForm): Built<Record<string, unknown>> {
  const errors: FieldErrors = {};
  const pid = form.public_id.trim();
  if (!pid) errors.public_id = "Indicá el id que verá la herramienta.";
  else if (/\s/.test(pid)) errors.public_id = "Sin espacios.";
  else if (pid.startsWith("rdx-")) errors.public_id = "El prefijo rdx- es interno.";
  if (form.face === "claude" && !form.family_tier) errors.family_tier = "En la cara Claude elegí el tier.";
  if (form.label_mode === "custom" && !form.label.trim()) errors.label = "Escribí la etiqueta.";
  const scope_value = checkScope(form.scope_type, form.scope_value, errors);
  if (Object.keys(errors).length) return { payload: null, errors };
  const tier = form.face === "claude" ? form.family_tier || null : null;
  return {
    payload: {
      face: form.face, public_id: pid, family_tier: tier,
      is_family_default: tier ? form.is_family_default : false,
      label: form.label_mode === "custom" ? form.label.trim() : null, label_mode: form.label_mode,
      scope_type: form.scope_type, scope_value,
      reference_model: form.reference_model.trim() || null,
    },
    errors,
  };
}

// ── reglas ──────────────────────────────────────────────────────────────────

export interface RuleForm {
  by: "published" | "tier";
  published_model_id: string;
  family_tier: FamilyTier | "";
  request_class: RequestClass | "";
  scope_type: ScopeType;
  scope_value: string;
  targets: string[];
}

export const newRuleForm = (): RuleForm => ({
  by: "published", published_model_id: "", family_tier: "", request_class: "",
  scope_type: "tenant", scope_value: "", targets: [],
});

export function buildRulePayload(form: RuleForm): Built<Record<string, unknown>> {
  const errors: FieldErrors = {};
  if (form.by === "published" && !form.published_model_id) errors.published_model_id = "Elegí el modelo publicado.";
  if (form.by === "tier" && !form.family_tier) errors.family_tier = "Elegí el tier.";
  if (!form.targets.length) errors.targets = "Agregá al menos un destino.";
  if (new Set(form.targets).size !== form.targets.length) errors.targets = "Un destino aparece dos veces.";
  const scope_value = checkScope(form.scope_type, form.scope_value, errors);
  if (Object.keys(errors).length) return { payload: null, errors };
  return {
    payload: {
      published_model_id: form.by === "published" ? form.published_model_id : null,
      family_tier: form.by === "tier" ? form.family_tier : null,
      request_class: form.request_class || null,
      scope_type: form.scope_type, scope_value, targets: [...form.targets],
    },
    errors,
  };
}

/** Mueve un elemento una posición (orden de destinos: [0] principal, resto fallbacks). */
export function moveItem<T>(items: T[], index: number, delta: -1 | 1): T[] {
  const to = index + delta;
  if (to < 0 || to >= items.length) return items;
  const out = [...items];
  [out[index], out[to]] = [out[to], out[index]];
  return out;
}

export function publishedLabel(p: PublishedModel): string {
  const tier = p.family_tier ? ` · ${p.family_tier}` : "";
  return `${p.public_id}${tier}`;
}

// ── política y postura ─────────────────────────────────────────────────────

export interface PolicyForm { scope_type: ScopeType; scope_value: string; state: PolicyState; reason: string }

export function buildPolicyRequest(form: PolicyForm): Built<{ path: string; body: { state: PolicyState; reason: string } }> {
  const errors: FieldErrors = {};
  const scope_value = checkScope(form.scope_type, form.scope_value, errors);
  if (form.reason.trim().length < 3) errors.reason = "Contá por qué (al menos 3 caracteres).";
  if (Object.keys(errors).length) return { payload: null, errors };
  return {
    payload: {
      path: `/policy/${encodeURIComponent(form.scope_type)}/${encodeURIComponent(scope_value)}`,
      body: { state: form.state, reason: form.reason.trim() },
    },
    errors,
  };
}

export interface PostureForm {
  scope_type: ScopeType;
  scope_value: string;
  mode: PostureMode;
  jurisdictions: string[];
  accept_foreign_entity: boolean;
  reason: string;
}

export const newPostureForm = (): PostureForm => ({
  scope_type: "tenant", scope_value: "", mode: "allowlist", jurisdictions: [], accept_foreign_entity: false, reason: "",
});

export function buildPosturePayload(form: PostureForm, perms: Permissions): Built<Record<string, unknown>> {
  const errors: FieldErrors = {};
  const scope_value = checkScope(form.scope_type, form.scope_value, errors);
  if (form.mode === "allowlist" && !form.jurisdictions.length) errors.jurisdictions = "Elegí al menos una jurisdicción.";
  if (form.accept_foreign_entity && !perms.canManagePosture) {
    errors.accept_foreign_entity = "Solo cumplimiento o el super-admin pueden aceptar entidades de otra jurisdicción.";
  }
  if (form.reason.trim().length < 3) errors.reason = "El motivo es obligatorio (al menos 3 caracteres).";
  if (Object.keys(errors).length) return { payload: null, errors };
  return {
    payload: {
      scope_type: form.scope_type, scope_value, mode: form.mode,
      jurisdictions: form.mode === "off" ? [] : form.jurisdictions.map(j => j.toUpperCase()),
      accept_foreign_entity: form.accept_foreign_entity, reason: form.reason.trim(),
    },
    errors,
  };
}

// ── errores ─────────────────────────────────────────────────────────────────

const FIELD_NAMES: Record<string, string> = {
  name: "nombre", real_model: "modelo real", reason: "motivo", public_id: "id publicado",
  api_base: "dirección base", targets: "destinos", jurisdictions: "jurisdicciones",
  inference_jurisdiction: "jurisdicción de inferencia", entity_jurisdiction: "jurisdicción de la entidad",
  label: "etiqueta", tenants: "organizaciones", state: "estado", mode: "modo",
};

function validationMessage(d: { loc?: unknown[]; msg?: string; type?: string }): string {
  const field = Array.isArray(d.loc) ? String(d.loc[d.loc.length - 1]) : "";
  const nice = FIELD_NAMES[field] ?? field;
  if (d.type === "string_too_short") return `El campo «${nice}» es demasiado corto.`;
  if (d.type === "string_too_long") return `El campo «${nice}» es demasiado largo.`;
  if (d.type === "missing") return `Falta el campo «${nice}».`;
  if (d.type === "string_pattern_mismatch") return `El campo «${nice}» tiene un formato inválido.`;
  return nice ? `El campo «${nice}» no es válido.` : "Hay datos inválidos en el formulario.";
}

export const POSTURE_LESS_STRICT =
  "Esa postura es menos estricta que la vigente; el administrador de empresa solo puede endurecer.";

/** Mensaje para la persona: el `detail` del backend (ya en castellano) o una explicación por
 *  código. Nunca un volcado técnico. */
export function describeApiError(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (status === 0) return "No se pudo contactar al servidor. Revisá la conexión y probá de nuevo.";
  if (status === 401) return "Tu sesión venció. Volvé a ingresar.";
  if (status === 403) {
    return typeof detail === "string" && !/not (enough|authenticated)|insufficient/i.test(detail)
      ? `No tenés permiso: ${detail}.` : "Tu rol no permite esta acción.";
  }
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const d = detail as { code?: unknown; message?: unknown; motivo?: unknown };
    if (d.code === "posture_less_strict") return POSTURE_LESS_STRICT;
    const text = [d.message, d.motivo].find(v => typeof v === "string" && v.trim()) as string | undefined;
    if (text) return `${text.trim().charAt(0).toUpperCase()}${text.trim().slice(1)}${/[.!?]$/.test(text.trim()) ? "" : "."}`;
  }
  if (Array.isArray(detail)) {
    const msgs = detail.map(d => (typeof d === "string" ? d : validationMessage(d ?? {})));
    return Array.from(new Set(msgs)).join(" ");
  }
  if (status === 404) {
    if (!detail || detail === "Not Found") return "La redirección de modelos no está activada en esta instalación.";
    return "No se encontró el elemento (puede que otra persona lo haya borrado). Recargá la lista.";
  }
  if (typeof detail === "string" && detail.trim()) {
    const d = detail.trim();
    return `${d.charAt(0).toUpperCase()}${d.slice(1)}${/[.!?]$/.test(d) ? "" : "."}`;
  }
  if (status >= 500) return "El servidor tuvo un problema. Probá de nuevo en unos minutos.";
  return "No se pudo completar la acción.";
}
