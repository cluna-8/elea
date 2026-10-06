import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { CostRouting } from "../CostRouting";

const dest = (id: string, name: string, price?: [number, number]) => ({
  id, level: "tenant", tenant_id: "t", name, provider: "openai_compatible", real_model: name,
  protocol_family: "openai_chat", inference_jurisdiction: "EU", entity_jurisdiction: "EU",
  blocked_by_default: false, enabled_at: null, enable_reason: null, has_credential: true, api_base: "http://x",
  status: "active", ...(price ? { price_override: { input_per_mtok: price[0], output_per_mtok: price[1] } } : {}),
});
const PUB = { id: "p-1", face: "claude", public_id: "claude-sonnet-4-5", family_tier: "sonnet", label: null };
const RULE = (over = {}) => ({ id: "r-1", published_model_id: "p-1", family_tier: null, request_class: null,
  scope_type: "tenant", scope_value: "*", targets: ["d-1", "d-2"], strategy: "order", ...over });

function setup(opts: { role?: string; rules?: unknown[]; dests?: unknown[]; patch?: Response } = {}) {
  const token = `h.${btoa(JSON.stringify({ role: opts.role ?? "tenant_admin" })).replace(/=+$/, "")}.s`;
  localStorage.setItem("sentinel_session_token", token);
  localStorage.setItem("sentinel_current_user", JSON.stringify({ id: "1", username: "u", role: "admin", email: "" }));
  const routes: Record<string, unknown> = {
    "/api/v1/redirect/rules": { data: opts.rules ?? [RULE()] },
    "/api/v1/redirect/published-models": { data: [PUB] },
    "/api/v1/redirect/destinations": { data: opts.dests ?? [dest("d-1", "Grande", [3, 15]), dest("d-2", "Chico", [0.3, 1.2])] },
    "/api/v1/redirect/capabilities": { operator: false },
  };
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (init?.method === "PATCH") return opts.patch ?? new Response(JSON.stringify(RULE({ strategy: "cheapest" })), { status: 200 });
    const b = routes[url];
    return b === undefined ? new Response("{}", { status: 404 }) : new Response(JSON.stringify(b), { status: 200 });
  }));
  return calls;
}

describe("Costo: estrategia por regla", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("carga las reglas con el id publicado, los destinos y su precio por millón", async () => {
    const calls = setup();
    render(<CostRouting />);
    expect(await screen.findByText(/claude-sonnet-4-5/)).toBeInTheDocument();
    expect(screen.getByText(/Es la primera versión del routing por costo/)).toBeInTheDocument();
    expect(screen.getByText(/Grande/)).toBeInTheDocument();
    expect(screen.getByText(/18 USD\/M/)).toBeInTheDocument();
    expect(screen.getByText(/1,5 USD\/M|1\.5 USD\/M/)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /Más barato primero/ })).toHaveAttribute("aria-checked", "false");
    expect(calls.filter(c => c.init?.method && c.init.method !== "GET")).toEqual([]);
  });

  it("alternar el interruptor hace PATCH con la estrategia y recarga", async () => {
    const calls = setup();
    render(<CostRouting />);
    fireEvent.click(await screen.findByRole("switch", { name: /Más barato primero/ }));
    await waitFor(() => expect(calls.some(c => c.init?.method === "PATCH")).toBe(true));
    const patch = calls.find(c => c.init?.method === "PATCH")!;
    expect(patch.url).toBe("/api/v1/redirect/rules/r-1");
    expect(JSON.parse(String(patch.init!.body))).toEqual({ strategy: "cheapest" });
    await waitFor(() => expect(calls.filter(c => c.url === "/api/v1/redirect/rules" && !c.init?.method).length).toBeGreaterThan(1));
  });

  it("una regla ya en «más barato» vuelve a «order» al apagar", async () => {
    const calls = setup({ rules: [RULE({ strategy: "cheapest" })] });
    render(<CostRouting />);
    const sw = await screen.findByRole("switch", { name: /Más barato primero/ });
    expect(sw).toHaveAttribute("aria-checked", "true");
    fireEvent.click(sw);
    await waitFor(() => expect(calls.some(c => c.init?.method === "PATCH")).toBe(true));
    expect(JSON.parse(String(calls.find(c => c.init?.method === "PATCH")!.init!.body))).toEqual({ strategy: "order" });
  });

  it("solo lectura: ve el estado pero no puede cambiarlo", async () => {
    const calls = setup({ role: "compliance_officer", rules: [RULE({ strategy: "cheapest" })] });
    render(<CostRouting />);
    const sw = await screen.findByRole("switch", { name: /Más barato primero/ });
    expect(sw).toBeDisabled();
    expect(sw).toHaveAttribute("aria-checked", "true");
    fireEvent.click(sw);
    expect(calls.filter(c => c.init?.method === "PATCH")).toEqual([]);
  });

  it("avisa de los destinos sin precio", async () => {
    setup({ dests: [dest("d-1", "Grande"), dest("d-2", "Chico", [0.3, 1.2])] });
    render(<CostRouting />);
    const row = (await screen.findByText(/claude-sonnet-4-5/)).closest("tr")!;
    expect(within(row).getByText(/sin precio: queda al final/)).toBeInTheDocument();
  });

  it("sin reglas muestra el estado vacío", async () => {
    setup({ rules: [] });
    render(<CostRouting />);
    expect(await screen.findByText(/Todavía no hay reglas/)).toBeInTheDocument();
  });

  it("si la API falla al guardar, muestra el error y no cambia el interruptor", async () => {
    setup({ patch: new Response(JSON.stringify({ detail: "estrategia desconocida" }), { status: 422 }) });
    render(<CostRouting />);
    const sw = await screen.findByRole("switch", { name: /Más barato primero/ });
    fireEvent.click(sw);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /Más barato primero/ })).toHaveAttribute("aria-checked", "false");
  });

  it("si la carga falla, muestra el error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 500 })));
    render(<CostRouting />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
