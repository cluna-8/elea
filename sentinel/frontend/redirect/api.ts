// Cliente de `/api/v1/redirect/*` (contracts/admin-api.md) y de los listados de la consola
// que alimentan los selectores de alcance. Mismo origen y misma sesión que el resto de la
// consola; los errores salen ya traducidos (`describeApiError`).
import { authStorage } from "../../../frontend/src/services/auth";
import { describeApiError, Destination, Lookups, PolicyRow, PostureRow, PublishedModel, Rule } from "./helpers";
import type { CostComparison, FidelityReport, Kit } from "./insights";

const API = "/api/v1";

export class RedirectApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "RedirectApiError";
    this.status = status;
    Object.setPrototypeOf(this, RedirectApiError.prototype);
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = authStorage.getToken();
  const headers: Record<string, string> = { ...(init.body ? { "Content-Type": "application/json" } : {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { ...init, headers: { ...headers, ...(init.headers as Record<string, string> | undefined) } });
  } catch {
    throw new RedirectApiError(describeApiError(0, null), 0);
  }
  if (res.status === 401) {
    authStorage.clear();
    window.location.reload();
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new RedirectApiError(describeApiError(res.status, body), res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json().catch(() => undefined as T);
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export const redirectApi = {
  capabilities: () => call<{ operator: boolean }>("/redirect/capabilities"),
  destinations: () => call<{ data: Destination[] }>("/redirect/destinations").then(r => r.data),
  // Los destinos son las entradas del catálogo (069 E3): se escriben con `catalogApi` (Modelos); acá solo se leen.

  published: () => call<{ data: PublishedModel[] }>("/redirect/published-models").then(r => r.data),
  createPublished: (body: Record<string, unknown>) => call<PublishedModel>("/redirect/published-models", json("POST", body)),
  deletePublished: (id: string) => call<void>(`/redirect/published-models/${id}`, { method: "DELETE" }),

  rules: () => call<{ data: Rule[] }>("/redirect/rules").then(r => r.data),
  createRule: (body: Record<string, unknown>) => call<Rule>("/redirect/rules", json("POST", body)),
  patchRule: (id: string, body: { strategy?: "order" | "cheapest" }) => call<Rule>(`/redirect/rules/${id}`, json("PATCH", body)),
  deleteRule: (id: string) => call<void>(`/redirect/rules/${id}`, { method: "DELETE" }),

  policy: () => call<{ data: PolicyRow[] }>("/redirect/policy").then(r => r.data),
  putPolicy: (path: string, body: unknown) => call<PolicyRow>(`/redirect${path}`, json("PUT", body)),

  postures: () => call<{ data: PostureRow[]; effective_tenant_redirected: { mode: string; jurisdictions: string[]; explicit: boolean } }>("/redirect/postures"),
  createPosture: (body: Record<string, unknown>) => call<PostureRow>("/redirect/postures", json("POST", body)),
  deletePosture: (id: string, reason: string) => call<unknown>(`/redirect/postures/${id}`, json("DELETE", { reason })),

  preview: (body: Record<string, unknown>) => call<PreviewResult>("/redirect/resolve-preview", json("POST", body)),

  /** Grupos, usuarios y conexiones para elegir alcances por nombre. Un listado que falla
   *  (p. ej. por rol) deja su selector vacío sin tumbar la pantalla. */
  lookups: async (): Promise<Lookups> => {
    const [groups, users, keys] = await Promise.all([
      call<{ id: string; name: string }[]>("/users/groups").catch(() => []),
      call<{ id: string; username: string }[]>("/users").catch(() => []),
      call<{ id: string; name: string }[]>("/keys").catch(() => []),
    ]);
    const arr = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);
    return {
      groups: arr<{ id: string; name: string }>(groups).map(g => ({ id: String(g.id), name: g.name })),
      users: arr<{ id: string; username: string }>(users).map(u => ({ id: String(u.id), username: u.username })),
      keys: arr<{ id: string; name: string }>(keys).map(k => ({ id: String(k.id), name: k.name })),
    };
  },
};

export interface PreviewResult {
  state: string;
  posture: { mode: string; jurisdictions: string[] };
  result: "resolved" | "unavailable";
  destination_id?: string;
  destination_name?: string;
  engine_model?: string;
  fidelity?: string;
  rule_id?: string | null;
  forced_masking?: boolean;
  substitution_reason?: string | null;
  kind?: string;
  error_class?: string;
  skipped: { destination_id: string; reason: string }[];
}

// ── US5: kits, prueba de fidelidad y costos ──────────────────────────────────

export const us5Api = {
  kit: (tool: string, scope: string, includeCredential: boolean) =>
    call<Kit>(`/redirect/kits/${tool}?scope=${encodeURIComponent(scope)}&include_credential=${includeCredential}`),
  runFidelity: (body: { destination_id: string; tool: string; tool_version?: string }) =>
    call<FidelityReport>("/redirect/fidelity-runs", json("POST", body)),
  fidelityRuns: (destinationId?: string) =>
    call<{ data: FidelityReport[] }>(`/redirect/fidelity-runs${destinationId ? `?destination_id=${destinationId}` : ""}`)
      .then(r => r.data),
  costs: (q: { from: string; to: string; scope: string }) =>
    call<CostComparison>(`/redirect/cost-comparison?from=${encodeURIComponent(q.from)}&to=${encodeURIComponent(q.to)}&scope=${encodeURIComponent(q.scope)}`),
};
