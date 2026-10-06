import { describe, expect, it } from "vitest";
import {
  buildBulkPayload, bulkRows, buildLimits, featureList, filterProviders, formatContext, formatPrice,
  newGuidedState, parseAdvanced, ProviderInfo, roleLabel, toFieldSpecs, toggleModel,
} from "../guided";

const ANTHROPIC: ProviderInfo = {
  provider: "anthropic", display_name: "Anthropic", supported: true,
  credential_fields: [{ key: "api_key", label: "Clave de API", required: true, field_type: "password" }],
  example_model: "claude-sonnet-4",
};
const AZURE: ProviderInfo = {
  provider: "azure", display_name: "Azure OpenAI", supported: true,
  credential_fields: [
    { key: "api_key", label: "Clave de API", required: true, field_type: "password" },
    { key: "api_version", label: "Versión de API", required: true, field_type: "text" },
  ],
};
const OLLAMA: ProviderInfo = { provider: "ollama", display_name: "Ollama", supported: true, credential_fields: [] };
const NOPE: ProviderInfo = { provider: "x", display_name: "Árbol X", supported: false, reason: "sin soporte", credential_fields: [] };

describe("proveedores", () => {
  it("el buscador ignora tildes y mayúsculas y busca por id y nombre", () => {
    const all = [ANTHROPIC, AZURE, OLLAMA, NOPE];
    expect(filterProviders(all, "AZU").map(p => p.provider)).toEqual(["azure"]);
    expect(filterProviders(all, "arbol").map(p => p.provider)).toEqual(["x"]);
    expect(filterProviders(all, "  ")).toHaveLength(4);
    expect(filterProviders(all, "zzz")).toEqual([]);
  });

  it("los campos de credencial del motor pasan a especificaciones del formulario", () => {
    const specs = toFieldSpecs([
      { key: "api_key", label: "Clave", required: true, field_type: "password" },
      { key: "vertex_credentials", label: "Cuenta", required: true, field_type: "json" },
      { key: "api_version", label: "Versión", required: false, field_type: "text" },
    ]);
    expect(specs).toEqual([
      { name: "api_key", label: "Clave", required: true, secret: true, multiline: false },
      { name: "vertex_credentials", label: "Cuenta", required: true, secret: true, multiline: true },
      { name: "api_version", label: "Versión", required: false, secret: false, multiline: false },
    ]);
  });
});

describe("sugerencias", () => {
  it("tipo de modelo en castellano", () => {
    expect(["text", "embeddings", "image", "audio", "rerank", "otro"].map(roleLabel))
      .toEqual(["Texto", "Embeddings", "Imagen", "Audio", "Reordenamiento", "otro"]);
  });
  it("precio por millón de tokens desde precio por token", () => {
    expect(formatPrice({ input: 0.000003, output: 0.000015 })).toBe("US$ 3 / US$ 15 por millón de tokens (entrada / salida)");
    expect(formatPrice({ input: null, output: null })).toBeNull();
    expect(formatPrice(undefined)).toBeNull();
  });
  it("contexto y capacidades", () => {
    expect(formatContext({ max_input_tokens: 200000, max_output_tokens: 8192 })).toBe("Contexto 200.000 · salida 8.192");
    expect(formatContext({})).toBeNull();
    expect(featureList({ images: true, tools: true, thinking: false })).toEqual(["Imágenes", "Herramientas"]);
  });
  it("togglear un modelo lo agrega con la sugerencia aceptada y lo quita", () => {
    const one = toggleModel([], "m1");
    expect(one).toEqual([{ real_model: "m1", name: "", accept_suggestion: true }]);
    expect(toggleModel(one, "m1")).toEqual([]);
    expect(toggleModel([], "m2", false)[0].accept_suggestion).toBe(false);
  });
});

describe("avanzado", () => {
  it("JSON vacío es válido y debe ser un objeto", () => {
    expect(parseAdvanced("")).toEqual({ value: null });
    expect(parseAdvanced('{"temperature": 0.2}')).toEqual({ value: { temperature: 0.2 } });
    expect(parseAdvanced("[1]").error).toMatch(/objeto/);
    expect(parseAdvanced("{roto").error).toMatch(/JSON/);
  });
  it("rechaza credenciales incrustadas, pero no max_tokens", () => {
    expect(parseAdvanced('{"api_key": "sk-1"}').error).toMatch(/credencial/i);
    expect(parseAdvanced('{"extra": {"Authorization": "x"}}').error).toMatch(/credencial/i);
    expect(parseAdvanced('{"max_tokens": 10}').value).toEqual({ max_tokens: 10 });
  });
  it("límites: enteros positivos; reintentos admite cero", () => {
    expect(buildLimits({ rpm: "", tpm: "", max_parallel_requests: "", timeout: "", num_retries: "" }))
      .toEqual({ limits: null, errors: {} });
    expect(buildLimits({ rpm: "60", tpm: "", max_parallel_requests: "4", timeout: "30", num_retries: "0" }).limits)
      .toEqual({ rpm: 60, max_parallel_requests: 4, timeout: 30, num_retries: 0 });
    const bad = buildLimits({ rpm: "0", tpm: "abc", max_parallel_requests: "", timeout: "", num_retries: "-1" });
    expect(Object.keys(bad.errors).sort()).toEqual(["limits.num_retries", "limits.rpm", "limits.tpm"]);
  });
});

describe("armado del alta masiva", () => {
  const SECRET = "sk-ant-SECRETO";
  it("credencial nueva con una sola clave: cadena; sin modelos no hay payload", () => {
    const st = newGuidedState("anthropic");
    expect(buildBulkPayload(st, toFieldSpecs(ANTHROPIC.credential_fields), { operator: false }).errors.models).toBeTruthy();
    st.selected = toggleModel(st.selected, "claude-sonnet-4");
    st.newName = "Mi clave";
    st.values = { api_key: SECRET };
    const built = buildBulkPayload(st, toFieldSpecs(ANTHROPIC.credential_fields), { operator: false });
    expect(built.payload).toEqual({
      provider: "anthropic", level: "tenant",
      credential: { new: { name: "Mi clave", value: SECRET } },
      models: [{ real_model: "claude-sonnet-4", accept_suggestion: true }],
    });
  });
  it("varios campos: objeto; faltantes obligatorios dan error por campo", () => {
    const st = newGuidedState("azure");
    st.selected = toggleModel(st.selected, "gpt-4o");
    st.values = { api_key: "k" };
    const specs = toFieldSpecs(AZURE.credential_fields);
    expect(buildBulkPayload(st, specs, { operator: false }).errors["cred.api_version"]).toBe("Obligatorio.");
    st.values = { api_key: "k", api_version: "2024-06-01" };
    st.apiBase = "https://x.openai.azure.com";
    const built = buildBulkPayload(st, specs, { operator: false });
    expect(built.payload).toMatchObject({
      credential: { new: { value: { api_key: "k", api_version: "2024-06-01" } } }, api_base: "https://x.openai.azure.com",
    });
  });
  it("credencial existente, nombre por modelo, avanzado y límites", () => {
    const st = newGuidedState("anthropic");
    st.selected = [{ real_model: "a", name: "Uno", accept_suggestion: false }, { real_model: "b", name: "", accept_suggestion: true }];
    st.credMode = "existing";
    st.credentialId = "c-1";
    st.advancedText = '{"temperature": 0.1}';
    st.limits = { rpm: "100", tpm: "", max_parallel_requests: "", timeout: "60", num_retries: "2" };
    st.baseModel = "claude-base";
    const built = buildBulkPayload(st, toFieldSpecs(ANTHROPIC.credential_fields), { operator: false });
    expect(built.payload).toEqual({
      provider: "anthropic", level: "tenant", credential: { id: "c-1" },
      models: [
        { real_model: "a", name: "Uno", accept_suggestion: false, advanced: { temperature: 0.1 }, limits: { rpm: 100, timeout: 60, num_retries: 2 }, base_model: "claude-base" },
        { real_model: "b", accept_suggestion: true, advanced: { temperature: 0.1 }, limits: { rpm: 100, timeout: 60, num_retries: 2 }, base_model: "claude-base" },
      ],
    });
  });
  it("errores de validación: sin credencial, JSON inválido, dirección base obligatoria", () => {
    const st = newGuidedState("ollama");
    st.selected = toggleModel(st.selected, "llama3");
    st.credMode = "none";
    st.advancedText = "{x";
    const built = buildBulkPayload(st, [], { operator: false });
    expect(built.payload).toBeNull();
    expect(built.errors.advanced).toMatch(/JSON/);
    expect(built.errors.api_base).toBeTruthy();
    const st2 = newGuidedState("anthropic");
    st2.selected = toggleModel(st2.selected, "m");
    st2.credMode = "none";
    expect(buildBulkPayload(st2, toFieldSpecs(ANTHROPIC.credential_fields), { operator: false }).errors.credential).toBeTruthy();
  });
  it("solo el operador crea en el nivel instalación", () => {
    const st = newGuidedState("ollama");
    st.selected = toggleModel(st.selected, "llama3");
    st.credMode = "none";
    st.apiBase = "http://x";
    st.level = "installation";
    expect(buildBulkPayload(st, [], { operator: false }).errors.level).toBeTruthy();
    expect(buildBulkPayload(st, [], { operator: true }).payload).toMatchObject({ level: "installation" });
  });
});

describe("resultado por modelo", () => {
  it("interpreta ok, errores y formas alternativas", () => {
    const rows = bulkRows({ results: [
      { real_model: "a", status: "created" },
      { real_model: "b", status: "error", detail: "ya existe" },
      { model: "c", ok: false, error: "precio inválido" },
    ] });
    expect(rows).toEqual([
      { model: "a", ok: true, message: "Creado" },
      { model: "b", ok: false, message: "Ya existe." },
      { model: "c", ok: false, message: "Precio inválido." },
    ]);
    expect(bulkRows({ data: [{ real_model: "z", status: 201 }] })).toEqual([{ model: "z", ok: true, message: "Creado" }]);
    expect(bulkRows(null)).toEqual([]);
  });
});
