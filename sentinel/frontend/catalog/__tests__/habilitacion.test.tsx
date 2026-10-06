// Habilitación explícita por datos (057 T025; FR-029, research R14): el panel no sabe de ningún proveedor
// «bloqueado»: muestra lo que dice el backend. Con las listas vacías (Eleia, D1) no hay nada bloqueado;
// una entrada bloqueada se habilita con motivo y rol permitido; las reglas se ven y se editan por rol.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { CatalogPage } from "../CatalogPage";

const SHEET = {
  provider_legal_entity: null, entity_jurisdiction: null, control_jurisdiction: null, inference_jurisdiction: "unknown",
  logs_jurisdiction: "unknown", zero_data_retention: null, trains_on_data: null, transfer_mechanism: "unknown",
  dpa_registry_id: null, eu_region_contracted: null, notes: null, classification_version: "console:0",
  classified_by: null, classified_at: null,
};
const entry = (over: Record<string, unknown>) => ({
  level: "tenant", tenant_id: "t", api_base: null, role: "text", capability: "standard", features: {}, context_window: null,
  max_output: null, blocked_by_default: false, enabled_at: null, status: "active", source: "console", has_credential: true,
  sheet: SHEET, is_aggregator: false, semaforo: { estado: "unclassified", motivos: [] }, ...over,
});
const LIBRE = entry({ id: "e-1", name: "Modelo libre", public_id: "libre", provider: "deepseek", real_model: "deepseek-chat", protocol_family: "openai_chat" });
const BLOQUEADA = entry({ id: "e-2", name: "Modelo bloqueado", public_id: "bloqueado", provider: "zai", real_model: "glm-4.6", protocol_family: "openai_chat", blocked_by_default: true });
const HABILITADA = entry({ id: "e-3", name: "Modelo habilitado", public_id: "habilitado", provider: "zai", real_model: "glm-4.6", protocol_family: "openai_chat", blocked_by_default: true, enabled_at: "2026-10-01T00:00:00Z" });
const REGLA_INST = { id: "r-1", kind: "provider", value: "zai", level: "installation", tenant_id: null, reason: "política", created_by_role: "super_admin", created_at: "2026-10-01T00:00:00Z" };
const REGLA_EMP = { id: "r-2", kind: "api_host", value: "api.ejemplo.cn", level: "tenant", tenant_id: "t", reason: "criterio propio", created_by_role: "compliance_officer", created_at: "2026-10-02T00:00:00Z" };

type Llamada = { url: string; init?: RequestInit };

function setup(role: string, { entries = [LIBRE], rules = [] as unknown[], operator = false } = {}) {
  const token = `h.${btoa(JSON.stringify({ role })).replace(/=+$/, "")}.s`;
  localStorage.setItem("sentinel_session_token", token);
  localStorage.setItem("sentinel_current_user", JSON.stringify({ id: "1", username: "u", role: "admin", email: "" }));
  const calls: Llamada[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const method = init?.method ?? "GET";
    if (url.startsWith("/api/v1/catalog/entries") && method === "GET") return new Response(JSON.stringify({ data: entries }), { status: 200 });
    if (url === "/api/v1/catalog/credentials") return new Response(JSON.stringify({ data: [] }), { status: 200 });
    if (url === "/api/v1/redirect/capabilities") return new Response(JSON.stringify({ operator }), { status: 200 });
    if (url === "/api/v1/catalog/enablement-rules" && method === "GET") return new Response(JSON.stringify({ data: rules }), { status: 200 });
    if (url === "/api/v1/catalog/enablement-rules" && method === "POST") {
      return new Response(JSON.stringify({ ...REGLA_EMP, id: "r-9", changed: 2 }), { status: 201 });
    }
    if (url.startsWith("/api/v1/catalog/enablement-rules/") && method === "DELETE") return new Response(JSON.stringify({ id: "r-2", changed: 1 }), { status: 200 });
    if (url.endsWith("/enable") && method === "POST") return new Response(JSON.stringify({ ...BLOQUEADA, enabled_at: "2026-10-06T00:00:00Z" }), { status: 200 });
    return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 });
  }));
  return calls;
}

describe("habilitación explícita en el panel", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("con las listas vacías nada figura bloqueado, ni siquiera el proveedor que otras instalaciones bloquean", async () => {
    setup("tenant_admin");
    render(<CatalogPage />);
    expect(await screen.findByText("Modelo libre")).toBeInTheDocument();
    expect(screen.queryByText("Bloqueado por defecto")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Habilitar / })).toBeNull();
  });

  it("el formulario de alta no promete un bloqueo fijo por proveedor (es dato, no código)", async () => {
    setup("tenant_admin");
    render(<CatalogPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Nuevo modelo" }));
    fireEvent.change(screen.getByLabelText("Proveedor"), { target: { value: "deepseek" } });
    expect(screen.queryByText(/Queda bloqueado/)).toBeNull();
  });

  it("una entrada bloqueada se marca y el rol permitido ve «Habilitar»; la habilitada no", async () => {
    setup("tenant_admin", { entries: [LIBRE, BLOQUEADA, HABILITADA] });
    render(<CatalogPage />);
    expect(await screen.findByText("Modelo bloqueado")).toBeInTheDocument();
    expect(screen.getAllByText("Bloqueado por defecto")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Habilitar Modelo bloqueado" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Habilitar Modelo habilitado" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Habilitar Modelo libre" })).toBeNull();
  });

  it.each(["lectura", "client"])("el rol %s no ve «Habilitar»", async role => {
    setup(role, { entries: [BLOQUEADA] });
    render(<CatalogPage />);
    expect(await screen.findByText("Modelo bloqueado")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Habilitar / })).toBeNull();
  });

  it("cumplimiento puede habilitar", async () => {
    setup("compliance_officer", { entries: [BLOQUEADA] });
    render(<CatalogPage />);
    expect(await screen.findByRole("button", { name: "Habilitar Modelo bloqueado" })).toBeInTheDocument();
  });

  it("habilitar exige motivo y lo manda a la API", async () => {
    const calls = setup("tenant_admin", { entries: [BLOQUEADA] });
    render(<CatalogPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Habilitar Modelo bloqueado" }));
    const dialog = await screen.findByRole("dialog");
    const confirmar = within(dialog).getByRole("button", { name: "Habilitar" });
    expect(confirmar).toBeDisabled();                                         // sin motivo no se puede
    fireEvent.change(within(dialog).getByLabelText("Motivo"), { target: { value: "ab" } });
    expect(confirmar).toBeDisabled();                                         // muy corto
    fireEvent.change(within(dialog).getByLabelText("Motivo"), { target: { value: "uso aprobado por cumplimiento" } });
    expect(confirmar).toBeEnabled();
    fireEvent.click(confirmar);
    await waitFor(() => expect(calls.find(c => c.url === "/api/v1/catalog/entries/e-2/enable" && c.init?.method === "POST")).toBeDefined());
    const post = calls.find(c => c.url.endsWith("/enable"));
    expect(JSON.parse(String(post?.init?.body))).toEqual({ reason: "uso aprobado por cumplimiento" });
  });

  // ── reglas ──
  const irAReglas = async () => fireEvent.click(await screen.findByRole("tab", { name: "Habilitación" }));

  it("sin reglas, la pestaña explica que nada nace bloqueado", async () => {
    setup("tenant_admin");
    render(<CatalogPage />);
    await irAReglas();
    expect(await screen.findByText(/ningún modelo nace bloqueado/i)).toBeInTheDocument();
  });

  it("muestra las reglas de instalación y las de la empresa, con su motivo", async () => {
    setup("compliance_officer", { rules: [REGLA_INST, REGLA_EMP] });
    render(<CatalogPage />);
    await irAReglas();
    expect(await screen.findByText("zai")).toBeInTheDocument();
    expect(screen.getByText("api.ejemplo.cn")).toBeInTheDocument();
    expect(screen.getByText("política")).toBeInTheDocument();
    expect(screen.getByText("criterio propio")).toBeInTheDocument();
  });

  it("cumplimiento agrega una regla de la empresa con motivo", async () => {
    const calls = setup("compliance_officer");
    render(<CatalogPage />);
    await irAReglas();
    fireEvent.click(await screen.findByRole("button", { name: "Agregar regla" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Tipo de regla"), { target: { value: "api_host" } });
    fireEvent.change(within(dialog).getByLabelText("Valor"), { target: { value: "dashscope*.aliyuncs.com" } });
    fireEvent.change(within(dialog).getByLabelText("Motivo"), { target: { value: "criterio de la empresa" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar regla" }));
    await waitFor(() => expect(calls.find(c => c.url === "/api/v1/catalog/enablement-rules" && c.init?.method === "POST")).toBeDefined());
    const post = calls.find(c => c.init?.method === "POST");
    expect(JSON.parse(String(post?.init?.body))).toEqual({
      kind: "api_host", value: "dashscope*.aliyuncs.com", level: "tenant", reason: "criterio de la empresa",
    });
    expect(await screen.findByText(/2 modelo\(s\) pasaron a bloqueados/)).toBeInTheDocument();
  });

  it("el operador elige el nivel «Instalación»", async () => {
    const calls = setup("super_admin", { operator: true });
    render(<CatalogPage />);
    await irAReglas();
    fireEvent.click(await screen.findByRole("button", { name: "Agregar regla" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Nivel"), { target: { value: "installation" } });
    fireEvent.change(within(dialog).getByLabelText("Valor"), { target: { value: "zai" } });
    fireEvent.change(within(dialog).getByLabelText("Motivo"), { target: { value: "política de la instalación" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar regla" }));
    await waitFor(() => expect(calls.find(c => c.init?.method === "POST")).toBeDefined());
    expect(JSON.parse(String(calls.find(c => c.init?.method === "POST")?.init?.body))).toMatchObject({ level: "installation", kind: "provider", value: "zai" });
  });

  it("el admin de empresa agrega pero no borra; cumplimiento borra solo las de su empresa", async () => {
    setup("tenant_admin", { rules: [REGLA_INST, REGLA_EMP] });
    const { unmount } = render(<CatalogPage />);
    await irAReglas();
    expect(await screen.findByRole("button", { name: "Agregar regla" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Quitar regla/ })).toBeNull();
    unmount();
    vi.unstubAllGlobals();
    localStorage.clear();
    const calls = setup("compliance_officer", { rules: [REGLA_INST, REGLA_EMP] });
    render(<CatalogPage />);
    await irAReglas();
    expect(await screen.findByRole("button", { name: "Quitar regla api_host api.ejemplo.cn" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Quitar regla provider zai" })).toBeNull();     // la de instalación no es suya
    fireEvent.click(screen.getByRole("button", { name: "Quitar regla api_host api.ejemplo.cn" }));
    fireEvent.click(await screen.findByRole("button", { name: "Quitar" }));
    await waitFor(() => expect(calls.find(c => c.init?.method === "DELETE")).toBeDefined());
    expect(calls.find(c => c.init?.method === "DELETE")?.url).toBe("/api/v1/catalog/enablement-rules/r-2");
  });

  it("lectura ve las reglas pero no puede cambiarlas", async () => {
    setup("lectura", { rules: [REGLA_INST] });
    render(<CatalogPage />);
    await irAReglas();
    expect(await screen.findByText("zai")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Agregar regla" })).toBeNull();
  });
});
