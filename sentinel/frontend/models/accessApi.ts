// Cliente de `/api/v1/access/*` (contracts/admin-perfiles.md, US2): perfiles, techos por riesgo del
// AI Act, asignaciones, perfil por llave y accesos efectivos. Mismo origen y sesión que el resto de la
// consola; los errores salen ya traducidos y llevan el estado HTTP (un 404 en `/profiles` significa que
// esta instalación todavía no tiene el backend de perfiles) y, si aplica, la marca `empty` del 422.
import { authStorage } from "../../../frontend/src/services/auth";
import { describeApiError } from "../redirect/helpers";

const API = "/api/v1/access";

export type ProfileKind = "company" | "ceiling" | "key";
export type RuleEffect = "include" | "exclude";
export type RuleSelector = "semaforo" | "jurisdiccion" | "proveedor" | "capacidad" | "entrada";
export type RiskLevel = "minimal" | "limited" | "high_risk_annex1" | "high_risk_annex3";
export type SubjectType = "tenant" | "group" | "user";

export interface ProfileRule { effect: RuleEffect; selector: RuleSelector; value: string }
export interface Profile {
  id: string;
  kind: ProfileKind;
  name: string;
  rules: ProfileRule[];
  archived: boolean;
  seeded: boolean;
  /** Cantidad de entradas del catálogo que el perfil permite hoy. */
  allows: number;
  version: number;
}
export type Ceilings = Record<RiskLevel, string | null>;
export interface Assignment { subject_type: SubjectType; subject_id: string; profiles: string[] }
export interface KeyProfile { key_id: string; profile_id: string | null; warnings?: string[] }
export interface EffectiveModel { id: string; public_id: string; name: string; provider: string; semaforo: { estado: string } | string | null }
export interface EffectiveAccess {
  permitidos: EffectiveModel[];
  restringe: boolean;
  techo: { risk_level: string; origen: string; count: number } | null;
  perfiles: { id: string; name: string; origen: "user" | "group" | "tenant" | string }[];
  llave: { profile_id: string | null } | null;
  version: number;
}
export interface PreviewResult { allowed: boolean; motivo: string | null; permitidos_origen?: string | null }
export type Subject = { user?: string; group?: string; key?: string };

export class AccessApiError extends Error {
  readonly status: number;
  /** El 422 de «el sujeto quedaría sin modelos»: se reintenta con `confirm_empty`. */
  readonly empty: boolean;
  constructor(message: string, status: number, empty = false) {
    super(message);
    this.name = "AccessApiError";
    this.status = status;
    this.empty = empty;
    Object.setPrototypeOf(this, AccessApiError.prototype);
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = authStorage.getToken();
  const headers: Record<string, string> = { ...(init.body ? { "Content-Type": "application/json" } : {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${API}${path}`, { ...init, headers });
  } catch {
    throw new AccessApiError(describeApiError(0, null), 0);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new AccessApiError(describeApiError(res.status, body), res.status, (body as { empty?: unknown } | null)?.empty === true);
  }
  if (res.status === 204) return undefined as T;
  return res.json().catch(() => undefined as T);
}

const json = (method: string, body: unknown): RequestInit => ({ method, body: JSON.stringify(body) });
const enc = encodeURIComponent;

export const accessApi = {
  profiles: (includeArchived = false) =>
    call<{ data: Profile[] }>(`/profiles${includeArchived ? "?include_archived=true" : ""}`).then(r => r.data),
  createProfile: (body: { kind: ProfileKind; name: string; rules: ProfileRule[] }) => call<Profile>("/profiles", json("POST", body)),
  patchProfile: (id: string, body: { name?: string; rules?: ProfileRule[] }) => call<Profile>(`/profiles/${enc(id)}`, json("PATCH", body)),
  archiveProfile: (id: string, reason: string) => call<Profile>(`/profiles/${enc(id)}/archive`, json("POST", { reason })),

  ceilings: () => call<{ data: Ceilings }>("/ceilings").then(r => r.data),
  putCeilings: (body: Partial<Ceilings>) => call<{ data: Ceilings }>("/ceilings", json("PUT", body)).then(r => r.data),

  assignments: (type: SubjectType, id: string) => call<Assignment>(`/assignments/${type}/${enc(id)}`),
  putAssignments: (type: SubjectType, id: string, profiles: string[], confirmEmpty = false) =>
    call<Assignment>(`/assignments/${type}/${enc(id)}`, json("PUT", { profiles, ...(confirmEmpty ? { confirm_empty: true } : {}) })),

  keyProfile: (keyId: string) => call<KeyProfile>(`/keys/${enc(keyId)}/profile`),
  putKeyProfile: (keyId: string, profileId: string | null) =>
    call<KeyProfile>(`/keys/${enc(keyId)}/profile`, json("PUT", { profile_id: profileId })),

  effective: (q: Subject) => {
    const qs = new URLSearchParams(Object.entries(q).filter(([, v]) => v) as [string, string][]);
    return call<EffectiveAccess>(`/effective?${qs}`);
  },
  preview: (body: Subject & { model: string }) => call<PreviewResult>("/preview", json("POST", body)),
};
