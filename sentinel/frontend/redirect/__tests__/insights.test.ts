import { describe, expect, it } from "vitest";
import { KIT_TOOLS } from "../catalog";
import { defaultPeriod, detailLabel, formatUsd, periodQuery, scopeParam, us5ErrorMessage } from "../insights";

describe("insights (US5)", () => {
  it("scopeParam: tenant sin id, el resto tipo:id", () => {
    expect(scopeParam("tenant", "")).toBe("tenant");
    expect(scopeParam("user", "u-1")).toBe("user:u-1");
    expect(scopeParam("connection", "k-1")).toBe("connection:k-1");
  });

  it("formatUsd: sin dato es raya; los importes chicos conservan cifras", () => {
    expect(formatUsd(null)).toBe("—");
    expect(formatUsd(undefined)).toBe("—");
    expect(formatUsd(0.0009)).toBe("US$ 0.000900");
    expect(formatUsd(0.0525)).toBe("US$ 0.0525");
    expect(formatUsd(12.5)).toBe("US$ 12.50");
  });

  it("detailLabel: códigos conocidos, http_NNN y desconocidos", () => {
    expect(detailLabel("no_tool_call")).toBe("No llamó a la herramienta pedida");
    expect(detailLabel("http_502")).toBe("El destino respondió con error 502");
    expect(detailLabel("algo_nuevo")).toBe("algo_nuevo");
  });

  it("período: 30 días por defecto y 'hasta' inclusivo", () => {
    expect(defaultPeriod(new Date("2026-10-01T12:00:00Z"))).toEqual({ from: "2026-09-01", to: "2026-10-01" });
    expect(periodQuery("2026-09-01", "2026-10-01")).toEqual({ from: "2026-09-01T00:00:00.000Z", to: "2026-10-02T00:00:00.000Z" });
    expect(periodQuery("2026-10-02", "2026-10-01")).toBeNull();
    expect(periodQuery("", "2026-10-01")).toBeNull();
  });

  it("us5ErrorMessage: el 404 usa el texto concreto", () => {
    expect(us5ErrorMessage(404, "genérico", "concreto")).toBe("concreto");
    expect(us5ErrorMessage(403, "genérico", "concreto")).toBe("genérico");
  });

  it("las herramientas del kit son las del backend", () => {
    expect([...KIT_TOOLS]).toEqual(["claude_desktop", "claude_code", "codex", "openai_generic"]);
  });
});
