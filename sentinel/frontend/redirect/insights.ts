// Funciones puras de las pestañas Kits, Fidelidad y Costos (US5): alcance → parámetro de la API,
// formato de importes, períodos y mensajes de error en castellano. Se testean solas
// (sentinel/frontend/redirect/__tests__/insights.test.ts).
import { DETAIL_LABELS, ScopeType } from "./catalog";

export interface KitFile { path: string; content: string; install_path?: string }
export interface Kit {
  tool: string;
  face: string;
  scope: string;
  catalog_version: string;
  uses_credential: boolean;
  issued_key_id: string | null;
  models: string[];
  files: KitFile[];
  notes: string[];
  context_window: number | null;
}

export interface FidelityResult { capability: string; name: string; passed: boolean; detail_code: string; silent: boolean }
export interface FidelityReport {
  id: string;
  destination_id: string;
  face: string;
  tool: string;
  tool_version: string | null;
  corpus_version: string;
  results: FidelityResult[];
  verdict: "apto" | "no_apto" | "incompleto";
  complete: boolean;
  pass_rate: number;
  cost: number;
  run_at: string;
  regressions?: { capability: string; name: string; detail_code: string }[];
  compared_with?: { id: string; tool_version: string | null; run_at: string } | null;
}

export interface CostLine {
  requests: number;
  cost_real: number;
  cost_real_comparable: number;
  cost_hypothetical: number | null;
  savings: number | null;
  without_reference: number;
  estimated_real: number;
}
export interface CostComparison {
  totals: CostLine;
  by_destination: (CostLine & { destination_id: string; destination_name: string | null })[];
  by_scope: (CostLine & { scope_type: ScopeType; scope_value: string })[];
  shadow_requests: number;
  truncated: boolean;
  from: string;
  to: string;
  scope: string;
}

/** `tenant` o `<tipo>:<id>`, el formato de `scope` de las rutas de US5. */
export function scopeParam(type: ScopeType, value: string): string {
  return type === "tenant" ? "tenant" : `${type}:${value}`;
}

export function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const digits = Math.abs(value) >= 1 ? 2 : Math.abs(value) >= 0.01 ? 4 : 6;
  return `US$ ${value.toFixed(digits)}`;
}

export function detailLabel(code: string): string {
  if (DETAIL_LABELS[code]) return DETAIL_LABELS[code];
  const http = /^http_(\d{3})$/.exec(code);
  return http ? `El destino respondió con error ${http[1]}` : code;
}

const ymd = (d: Date) => d.toISOString().slice(0, 10);

/** Últimos `days` días, ambos extremos como fecha (YYYY-MM-DD). */
export function defaultPeriod(now: Date, days = 30): { from: string; to: string } {
  return { from: ymd(new Date(now.getTime() - days * 86_400_000)), to: ymd(now) };
}

/** Fechas del formulario → intervalo [from, to) en UTC: `to` incluye el día completo. */
export function periodQuery(from: string, to: string): { from: string; to: string } | null {
  const a = Date.parse(`${from}T00:00:00Z`);
  const b = Date.parse(`${to}T00:00:00Z`);
  if (Number.isNaN(a) || Number.isNaN(b) || b < a) return null;
  return { from: new Date(a).toISOString(), to: new Date(b + 86_400_000).toISOString() };
}

/** Mensaje de error de una acción de US5: el 404 de las rutas significa algo más concreto que el
 *  genérico «no se encontró». */
export function us5ErrorMessage(status: number | undefined, fallback: string, notFound: string): string {
  return status === 404 ? notFound : fallback;
}
