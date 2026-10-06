import { describe, expect, it } from "vitest";
import { barPct, fmtMs, periodRange, sortRows } from "../usageHelpers";
import type { UsageRow } from "../usageApi";

const row = (o: Partial<UsageRow>): UsageRow => ({
  key: "k", name: "k", requests: 1, prompt_tokens: 1, completion_tokens: 1, cost_usd: 0,
  latency_avg_ms: 1, latency_p95_ms: 1, billing: "measured", ...o,
});

describe("helpers de consumo", () => {
  it("el período cuenta hoy y los días anteriores", () => {
    expect(periodRange(7, new Date("2026-10-01T15:00:00Z"))).toEqual({ from: "2026-09-25", to: "2026-10-01" });
  });
  it("ordena por costo y por nombre en ambos sentidos", () => {
    const rows = [row({ key: "a", name: "b", cost_usd: 1 }), row({ key: "b", name: "A", cost_usd: 3 })];
    expect(sortRows(rows, "cost_usd", "desc").map(r => r.key)).toEqual(["b", "a"]);
    expect(sortRows(rows, "name", "asc").map(r => r.key)).toEqual(["b", "a"]);
  });
  it("la barra es proporcional al máximo y 0 sin dato", () => {
    expect(barPct(50, 100)).toBe(50);
    expect(barPct(0, 100)).toBe(0);
    expect(barPct(5, 0)).toBe(0);
    expect(fmtMs(null)).toBe("—");
  });
});
