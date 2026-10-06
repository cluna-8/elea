// Cliente de `/api/v1/catalog/*` (contracts/admin-catalogo.md). Mismo origen y misma sesión que el
// resto de la consola; los errores salen ya traducidos (`describeApiError`, el mismo de la 068).
// Las credenciales son solo escritura: ninguna respuesta trae un valor, solo huella.
import { authStorage } from "../../../frontend/src/services/auth";
import { describeApiError } from "../redirect/helpers";
import type { CredentialRow, DpaRow, EntryView } from "./helpers";

const API = "/api/v1/catalog";

export class CatalogApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "CatalogApiError";
    this.status = status;
    Object.setPrototypeOf(this, CatalogApiError.prototype);
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
    throw new CatalogApiError(describeApiError(0, null), 0);
  }
  if (res.status === 401) {
    authStorage.clear();
    window.location.reload();
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new CatalogApiError(describeApiError(res.status, body), res.status);
  }
  if (res.status === 204) return undefined as T;
  return res.json().catch(() => undefined as T);
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });

export const catalogApi = {
  entries: (includeArchived = false) =>
    call<{ data: EntryView[] }>(`/entries${includeArchived ? "?include_archived=true" : ""}`).then(r => r.data),
  createEntry: (body: Record<string, unknown>) => call<EntryView>("/entries", json("POST", body)),
  patchEntry: (id: string, body: Record<string, unknown>) => call<EntryView>(`/entries/${id}`, json("PATCH", body)),
  archiveEntry: (id: string, reason: string) => call<EntryView>(`/entries/${id}/archive`, json("POST", { reason })),
  /** Devuelve la vista completa con el semáforo recalculado por el backend. */
  putSheet: (id: string, body: Record<string, unknown>) => call<EntryView>(`/entries/${id}/sheet`, json("PUT", body)),
  putOffers: (id: string, tenants: string[], reason: string) =>
    call<{ entry_id: string; tenants: string[] }>(`/entries/${id}/offers`, json("PUT", { tenants, reason: reason || null })),

  /** DPAs del registro de la organización (solo metadatos), para elegir uno en la ficha. */
  dpas: () => call<{ data: DpaRow[] }>("/dpas").then(r => r.data ?? []),

  credentials: () => call<{ data: CredentialRow[] }>("/credentials").then(r => r.data),
  createCredential: (body: Record<string, unknown>) => call<CredentialRow>("/credentials", json("POST", body)),
  replaceCredential: (id: string, value: string | Record<string, unknown>) =>
    call<CredentialRow>(`/credentials/${id}/replace`, json("POST", { value })),
  revokeCredential: (id: string, body: Record<string, unknown>) =>
    call<{ id: string; status: string }>(`/credentials/${id}/revoke`, json("POST", body)),
};
