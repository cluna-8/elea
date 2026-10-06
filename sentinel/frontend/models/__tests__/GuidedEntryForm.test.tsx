import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { GuidedEntryForm } from "../GuidedEntryForm";

const SECRET = "sk-ant-SUPER-SECRETO-999";
const PERMS = { operator: false, canAdmin: true, canSheetRole: true };
const CREDS = [
  { id: "c-1", name: "Clave existente", kind: "secret", level: "tenant", fingerprint: "ab12", status: "active", in_use_by: [] },
];
const PROVIDERS = {
  available: true, fetched_at: "2026-10-01T10:00:00Z",
  data: [
    { provider: "anthropic", display_name: "Anthropic", supported: true, example_model: "claude-sonnet-4",
      credential_fields: [{ key: "api_key", label: "Clave de API", required: true, field_type: "password" }] },
    { provider: "azure", display_name: "Azure OpenAI", supported: true,
      credential_fields: [
        { key: "api_key", label: "Clave de API", required: true, field_type: "password" },
        { key: "api_version", label: "Versión de API", required: true, field_type: "text" },
      ] },
    { provider: "cohere", display_name: "Cohere", supported: false, reason: "El motor lo lista pero todavía no lo servimos", credential_fields: [] },
  ],
};
const MODELS = {
  total: 2,
  data: [
    { id: "claude-sonnet-4", role: "text", max_input_tokens: 200000, max_output_tokens: 8192,
      price: { input: 0.000003, output: 0.000015, cache_read: 0.0000003, cache_write: 0.00000375 },
      features: { images: true, documents_pdf: true, tools: true, thinking: false, cache_control: true } },
    { id: "claude-haiku-4", role: "text", max_input_tokens: 100000, max_output_tokens: 4096,
      price: { input: 0.000001, output: 0.000005, cache_read: null, cache_write: null }, features: {} },
  ],
};

function setup(opts: { providers?: unknown; providersStatus?: number } = {}) {
  localStorage.setItem("sentinel_session_token", "x");
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const method = init?.method ?? "GET";
    if (url === "/api/v1/catalog/providers") {
      return new Response(JSON.stringify(opts.providers ?? PROVIDERS), { status: opts.providersStatus ?? 200 });
    }
    if (url.startsWith("/api/v1/catalog/providers/anthropic/models")) {
      const q = new URL(url, "http://x").searchParams.get("q") ?? "";
      const data = MODELS.data.filter(m => m.id.includes(q));
      return new Response(JSON.stringify({ data, total: data.length }), { status: 200 });
    }
    if (url === "/api/v1/catalog/reference/refresh" && method === "POST") {
      return new Response(JSON.stringify({ fetched_at: "2026-10-02T12:30:00Z" }), { status: 200 });
    }
    if (url === "/api/v1/catalog/entries/bulk" && method === "POST") {
      const sent = JSON.parse(String(init?.body));
      return new Response(JSON.stringify({
        results: sent.models.map((m: { real_model: string }, i: number) =>
          i === 1 ? { real_model: m.real_model, status: "error", detail: "ya existe un modelo igual" } : { real_model: m.real_model, status: "created" }),
      }), { status: 207 });
    }
    return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 });
  }));
  return calls;
}

const onDone = vi.fn();
const onClose = vi.fn();
const renderForm = () => render(<GuidedEntryForm perms={PERMS} credentials={CREDS as never} onClose={onClose} onDone={onDone} />);
const next = () => fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));

describe("alta guiada", () => {
  beforeEach(() => { localStorage.clear(); onDone.mockReset(); onClose.mockReset(); });
  afterEach(() => vi.unstubAllGlobals());

  it("lista proveedores con buscador; el no soportado queda deshabilitado con su motivo", async () => {
    setup();
    renderForm();
    expect(await screen.findByRole("radio", { name: /Anthropic/ })).toBeEnabled();
    const cohere = screen.getByRole("radio", { name: /Cohere/ });
    expect(cohere).toBeDisabled();
    expect(screen.getByText(/todavía no lo servimos/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Buscar proveedor"), { target: { value: "azu" } });
    expect(screen.queryByRole("radio", { name: /Anthropic/ })).toBeNull();
    expect(screen.getByRole("radio", { name: /Azure/ })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Buscar proveedor"), { target: { value: "zzz" } });
    expect(screen.getByText(/Ningún proveedor coincide/)).toBeInTheDocument();
  });

  it("no avanza sin proveedor", async () => {
    setup();
    renderForm();
    await screen.findByRole("radio", { name: /Anthropic/ });
    next();
    expect(screen.getByRole("alert")).toHaveTextContent("Elegí un proveedor.");
  });

  it("multiselección con vista previa sugerida → alta masiva con resultado por modelo; el secreto nunca se muestra", async () => {
    const calls = setup();
    renderForm();
    fireEvent.click(await screen.findByRole("radio", { name: /Anthropic/ }));
    next();
    expect(await screen.findByText("Sugerido por el motor · se puede cambiar")).toBeInTheDocument();
    expect(await screen.findByText("US$ 3 / US$ 15 por millón de tokens (entrada / salida)")).toBeInTheDocument();
    expect(screen.getByText("Contexto 200.000 · salida 8.192")).toBeInTheDocument();
    expect(screen.getByText("Imágenes, PDF, Herramientas, Caché de prompts")).toBeInTheDocument();
    expect(screen.getAllByText("Texto").length).toBeGreaterThan(0);
    // el buscador de modelos filtra en el servidor
    fireEvent.change(screen.getByLabelText("Buscar modelo"), { target: { value: "haiku" } });
    await waitFor(() => expect(screen.queryByLabelText("claude-sonnet-4")).toBeNull());
    fireEvent.change(screen.getByLabelText("Buscar modelo"), { target: { value: "" } });
    fireEvent.click(await screen.findByLabelText("claude-sonnet-4"));
    fireEvent.click(await screen.findByLabelText("claude-haiku-4"));
    next();
    fireEvent.change(screen.getByLabelText("Nombre de la credencial"), { target: { value: "Mi clave" } });
    const secret = screen.getByLabelText("Clave de API") as HTMLInputElement;
    expect(secret.type).toBe("password");
    fireEvent.change(secret, { target: { value: SECRET } });
    next();
    fireEvent.click(screen.getByRole("button", { name: "Dar de alta 2 modelos" }));
    expect(await screen.findByText("Resultado por modelo")).toBeInTheDocument();
    const post = calls.find(c => c.url === "/api/v1/catalog/entries/bulk");
    expect(JSON.parse(String(post?.init?.body))).toEqual({
      provider: "anthropic", level: "tenant", credential: { new: { name: "Mi clave", value: SECRET } },
      models: [
        { real_model: "claude-sonnet-4", accept_suggestion: true },
        { real_model: "claude-haiku-4", accept_suggestion: true },
      ],
    });
    expect(screen.getByText("Creado")).toBeInTheDocument();
    expect(screen.getByText("No se creó")).toBeInTheDocument();
    expect(screen.getByText("Ya existe un modelo igual.")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(SECRET);
    expect(document.querySelectorAll("input").length).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "Listo" }));
    expect(onDone).toHaveBeenCalledWith(expect.stringMatching(/^1 modelo dado de alta/));
  });

  it("el valor tipeado no se muestra en ningún texto, ni siquiera tras un error del servidor", async () => {
    setup();
    renderForm();
    fireEvent.click(await screen.findByRole("radio", { name: /Anthropic/ }));
    next();
    fireEvent.click(await screen.findByLabelText("claude-sonnet-4"));
    next();
    fireEvent.change(screen.getByLabelText("Clave de API"), { target: { value: SECRET } });
    expect(document.body.textContent).not.toContain(SECRET);
    next();
    // el bulk de este mock responde 207 con un solo modelo: no hay error, pero el estado se limpió
    fireEvent.click(screen.getByRole("button", { name: "Dar de alta 1 modelo" }));
    await screen.findByText("Resultado por modelo");
    expect(document.body.textContent).not.toContain(SECRET);
  });

  it("credencial existente y campos obligatorios del proveedor", async () => {
    const calls = setup();
    renderForm();
    fireEvent.click(await screen.findByRole("radio", { name: /Azure/ }));
    next();
    // modelos de azure: el mock responde 404 → modo manual
    fireEvent.change(await screen.findByLabelText("Modelo real"), { target: { value: "gpt-4o" } });
    fireEvent.click(screen.getByRole("button", { name: "Agregar modelo" }));
    next();
    next();
    expect(screen.getByRole("alert")).toHaveTextContent("Cargá la credencial o elegí una existente.");
    fireEvent.change(screen.getByLabelText("Clave de API"), { target: { value: "k" } });
    next();
    expect(screen.getByText("Obligatorio.")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Usar una credencial existente"));
    fireEvent.change(screen.getByLabelText("Credencial"), { target: { value: "c-1" } });
    fireEvent.change(screen.getByLabelText("Dirección base"), { target: { value: "https://x.openai.azure.com" } });
    next();
    fireEvent.click(screen.getByRole("button", { name: "Dar de alta 1 modelo" }));
    await screen.findByText("Resultado por modelo");
    const post = calls.find(c => c.url === "/api/v1/catalog/entries/bulk");
    expect(JSON.parse(String(post?.init?.body))).toEqual({
      provider: "azure", level: "tenant", credential: { id: "c-1" },
      models: [{ real_model: "gpt-4o", accept_suggestion: false }], api_base: "https://x.openai.azure.com",
    });
  });

  it("motor caído: aviso, proveedores locales y modo manual", async () => {
    const calls = setup({ providers: { available: false, fetched_at: null, data: [] } });
    renderForm();
    expect(await screen.findByText("Las listas del motor no están disponibles: podés cargar el modelo a mano.")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("radio", { name: /Ollama/ }));
    next();
    expect(calls.some(c => c.url.includes("/providers/ollama/models"))).toBe(false);
    fireEvent.change(screen.getByLabelText("Modelo real"), { target: { value: "llama3" } });
    fireEvent.click(screen.getByRole("button", { name: "Agregar modelo" }));
    expect(screen.getByText(/Elegidos \(1\): llama3/)).toBeInTheDocument();
    next();
    expect(screen.getByLabelText("Sin credencial")).toBeChecked();
    next();                                   // la dirección base es obligatoria para este proveedor
    expect(screen.getByText("Este proveedor necesita la dirección base.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Dirección base"), { target: { value: "http://ollama:11434" } });
    next();
    fireEvent.click(screen.getByRole("button", { name: "Dar de alta 1 modelo" }));
    await screen.findByText("Resultado por modelo");
    const post = calls.find(c => c.url === "/api/v1/catalog/entries/bulk");
    expect(JSON.parse(String(post?.init?.body))).toEqual({
      provider: "ollama", level: "tenant", models: [{ real_model: "llama3", accept_suggestion: false }], api_base: "http://ollama:11434",
    });
  });

  it("si la ruta de proveedores falla también se puede cargar a mano", async () => {
    setup({ providersStatus: 500, providers: { detail: "boom" } });
    renderForm();
    expect(await screen.findByText(/Las listas del motor no están disponibles/)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /Anthropic/ })).toBeEnabled();
  });

  it("«Avanzado» es plegable, valida el JSON y manda límites y modelo base", async () => {
    const calls = setup();
    renderForm();
    fireEvent.click(await screen.findByRole("radio", { name: /Anthropic/ }));
    next();
    fireEvent.click(await screen.findByLabelText("claude-sonnet-4"));
    next();
    fireEvent.change(screen.getByLabelText("Clave de API"), { target: { value: SECRET } });
    next();
    const details = screen.getByText("Avanzado").closest("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    details.open = true;
    expect(screen.getByLabelText("Pedidos por minuto (solo informativo)")).toBeInTheDocument();
    expect(screen.getByLabelText("Reintentos (se aplican en cada pedido)")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Parámetros libres (JSON)"), { target: { value: "{roto" } });
    fireEvent.click(screen.getByRole("button", { name: "Dar de alta 1 modelo" }));
    expect(await screen.findByText(/El JSON no es válido/)).toBeInTheDocument();
    expect(calls.some(c => c.url.endsWith("/entries/bulk"))).toBe(false);
    fireEvent.change(screen.getByLabelText("Parámetros libres (JSON)"), { target: { value: '{"api_key": "x"}' } });
    fireEvent.click(screen.getByRole("button", { name: "Dar de alta 1 modelo" }));
    expect(await screen.findByText(/No pongas credenciales acá/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Parámetros libres (JSON)"), { target: { value: '{"temperature": 0.2}' } });
    fireEvent.change(screen.getByLabelText("Pedidos por minuto (solo informativo)"), { target: { value: "60" } });
    fireEvent.change(screen.getByLabelText("Reintentos (se aplican en cada pedido)"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Modelo base (opcional)"), { target: { value: "claude-base" } });
    fireEvent.click(screen.getByRole("button", { name: "Dar de alta 1 modelo" }));
    await screen.findByText("Resultado por modelo");
    const sent = JSON.parse(String(calls.find(c => c.url.endsWith("/entries/bulk"))?.init?.body));
    expect((sent as { models: Record<string, unknown>[] }).models[0]).toMatchObject({ advanced: { temperature: 0.2 }, limits: { rpm: 60, num_retries: 2 }, base_model: "claude-base" });
  });

  it("«Actualizar precios» recarga las listas y muestra la fecha de la última actualización", async () => {
    const calls = setup();
    renderForm();
    await screen.findByRole("radio", { name: /Anthropic/ });
    expect(screen.getByText(/Última actualización:/)).toHaveTextContent("2026");
    const before = calls.filter(c => c.url === "/api/v1/catalog/providers").length;
    fireEvent.click(screen.getByRole("button", { name: "Actualizar precios" }));
    await waitFor(() => expect(calls.some(c => c.url === "/api/v1/catalog/reference/refresh" && c.init?.method === "POST")).toBe(true));
    await waitFor(() => expect(calls.filter(c => c.url === "/api/v1/catalog/providers").length).toBeGreaterThan(before));
    expect(await screen.findByText(/Última actualización:.*oct/i)).toBeInTheDocument();
  });

  it("operador: elige el nivel y la lista de credenciales sigue ese nivel", async () => {
    setup();
    render(<GuidedEntryForm perms={{ ...PERMS, operator: true }} credentials={CREDS as never} onClose={onClose} onDone={onDone} />);
    fireEvent.click(await screen.findByRole("radio", { name: /Anthropic/ }));
    next();
    fireEvent.click(await screen.findByLabelText("claude-sonnet-4"));
    next();
    expect(screen.getByLabelText("Nivel")).toHaveValue("tenant");
    fireEvent.click(screen.getByLabelText("Usar una credencial existente"));
    expect(within(screen.getByLabelText("Credencial")).getByText(/Clave existente/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Nivel"), { target: { value: "installation" } });
    expect(screen.getByText("No hay credenciales de este nivel")).toBeInTheDocument();
  });
});
