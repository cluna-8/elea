// Funciones puras de la pantalla «Catálogo de modelos» (spec 069): tipos de la API, semáforo con
// motivos legibles, permisos por rol, formulario → cuerpo de la API y validaciones.
// Sin React ni fetch: se testean solas (sentinel/frontend/catalog/__tests__/helpers.test.ts).
import {
  DEFAULT_API_BASE, ENV_NAME_PREFIX, ENV_NAME_RE, JURISDICTIONS, Provider, ProtocolFamily,
  REQUIRES_API_BASE, SUGGESTED_PROTOCOL,
} from "../redirect/catalog";
import { Built, CredentialFieldSpec, credentialFields, FieldErrors, parseTokens } from "../redirect/helpers";

// ── tipos de la API (contracts/admin-catalogo.md; vista: sentinel/catalog/store.py::entry_view) ──

export type SemaforoState = "eu_ok" | "standard" | "unclassified";
export interface Semaforo { estado: SemaforoState; motivos: string[] }

export interface SheetView {
  provider_legal_entity: string | null;
  entity_jurisdiction: string | null;
  inference_jurisdiction: string;
  logs_jurisdiction: string;
  zero_data_retention: boolean | null;
  trains_on_data: boolean | null;
  transfer_mechanism: string;
  dpa_registry_id: string | null;
  eu_region_contracted: boolean | null;
  notes: string | null;
  classification_version: string | null;
  classified_by: string | null;
  classified_at: string | null;
}

// Claves que el backend acepta en `features` (sentinel/catalog/models.py::FEATURES). `mid_system_messages`
// es avanzada: no se muestra como casilla, pero se conserva intacta al editar.
export const FEATURES = ["images", "documents_pdf", "tools", "thinking", "cache_control"] as const;
export type Feature = (typeof FEATURES)[number];
export const FEATURE_LABELS: Record<Feature, string> = {
  images: "Imágenes",
  documents_pdf: "PDF",
  tools: "Herramientas",
  thinking: "Razonamiento extendido",
  cache_control: "Caché de prompts",
};

export const CAPABILITIES = ["small", "standard", "frontier"] as const;
export type Capability = (typeof CAPABILITIES)[number];
export const CAPABILITY_LABELS: Record<Capability, string> = {
  small: "Pequeño", standard: "Estándar", frontier: "Frontera",
};

export const ROLES = ["text", "embeddings"] as const;
export type EntryRole = (typeof ROLES)[number];
export const ROLE_LABELS: Record<EntryRole, string> = { text: "Texto", embeddings: "Embeddings" };

export type EntryLevel = "installation" | "tenant";
export type EntryStatus = "active" | "inactive" | "archived";

export interface EntryView {
  id: string;
  level: EntryLevel;
  tenant_id: string | null;
  name: string;
  /** Slug con el que Hub y otras herramientas piden el modelo. */
  public_id: string;
  provider: Provider;
  real_model: string;
  protocol_family: ProtocolFamily;
  api_base: string | null;
  is_aggregator: boolean;
  role: EntryRole;
  capability: Capability;
  features: Partial<Record<Feature | "mid_system_messages", boolean>>;
  /** Parámetros del pedido que el modelo no acepta (se quitan antes del proveedor); ausente en servidores viejos. */
  unsupported_params?: string[];
  context_window: number | null;
  max_output: number | null;
  blocked_by_default: boolean;
  enabled_at: string | null;
  status: EntryStatus;
  source: string;
  has_credential: boolean;
  /** Solo para quien administra la entrada; nunca trae el valor. */
  credential?: { id: string; name: string; kind: "secret" | "env_ref"; fingerprint: string | null };
  sheet: SheetView;
  semaforo: Semaforo;
  /** Solo el operador, en entradas de instalación: ids de organización o «*». */
  offered_to?: string[];
}

export interface CredentialRow {
  id: string;
  name: string;
  kind: "secret" | "env_ref";
  level: EntryLevel;
  fingerprint: string | null;
  status: "active" | "revoked";
  /** Nombres de los modelos que la usan. */
  in_use_by: string[];
}

// ── semáforo ────────────────────────────────────────────────────────────────

export const SEMAFORO_LABELS: Record<SemaforoState, string> = {
  eu_ok: "Admisible UE",
  standard: "Estándar",
  unclassified: "Sin clasificar",
};

export type Tone = "ok" | "warn" | "danger" | "info" | "neutral";
export const SEMAFORO_TONES: Record<SemaforoState, Tone> = {
  eu_ok: "ok", standard: "warn", unclassified: "neutral",
};

const SHEET_FIELD_LABELS: Record<string, string> = {
  inference_jurisdiction: "jurisdicción de inferencia",
  logs_jurisdiction: "jurisdicción de registros",
  trains_on_data: "entrena con datos",
  transfer_mechanism: "mecanismo de transferencia",
  eu_region_contracted: "región UE contratada",
  zero_data_retention: "retención cero",
  entity_jurisdiction: "jurisdicción de la entidad",
  dpa_registry_id: "DPA asociado",
};

const MOTIVO_LABELS: Record<string, string> = {
  local: "Local: los datos no salen de la infraestructura",
  dpa_vencido: "DPA vencido",
  sin_dpa: "Sin DPA",
  agregador: "Agregador: no cubre al proveedor final",
  inferencia_fuera_ue: "Inferencia fuera de la UE",
  registros_fuera_ue: "Registros fuera de la UE",
  entrena_con_datos: "Entrena con datos",
  transferencia_sin_mecanismo: "Transferencia sin mecanismo de garantía",
  dpa_region_no_ue: "El DPA no fija procesamiento en la UE",
  dpa_inactivo: "DPA inactivo",
  ficha_desactualizada: "Ficha desactualizada: cambió el proveedor o el modelo",
};

export function motivoLabel(motivo: string): string {
  if (motivo.startsWith("dato_desconocido:")) {
    const field = motivo.slice("dato_desconocido:".length);
    return `Falta cargar: ${SHEET_FIELD_LABELS[field] ?? field}`;
  }
  return MOTIVO_LABELS[motivo] ?? motivo;
}

export const semaforoLabel = (s: Semaforo | undefined | null): string =>
  s ? SEMAFORO_LABELS[s.estado] ?? s.estado : SEMAFORO_LABELS.unclassified;

export const isStale = (e: Pick<EntryView, "sheet" | "semaforo">): boolean =>
  e.sheet?.classification_version === "stale" || (e.semaforo?.motivos ?? []).includes("ficha_desactualizada");

// ── estado, nivel ───────────────────────────────────────────────────────────

export function entryStatus(e: Pick<EntryView, "status" | "blocked_by_default" | "enabled_at">): { label: string; tone: Tone } {
  if (e.status === "archived") return { label: "Archivado", tone: "neutral" };
  if (e.status === "inactive") return { label: "Inactivo", tone: "neutral" };
  if (e.blocked_by_default && !e.enabled_at) return { label: "Bloqueado por defecto", tone: "warn" };
  return { label: "Activo", tone: "ok" };
}

export const levelLabel = (l: EntryLevel) => (l === "installation" ? "Instalación" : "Organización");

// ── permisos por rol ────────────────────────────────────────────────────────

export interface Permissions {
  /** Operador de la instalación (entradas de instalación, ofertas, referencias del servidor). */
  operator: boolean;
  /** Alta, edición, archivo y credenciales de las entradas de su nivel. */
  canAdmin: boolean;
  /** Editar la ficha de cumplimiento (administración y cumplimiento). */
  canSheetRole: boolean;
}

const ADMIN_ROLES = ["admin", "tenant_admin", "super_admin"];

/** `role` sale de `sessionRole` (token). `operator` viene de `GET /redirect/capabilities`; solo vale
 *  para roles de administración (una persona de solo lectura del tenant operador no escribe).
 *  Solo decide qué botones se muestran: el backend aplica los permisos igual. */
export function permissionsFor(role: string, operator = false): Permissions {
  const adminRole = ADMIN_ROLES.includes(role);
  const isOperator = role === "super_admin" || (operator && adminRole);
  return {
    operator: isOperator,
    canAdmin: adminRole,
    canSheetRole: adminRole || role === "compliance_officer",
  };
}

export const canWriteEntry = (p: Permissions, e: Pick<EntryView, "level" | "status">) =>
  p.canAdmin && e.status !== "archived" && (e.level === "tenant" || p.operator);

export const canEditSheet = (p: Permissions, e: Pick<EntryView, "level" | "status">) =>
  p.canSheetRole && e.status !== "archived" && (e.level === "tenant" || p.operator);

// ── credenciales: valor write-only ──────────────────────────────────────────

export const SECRET_API_KEY_FIELD: CredentialFieldSpec = {
  name: "api_key", label: "Clave de API", required: true, secret: true, multiline: false,
};

/** Campos que se piden para el valor de una credencial: los del proveedor, o una sola clave. */
export function valueFields(provider: Provider | null): CredentialFieldSpec[] {
  if (!provider) return [SECRET_API_KEY_FIELD];
  return credentialFields(provider);
}

/** Valor para la API: una cadena si es solo `api_key`; un objeto si hay varios campos. `null` si no
 *  se tipeó nada. Los errores salen por campo (`cred.<campo>`). */
export function buildSecretValue(
  fields: CredentialFieldSpec[], values: Record<string, string>,
): { value: string | Record<string, unknown> | null; errors: FieldErrors } {
  const errors: FieldErrors = {};
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const raw = (values[f.name] ?? "").trim();
    if (!raw) {
      continue;
    }
    if (f.name === "vertex_credentials") {
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
  const touched = Object.keys(out).length > 0 || Object.keys(errors).length > 0;
  if (touched) {
    for (const f of fields) {
      if (f.required && !(f.name in out) && !errors[`cred.${f.name}`]) errors[`cred.${f.name}`] = "Obligatorio.";
    }
  }
  if (Object.keys(errors).length) return { value: null, errors };
  if (!touched) return { value: null, errors };
  if (fields.length === 1 && fields[0].name === "api_key") return { value: out.api_key as string, errors };
  return { value: out, errors };
}

/** Nombre de variable del servidor: acepta la referencia completa, el nombre o solo el sufijo.
 *  La API recibe el nombre (`REDIRECT_CRED_…`), sin el prefijo `env:`. */
export function normalizeEnvName(raw: string): { name: string | null; error?: string } {
  const bare = raw.trim().replace(/^env:/i, "").toUpperCase();
  if (!bare) return { name: null, error: "Obligatorio." };
  const name = bare.startsWith(ENV_NAME_PREFIX) ? bare : `${ENV_NAME_PREFIX}${bare}`;
  if (!ENV_NAME_RE.test(name)) return { name: null, error: "Nombre de variable inválido (letras, números y _)." };
  return { name };
}

// ── alta y edición de modelos ───────────────────────────────────────────────

export type CredMode = "keep" | "none" | "existing" | "new" | "env";

export interface EntryForm {
  level: EntryLevel;
  name: string;
  public_id: string;
  provider: Provider;
  real_model: string;
  protocol_family: ProtocolFamily;
  api_base: string;
  role: EntryRole;
  capability: Capability;
  context_window: string;
  max_output: string;
  features: Record<Feature, boolean>;
  aggregator: boolean;
  /** Parámetros no soportados, tal como se escriben (separados por comas o espacios). */
  unsupported: string;
  credMode: CredMode;
  credentialId: string;
  newName: string;
  values: Record<string, string>;
  envRef: string;
}

const noFeatures = (): Record<Feature, boolean> =>
  ({ images: false, documents_pdf: false, tools: false, thinking: false, cache_control: false });

export const defaultAggregator = (p: Provider) => p === "openrouter";
export const needsApiBase = (p: Provider) => REQUIRES_API_BASE.includes(p);

export function newEntryForm(provider: Provider = "anthropic"): EntryForm {
  return {
    level: "tenant", name: "", public_id: "", provider, real_model: "", protocol_family: SUGGESTED_PROTOCOL[provider],
    api_base: DEFAULT_API_BASE[provider] ?? "", role: "text", capability: "standard",
    context_window: "", max_output: "", features: noFeatures(), aggregator: defaultAggregator(provider),
    unsupported: "", credMode: "new", credentialId: "", newName: "", values: {}, envRef: "",
  };
}

export function entryToForm(e: EntryView): EntryForm {
  return {
    level: e.level, name: e.name, public_id: e.public_id ?? "", provider: e.provider, real_model: e.real_model,
    protocol_family: e.protocol_family, api_base: e.api_base ?? "", role: e.role, capability: e.capability,
    context_window: e.context_window ? String(e.context_window) : "",
    max_output: e.max_output ? String(e.max_output) : "",
    features: { ...noFeatures(), ...Object.fromEntries(FEATURES.map(f => [f, Boolean(e.features?.[f])])) },
    aggregator: e.is_aggregator, unsupported: (e.unsupported_params ?? []).join(", "), credMode: "keep", credentialId: "", newName: "", values: {}, envRef: "",
  };
}

/** Cambiar de proveedor re-sugiere familia, base y agregador, y descarta lo tipeado de credencial
 *  (otra forma de campos). */
export function withProvider(form: EntryForm, provider: Provider): EntryForm {
  const prevDefault = DEFAULT_API_BASE[form.provider] ?? "";
  return {
    ...form, provider, protocol_family: SUGGESTED_PROTOCOL[provider],
    api_base: !form.api_base || form.api_base === prevDefault ? DEFAULT_API_BASE[provider] ?? "" : form.api_base,
    aggregator: form.aggregator === defaultAggregator(form.provider) ? defaultAggregator(provider) : form.aggregator,
    values: {},
  };
}

/** Cambiar de nivel descarta la credencial elegida (las de un nivel no sirven en el otro). */
export function withLevel(form: EntryForm, level: EntryLevel): EntryForm {
  return { ...form, level, credMode: level === "installation" ? "env" : "new", credentialId: "", values: {}, envRef: "" };
}

/** ¿Editar cambia lo que describe la ficha? (el backend la marca desactualizada). */
export const changesSheetSubject = (form: EntryForm, e: EntryView) =>
  form.provider !== e.provider || form.real_model.trim() !== e.real_model;

/** Id público: opcional al crear (se genera del nombre); sin espacios ni el prefijo interno rdx-. */
export function checkPublicId(raw: string): string | null {
  const v = raw.trim();
  if (!v) return null;
  if (/\s/.test(v)) return "Sin espacios.";
  if (v.toLowerCase().startsWith("rdx-")) return "El prefijo rdx- es interno.";
  return null;
}

/** Nombres de parámetros escritos por el admin → lista sin duplicados, en el orden en que se escribieron. */
export function parseParamList(text: string): string[] {
  return Array.from(new Set(text.split(/[\s,;]+/).map(n => n.trim()).filter(Boolean)));
}

// Mismo criterio que la API (sentinel/catalog/validation.py::check_unsupported_params).
const PARAM_NAME = /^[a-z][a-z0-9_]{0,63}$/;
const PROTECTED_PARAMS = ["model", "messages", "input", "prompt", "stream", "api_key", "api_base", "headers",
  "extra_headers", "guardrails", "metadata", "input_cost_per_token", "output_cost_per_token", "timeout", "num_retries",
  "max_parallel_requests", "proxy_server_request", "litellm_params", "custom_llm_provider", "mock_response"];
const isProtectedParam = (n: string) => PROTECTED_PARAMS.includes(n) || n.startsWith("user_api_key");

function checkParams(text: string): string | null {
  const names = parseParamList(text);
  if (names.length > 32) return "Hasta 32 parámetros.";
  if (names.some(n => !PARAM_NAME.test(n))) return "Nombres en minúsculas (letras, números y guion bajo), separados por comas.";
  const bad = names.find(isProtectedParam);
  return bad ? `${bad} es parte del pedido y no se puede quitar.` : null;
}

function checkCommon(form: EntryForm, errors: FieldErrors) {
  if (!form.name.trim()) errors.name = "Poné un nombre.";
  const pid = checkPublicId(form.public_id);
  if (pid) errors.public_id = pid;
  if (!form.real_model.trim()) errors.real_model = "Indicá el modelo real del proveedor.";
  const apiBase = form.api_base.trim();
  if (needsApiBase(form.provider) && !apiBase) errors.api_base = "Este proveedor necesita la dirección base.";
  if (apiBase && !/^https?:\/\//i.test(apiBase)) errors.api_base = "La dirección debe empezar con http:// o https://.";
  const win = parseTokens(form.context_window), out = parseTokens(form.max_output);
  if (win.error) errors.context_window = win.error;
  if (out.error) errors.max_output = out.error;
  const params = checkParams(form.unsupported);
  if (params) errors.unsupported_params = params;
  return { apiBase, win: win.value, out: out.value };
}

/** `credential` de la API según el modo elegido; `undefined` = no se manda. */
function buildCredentialSpec(form: EntryForm, errors: FieldErrors, ctx: { operator: boolean }): Record<string, unknown> | undefined {
  const fields = valueFields(form.provider);
  const needsSecret = fields.some(f => f.required);
  switch (form.credMode) {
    case "keep":
      return undefined;
    case "none":
      if (needsSecret) errors.credential = "Este proveedor requiere credencial.";
      return undefined;
    case "existing":
      if (!form.credentialId) { errors.credential = "Elegí una credencial."; return undefined; }
      return { id: form.credentialId };
    case "env": {
      if (!ctx.operator || form.level !== "installation") {
        errors.credential = "Las referencias del servidor solo valen para modelos de instalación.";
        return undefined;
      }
      const env = normalizeEnvName(form.envRef);
      if (!env.name) { errors["cred.env"] = env.error ?? "Obligatorio."; return undefined; }
      return { env_ref: env.name };
    }
    case "new": {
      const built = buildSecretValue(fields, form.values);
      Object.assign(errors, built.errors);
      if (built.value === null) {
        if (!Object.keys(built.errors).length) {
          errors.credential = fields.some(f => f.required)
            ? "Cargá la credencial o elegí una existente."
            : "Cargá el valor o elegí «Sin credencial».";
        }
        return undefined;
      }
      const name = form.newName.trim() || `Credencial de ${form.name.trim() || "modelo"}`;
      return { new: { name, value: built.value } };
    }
  }
}

export function buildCreatePayload(form: EntryForm, ctx: { operator: boolean }): Built<Record<string, unknown>> {
  const errors: FieldErrors = {};
  const { apiBase, win, out } = checkCommon(form, errors);
  if (form.level === "installation" && !ctx.operator) errors.level = "Solo el operador crea modelos de instalación.";
  const credential = buildCredentialSpec(form, errors, ctx);
  if (Object.keys(errors).length) return { payload: null, errors };
  const payload: Record<string, unknown> = {
    level: form.level, name: form.name.trim(), provider: form.provider, real_model: form.real_model.trim(),
    protocol_family: form.protocol_family, api_base: apiBase || null, role: form.role,
    capability: form.capability, features: { ...form.features },
  };
  if (form.public_id.trim()) payload.public_id = form.public_id.trim();
  if (form.aggregator !== defaultAggregator(form.provider)) payload.is_aggregator = form.aggregator;
  if (win !== null) payload.context_window = win;
  if (out !== null) payload.max_output = out;
  const unsupported = parseParamList(form.unsupported);
  if (unsupported.length) payload.unsupported_params = unsupported;
  if (credential) payload.credential = credential;
  return { payload, errors };
}

/** Cuerpo del PATCH: solo lo que cambió respecto de la entrada. */
export function buildPatchPayload(form: EntryForm, e: EntryView, ctx: { operator: boolean }): Built<Record<string, unknown>> {
  const errors: FieldErrors = {};
  const { apiBase, win, out } = checkCommon(form, errors);
  const credential = buildCredentialSpec(form, errors, ctx);
  if (Object.keys(errors).length) return { payload: null, errors };
  const p: Record<string, unknown> = {};
  if (form.name.trim() !== e.name) p.name = form.name.trim();
  if (form.public_id.trim() && form.public_id.trim() !== e.public_id) p.public_id = form.public_id.trim();
  if (form.provider !== e.provider) p.provider = form.provider;
  if (form.real_model.trim() !== e.real_model) p.real_model = form.real_model.trim();
  if (form.protocol_family !== e.protocol_family) p.protocol_family = form.protocol_family;
  if (apiBase !== (e.api_base ?? "")) p.api_base = apiBase || null;
  if (form.role !== e.role) p.role = form.role;
  if (form.capability !== e.capability) p.capability = form.capability;
  if (form.aggregator !== e.is_aggregator) p.is_aggregator = form.aggregator;
  if (win !== null && win !== e.context_window) p.context_window = win;
  if (out !== null && out !== e.max_output) p.max_output = out;
  // El PATCH reemplaza el dict completo: se conservan las claves que la pantalla no muestra.
  if (FEATURES.some(f => form.features[f] !== Boolean(e.features?.[f]))) p.features = { ...e.features, ...form.features };
  const unsupported = parseParamList(form.unsupported);
  if (unsupported.join(",") !== (e.unsupported_params ?? []).join(",")) p.unsupported_params = unsupported;
  if (credential) p.credential = credential;
  if (!Object.keys(p).length) {
    return { payload: null, errors: { form: "No hay cambios para guardar." } };
  }
  return { payload: p, errors };
}

/** Archivar pide un motivo de al menos 3 caracteres (igual que la API). */
export function validateReason(reason: string): string | null {
  return reason.trim().length >= 3 ? null : "Contá por qué (al menos 3 caracteres).";
}

// ── ficha de cumplimiento ───────────────────────────────────────────────────

export type Tri = "yes" | "no" | "unknown";
export const TRI_LABELS: Record<Tri, string> = { unknown: "Desconocido", yes: "Sí", no: "No" };
export const triFrom = (v: boolean | null | undefined): Tri => (v === true ? "yes" : v === false ? "no" : "unknown");
export const triTo = (t: Tri): boolean | null => (t === "yes" ? true : t === "no" ? false : null);

export const TRANSFER_MECHANISMS = ["n/a", "dpf", "scc", "none", "unknown"] as const;
export const TRANSFER_LABELS: Record<string, string> = {
  "n/a": "No aplica (no hay transferencia)",
  dpf: "Marco de privacidad UE–EE. UU. (DPF)",
  scc: "Cláusulas contractuales tipo (SCC)",
  none: "Sin mecanismo",
  unknown: "Desconocido",
};

const SPECIAL_JURISDICTIONS: { value: string; label: string }[] = [
  { value: "unknown", label: "Desconocida" },
  { value: "EU", label: "Unión Europea (EU)" },
  { value: "US", label: "Estados Unidos (US)" },
  { value: "global", label: "Global (sin región fija)" },
  { value: "local", label: "Local (infraestructura propia)" },
];

/** Opciones de jurisdicción: valores especiales + países de dos letras. `extra` suma un valor ya
 *  guardado que no esté en la lista (para no perderlo al editar). */
export function jurisdictionOptions(opts: { none?: boolean; extra?: string | null } = {}): { value: string; label: string }[] {
  const out = [...SPECIAL_JURISDICTIONS];
  if (opts.none) out.push({ value: "none", label: "Ninguna (no se guardan registros)" });
  const seen = new Set(out.map(o => o.value.toLowerCase()));
  for (const j of JURISDICTIONS) {
    if (j.code.length <= 2 && !seen.has(j.code.toLowerCase())) {
      out.push({ value: j.code, label: `${j.label} (${j.code})` });
      seen.add(j.code.toLowerCase());
    }
  }
  if (opts.extra && !seen.has(opts.extra.toLowerCase())) out.push({ value: opts.extra, label: opts.extra });
  return out;
}

export interface SheetForm {
  provider_legal_entity: string;
  entity_jurisdiction: string;
  inference_jurisdiction: string;
  logs_jurisdiction: string;
  zero_data_retention: Tri;
  trains_on_data: Tri;
  transfer_mechanism: string;
  dpa_registry_id: string;
  eu_region_contracted: Tri;
  notes: string;
}

export function sheetToForm(s: SheetView): SheetForm {
  return {
    provider_legal_entity: s.provider_legal_entity ?? "",
    entity_jurisdiction: s.entity_jurisdiction ?? "",
    inference_jurisdiction: s.inference_jurisdiction || "unknown",
    logs_jurisdiction: s.logs_jurisdiction || "unknown",
    zero_data_retention: triFrom(s.zero_data_retention),
    trains_on_data: triFrom(s.trains_on_data),
    transfer_mechanism: s.transfer_mechanism || "unknown",
    dpa_registry_id: s.dpa_registry_id ?? "",
    eu_region_contracted: triFrom(s.eu_region_contracted),
    notes: s.notes ?? "",
  };
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Cuerpo del PUT de la ficha. El semáforo NO viaja nunca: lo calcula el backend (FR-003a). */
export function buildSheetPayload(form: SheetForm, e: Pick<EntryView, "is_aggregator">): Built<Record<string, unknown>> {
  const errors: FieldErrors = {};
  const dpa = form.dpa_registry_id.trim();
  if (dpa && !UUID_RE.test(dpa)) errors.dpa_registry_id = "Pegá el identificador del DPA tal como figura en el registro de DPAs.";
  if (form.provider_legal_entity.length > 256) errors.provider_legal_entity = "Demasiado largo (máximo 256 caracteres).";
  if (Object.keys(errors).length) return { payload: null, errors };
  return {
    payload: {
      provider_legal_entity: form.provider_legal_entity.trim() || null,
      entity_jurisdiction: form.entity_jurisdiction || null,
      inference_jurisdiction: form.inference_jurisdiction || "unknown",
      logs_jurisdiction: form.logs_jurisdiction || "unknown",
      zero_data_retention: triTo(form.zero_data_retention),
      trains_on_data: triTo(form.trains_on_data),
      transfer_mechanism: form.transfer_mechanism || "unknown",
      dpa_registry_id: dpa || null,
      eu_region_contracted: e.is_aggregator ? triTo(form.eu_region_contracted) : null,
      notes: form.notes.trim() || null,
    },
    errors,
  };
}

// ── credenciales (pestaña) ──────────────────────────────────────────────────

export type RevokeChoice = "replace" | "deactivate";

export function buildRevokeBody(
  inUse: boolean, choice: RevokeChoice | "", replacementId: string, reason: string,
): Built<Record<string, unknown>> {
  const errors: FieldErrors = {};
  const body: Record<string, unknown> = {};
  if (inUse) {
    if (!choice) errors.choice = "Elegí qué hacer con los modelos que la usan.";
    else if (choice === "replace") {
      if (!replacementId) errors.replacement_id = "Elegí la credencial de reemplazo.";
      else body.replacement_id = replacementId;
    } else body.deactivate_entries = true;
  }
  if (reason.trim()) body.reason = reason.trim();
  if (Object.keys(errors).length) return { payload: null, errors };
  return { payload: body, errors };
}

/** Proveedor de la primera entrada que usa la credencial (da la forma del valor al reemplazarla). */
export function providerOfCredential(cred: CredentialRow, entries: EntryView[]): Provider | null {
  return entries.find(e => e.credential?.id === cred.id)?.provider ?? null;
}

export const CREDENTIAL_SHAPE_CHOICES: { value: string; label: string; provider: Provider | null }[] = [
  { value: "api_key", label: "Clave de API (un solo valor)", provider: null },
  { value: "azure", label: "Azure OpenAI (clave y versión)", provider: "azure" },
  { value: "bedrock", label: "AWS Bedrock (claves y región)", provider: "bedrock" },
  { value: "vertex_ai", label: "Google Vertex AI (cuenta de servicio)", provider: "vertex_ai" },
];

export interface CredentialCreateForm {
  name: string;
  level: EntryLevel;
  mode: "secret" | "env_ref";
  shape: string;
  values: Record<string, string>;
  envName: string;
}

export const newCredentialForm = (): CredentialCreateForm =>
  ({ name: "", level: "tenant", mode: "secret", shape: "api_key", values: {}, envName: "" });

export function buildCredentialCreate(form: CredentialCreateForm, ctx: { operator: boolean }): Built<Record<string, unknown>> {
  const errors: FieldErrors = {};
  if (!form.name.trim()) errors.name = "Poné un nombre.";
  if (form.level === "installation" && !ctx.operator) errors.level = "Solo el operador crea credenciales de instalación.";
  if (form.mode === "env_ref") {
    if (!ctx.operator || form.level !== "installation") errors.mode = "Las referencias del servidor solo valen para credenciales de instalación.";
    const env = normalizeEnvName(form.envName);
    if (!env.name) errors["cred.env"] = env.error ?? "Obligatorio.";
    if (Object.keys(errors).length) return { payload: null, errors };
    return { payload: { name: form.name.trim(), kind: "env_ref", env_name: env.name, level: form.level }, errors };
  }
  const provider = CREDENTIAL_SHAPE_CHOICES.find(c => c.value === form.shape)?.provider ?? null;
  const built = buildSecretValue(valueFields(provider), form.values);
  Object.assign(errors, built.errors);
  if (built.value === null && !Object.keys(built.errors).length) errors.credential = "Cargá el valor de la credencial.";
  if (Object.keys(errors).length) return { payload: null, errors };
  return { payload: { name: form.name.trim(), kind: "secret", value: built.value, level: form.level }, errors };
}

/** Etiqueta para elegir una credencial existente: nombre + huella (nunca el valor). */
export const credentialOptionLabel = (c: Pick<CredentialRow, "name" | "fingerprint">) =>
  c.fingerprint ? `${c.name} · huella ${c.fingerprint}` : c.name;

/** Fila del registro de DPAs que sirve la API para el selector de la ficha (sin documento ni notas). */
export interface DpaRow {
  id: string;
  provider_name: string | null;
  dpa_type: string | null;
  processing_region: string | null;
  expiration_date: string | null;
  vigente: boolean;
}

const norm = (v: string | null | undefined) => (v ?? "").toLowerCase().replace(/[^a-z0-9]/g, "");

/** El DPA cuyo proveedor coincide con el de la entrada (solo se sugiere: nunca se elige solo). */
export function suggestDpa(provider: string, dpas: DpaRow[]): DpaRow | null {
  const p = norm(provider);
  if (!p) return null;
  const hits = dpas.filter(d => {
    const n = norm(d.provider_name);
    return n !== "" && (n.includes(p) || p.includes(n));
  });
  return hits.find(d => d.vigente) ?? hits[0] ?? null;
}

export function dpaLabel(d: DpaRow): string {
  const partes = [d.provider_name || "Sin proveedor", d.processing_region || "región sin indicar"];
  partes.push(d.expiration_date ? `vence ${d.expiration_date}` : "sin vencimiento");
  return partes.join(" · ") + (d.vigente ? "" : " (no vigente)");
}
