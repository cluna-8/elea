// Cliente de la pantalla «Modelos» sobre `/api/v1/catalog/*` (contracts/admin-modelos.md). Mismo
// patrón que `catalog/api.ts`: mismo origen, misma sesión y errores ya traducidos. Ninguna respuesta
// trae el valor de una credencial.
import { authStorage } from "../../../frontend/src/services/auth";
import { describeApiError } from "../redirect/helpers";
import type { EntryView } from "../catalog/helpers";
import type { ProvidersResponse, RefModelsResponse } from "./guided";

const API = "/api/v1/catalog";

export class ModelsApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ModelsApiError";
    this.status = status;
    Object.setPrototypeOf(this, ModelsApiError.prototype);
  }
}

/** `soft`: una sesión vencida o una ruta ausente no recargan la consola (se usa en lo opcional). */
async function call<T>(path: string, init: RequestInit = {}, soft = false): Promise<T> {
  const token = authStorage.getToken();
  const headers: Record<string, string> = { ...(init.body ? { "Content-Type": "application/json" } : {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { ...init, headers: { ...headers, ...(init.headers as Record<string, string> | undefined) } });
  } catch {
    throw new ModelsApiError(describeApiError(0, null), 0);
  }
  if (res.status === 401 && !soft) {
    authStorage.clear();
    window.location.reload();
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ModelsApiError(describeApiError(res.status, body), res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json().catch(() => undefined as T);
}

const post = (body?: unknown): RequestInit => ({ method: "POST", ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

/** Fila heredada del motor (modelo que existía antes del catálogo). Solo se leen estos campos. */
export interface LegacyModel {
  model_name: string;
  provider?: string | null;
  real_model?: string | null;
  role?: string | null;
  adopted?: boolean;
}

/** El backend nombra `real_model`/`context_window`/`max_output` a lo que la pantalla llama `id`/
 *  `max_input_tokens`/`max_output_tokens`: se traduce acá, en el borde, para no ensuciar los componentes. */
export function normalizeRefModels(r: unknown): RefModelsResponse {
  const raw = (r ?? {}) as { data?: Record<string, unknown>[]; total?: number };
  const data = (Array.isArray(raw.data) ? raw.data : []).map(m => ({
    id: String(m.id ?? m.real_model ?? ""),
    role: String(m.role ?? "text"),
    max_input_tokens: (m.max_input_tokens ?? m.context_window ?? null) as number | null,
    max_output_tokens: (m.max_output_tokens ?? m.max_output ?? null) as number | null,
    price: (m.price ?? null) as RefModelsResponse["data"][number]["price"],
    features: (m.features ?? null) as RefModelsResponse["data"][number]["features"],
  })).filter(m => m.id);
  return { data, total: typeof raw.total === "number" ? raw.total : data.length };
}

/** Las filas heredadas traen `model_id` (modelo real); la pantalla lo muestra como `real_model`. */
export function normalizeLegacy(rows: unknown): LegacyModel[] {
  return (Array.isArray(rows) ? rows : []).map((m: Record<string, unknown>) => ({
    model_name: String(m.model_name ?? ""),
    provider: (m.provider ?? null) as string | null,
    real_model: (m.real_model ?? m.model_id ?? null) as string | null,
    role: (m.role ?? null) as string | null,
    adopted: Boolean(m.adopted),
  })).filter(m => m.model_name);
}

/** Estado del corte a una sola fuente de modelos (`GET /catalog/status`). */
export interface CatalogStatus {
  catalog_only: boolean;
  direct_enabled: boolean;
  legacy_total: number;
  legacy_pending: number;
}

export interface AdoptAllResult { adopted: number; skipped: number; failed: number }

export const modelsApi = {
  providers: () => call<ProvidersResponse>("/providers"),
  providerModels: (provider: string, opts: { q?: string; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    if (opts.q) qs.set("q", opts.q);
    qs.set("limit", String(opts.limit ?? 50));
    qs.set("offset", String(opts.offset ?? 0));
    return call<unknown>(`/providers/${encodeURIComponent(provider)}/models?${qs}`).then(normalizeRefModels);
  },
  refreshReference: () => call<{ fetched_at?: string | null }>("/reference/refresh", post()),
  bulkCreate: (body: Record<string, unknown>) => call<unknown>("/entries/bulk", post(body)),
  /** Si la ruta no existe (404) o no hay permiso (401/403), la lista sigue sin filas heredadas. */
  legacyModels: async (): Promise<LegacyModel[]> => {
    try {
      const r = await call<{ data?: LegacyModel[] }>("/legacy-models", {}, true);
      return normalizeLegacy(r?.data).filter(m => !m.adopted);   // los ya adoptados salen en el catálogo
    } catch {
      return [];
    }
  },
  /** Si la ruta no existe (404) o no hay permiso, el aviso del corte simplemente no se muestra. */
  status: async (): Promise<CatalogStatus | null> => {
    try { return await call<CatalogStatus>("/status", {}, true); } catch { return null; }
  },
  adoptAll: () => call<AdoptAllResult>("/legacy-models/adopt-all", post()),
  adoptLegacy: (modelName: string) => call<EntryView>(`/legacy-models/${encodeURIComponent(modelName)}/adopt`, post()),
};
