// Funciones puras del alta guiada de «Modelos» (spec 069, US8): proveedores y modelos que ofrece el
// motor, sugerencias de precio/contexto, bloque «Avanzado» y armado del alta masiva.
// Sin React ni fetch: se testean solas (sentinel/frontend/models/__tests__/guided.test.ts).
import { PROVIDERS, PROVIDER_LABELS, REQUIRES_API_BASE } from "../redirect/catalog";
import { Built, CredentialFieldSpec, credentialFields, FieldErrors, parseTokens } from "../redirect/helpers";
import { buildSecretValue, EntryLevel, FEATURE_LABELS, FEATURES } from "../catalog/helpers";

// ── tipos de la API (contracts/admin-modelos.md) ────────────────────────────

export interface ProviderField { key: string; label: string; required: boolean; field_type: string }
export interface ProviderInfo {
  provider: string;
  display_name: string;
  supported: boolean;
  reason?: string | null;
  credential_fields: ProviderField[];
  example_model?: string | null;
}
export interface ProvidersResponse { available: boolean; fetched_at: string | null; data: ProviderInfo[] }

export interface RefPrice {
  input?: number | null; output?: number | null; cache_read?: number | null; cache_write?: number | null;
}
export interface RefModel {
  id: string;
  role: string;
  max_input_tokens?: number | null;
  max_output_tokens?: number | null;
  price?: RefPrice | null;
  features?: Record<string, boolean | undefined> | null;
}
export interface RefModelsResponse { data: RefModel[]; total: number }

// ── proveedores ─────────────────────────────────────────────────────────────

const fold = (s: string) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

export function filterProviders(list: ProviderInfo[], q: string): ProviderInfo[] {
  const needle = fold(q.trim());
  if (!needle) return list;
  return list.filter(p => fold(p.display_name).includes(needle) || fold(p.provider).includes(needle));
}

/** Los campos que exige el proveedor, como especificación del formulario de secretos. */
export function toFieldSpecs(fields: ProviderField[]): CredentialFieldSpec[] {
  return fields.map(f => {
    const kind = f.field_type.toLowerCase();
    const multiline = kind === "json" || kind === "textarea";
    return {
      name: f.key, label: f.label, required: f.required,
      secret: multiline || ["password", "secret"].includes(kind) || /key|secret|token/.test(f.key),
      multiline,
    };
  });
}

/** Lista local de proveedores (la que el catálogo ya conoce): se usa cuando el motor no responde. */
export function localProviders(): ProviderInfo[] {
  return PROVIDERS.map(p => ({
    provider: p,
    display_name: PROVIDER_LABELS[p],
    supported: true,
    credential_fields: credentialFields(p).map(f => ({
      key: f.name, label: f.label, required: f.required, field_type: f.multiline ? "json" : f.secret ? "password" : "text",
    })),
  }));
}

const needsBase = (provider: string) => (REQUIRES_API_BASE as readonly string[]).includes(provider);
export { needsBase as providerNeedsApiBase };

// ── etiquetas y sugerencias ─────────────────────────────────────────────────

const ROLE_LABELS: Record<string, string> = {
  text: "Texto", embeddings: "Embeddings", image: "Imagen", audio: "Audio", rerank: "Reordenamiento",
};
export const MODEL_ROLES = ["text", "embeddings", "image", "audio", "rerank"] as const;
export const roleLabel = (role: string): string => ROLE_LABELS[role] ?? role;

const nf = new Intl.NumberFormat("es", { maximumFractionDigits: 4 });
const perMillion = (v: number) => `US$ ${nf.format(Math.round(v * 1e6 * 1e6) / 1e6)}`;

/** Precio sugerido (por token, como lo da el motor) expresado por millón de tokens. */
export function formatPrice(price: RefPrice | null | undefined): string | null {
  if (price?.input == null || price?.output == null) return null;
  return `${perMillion(price.input)} / ${perMillion(price.output)} por millón de tokens (entrada / salida)`;
}

export function formatContext(m: Pick<RefModel, "max_input_tokens" | "max_output_tokens">): string | null {
  const parts: string[] = [];
  if (m.max_input_tokens) parts.push(`Contexto ${m.max_input_tokens.toLocaleString("es-AR")}`);
  if (m.max_output_tokens) parts.push(`salida ${m.max_output_tokens.toLocaleString("es-AR")}`);
  return parts.length ? parts.join(" · ") : null;
}

export function featureList(features: Record<string, boolean | undefined> | null | undefined): string[] {
  return FEATURES.filter(f => features?.[f]).map(f => FEATURE_LABELS[f]);
}

export function formatFetchedAt(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleString("es", { dateStyle: "medium", timeStyle: "short" });
}

// ── avanzado ────────────────────────────────────────────────────────────────

const CREDENTIAL_KEY = /(api[_-]?key|secret|password|authorization|bearer)/i;

function hasCredentialKey(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  return Object.entries(value as Record<string, unknown>).some(([k, v]) => CREDENTIAL_KEY.test(k) || hasCredentialKey(v));
}

/** JSON libre del bloque «Avanzado»: vacío = nada; debe ser un objeto sin credenciales incrustadas
 *  (el backend valida las claves admitidas y rechaza igual). */
export function parseAdvanced(text: string): { value: Record<string, unknown> | null; error?: string } {
  if (!text.trim()) return { value: null };
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { value: null, error: "El JSON no es válido. Revisá comas y llaves." };
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { value: null, error: "Tiene que ser un objeto JSON, por ejemplo {\"temperature\": 0.2}." };
  }
  if (hasCredentialKey(parsed)) {
    return { value: null, error: "No pongas credenciales acá: cargalas en el paso Credencial." };
  }
  return { value: parsed as Record<string, unknown> };
}

export interface LimitsForm {
  rpm: string; tpm: string; max_parallel_requests: string; timeout: string; num_retries: string;
}
export const emptyLimits = (): LimitsForm => ({ rpm: "", tpm: "", max_parallel_requests: "", timeout: "", num_retries: "" });

/** `num_retries` admite cero; el resto, enteros positivos. */
export function buildLimits(form: LimitsForm): { limits: Record<string, number> | null; errors: FieldErrors } {
  const errors: FieldErrors = {};
  const out: Record<string, number> = {};
  (Object.keys(form) as (keyof LimitsForm)[]).forEach(k => {
    if (!form[k].trim()) return;
    const parsed = parseTokens(form[k]);
    const zeroOk = k === "num_retries" && form[k].trim() === "0";
    if (zeroOk) { out[k] = 0; return; }
    if (parsed.error || parsed.value === null) errors[`limits.${k}`] = "Poné un número entero positivo.";
    else out[k] = parsed.value;
  });
  return { limits: Object.keys(out).length && !Object.keys(errors).length ? out : null, errors };
}

// ── armado del alta masiva ──────────────────────────────────────────────────

export interface SelectedModel { real_model: string; name: string; accept_suggestion: boolean }

export function toggleModel(selected: SelectedModel[], id: string, hasSuggestion = true): SelectedModel[] {
  return selected.some(m => m.real_model === id)
    ? selected.filter(m => m.real_model !== id)
    : [...selected, { real_model: id, name: "", accept_suggestion: hasSuggestion }];
}

export interface GuidedState {
  provider: string;
  level: EntryLevel;
  selected: SelectedModel[];
  credMode: "existing" | "new" | "none";
  credentialId: string;
  newName: string;
  values: Record<string, string>;
  apiBase: string;
  advancedText: string;
  limits: LimitsForm;
  baseModel: string;
  /** Solo OpenRouter (agregador): los proveedores finales a los que se permite mandar el pedido. */
  providersAllowlist: string;
}

/** Proveedores permitidos de un agregador: separados por coma, espacio o línea; sin vacíos ni repetidos. */
export function parseProvidersAllowlist(text: string): string[] {
  return [...new Set(text.split(/[\s,]+/).map(t => t.trim()).filter(Boolean))];
}

export const providerNeedsAllowlist = (provider: string) => provider === "openrouter";

export const newGuidedState = (provider = ""): GuidedState => ({
  provider, level: "tenant", selected: [], credMode: "new", credentialId: "", newName: "", values: {},
  apiBase: "", advancedText: "", limits: emptyLimits(), baseModel: "", providersAllowlist: "",
});

export function buildBulkPayload(
  st: GuidedState, fields: CredentialFieldSpec[], ctx: { operator: boolean },
): Built<Record<string, unknown>> {
  const errors: FieldErrors = {};
  if (!st.provider) errors.provider = "Elegí un proveedor.";
  if (!st.selected.length) errors.models = "Elegí al menos un modelo.";
  if (st.level === "installation" && !ctx.operator) errors.level = "Solo el operador crea modelos de instalación.";

  const apiBase = st.apiBase.trim();
  if (needsBase(st.provider) && !apiBase) errors.api_base = "Este proveedor necesita la dirección base.";
  if (apiBase && !/^https?:\/\//i.test(apiBase)) errors.api_base = "La dirección debe empezar con http:// o https://.";

  let credential: Record<string, unknown> | undefined;
  const needsSecret = fields.some(f => f.required);
  if (st.credMode === "existing") {
    if (!st.credentialId) errors.credential = "Elegí una credencial.";
    else credential = { id: st.credentialId };
  } else if (st.credMode === "new") {
    const built = buildSecretValue(fields, st.values);
    Object.assign(errors, built.errors);
    if (built.value === null) {
      if (!Object.keys(built.errors).length) {
        errors.credential = needsSecret ? "Cargá la credencial o elegí una existente." : "Cargá el valor o elegí «Sin credencial».";
      }
    } else {
      credential = { new: { name: st.newName.trim() || `Credencial de ${st.provider}`, value: built.value } };
    }
  } else if (needsSecret) {
    errors.credential = "Este proveedor requiere credencial.";
  }

  const allowlist = providerNeedsAllowlist(st.provider) ? parseProvidersAllowlist(st.providersAllowlist) : [];
  if (providerNeedsAllowlist(st.provider) && !allowlist.length) {
    errors.providers_allowlist = "OpenRouter necesita los proveedores permitidos: la lista de a quién se le puede mandar el pedido.";
  }

  const advanced = parseAdvanced(st.advancedText);
  if (advanced.error) errors.advanced = advanced.error;
  const limits = buildLimits(st.limits);
  Object.assign(errors, limits.errors);

  if (Object.keys(errors).length) return { payload: null, errors };
  const payload: Record<string, unknown> = {
    provider: st.provider,
    level: st.level,
    ...(credential ? { credential } : {}),
    // `advanced`, `limits` y `base_model` van DENTRO de cada modelo (el cuerpo del pedido no los admite)
    models: st.selected.map(m => ({
      real_model: m.real_model,
      ...(m.name.trim() ? { name: m.name.trim() } : {}),
      accept_suggestion: m.accept_suggestion,
      ...(advanced.value ? { advanced: advanced.value } : {}),
      ...(limits.limits ? { limits: limits.limits } : {}),
      ...(st.baseModel.trim() ? { base_model: st.baseModel.trim() } : {}),
    })),
  };
  if (apiBase) payload.api_base = apiBase;
  if (allowlist.length) payload.provider_options = { providers_allowlist: allowlist };
  return { payload, errors };
}

// ── resultado por modelo (207) ──────────────────────────────────────────────

export interface BulkRow { model: string; ok: boolean; message: string }

const sentence = (s: string) => {
  const t = s.trim();
  return t ? `${t.charAt(0).toUpperCase()}${t.slice(1)}${/[.!?]$/.test(t) ? "" : "."}` : "";
};

/** Tolerante con la forma del 207: `results` o `data`, con `ok`, `status` numérico o textual. */
export function bulkRows(body: unknown): BulkRow[] {
  const b = body as { results?: unknown; data?: unknown } | null;
  const list = Array.isArray(b?.results) ? b?.results : Array.isArray(b?.data) ? b?.data : [];
  return (list as Record<string, unknown>[]).map(r => {
    const status = r.status;
    const failed = r.ok === false || Boolean(r.error)
      || status === "error" || status === "failed" || (typeof status === "number" && status >= 400);
    const reason = String(r.error ?? r.detail ?? r.message ?? "");
    return {
      model: String(r.real_model ?? r.model ?? r.id ?? ""),
      ok: !failed,
      message: failed ? sentence(reason) || "No se pudo crear." : "Creado",
    };
  });
}
