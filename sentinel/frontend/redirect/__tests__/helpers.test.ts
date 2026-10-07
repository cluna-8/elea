import { describe, expect, it } from "vitest";
import { PROVIDERS } from "../catalog";
import {
  buildCapabilityProfile, buildCredential, buildDestinationPayload, capabilityFlags, capabilityLabel, buildPrice, buildWindowPatch, parsePrice, parseTokens, priceLabel, buildPolicyRequest, buildPosturePayload, buildPublishedPayload,
  buildRulePayload, credentialFields, describeApiError, moveItem, newDestinationForm, newPostureForm,
  newPublishedForm, newRuleForm, parseOfferTenants, permissionsFor, scopeLabel, sessionRole, withProvider,
} from "../helpers";
import { buildPreviewBody } from "../PreviewTab";

const lookups = {
  groups: [{ id: "g-1", name: "Ventas" }],
  users: [{ id: "u-1", username: "ana" }],
  keys: [{ id: "k-1", name: "Laptop de Ana" }],
};

describe("forma de la credencial por proveedor", () => {
  it("cada proveedor del catálogo tiene forma; ollama sin secreto, bedrock con token opcional", () => {
    for (const p of PROVIDERS) expect(Array.isArray(credentialFields(p))).toBe(true);
    expect(credentialFields("ollama")).toEqual([
      { name: "api_key", label: "Clave de API", required: false, secret: true, multiline: false },
    ]);
    const bedrock = credentialFields("bedrock");
    expect(bedrock.map(f => [f.name, f.required])).toEqual([
      ["aws_access_key_id", true], ["aws_secret_access_key", true], ["aws_region_name", true], ["aws_session_token", false],
    ]);
    expect(bedrock.find(f => f.name === "aws_region_name")?.secret).toBe(false);
    expect(credentialFields("vertex_ai").find(f => f.name === "vertex_credentials")?.multiline).toBe(true);
    expect(credentialFields("azure").map(f => f.name)).toEqual(["api_key", "api_version"]);
  });

  it("faltantes marcan error; opcionales vacíos no viajan", () => {
    const r = buildCredential("bedrock", { mode: "values", values: { aws_access_key_id: "A", aws_region_name: "eu-west-1" } }, "tenant");
    expect(r.credential).toBeNull();
    expect(r.errors).toEqual({ "cred.aws_secret_access_key": "Obligatorio." });
    const ok = buildCredential("bedrock", { mode: "values", values: {
      aws_access_key_id: " A ", aws_secret_access_key: "S", aws_region_name: "eu-west-1", aws_session_token: "" } }, "tenant");
    expect(ok.credential).toEqual({ aws_access_key_id: "A", aws_secret_access_key: "S", aws_region_name: "eu-west-1" });
  });

  it("ollama sin clave no manda credencial", () => {
    expect(buildCredential("ollama", { mode: "values", values: {} }, "tenant")).toEqual({ credential: null, errors: {} });
  });

  it("vertex: el JSON de la cuenta de servicio se parsea; basura es error", () => {
    const base = { vertex_project: "p", vertex_location: "europe-west4" };
    expect(buildCredential("vertex_ai", { mode: "values", values: { ...base, vertex_credentials: '{"type":"service_account"}' } }, "tenant").credential)
      .toEqual({ ...base, vertex_credentials: { type: "service_account" } });
    expect(buildCredential("vertex_ai", { mode: "values", values: { ...base, vertex_credentials: "no-json" } }, "tenant").errors)
      .toHaveProperty("cred.vertex_credentials");
  });

  it("referencia del servidor: prefijo obligatorio, solo nivel instalación", () => {
    expect(buildCredential("openai", { mode: "env", values: { api_key: "acme_key" } }, "installation").credential)
      .toEqual({ api_key: "env:REDIRECT_CRED_ACME_KEY" });
    expect(buildCredential("openai", { mode: "env", values: { api_key: "REDIRECT_CRED_X1" } }, "installation").credential)
      .toEqual({ api_key: "env:REDIRECT_CRED_X1" });
    expect(buildCredential("openrouter", { mode: "env", values: { api_key: "env:REDIRECT_CRED_OPENROUTER" } }, "installation").credential)
      .toEqual({ api_key: "env:REDIRECT_CRED_OPENROUTER" });
    expect(buildCredential("openai", { mode: "env", values: { api_key: "con espacio" } }, "installation").errors)
      .toHaveProperty("cred.api_key");
    expect(buildCredential("openai", { mode: "env", values: { api_key: "X" } }, "tenant").errors)
      .toHaveProperty("credential");
  });
});

describe("formulario de destino → cuerpo", () => {
  it("sugiere familia y base al cambiar de proveedor y limpia la credencial", () => {
    let f = newDestinationForm("openai");
    expect(f.protocol_family).toBe("openai_responses");
    f = { ...f, credential: { mode: "values", values: { api_key: "sk" } } };
    f = withProvider(f, "openrouter");
    expect(f.protocol_family).toBe("openai_chat");
    expect(f.api_base).toBe("https://openrouter.ai/api/v1");
    expect(f.credential.values).toEqual({});
    expect(withProvider(f, "anthropic").api_base).toBe("");
    expect(withProvider({ ...f, api_base: "https://mio" }, "anthropic").api_base).toBe("https://mio");
  });

  it("arma el cuerpo con jurisdicciones nulas si no se declaran", () => {
    const f = { ...newDestinationForm("openai_compatible"), name: " Local ", real_model: "qwen3", api_base: "http://10.0.0.5:8000/v1",
      inference_jurisdiction: "EU", credential: { mode: "values" as const, values: { api_key: "k" } } };
    const r = buildDestinationPayload(f);
    expect(r.errors).toEqual({});
    expect(r.payload).toEqual({
      level: "tenant", name: "Local", provider: "openai_compatible", real_model: "qwen3", protocol_family: "openai_chat",
      inference_jurisdiction: "EU", entity_jurisdiction: null, api_base: "http://10.0.0.5:8000/v1", credential: { api_key: "k" },
    });
  });

  it("OpenRouter de instalación con referencia del servidor y base opcional", () => {
    const f = { ...withProvider(newDestinationForm(), "openrouter"), level: "installation" as const, name: "OR", real_model: "qwen/qwen3",
      credential: { mode: "env" as const, values: { api_key: "env:REDIRECT_CRED_OPENROUTER" } } };
    expect(buildDestinationPayload(f).payload).toMatchObject({
      level: "installation", provider: "openrouter", api_base: "https://openrouter.ai/api/v1",
      credential: { api_key: "env:REDIRECT_CRED_OPENROUTER" } });
    expect(buildDestinationPayload({ ...f, api_base: "" }).payload).toMatchObject({ api_base: null });
  });

  it("exige base donde el proveedor la necesita", () => {
    const r = buildDestinationPayload({ ...newDestinationForm("azure"), name: "a", real_model: "m",
      credential: { mode: "values", values: { api_key: "k", api_version: "2024-10-01" } } });
    expect(r.payload).toBeNull();
    expect(r.errors.api_base).toMatch(/dirección base/);
  });

  it("oferta: * gana, uuids validados", () => {
    expect(parseOfferTenants("")).toEqual({ tenants: [] });
    expect(parseOfferTenants("a, *")).toEqual({ tenants: ["*"] });
    const id = "0b3e8f1c-1111-4222-8333-944455556666";
    expect(parseOfferTenants(`${id}\n${id.toUpperCase()}`).tenants).toHaveLength(2);
    expect(parseOfferTenants("nope").error).toMatch(/inválido/);
  });
});

describe("publicados, reglas, política y postura", () => {
  it("publicado: la etiqueta por defecto es el id pedido, nunca el destino (057 R40)", () => {
    expect(newPublishedForm().label_mode).toBe("requested");
    const r = buildPublishedPayload({ ...newPublishedForm(), face: "claude", public_id: "claude-sonnet-4-6", family_tier: "sonnet" });
    expect(r.payload).toMatchObject({ label_mode: "requested", label: null });
  });
  it("publicado: tier solo en cara claude, alcance tenant = *", () => {
    const r = buildPublishedPayload({ ...newPublishedForm(), face: "claude", public_id: "pro", family_tier: "sonnet", is_family_default: true });
    expect(r.payload).toMatchObject({ face: "claude", public_id: "pro", family_tier: "sonnet", is_family_default: true, scope_type: "tenant", scope_value: "*", label: null });
    const g = buildPublishedPayload({ ...newPublishedForm(), public_id: "x", family_tier: "opus", scope_type: "group", scope_value: "g-1" });
    expect(g.payload).toMatchObject({ family_tier: null, is_family_default: false, scope_type: "group", scope_value: "g-1" });
    expect(buildPublishedPayload({ ...newPublishedForm(), public_id: "rdx-a" }).errors.public_id).toMatch(/interno/);
    expect(buildPublishedPayload({ ...newPublishedForm(), public_id: "a", scope_type: "user" }).errors.scope_value).toBeTruthy();
    expect(buildPublishedPayload({ ...newPublishedForm(), public_id: "a", label_mode: "custom", label: "Mío" }).payload)
      .toMatchObject({ label_mode: "custom", label: "Mío" });
  });

  it("regla: por id o por tier, destinos en orden y sin repetir", () => {
    const r = buildRulePayload({ ...newRuleForm(), published_model_id: "p1", request_class: "subagent", targets: ["d2", "d1"] });
    expect(r.payload).toEqual({ published_model_id: "p1", family_tier: null, request_class: "subagent", scope_type: "tenant", scope_value: "*", targets: ["d2", "d1"] });
    const t = buildRulePayload({ ...newRuleForm(), by: "tier", published_model_id: "p1", family_tier: "haiku", targets: ["d1"] });
    expect(t.payload).toMatchObject({ published_model_id: null, family_tier: "haiku", request_class: null });
    expect(buildRulePayload({ ...newRuleForm(), published_model_id: "p", targets: [] }).errors.targets).toBeTruthy();
    expect(moveItem(["a", "b", "c"], 2, -1)).toEqual(["a", "c", "b"]);
    expect(moveItem(["a", "b"], 0, -1)).toEqual(["a", "b"]);
  });

  it("política: ruta por alcance y motivo obligatorio", () => {
    expect(buildPolicyRequest({ scope_type: "tenant", scope_value: "", state: "on", reason: "piloto" }).payload)
      .toEqual({ path: "/policy/tenant/*", body: { state: "on", reason: "piloto" } });
    expect(buildPolicyRequest({ scope_type: "connection", scope_value: "k-1", state: "shadow", reason: "probar" }).payload?.path)
      .toBe("/policy/connection/k-1");
    expect(buildPolicyRequest({ scope_type: "tenant", scope_value: "", state: "off", reason: "" }).errors.reason).toBeTruthy();
  });

  it("postura: allowlist exige jurisdicciones; aceptar entidad ajena es de cumplimiento", () => {
    const admin = permissionsFor("tenant_admin");
    const dpo = permissionsFor("compliance_officer");
    const f = { ...newPostureForm(), jurisdictions: ["eu", "LATAM"], reason: "RGPD" };
    expect(buildPosturePayload(f, admin).payload).toEqual({
      scope_type: "tenant", scope_value: "*", mode: "allowlist", jurisdictions: ["EU", "LATAM"], accept_foreign_entity: false, reason: "RGPD" });
    expect(buildPosturePayload({ ...f, jurisdictions: [] }, admin).errors.jurisdictions).toBeTruthy();
    expect(buildPosturePayload({ ...f, accept_foreign_entity: true }, admin).payload).toBeNull();
    expect(buildPosturePayload({ ...f, accept_foreign_entity: true }, dpo).payload).toMatchObject({ accept_foreign_entity: true });
    expect(buildPosturePayload({ ...f, mode: "off" }, dpo).payload).toMatchObject({ jurisdictions: [] });
  });

  it("vista previa: vacíos como null y grupo como lista", () => {
    expect(buildPreviewBody({ face: "claude", public_id: " pro ", request_class: "", connection_id: "k-1", user_id: "", group_id: "g-1" }))
      .toEqual({ face: "claude", public_id: "pro", request_class: null, connection_id: "k-1", user_id: null, group_ids: ["g-1"] });
  });
});

describe("alcances, roles y errores", () => {
  it("etiqueta de alcance con nombre, o id corto si no se conoce", () => {
    expect(scopeLabel("tenant", "*", lookups)).toBe("Toda la organización");
    expect(scopeLabel("group", "g-1", lookups)).toBe("Grupo: Ventas");
    expect(scopeLabel("user", "u-1", lookups)).toBe("Usuario: ana");
    expect(scopeLabel("connection", "k-1", lookups)).toBe("Conexión: Laptop de Ana");
    expect(scopeLabel("group", "0b3e8f1c-1111-4222-8333-944455556666", lookups)).toBe("Grupo: (0b3e8f1c…)");
  });

  it("rol canónico desde el token; si no, el guardado", () => {
    const payload = btoa(JSON.stringify({ role: "super_admin", sub: "x" })).replace(/=+$/, "");
    expect(sessionRole(`h.${payload}.s`, "admin")).toBe("super_admin");
    expect(sessionRole("opaco", "admin")).toBe("admin");
    expect(sessionRole(null, "compliance_officer")).toBe("compliance_officer");
    expect(permissionsFor("admin")).toMatchObject({ canAdmin: true, isSuper: false, canEnable: false, canManagePosture: false });
    // tenant operador de la instalación (capabilities.operator): opera como super_admin
    expect(permissionsFor("admin", true)).toMatchObject({ canAdmin: true, isSuper: true, canEnable: true, canManagePosture: true });
    expect(permissionsFor("compliance_officer", false).isSuper).toBe(false);
    expect(permissionsFor("super_admin")).toMatchObject({ canAdmin: true, isSuper: true, canEnable: true, canManagePosture: true });
    expect(permissionsFor("compliance_officer")).toMatchObject({ canAdmin: false, canEnable: true, canAddPosture: true });
  });

  it("errores en castellano llano", () => {
    expect(describeApiError(0, null)).toMatch(/No se pudo contactar/);
    expect(describeApiError(404, { detail: "Not Found" })).toMatch(/no está activada/);
    expect(describeApiError(404, { detail: "destino inexistente" })).toMatch(/No se encontró/);
    expect(describeApiError(403, { detail: "Insufficient permissions" })).toBe("Tu rol no permite esta acción.");
    expect(describeApiError(403, { detail: "solo super_admin crea destinos de instalación" })).toMatch(/^No tenés permiso/);
    expect(describeApiError(422, { detail: "este proveedor requiere api_base" })).toBe("Este proveedor requiere api_base.");
    expect(describeApiError(422, { detail: [{ loc: ["body", "reason"], type: "string_too_short", msg: "String should…" }] }))
      .toBe("El campo «motivo» es demasiado corto.");
    expect(describeApiError(500, null)).toMatch(/servidor tuvo un problema/);
  });
});

describe("ventana del destino", () => {
  it("tokens: vacío es sin declarar, acepta separadores de miles y rechaza lo que no es entero", () => {
    expect(parseTokens("")).toEqual({ value: null });
    expect(parseTokens("128.000")).toEqual({ value: 128000 });
    expect(parseTokens("64k").error).toBeTruthy();
    expect(parseTokens("0").error).toBeTruthy();
  });

  it("el alta manda la ventana solo si se declaró", () => {
    const f = { ...withProvider(newDestinationForm(), "openrouter"), name: "OR", real_model: "deepseek/deepseek-chat-v3-0324",
      credential: { mode: "values" as const, values: { api_key: "k" } } };
    expect(buildDestinationPayload(f).payload).not.toHaveProperty("context_window");
    expect(buildDestinationPayload({ ...f, context_window: "163840", max_output: "8192" }).payload)
      .toMatchObject({ context_window: 163840, max_output: 8192 });
    expect(buildDestinationPayload({ ...f, context_window: "mucho" }).errors.context_window).toBeTruthy();
  });

  it("el PATCH de ventana exige al menos la ventana y manda solo lo declarado", () => {
    expect(buildWindowPatch("", "").errors.context_window).toBeTruthy();
    expect(buildWindowPatch("163840", "")).toEqual({ payload: { context_window: 163840 }, errors: {} });
  });
});

describe("precio del destino", () => {
  it("acepta coma o punto y rechaza lo que no es un número", () => {
    expect(parsePrice("0,29")).toEqual({ value: 0.29 });
    expect(parsePrice("1.14")).toEqual({ value: 1.14 });
    expect(parsePrice("")).toEqual({ value: null });
    expect(parsePrice("-1").error).toBeTruthy();
    expect(parsePrice("barato").error).toBeTruthy();
  });

  it("exige los dos precios o ninguno (ninguno = automático)", () => {
    expect(buildPrice("", "")).toEqual({ payload: null, errors: {} });
    expect(buildPrice("0,29", "1,14")).toEqual({ payload: { input_per_mtok: 0.29, output_per_mtok: 1.14 }, errors: {} });
    expect(buildPrice("0,29", "").errors.price_output).toBeTruthy();
  });

  it("el alta manda el precio solo si se cargó", () => {
    const f = { ...withProvider(newDestinationForm(), "openrouter"), name: "OR", real_model: "deepseek/deepseek-chat-v3-0324",
      credential: { mode: "values" as const, values: { api_key: "k" } } };
    expect(buildDestinationPayload(f).payload).not.toHaveProperty("price_override");
    expect(buildDestinationPayload({ ...f, price_input: "0,29", price_output: "1,14" }).payload)
      .toMatchObject({ price_override: { input_per_mtok: 0.29, output_per_mtok: 1.14 } });
  });

  it("la fila dice qué precio se usa", () => {
    const d = { price_override: { input_per_mtok: 0.29, output_per_mtok: 1.14 } } as never;
    expect(priceLabel(d)).toContain("0,29");
    expect(priceLabel({ price_override: null } as never)).toContain("automático");
  });
});

describe("capacidades del destino (acepta imágenes / PDF)", () => {
  it("lee las claves existentes del perfil: images y documents_pdf", () => {
    expect(capabilityFlags({ capability_profile: { images: true } })).toEqual({ images: true, documents_pdf: false });
    expect(capabilityFlags({ capability_profile: null })).toEqual({ images: false, documents_pdf: false });
    expect(capabilityFlags({})).toEqual({ images: false, documents_pdf: false });
  });

  it("fusiona con el perfil: no borra otras claves como cache_control", () => {
    const prev = { images: true, cache_control: false, mid_system_messages: true };
    expect(buildCapabilityProfile(prev, { images: false, documents_pdf: true })).toEqual(
      { images: false, documents_pdf: true, cache_control: false, mid_system_messages: true });
    expect(prev).toEqual({ images: true, cache_control: false, mid_system_messages: true });   // no muta
    expect(buildCapabilityProfile(undefined, { images: true, documents_pdf: false })).toEqual(
      { images: true, documents_pdf: false });
  });

  it("etiqueta para la tabla", () => {
    expect(capabilityLabel({ capability_profile: {} })).toBe("Acepta: solo texto");
    expect(capabilityLabel({ capability_profile: { images: true } })).toBe("Acepta: imágenes");
    expect(capabilityLabel({ capability_profile: { images: true, documents_pdf: true } })).toBe("Acepta: imágenes y PDF");
    expect(capabilityLabel({ capability_profile: { documents_pdf: true } })).toBe("Acepta: PDF");
  });

  it("el alta manda el perfil solo si se marcó alguna casilla", () => {
    const base = { ...newDestinationForm("openrouter"), name: "Kimi", real_model: "moonshotai/kimi-k3",
      credential: { mode: "values" as const, values: { api_key: "sk-or" } } };
    expect(buildDestinationPayload(base).payload).not.toHaveProperty("capability_profile");
    const conVision = buildDestinationPayload({ ...base, accepts_images: true });
    expect(conVision.payload?.capability_profile).toEqual({ images: true, documents_pdf: false });
  });
});
