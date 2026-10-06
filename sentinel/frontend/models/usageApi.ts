// Cliente de `GET /api/v1/catalog/usage` (contracts/admin-modelos.md): consumo de la organización
// de la sesión por modelo o por destino. Solo cifras: nunca contenido de pedidos.
import { authStorage } from "../../../frontend/src/services/auth";
import { describeApiError } from "../redirect/helpers";

export type UsageGroup = "model" | "destination";

export interface UsageRow {
  key: string;
  name: string;
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  latency_avg_ms: number | null;
  latency_p95_ms: number | null;
  /** `measured`: costo calculado con los tokens reales; `flat`: tarifa plana (no se mide por token). */
  billing: "measured" | "flat";
}

export interface UsageTotals {
  requests: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
}

export interface UsageReport {
  from: string;
  to: string;
  group: UsageGroup;
  data: UsageRow[];
  totals: UsageTotals;
}

export class UsageApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "UsageApiError";
    this.status = status;
    Object.setPrototypeOf(this, UsageApiError.prototype);
  }
}

export async function fetchUsage(from: string, to: string, group: UsageGroup): Promise<UsageReport> {
  const token = authStorage.getToken();
  const headers: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
  const qs = new URLSearchParams({ from, to, group });
  let res: Response;
  try {
    res = await fetch(`/api/v1/catalog/usage?${qs}`, { headers });
  } catch {
    throw new UsageApiError(describeApiError(0, null), 0);
  }
  if (res.status === 401) {
    authStorage.clear();
    window.location.reload();
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new UsageApiError(describeApiError(res.status, body), res.status);
  }
  return res.json();
}
