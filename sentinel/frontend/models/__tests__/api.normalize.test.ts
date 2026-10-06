import { describe, expect, it } from "vitest";
import { normalizeLegacy, normalizeRefModels } from "../api";

describe("normalización de las respuestas del backend", () => {
  it("modelos de referencia: real_model/context_window/max_output → id/max_input_tokens/max_output_tokens", () => {
    const r = normalizeRefModels({ total: 1, data: [{ real_model: "z-ai/glm-4.6", role: "text", context_window: 200000,
      max_output: 8192, price: { input: 6e-7, output: 2.2e-6 }, features: { tools: true } }] });
    expect(r.total).toBe(1);
    expect(r.data[0]).toMatchObject({ id: "z-ai/glm-4.6", max_input_tokens: 200000, max_output_tokens: 8192, role: "text" });
    expect(r.data[0].features).toEqual({ tools: true });
  });
  it("tolera nombres ya traducidos y respuestas vacías o ajenas", () => {
    expect(normalizeRefModels({ data: [{ id: "x", max_input_tokens: 5 }] }).data[0]).toMatchObject({ id: "x", max_input_tokens: 5 });
    expect(normalizeRefModels(undefined)).toEqual({ data: [], total: 0 });
    expect(normalizeRefModels({ data: [{ role: "text" }] }).data).toEqual([]);
  });
  it("heredados: model_id → real_model y descarta filas sin nombre", () => {
    expect(normalizeLegacy([{ model_name: "nix-us-pro", provider: "openai", model_id: "gpt-5.4" }, { provider: "x" }]))
      .toEqual([{ model_name: "nix-us-pro", provider: "openai", real_model: "gpt-5.4", role: null, adopted: false }]);
    expect(normalizeLegacy(null)).toEqual([]);
  });
});
