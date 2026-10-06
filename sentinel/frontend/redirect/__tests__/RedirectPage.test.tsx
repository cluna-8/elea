import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { collectPluginPages } from "../../../../frontend/src/plugins/registry";
import { RedirectPage } from "../RedirectPage";

const DEST = {
  id: "d-1", level: "tenant", tenant_id: "t", name: "Local UE", provider: "openai_compatible", real_model: "qwen3",
  protocol_family: "openai_chat", inference_jurisdiction: "EU", entity_jurisdiction: "EU", blocked_by_default: false,
  enabled_at: null, enable_reason: null, has_credential: true, api_base: "http://x", status: "active",
  public_id: "local-ue", unsupported_params: [],
};

function mockFetch(role: string, operator = false, dest: Record<string, unknown> = DEST,
                   extra: { rules?: unknown[] } = {}) {
  const token = `h.${btoa(JSON.stringify({ role })).replace(/=+$/, "")}.s`;
  localStorage.setItem("sentinel_session_token", token);
  localStorage.setItem("sentinel_current_user", JSON.stringify({ id: "1", username: "u", role: "admin", email: "" }));
  const calls: { url: string; init?: RequestInit }[] = [];
  const routes: Record<string, unknown> = {
    "/api/v1/redirect/destinations": { data: [dest], warnings: [] },
    "/api/v1/redirect/published-models": { data: [] },
    "/api/v1/redirect/rules": { data: extra.rules ?? [] },
    "/api/v1/redirect/policy": { data: [{ id: "p", scope_type: "group", scope_value: "g-1", state: "shadow", reason: "piloto", changed_at: null }] },
    "/api/v1/redirect/postures": { data: [], effective_tenant_redirected: { mode: "allowlist", jurisdictions: ["EU"], explicit: false } },
    "/api/v1/users/groups": [{ id: "g-1", name: "Ventas" }],
    "/api/v1/users": [],
    "/api/v1/keys": [],
    "/api/v1/redirect/capabilities": { operator },
  };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const body = routes[url];
    return body === undefined ? new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })
      : new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

const writes = (calls: { url: string; init?: RequestInit }[]) =>
  calls.filter(c => c.init?.method && c.init.method !== "GET");

describe("pantalla de redirección", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("la redirección ya no es una página aparte: la absorbe la pantalla única «Modelos»", () => {
    const pages = collectPluginPages(import.meta.glob("../../pages/*.tsx", { eager: true }));
    expect(pages.find(p => p.path === "/redireccion")).toBeUndefined();
    expect(pages.find(p => p.path === "/modelos")).toMatchObject({ menu: { label: "Modelos", section: "governance" } });
  });

  it("Destinos es una vista del catálogo: lista los modelos, con el enlace a Modelos y sin formulario ni acciones", async () => {
    const calls = mockFetch("tenant_admin");
    const onOpenModels = vi.fn();
    render(<RedirectPage onOpenModels={onOpenModels} />);
    expect(await screen.findByText("Local UE")).toBeInTheDocument();
    expect(screen.getByText("local-ue")).toBeInTheDocument();
    expect(screen.getByText("Credencial guardada")).toBeInTheDocument();
    expect(screen.getByText(/se dan de alta, se editan, se archivan, se habilitan y se ofrecen/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ir a Modelos" }));
    expect(onOpenModels).toHaveBeenCalledTimes(1);
    // sin formulario de alta ni acciones de escritura (alta, credencial, ventana, precio, capacidades, habilitar, ofrecer, revocar)
    for (const name of ["Nuevo destino", "Crear destino", "Reemplazar credencial", "Ventana", "Precio", "Capacidades",
      "Habilitar", "Ofrecer", "Revocar", "Desactivar", "Activar"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.queryByLabelText("Clave de API")).toBeNull();
    expect(writes(calls)).toEqual([]);
  });

  it("la credencial nunca aparece y el alcance se muestra por nombre en Política", async () => {
    mockFetch("tenant_admin");
    render(<RedirectPage />);
    expect(await screen.findByText("Local UE")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/sk-|api_key/);
    fireEvent.click(screen.getByRole("tab", { name: "Política" }));
    expect(screen.getByText("Grupo: Ventas")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Residencia" }));
    expect(screen.getByText("Solo jurisdicciones permitidas")).toBeInTheDocument();
  });

  it("super_admin y tenant operador ven lo mismo: el alta es del catálogo para todos", async () => {
    for (const [role, operator] of [["super_admin", false], ["tenant_admin", true]] as const) {
      localStorage.clear();
      mockFetch(role, operator);
      const { unmount } = render(<RedirectPage />);
      expect(await screen.findByText("Local UE")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Nuevo destino" })).toBeNull();
      expect(screen.queryByRole("button", { name: "Ofrecer" })).toBeNull();
      unmount();
    }
  });

  it("muestra ventana, precio, capacidades y parámetros que el modelo no acepta (de la ficha del catálogo)", async () => {
    const sol = { ...DEST, name: "GPT 6.1 Sol", real_model: "gpt-6.1-sol", context_window: 400000,
      price_override: { input_per_mtok: 2.5, output_per_mtok: 10 }, capability_profile: { images: true },
      unsupported_params: ["temperature"] };
    mockFetch("tenant_admin", false, sol);
    render(<RedirectPage />);
    expect(await screen.findByText("GPT 6.1 Sol")).toBeInTheDocument();
    expect(screen.getByText(/Ventana: 400\.000|Ventana: 400,000|Ventana: 400000/)).toBeInTheDocument();
    expect(screen.getByText(/Precio: .*2,5.*10/)).toBeInTheDocument();
    expect(screen.getByText("Acepta: imágenes")).toBeInTheDocument();
    expect(screen.getByText("No acepta: temperature")).toBeInTheDocument();
  });

  it("destino sin perfil declarado: se muestra como solo texto y sin ventana", async () => {
    mockFetch("tenant_admin");
    render(<RedirectPage />);
    expect(await screen.findByText("Acepta: solo texto")).toBeInTheDocument();
    expect(screen.getByText("Ventana: sin declarar")).toBeInTheDocument();
    expect(screen.getByText(/Precio: automático/)).toBeInTheDocument();
  });

  it("cuenta las reglas que usan cada destino y avisa de los que ya no están disponibles", async () => {
    const rule = (id: string, targets: string[], warnings: unknown[] = []) =>
      ({ id, published_model_id: null, family_tier: "opus", request_class: null, scope_type: "tenant",
        scope_value: "*", targets, strategy: "order", warnings });
    const gone = "9f9f9f9f-0000-4000-8000-000000000001";
    mockFetch("tenant_admin", false, DEST, { rules: [
      rule("r1", ["d-1"]), rule("r2", ["d-1", gone], [{ code: "destination_unavailable", destination_id: gone }]),
      rule("r3", [gone], [{ code: "destination_unavailable", destination_id: gone }]),
    ] });
    render(<RedirectPage />);
    expect(await screen.findByText("2 reglas")).toBeInTheDocument();
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Hay reglas que nombran destinos que ya no están disponibles");
    expect(alert).toHaveTextContent(gone);
    expect(alert).toHaveTextContent("2 reglas");
    expect(alert).toHaveTextContent("Reponelo en Modelos");
  });

  it("Reglas ofrece los destinos del catálogo y marca el que ya no está", async () => {
    const gone = "9f9f9f9f-0000-4000-8000-000000000002";
    mockFetch("tenant_admin", false, DEST, { rules: [
      { id: "r1", published_model_id: null, family_tier: "opus", request_class: null, scope_type: "tenant",
        scope_value: "*", targets: [gone, "d-1"], strategy: "order",
        warnings: [{ code: "offer_withdrawn", destination_id: gone }] },
    ] });
    render(<RedirectPage />);
    fireEvent.click(await screen.findByRole("tab", { name: "Reglas" }));
    expect(await screen.findByText(/oferta retirada/)).toBeInTheDocument();
    expect(screen.getByText("Local UE")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Nueva regla" }));
    const options = Array.from((screen.getByLabelText("Agregar destino") as HTMLSelectElement).options).map(o => o.textContent);
    expect(options).toContain("Local UE");
  });

  it("cumplimiento entra en modo consulta y ve que el alta la hace administración", async () => {
    mockFetch("compliance_officer");
    render(<RedirectPage />);
    expect(await screen.findByText(/modo consulta/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Nuevo destino" })).toBeNull();
    expect(screen.getByText(/lo hace el rol de administración/)).toBeInTheDocument();
  });

  it("sin la extensión activa lo dice en castellano", async () => {
    localStorage.setItem("sentinel_session_token", "x");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })));
    render(<RedirectPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("no está activada en esta instalación");
  });
});
