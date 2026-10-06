// Funciones puras de la pestaña «Consumo»: períodos, orden y proporciones de las barras.
import type { UsageRow } from "./usageApi";

export const PERIODS = [7, 30, 90] as const;
export type Period = (typeof PERIODS)[number];

export type SortKey = "name" | "requests" | "tokens" | "cost_usd" | "latency_avg_ms" | "latency_p95_ms";
export type SortDir = "asc" | "desc";

/** Rango [from, to] en ISO (día completo en UTC) para los últimos `days` días contando hoy. */
export function periodRange(days: number, now: Date = new Date()): { from: string; to: string } {
  const to = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  const from = new Date(to.getTime() - (days - 1) * 86_400_000);
  const iso = (d: Date) => d.toISOString().slice(0, 10);
  return { from: iso(from), to: iso(to) };
}

export const tokensOf = (r: UsageRow) => r.prompt_tokens + r.completion_tokens;

const value = (r: UsageRow, k: SortKey): number | string => {
  if (k === "name") return r.name.toLowerCase();
  if (k === "tokens") return tokensOf(r);
  return r[k] ?? -1;
};

export function sortRows(rows: UsageRow[], key: SortKey, dir: SortDir): UsageRow[] {
  const f = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = value(a, key), y = value(b, key);
    return (x < y ? -1 : x > y ? 1 : 0) * f;
  });
}

/** Porcentaje entero 0–100 de `v` respecto del máximo de la columna (barra CSS). */
export function barPct(v: number, max: number): number {
  if (!(max > 0) || !(v > 0)) return 0;
  return Math.max(2, Math.round((v / max) * 100));
}

export const fmtInt = (n: number) => n.toLocaleString("es-AR");
export const fmtUsd = (n: number) => `US$ ${n.toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: n < 1 ? 4 : 2 })}`;
export const fmtMs = (n: number | null | undefined) => (n == null ? "—" : `${fmtInt(Math.round(n))} ms`);
