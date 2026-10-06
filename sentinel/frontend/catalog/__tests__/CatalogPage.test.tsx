import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { collectPluginPages } from "../../../../frontend/src/plugins/registry";
import { CatalogPage } from "../CatalogPage";

const SECRET = "sk-or-SUPER-SECRETO-123";
const SHEET = {
  provider_legal_entity: null, entity_jurisdiction: null, inference_jurisdiction: "unknown", logs_jurisdiction: "unknown",
  zero_data_retention: null, trains_on_data: null, transfer_mechanism: "unknown", dpa_registry_id: null,
  eu_region_contracted: null, notes: null, classification_version: "console:0", classified_by: null, classified_at: null,
};
const base = {
  level: "tenant", tenant_id: "t", api_base: null, role: "text", capability: "standard", features: {},
  context_window: null, max_output: null, blocked_by_default: false, enabled_at: null, status: "active",
  source: "console", has_credential: true, sheet: SHEET,
};
const CLAUDE = {
  ...base, id: "e-1", public_id: "claude-sonnet", name: "Claude Sonnet", provider: "anthropic", real_model: "claude-sonnet", protocol_family: "anthropic_messages",
  is_aggregator: false, credential: { id: "c-1", name: "Clave Anthropic", kind: "secret", fingerprint: "ab12" },
  semaforo: { estado: "unclassified", motivos: ["dato_desconocido:inference_jurisdiction"] },
};
const OR = {
  ...base, id: "e-2", public_id: "openrouter-qwen", name: "OpenRouter Qwen", provider: "openrouter", real_model: "qwen/qwen3", protocol_family: "openai_chat",
  is_aggregator: true, api_base: "https://openrouter.ai/api/v1", credential: { id: "c-2", name: "Clave OR", kind: "secret", fingerprint: "cd34" },
  semaforo: { estado: "standard", motivos: ["agregador", "sin_dpa"] },
};
const LOCAL = {
  ...base, id: "e-3", public_id: "local-ue", name: "Local UE", provider: "ollama", real_model: "llama3", protocol_family: "openai_chat", has_credential: false,
  is_aggregator: false, semaforo: { estado: "eu_ok", motivos: ["local"] },
};
const CREDS = [
  { id: "c-1", name: "Clave Anthropic", kind: "secret", level: "tenant", fingerprint: "ab12", status: "active", in_use_by: ["Claude Sonnet"] },
  { id: "c-2", name: "Clave OR", kind: "secret", level: "tenant", fingerprint: "cd34", status: "active", in_use_by: [] },
];

const DPAS = [
  { id: "6f1a0c2e-0000-4000-8000-000000000001", provider_name: "OpenAI", dpa_type: "standard", processing_region: "US", expiration_date: "2027-01-01", vigente: true },
  { id: "6f1a0c2e-0000-4000-8000-000000000002", provider_name: "Anthropic", dpa_type: "standard", processing_region: "EU", expiration_date: "2027-06-30", vigente: true },
];

function setup(role: string, operator = false) {
  const token = `h.${btoa(JSON.stringify({ role })).replace(/=+$/, "")}.s`;
  localStorage.setItem("sentinel_session_token", token);
  localStorage.setItem("sentinel_current_user", JSON.stringify({ id: "1", username: "u", role: "admin", email: "" }));
  const calls: { url: string; init?: RequestInit }[] = [];
  const entries = [CLAUDE, OR, LOCAL];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const method = init?.method ?? "GET";
    if (url.startsWith("/api/v1/catalog/entries") && method === "GET") return new Response(JSON.stringify({ data: entries }), { status: 200 });
    if (url === "/api/v1/catalog/credentials" && method === "GET") return new Response(JSON.stringify({ data: CREDS }), { status: 200 });
    if (url === "/api/v1/catalog/dpas") return new Response(JSON.stringify({ data: DPAS }), { status: 200 });
    if (url === "/api/v1/redirect/capabilities") return new Response(JSON.stringify({ operator }), { status: 200 });
    if (url === "/api/v1/catalog/entries" && method === "POST") {
      const sent = JSON.parse(String(init?.body));
      return new Response(JSON.stringify({ ...OR, id: "e-9", name: sent.name, has_credential: true }), { status: 201 });
    }
    if (url === "/api/v1/catalog/entries/e-1/sheet" && method === "PUT") {
      return new Response(JSON.stringify({ ...CLAUDE, semaforo: { estado: "standard", motivos: ["sin_dpa"] },
        sheet: { ...SHEET, inference_jurisdiction: "EU", classification_version: "console:1" } }), { status: 200 });
    }
    if (url.includes("/revoke") && method === "POST") {
      return new Response(JSON.stringify({ detail: "la credencial está en uso por: Claude Sonnet. Elegí un reemplazo o desactivá esos modelos." }), { status: 409 });
    }
    if (method === "POST" || method === "PUT" || method === "PATCH") return new Response(JSON.stringify({}), { status: 200 });
    return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

describe("pantalla del catálogo", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("el catálogo ya no es una página aparte: lo absorbe la pantalla única «Modelos»", () => {
    const pages = collectPluginPages(import.meta.glob("../../pages/*.tsx", { eager: true }));
    expect(pages.find(p => p.path === "/catalogo")).toBeUndefined();
    expect(pages.find(p => p.path === "/modelos")).toMatchObject({ roles: ["admin", "compliance_officer", "lectura"] });
  });

  it("lista única con semáforo, motivos legibles y etiqueta Agregador; sin valores de credencial", async () => {
    setup("tenant_admin");
    render(<CatalogPage />);
    expect(await screen.findByText("Claude Sonnet")).toBeInTheDocument();
    expect(screen.getByText("Sin clasificar")).toBeInTheDocument();
    expect(screen.getByText("Falta cargar: jurisdicción de inferencia")).toBeInTheDocument();
    expect(screen.getByLabelText("Semáforo: Estándar")).toBeInTheDocument();
    expect(screen.getByText("Agregador: no cubre al proveedor final · Sin DPA")).toBeInTheDocument();
    expect(screen.getByText("Admisible UE")).toBeInTheDocument();
    expect(screen.getByText("Agregador")).toBeInTheDocument();
    expect(screen.getByText(/huella ab12/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(SECRET);
    expect(screen.getByRole("button", { name: "Nuevo modelo" })).toBeInTheDocument();
  });

  it("alta de OpenRouter con credencial nueva: cuerpo correcto y secreto borrado del formulario", async () => {
    const calls = setup("tenant_admin");
    render(<CatalogPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Nuevo modelo" }));
    fireEvent.change(screen.getByLabelText("Proveedor"), { target: { value: "openrouter" } });
    expect(screen.getByLabelText("Es un agregador")).toBeChecked();
    expect(screen.getByLabelText("Familia de protocolo")).toHaveValue("openai_chat");
    fireEvent.change(screen.getByLabelText("Nombre"), { target: { value: "OR nuevo" } });
    fireEvent.change(screen.getByLabelText("Modelo real"), { target: { value: "qwen/qwen3" } });
    fireEvent.change(screen.getByLabelText("Nombre de la credencial"), { target: { value: "Clave nueva" } });
    const secret = screen.getByLabelText("Clave de API") as HTMLInputElement;
    expect(secret.type).toBe("password");
    fireEvent.change(secret, { target: { value: SECRET } });
    fireEvent.change(screen.getByLabelText("Id público (opcional)"), { target: { value: "or-nuevo" } });
    fireEvent.click(screen.getByLabelText("Imágenes"));
    fireEvent.click(screen.getByLabelText("PDF"));
    fireEvent.click(screen.getByRole("button", { name: "Crear modelo" }));
    expect(await screen.findByText(/creado/)).toBeInTheDocument();
    const post = calls.find(c => c.url === "/api/v1/catalog/entries" && c.init?.method === "POST");
    const body = JSON.parse(String(post?.init?.body));
    expect(body).toMatchObject({
      level: "tenant", name: "OR nuevo", provider: "openrouter", real_model: "qwen/qwen3", protocol_family: "openai_chat",
      api_base: "https://openrouter.ai/api/v1", credential: { new: { name: "Clave nueva", value: SECRET } },
      public_id: "or-nuevo", features: { images: true, documents_pdf: true, tools: false },
    });
    expect(document.body.textContent).not.toContain(SECRET);
  });

  it("el admin declara los parámetros no soportados en la ficha y el PATCH los manda", async () => {
    const calls = setup("tenant_admin");
    render(<CatalogPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Editar Claude Sonnet" }));
    const dialog = await screen.findByRole("dialog");
    const campo = within(dialog).getByLabelText("Parámetros no soportados") as HTMLInputElement;
    expect(campo.value).toBe("");                                              // nada precargado
    fireEvent.change(campo, { target: { value: "temperature, top_p" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar cambios" }));
    await waitFor(() => expect(calls.find(c => c.url === "/api/v1/catalog/entries/e-1" && c.init?.method === "PATCH")).toBeDefined());
    const patch = calls.find(c => c.init?.method === "PATCH");
    expect(JSON.parse(String(patch?.init?.body))).toEqual({ unsupported_params: ["temperature", "top_p"] });
  });

  it("la ficha muestra el semáforo recalculado por el backend y no ofrece editarlo", async () => {
    const calls = setup("compliance_officer");
    render(<CatalogPage />);
    expect(await screen.findByText("Claude Sonnet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Nuevo modelo" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ficha de Claude Sonnet" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByLabelText("Semáforo")).toBeNull();
    fireEvent.change(within(dialog).getByLabelText("Jurisdicción de inferencia"), { target: { value: "EU" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar ficha" }));
    expect(await within(dialog).findByText("Semáforo recalculado")).toBeInTheDocument();
    expect(within(dialog).getByText("Sin DPA")).toBeInTheDocument();
    const put = calls.find(c => c.init?.method === "PUT" && c.url.endsWith("/e-1/sheet"));
    const sent = JSON.parse(String(put?.init?.body));
    expect(sent).toMatchObject({ inference_jurisdiction: "EU" });
    expect(sent).not.toHaveProperty("semaforo");
    // el formulario de la ficha no tiene ningún control de semáforo
    expect(within(dialog).queryByRole("combobox", { name: /sem[aá]foro/i })).toBeNull();
  });

  it("la ficha elige el DPA de una lista (sin pedir un UUID) y sugiere el del proveedor", async () => {
    const calls = setup("compliance_officer");
    render(<CatalogPage />);
    expect(await screen.findByText("Claude Sonnet")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ficha de Claude Sonnet" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByPlaceholderText("Identificador en el registro de DPAs")).toBeNull();
    const select = await within(dialog).findByLabelText("DPA asociado");
    expect(await within(dialog).findByText(/Anthropic · EU · vence 2027-06-30 — sugerido/)).toBeInTheDocument();
    expect((select as HTMLSelectElement).value).toBe("");            // sugerir no es elegir
    fireEvent.change(select, { target: { value: "6f1a0c2e-0000-4000-8000-000000000002" } });
    fireEvent.change(within(dialog).getByLabelText("Jurisdicción de inferencia"), { target: { value: "EU" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar ficha" }));
    await within(dialog).findByText("Semáforo recalculado");
    const put = calls.find(c => c.init?.method === "PUT" && c.url.endsWith("/e-1/sheet"));
    expect(JSON.parse(String(put?.init?.body))).toMatchObject({ dpa_registry_id: "6f1a0c2e-0000-4000-8000-000000000002" });
  });

  it("ficha desactualizada: aviso claro", async () => {
    setup("tenant_admin");
    const stale = { ...CLAUDE, sheet: { ...SHEET, classification_version: "stale" },
      semaforo: { estado: "unclassified", motivos: ["ficha_desactualizada"] } };
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      new Response(JSON.stringify(url.startsWith("/api/v1/catalog/entries") ? { data: [stale] }
        : url.endsWith("credentials") ? { data: [] } : { operator: false }), { status: 200 })));
    render(<CatalogPage />);
    expect((await screen.findAllByText("Ficha desactualizada")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Ficha de Claude Sonnet" }));
    expect(await screen.findByText(/La ficha está desactualizada/)).toBeInTheDocument();
  });

  it("el rol lectura no ve ningún botón de escritura", async () => {
    setup("lectura", true);
    render(<CatalogPage />);
    expect(await screen.findByText("Claude Sonnet")).toBeInTheDocument();
    expect(screen.getByText(/modo consulta/)).toBeInTheDocument();
    for (const name of [/Nuevo modelo/, /^Editar/, /^Archivar/, /^Desactivar/, /^Ofrecer/]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    fireEvent.click(screen.getByRole("button", { name: "Ficha de Claude Sonnet" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByRole("button", { name: "Guardar ficha" })).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Credenciales" }));
    expect(screen.getByText(/administra el rol de administración/)).toBeInTheDocument();
  });

  it("archivar pide motivo de al menos 3 caracteres", async () => {
    const calls = setup("tenant_admin");
    render(<CatalogPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Archivar Claude Sonnet" }));
    const confirm = within(screen.getByRole("dialog")).getByRole("button", { name: "Archivar" });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(screen.getByRole("dialog")).getByRole("textbox"), { target: { value: "ya no se usa" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(calls.some(c => c.url.endsWith("/e-1/archive"))).toBe(true));
    const call = calls.find(c => c.url.endsWith("/e-1/archive"));
    expect(JSON.parse(String(call?.init?.body))).toEqual({ reason: "ya no se usa" });
  });

  it("solo el operador ve Nivel y Ofrecer", async () => {
    setup("tenant_admin", false);
    const { unmount } = render(<CatalogPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Nuevo modelo" }));
    expect(screen.queryByLabelText("Nivel")).toBeNull();
    unmount();
    setup("tenant_admin", true);
    render(<CatalogPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Nuevo modelo" }));
    expect(await screen.findByLabelText("Nivel")).toBeInTheDocument();
  });

  it("credenciales: lista con huella y uso; revocar en uso ofrece reemplazo o desactivar", async () => {
    const calls = setup("tenant_admin");
    render(<CatalogPage />);
    await screen.findByText("Claude Sonnet");
    fireEvent.click(screen.getByRole("tab", { name: "Credenciales" }));
    expect(screen.getByText("ab12")).toBeInTheDocument();
    expect(screen.getByText("1 modelo")).toBeInTheDocument();
    expect(screen.getByText("0 modelos")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Revocar Clave Anthropic" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Revocar" })).toBeDefined();
    fireEvent.click(within(dialog).getByLabelText("Pasar los modelos a otra credencial"));
    fireEvent.change(within(dialog).getByLabelText("Credencial de reemplazo"), { target: { value: "c-2" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Revocar" }));
    await waitFor(() => expect(calls.some(c => c.url.endsWith("/c-1/revoke"))).toBe(true));
    const revoke = calls.find(c => c.url.endsWith("/c-1/revoke"));
    expect(JSON.parse(String(revoke?.init?.body))).toEqual({ replacement_id: "c-2" });
    // la API respondió 409: el mensaje llega en castellano dentro del diálogo
    expect(await within(dialog).findByText(/está en uso por/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(SECRET);
  });

  it("reemplazar valor: campo contraseña vacío; se manda como cadena y nunca se muestra", async () => {
    const calls = setup("tenant_admin");
    render(<CatalogPage />);
    await screen.findByText("Claude Sonnet");
    fireEvent.click(screen.getByRole("tab", { name: "Credenciales" }));
    fireEvent.click(screen.getByRole("button", { name: "Reemplazar valor de Clave Anthropic" }));
    const field = within(screen.getByRole("dialog")).getByLabelText("Clave de API") as HTMLInputElement;
    expect(field.type).toBe("password");
    expect(field.value).toBe("");
    fireEvent.change(field, { target: { value: SECRET } });
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Reemplazar" }));
    await waitFor(() => expect(calls.some(c => c.url.endsWith("/c-1/replace"))).toBe(true));
    expect(JSON.parse(String(calls.find(c => c.url.endsWith("/c-1/replace"))?.init?.body))).toEqual({ value: SECRET });
    await waitFor(() => expect(document.body.textContent).not.toContain(SECRET));
  });

  it("sin la extensión activa lo dice en castellano", async () => {
    localStorage.setItem("sentinel_session_token", "x");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })));
    render(<CatalogPage />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
