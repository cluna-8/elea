import { describe, expect, it } from "vitest";
import {
  checkPublicId, buildCreatePayload, buildCredentialCreate, buildPatchPayload, buildRevokeBody, buildSecretValue, buildSheetPayload,
  canEditSheet, canWriteEntry, changesSheetSubject, entryStatus, entryToForm, EntryView, isStale, jurisdictionOptions,
  motivoLabel, newCredentialForm, newEntryForm, normalizeEnvName, permissionsFor, sheetToForm, triFrom, triTo,
  parseParamList, validateReason, valueFields, withLevel, withProvider,
} from "../helpers";

const ENTRY: EntryView = {
  id: "e-1", level: "tenant", tenant_id: "t", name: "Claude", public_id: "claude", provider: "anthropic", real_model: "claude-x",
  protocol_family: "anthropic_messages", api_base: null, is_aggregator: false, role: "text", capability: "standard",
  features: { images: true }, context_window: 200000, max_output: null, blocked_by_default: false, enabled_at: null,
  status: "active", source: "console", has_credential: true,
  credential: { id: "c-1", name: "Clave", kind: "secret", fingerprint: "ab12" },
  sheet: {
    provider_legal_entity: null, entity_jurisdiction: null, inference_jurisdiction: "unknown", logs_jurisdiction: "unknown",
    zero_data_retention: null, trains_on_data: null, transfer_mechanism: "unknown", dpa_registry_id: null,
    eu_region_contracted: null, notes: null, classification_version: "console:0", classified_by: null, classified_at: null,
  },
  semaforo: { estado: "unclassified", motivos: ["dato_desconocido:trains_on_data"] },
};

describe("semáforo", () => {
  it("motivos en castellano", () => {
    expect(motivoLabel("dpa_vencido")).toBe("DPA vencido");
    expect(motivoLabel("sin_dpa")).toBe("Sin DPA");
    expect(motivoLabel("agregador")).toBe("Agregador: no cubre al proveedor final");
    expect(motivoLabel("dato_desconocido:trains_on_data")).toBe("Falta cargar: entrena con datos");
    expect(motivoLabel("dato_desconocido:eu_region_contracted")).toBe("Falta cargar: región UE contratada");
    expect(motivoLabel("dato_desconocido:algo_nuevo")).toBe("Falta cargar: algo_nuevo");
    expect(motivoLabel("motivo_nuevo")).toBe("motivo_nuevo");
  });
  it("ficha desactualizada", () => {
    expect(isStale(ENTRY)).toBe(false);
    expect(isStale({ ...ENTRY, sheet: { ...ENTRY.sheet, classification_version: "stale" } })).toBe(true);
    expect(isStale({ ...ENTRY, semaforo: { estado: "unclassified", motivos: ["ficha_desactualizada"] } })).toBe(true);
  });
  it("estado de la entrada", () => {
    expect(entryStatus(ENTRY).label).toBe("Activo");
    expect(entryStatus({ ...ENTRY, blocked_by_default: true }).label).toBe("Bloqueado por defecto");
    expect(entryStatus({ ...ENTRY, status: "archived" }).label).toBe("Archivado");
  });
});

describe("permisos", () => {
  it("admin escribe; cumplimiento solo ficha; lectura nada", () => {
    expect(permissionsFor("tenant_admin")).toMatchObject({ canAdmin: true, canSheetRole: true, operator: false });
    expect(permissionsFor("compliance_officer")).toMatchObject({ canAdmin: false, canSheetRole: true });
    expect(permissionsFor("lectura", true)).toEqual({ operator: false, canAdmin: false, canSheetRole: false });
  });
  it("las entradas de instalación las escribe solo el operador", () => {
    const inst = { ...ENTRY, level: "installation" as const };
    expect(canWriteEntry(permissionsFor("tenant_admin"), inst)).toBe(false);
    expect(canWriteEntry(permissionsFor("tenant_admin", true), inst)).toBe(true);
    expect(canEditSheet(permissionsFor("compliance_officer"), inst)).toBe(false);
    expect(canEditSheet(permissionsFor("compliance_officer"), ENTRY)).toBe(true);
    expect(canWriteEntry(permissionsFor("super_admin"), { ...ENTRY, status: "archived" })).toBe(false);
  });
});

describe("valor de credencial", () => {
  it("una sola clave de API va como cadena; varios campos como objeto", () => {
    expect(buildSecretValue(valueFields("openrouter"), { api_key: " sk-1 " }).value).toBe("sk-1");
    const az = buildSecretValue(valueFields("azure"), { api_key: "k", api_version: "2024-06-01" });
    expect(az.value).toEqual({ api_key: "k", api_version: "2024-06-01" });
  });
  it("faltan campos obligatorios y JSON inválido", () => {
    expect(buildSecretValue(valueFields("azure"), { api_key: "k" }).errors["cred.api_version"]).toBe("Obligatorio.");
    const v = buildSecretValue(valueFields("vertex_ai"), { vertex_credentials: "{no", vertex_project: "p", vertex_location: "eu" });
    expect(v.errors["cred.vertex_credentials"]).toMatch(/JSON/);
  });
  it("vacío = nada que mandar", () => {
    expect(buildSecretValue(valueFields("ollama"), {})).toEqual({ value: null, errors: {} });
  });
  it("referencia del servidor", () => {
    expect(normalizeEnvName("openrouter").name).toBe("REDIRECT_CRED_OPENROUTER");
    expect(normalizeEnvName("env:REDIRECT_CRED_X").name).toBe("REDIRECT_CRED_X");
    expect(normalizeEnvName("mal nombre").name).toBeNull();
  });
});

describe("alta de modelo", () => {
  it("OpenRouter: familia sugerida, base por defecto, agregador implícito y credencial nueva", () => {
    const f = withProvider({ ...newEntryForm(), name: "OR", real_model: "qwen/qwen3", values: {} }, "openrouter");
    expect(f.protocol_family).toBe("openai_chat");
    expect(f.api_base).toBe("https://openrouter.ai/api/v1");
    expect(f.aggregator).toBe(true);
    const built = buildCreatePayload({ ...f, newName: "Clave OR", values: { api_key: "sk-or" } }, { operator: false });
    expect(built.errors).toEqual({});
    expect(built.payload).toMatchObject({
      level: "tenant", provider: "openrouter", protocol_family: "openai_chat",
      credential: { new: { name: "Clave OR", value: "sk-or" } },
    });
    expect(built.payload).not.toHaveProperty("is_aggregator");   // lo marca el backend
    expect(built.payload!.features).toEqual({ images: false, documents_pdf: false, tools: false, thinking: false, cache_control: false });
  });
  it("el agregador solo se manda si se aparta del default del proveedor", () => {
    const f = { ...newEntryForm("anthropic"), name: "A", real_model: "m", aggregator: true, values: { api_key: "k" } };
    expect(buildCreatePayload(f, { operator: false }).payload).toMatchObject({ is_aggregator: true });
  });
  it("validaciones: nombre, modelo, base obligatoria, credencial", () => {
    const f = withProvider(newEntryForm(), "azure");
    const { errors } = buildCreatePayload(f, { operator: false });
    expect(errors).toMatchObject({ name: expect.any(String), real_model: expect.any(String), api_base: expect.any(String) });
    expect(buildCreatePayload({ ...newEntryForm(), name: "n", real_model: "m" }, { operator: false }).errors.credential)
      .toMatch(/Cargá la credencial/);
    expect(buildCreatePayload({ ...newEntryForm(), name: "n", real_model: "m", credMode: "none" }, { operator: false }).errors.credential)
      .toBe("Este proveedor requiere credencial.");
  });
  it("proveedor sin secreto obligatorio admite «sin credencial»", () => {
    const f = { ...withProvider(newEntryForm(), "ollama"), name: "L", real_model: "llama3", api_base: "http://x:11434", credMode: "none" as const };
    const built = buildCreatePayload(f, { operator: false });
    expect(built.payload).not.toBeNull();
    expect(built.payload).not.toHaveProperty("credential");
  });
  it("credencial existente por id y referencia del servidor (solo operador + instalación)", () => {
    const base = { ...newEntryForm("openrouter"), name: "n", real_model: "m" };
    expect(buildCreatePayload({ ...base, credMode: "existing", credentialId: "c-9" }, { operator: false }).payload)
      .toMatchObject({ credential: { id: "c-9" } });
    expect(buildCreatePayload({ ...base, credMode: "existing" }, { operator: false }).errors.credential).toBe("Elegí una credencial.");
    expect(buildCreatePayload({ ...base, credMode: "env", envRef: "OR" }, { operator: true }).errors.credential).toMatch(/instalación/);
    const inst = { ...withLevel(base, "installation"), envRef: "OR" };
    expect(inst.credMode).toBe("env");
    expect(buildCreatePayload(inst, { operator: true }).payload).toMatchObject({
      level: "installation", credential: { env_ref: "REDIRECT_CRED_OR" } });
    expect(buildCreatePayload(inst, { operator: false }).errors.level).toBeDefined();
  });
});

describe("edición", () => {
  it("manda solo lo que cambió y avisa cuando la ficha quedará desactualizada", () => {
    const f = { ...entryToForm(ENTRY), capability: "frontier" as const, real_model: "claude-y" };
    expect(changesSheetSubject(f, ENTRY)).toBe(true);
    expect(buildPatchPayload(f, ENTRY, { operator: false }).payload).toEqual({ capability: "frontier", real_model: "claude-y" });
  });
  it("sin cambios no hay cuerpo; la credencial se mantiene", () => {
    const built = buildPatchPayload(entryToForm(ENTRY), ENTRY, { operator: false });
    expect(built.payload).toBeNull();
    expect(built.errors.form).toBe("No hay cambios para guardar.");
  });
  it("capacidades funcionales cambiadas viajan completas", () => {
    const f = entryToForm(ENTRY);
    const built = buildPatchPayload({ ...f, features: { ...f.features, documents_pdf: true } }, ENTRY, { operator: false });
    expect(built.payload).toEqual({ features: { images: true, documents_pdf: true, tools: false, thinking: false, cache_control: false } });
  });
  it("las capacidades avanzadas que la pantalla no muestra se conservan al editar", () => {
    const e = { ...ENTRY, features: { images: true, mid_system_messages: true } };
    const f = entryToForm(e);
    expect(Object.keys(f.features)).not.toContain("mid_system_messages");
    const built = buildPatchPayload({ ...f, features: { ...f.features, tools: true } }, e, { operator: false });
    expect(built.payload).toEqual({ features: { images: true, mid_system_messages: true, tools: true,
      documents_pdf: false, thinking: false, cache_control: false } });
  });
  it("id público: opcional al crear, sin espacios ni rdx-; el cambio viaja en el PATCH", () => {
    const base = { ...newEntryForm("anthropic"), name: "n", real_model: "m", values: { api_key: "k" } };
    expect(buildCreatePayload(base, { operator: false }).payload).not.toHaveProperty("public_id");
    expect(buildCreatePayload({ ...base, public_id: " mi-modelo " }, { operator: false }).payload).toMatchObject({ public_id: "mi-modelo" });
    expect(buildCreatePayload({ ...base, public_id: "con espacio" }, { operator: false }).errors.public_id).toBe("Sin espacios.");
    expect(buildCreatePayload({ ...base, public_id: "rdx-uno" }, { operator: false }).errors.public_id).toMatch(/rdx-/);
    expect(checkPublicId("")).toBeNull();
    const f = { ...entryToForm(ENTRY), public_id: "claude-2" };
    expect(buildPatchPayload(f, ENTRY, { operator: false }).payload).toEqual({ public_id: "claude-2" });
  });
});

describe("ficha", () => {
  it("tri-estado y cuerpo: el semáforo nunca viaja", () => {
    expect(triFrom(true)).toBe("yes"); expect(triFrom(false)).toBe("no"); expect(triFrom(null)).toBe("unknown");
    expect(triTo("yes")).toBe(true); expect(triTo("no")).toBe(false); expect(triTo("unknown")).toBeNull();
    const form = { ...sheetToForm(ENTRY.sheet), inference_jurisdiction: "EU", trains_on_data: "no" as const,
      eu_region_contracted: "yes" as const, notes: "  ok " };
    const { payload } = buildSheetPayload(form, { is_aggregator: false });
    expect(payload).toMatchObject({ inference_jurisdiction: "EU", trains_on_data: false, eu_region_contracted: null, notes: "ok" });
    expect(payload).not.toHaveProperty("semaforo");
    expect(buildSheetPayload(form, { is_aggregator: true }).payload).toMatchObject({ eu_region_contracted: true });
  });
  it("DPA debe ser un identificador válido", () => {
    expect(buildSheetPayload({ ...sheetToForm(ENTRY.sheet), dpa_registry_id: "nada" }, ENTRY).errors.dpa_registry_id).toBeDefined();
    const id = "3f2c1b0a-1111-4222-8333-444455556666";
    expect(buildSheetPayload({ ...sheetToForm(ENTRY.sheet), dpa_registry_id: id }, ENTRY).payload).toMatchObject({ dpa_registry_id: id });
  });
  it("opciones de jurisdicción incluyen especiales, «ninguna» para registros y valores guardados", () => {
    const vals = jurisdictionOptions({ none: true, extra: "latam" }).map(o => o.value);
    expect(vals).toEqual(expect.arrayContaining(["unknown", "EU", "US", "global", "local", "none", "latam", "AR"]));
    expect(new Set(vals).size).toBe(vals.length);
  });
});

describe("credenciales y archivo", () => {
  it("archivar pide al menos 3 caracteres", () => {
    expect(validateReason("ab")).not.toBeNull();
    expect(validateReason(" abc ")).toBeNull();
  });
  it("revocar en uso exige reemplazo o desactivar", () => {
    expect(buildRevokeBody(true, "", "", "").payload).toBeNull();
    expect(buildRevokeBody(true, "replace", "", "").errors.replacement_id).toBeDefined();
    expect(buildRevokeBody(true, "replace", "c-2", " cambio ").payload).toEqual({ replacement_id: "c-2", reason: "cambio" });
    expect(buildRevokeBody(true, "deactivate", "", "").payload).toEqual({ deactivate_entries: true });
    expect(buildRevokeBody(false, "", "", "").payload).toEqual({});
  });
  it("alta de credencial: valor secreto y referencia del servidor", () => {
    const f = { ...newCredentialForm(), name: "Clave", values: { api_key: "sk-x" } };
    expect(buildCredentialCreate(f, { operator: false }).payload).toEqual({ name: "Clave", kind: "secret", value: "sk-x", level: "tenant" });
    expect(buildCredentialCreate({ ...f, values: {} }, { operator: false }).errors.credential).toBeDefined();
    const env = { ...newCredentialForm(), name: "R", level: "installation" as const, mode: "env_ref" as const, envName: "or" };
    expect(buildCredentialCreate(env, { operator: true }).payload).toEqual({
      name: "R", kind: "env_ref", env_name: "REDIRECT_CRED_OR", level: "installation" });
    expect(buildCredentialCreate(env, { operator: false }).payload).toBeNull();
  });
});

describe("parámetros no soportados de la ficha", () => {
  it("se escriben separados por comas o espacios, sin duplicados, y se normalizan", () => {
    expect(parseParamList(" temperature, top_p  temperature\n")).toEqual(["temperature", "top_p"]);
    expect(parseParamList("")).toEqual([]);
  });
  it("la ficha nueva no trae nada precargado y la existente muestra su lista", () => {
    expect(newEntryForm().unsupported).toBe("");
    expect(entryToForm(ENTRY).unsupported).toBe("");                              // el servidor viejo no manda el campo
    expect(entryToForm({ ...ENTRY, unsupported_params: ["temperature", "top_p"] }).unsupported).toBe("temperature, top_p");
  });
  it("el alta manda la lista solo si hay algo", () => {
    const base = { ...newEntryForm("anthropic"), name: "n", real_model: "m", values: { api_key: "k" } };
    expect(buildCreatePayload(base, { operator: false }).payload).not.toHaveProperty("unsupported_params");
    expect(buildCreatePayload({ ...base, unsupported: "temperature top_p" }, { operator: false }).payload)
      .toMatchObject({ unsupported_params: ["temperature", "top_p"] });
  });
  it("el PATCH la manda solo si cambió, y vacía con una lista vacía", () => {
    const f = entryToForm({ ...ENTRY, unsupported_params: ["temperature"] });
    const e = { ...ENTRY, unsupported_params: ["temperature"] };
    expect(buildPatchPayload(f, e, { operator: false }).payload).toBeNull();
    expect(buildPatchPayload({ ...f, unsupported: "temperature, top_p" }, e, { operator: false }).payload)
      .toEqual({ unsupported_params: ["temperature", "top_p"] });
    expect(buildPatchPayload({ ...f, unsupported: "" }, e, { operator: false }).payload).toEqual({ unsupported_params: [] });
  });
  it("el costo, los límites y los internos del motor tampoco se pueden quitar", () => {
    const f = entryToForm(ENTRY);
    for (const n of ["input_cost_per_token", "output_cost_per_token", "timeout", "num_retries", "user_api_key_hash"]) {
      expect(buildPatchPayload({ ...f, unsupported: n }, ENTRY, { operator: false }).errors.unsupported_params).toMatch(n);
    }
  });
  it("nombres inválidos o estructurales se rechazan antes de llamar a la API", () => {
    const f = { ...entryToForm(ENTRY), unsupported: "Temperature" };
    expect(buildPatchPayload(f, ENTRY, { operator: false }).errors.unsupported_params).toMatch(/minúsculas/);
    expect(buildPatchPayload({ ...f, unsupported: "messages" }, ENTRY, { operator: false }).errors.unsupported_params)
      .toMatch(/messages/);
  });
});
