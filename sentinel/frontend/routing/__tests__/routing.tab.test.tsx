import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { RoutingTab } from "../RoutingTab";
import { CostRouting } from "../CostRouting";

const DEST = {
  id: "d-1", level: "tenant", tenant_id: "t", name: "Local UE", provider: "openai_compatible", real_model: "qwen3",
  protocol_family: "openai_chat", inference_jurisdiction: "EU", entity_jurisdiction: "EU", blocked_by_default: false,
  enabled_at: null, enable_reason: null, has_credential: true, api_base: "http://x", status: "active",
};

function setup() {
  const token = `h.${btoa(JSON.stringify({ role: "tenant_admin" })).replace(/=+$/, "")}.s`;
  localStorage.setItem("sentinel_session_token", token);
  localStorage.setItem("sentinel_current_user", JSON.stringify({ id: "1", username: "u", role: "admin", email: "" }));
  const routes: Record<string, unknown> = {
    "/api/v1/chat/router-config": { enabled: false, default_model: "", timeout_seconds: 5, embedding_model: "", routes: [] },
    "/api/v1/chat/models": [],
    "/api/v1/redirect/destinations": { data: [DEST] },
    "/api/v1/redirect/published-models": { data: [] },
    "/api/v1/redirect/rules": { data: [] },
    "/api/v1/redirect/policy": { data: [] },
    "/api/v1/redirect/postures": { data: [], effective_tenant_redirected: { mode: "allowlist", jurisdictions: ["EU"], explicit: false } },
    "/api/v1/users/groups": [], "/api/v1/users": [], "/api/v1/keys": [],
    "/api/v1/redirect/capabilities": { operator: false },
  };
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const b = routes[url];
    return b === undefined ? new Response("{}", { status: 404 }) : new Response(JSON.stringify(b), { status: 200 });
  }));
  return calls;
}

describe("Ruteo: sub-pestañas", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("arranca en Contenido y ofrece Contenido, Redirección y Costo", async () => {
    setup();
    render(<RoutingTab />);
    const tabs = screen.getAllByRole("tab").map(t => t.textContent);
    expect(tabs).toEqual(["Contenido", "Redirección", "Costo"]);
    expect(screen.getByRole("tab", { name: "Contenido" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("Ruteo por contenido")).toBeInTheDocument();
  });

  it("Redirección monta la política de la 068 sin encabezado de página", async () => {
    const calls = setup();
    render(<RoutingTab />);
    fireEvent.click(screen.getByRole("tab", { name: "Redirección" }));
    expect(await screen.findByText("Local UE")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Redirección de modelos" })).toBeNull();
    expect(screen.getByRole("tab", { name: "Destinos" })).toBeInTheDocument();
    expect(calls.some(c => c.url === "/api/v1/redirect/destinations")).toBe(true);
  });

  it("Redirección › Destinos es una vista: el enlace a Modelos llama al anfitrión y no hay formulario", async () => {
    const calls = setup();
    const onOpenModels = vi.fn();
    render(<RoutingTab onOpenModels={onOpenModels} />);
    fireEvent.click(screen.getByRole("tab", { name: "Redirección" }));
    expect(await screen.findByText("Local UE")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Nuevo destino" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ir a Modelos" }));
    expect(onOpenModels).toHaveBeenCalledTimes(1);
    expect(calls.filter(c => c.init?.method && c.init.method !== "GET")).toEqual([]);
  });

  it("Costo explica la primera versión y no escribe nada al abrirse", async () => {
    const calls = setup();
    render(<RoutingTab />);
    fireEvent.click(screen.getByRole("tab", { name: "Costo" }));
    expect(await screen.findByText(/primera versión del routing por costo/)).toBeInTheDocument();
    expect(screen.queryByText(/todavía no cambia ningún pedido/)).toBeNull();
    expect(calls.filter(c => c.init?.method && c.init.method !== "GET")).toEqual([]);
  });

  it("CostRouting lee las reglas por la API de redirección", async () => {
    const calls = setup();
    render(<CostRouting />);
    await screen.findByText(/primera versión del routing por costo/);
    expect(calls.some(c => c.url === "/api/v1/redirect/rules")).toBe(true);
  });
});
