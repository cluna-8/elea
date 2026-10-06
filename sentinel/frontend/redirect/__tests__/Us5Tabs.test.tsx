import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RedirectPage } from "../RedirectPage";

const DEST = {
  id: "d-1", level: "tenant", tenant_id: "t", name: "Local UE", provider: "openai_compatible", real_model: "qwen3",
  protocol_family: "openai_chat", inference_jurisdiction: "EU", entity_jurisdiction: "EU", blocked_by_default: false,
  enabled_at: null, enable_reason: null, has_credential: true, api_base: "http://x", status: "active",
};
const KIT = {
  tool: "claude_code", face: "claude", scope: "tenant:*", catalog_version: "abc123", uses_credential: false,
  issued_key_id: null, models: ["claude-sonnet-4-5"], context_window: 128000, notes: ["Usá un directorio aislado."],
  files: [{ path: "claude-code.env", content: "ANTHROPIC_BASE_URL=https://gw.test/api/v1/gw\n" }],
};
const REPORT = {
  id: "r-1", destination_id: "d-1", face: "claude", tool: "claude_code", tool_version: "2.1.0", corpus_version: "2026.10.1",
  verdict: "no_apto", complete: true, pass_rate: 0.8, cost: 0.0012, run_at: "2026-10-01T10:00:00Z",
  results: [
    { capability: "conversation", name: "a", passed: true, detail_code: "ok", silent: false },
    { capability: "tools", name: "b", passed: false, detail_code: "no_tool_call", silent: true },
  ],
  regressions: [{ capability: "tools", name: "b", detail_code: "no_tool_call" }],
  compared_with: { id: "r-0", tool_version: "2.0.0", run_at: "2026-09-30T10:00:00Z" },
};
const COSTS = {
  totals: { requests: 3, cost_real: 0.0018, cost_real_comparable: 0.0018, cost_hypothetical: 0.0525, savings: 0.0507,
    without_reference: 1, estimated_real: 0 },
  by_destination: [{ destination_id: "d-1", destination_name: "Local UE", requests: 3, cost_real: 0.0018,
    cost_real_comparable: 0.0018, cost_hypothetical: 0.0525, savings: 0.0507, without_reference: 1, estimated_real: 0 }],
  by_scope: [{ scope_type: "tenant", scope_value: "*", requests: 3, cost_real: 0.0018, cost_real_comparable: 0.0018,
    cost_hypothetical: 0.0525, savings: 0.0507, without_reference: 1, estimated_real: 0 }],
  shadow_requests: 0, truncated: false, from: "", to: "", scope: "tenant:*",
};

function mockFetch(role = "tenant_admin", overrides: Record<string, () => Response> = {}) {
  const token = `h.${btoa(JSON.stringify({ role })).replace(/=+$/, "")}.s`;
  localStorage.setItem("sentinel_session_token", token);
  localStorage.setItem("sentinel_current_user", JSON.stringify({ id: "1", username: "u", role: "admin", email: "" }));
  const calls: { url: string; init?: RequestInit }[] = [];
  const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    for (const [prefix, make] of Object.entries(overrides)) if (url.startsWith(prefix)) return make();
    if (url.startsWith("/api/v1/redirect/kits/")) return json(KIT);
    if (url.startsWith("/api/v1/redirect/fidelity-runs")) return init?.method === "POST" ? json(REPORT, 201) : json({ data: [] });
    if (url.startsWith("/api/v1/redirect/cost-comparison")) return json(COSTS);
    const plain: Record<string, unknown> = {
      "/api/v1/redirect/destinations": { data: [DEST] }, "/api/v1/redirect/published-models": { data: [] },
      "/api/v1/redirect/rules": { data: [] }, "/api/v1/redirect/policy": { data: [] },
      "/api/v1/redirect/postures": { data: [], effective_tenant_redirected: { mode: "allowlist", jurisdictions: ["EU"], explicit: false } },
      "/api/v1/users/groups": [], "/api/v1/users": [], "/api/v1/keys": [], "/api/v1/redirect/capabilities": { operator: false },
    };
    return plain[url] === undefined ? json({ detail: "Not Found" }, 404) : json(plain[url]);
  }));
  return calls;
}

async function openTab(name: string) {
  render(<RedirectPage />);
  await screen.findByText("Local UE");
  fireEvent.click(screen.getByRole("tab", { name }));
}

describe("pestañas de US5", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("kits: genera sin credencial por defecto y muestra los archivos", async () => {
    const calls = mockFetch();
    await openTab("Kits");
    fireEvent.click(screen.getByRole("button", { name: "Generar kit" }));
    expect(await screen.findByText("claude-code.env")).toBeInTheDocument();
    expect(screen.getByText(/ANTHROPIC_BASE_URL=https:\/\/gw.test/)).toBeInTheDocument();
    expect(calls.find(c => c.url.startsWith("/api/v1/redirect/kits/"))?.url)
      .toBe("/api/v1/redirect/kits/claude_code?scope=tenant&include_credential=false");
    expect(screen.queryByText(/Se emitió una llave nueva/)).toBeNull();
  });

  it("kits: con llave pide include_credential y avisa que se muestra una sola vez", async () => {
    const calls = mockFetch("tenant_admin", {
      "/api/v1/redirect/kits/": () => new Response(JSON.stringify({ ...KIT, uses_credential: true, issued_key_id: "k-9" })),
    });
    await openTab("Kits");
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Generar kit" }));
    expect(await screen.findByText(/Se emitió una llave nueva/)).toBeInTheDocument();
    expect(calls.find(c => c.url.startsWith("/api/v1/redirect/kits/"))?.url).toContain("include_credential=true");
  });

  it("kits: sin modelos publicados el 404 se explica", async () => {
    mockFetch("tenant_admin", {
      "/api/v1/redirect/kits/": () => new Response(JSON.stringify({ detail: "no hay modelos publicados" }), { status: 404 }),
    });
    await openTab("Kits");
    fireEvent.click(screen.getByRole("button", { name: "Generar kit" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No hay modelos publicados para esta herramienta en este alcance.");
  });

  it("kits: cumplimiento solo consulta, sin generar", async () => {
    mockFetch("compliance_officer");
    await openTab("Kits");
    expect(screen.queryByRole("button", { name: "Generar kit" })).toBeNull();
    expect(screen.getByText(/Los kits los genera quien administra/)).toBeInTheDocument();
  });

  it("fidelidad: ejecuta contra un destino y muestra veredicto, funciones y regresión", async () => {
    const calls = mockFetch();
    await openTab("Fidelidad");
    fireEvent.click(screen.getByRole("button", { name: "Ejecutar prueba" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Elegí el destino a probar.");
    fireEvent.change(screen.getByLabelText("Destino"), { target: { value: "d-1" } });
    fireEvent.change(screen.getByLabelText("Versión de la herramienta (opcional)"), { target: { value: "2.1.0" } });
    fireEvent.click(screen.getByRole("button", { name: "Ejecutar prueba" }));
    expect(await screen.findByText("No apto")).toBeInTheDocument();
    expect(screen.getByText("No llamó a la herramienta pedida")).toBeInTheDocument();
    expect(screen.getByText("en silencio")).toBeInTheDocument();
    expect(screen.getByText(/Regresión respecto de la corrida anterior \(2.0.0\)/)).toBeInTheDocument();
    const post = calls.find(c => c.init?.method === "POST");
    expect(JSON.parse(String(post?.init?.body))).toEqual({ destination_id: "d-1", tool: "claude_code", tool_version: "2.1.0" });
  });

  it("fidelidad: error del backend en castellano", async () => {
    mockFetch("tenant_admin", {
      "/api/v1/redirect/fidelity-runs": () => new Response(JSON.stringify({ detail: "destino no permitido para la prueba: residency" }), { status: 403 }),
    });
    await openTab("Fidelidad");
    fireEvent.change(screen.getByLabelText("Destino"), { target: { value: "d-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Ejecutar prueba" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No tenés permiso: destino no permitido para la prueba: residency.");
  });

  it("costos: compara real e hipotético y avisa de los pedidos sin referencia", async () => {
    const calls = mockFetch("compliance_officer");
    await openTab("Costos");
    fireEvent.click(screen.getByRole("button", { name: "Comparar" }));
    expect(await screen.findByText("Costo hipotético")).toBeInTheDocument();
    expect(screen.getByText("1 sin modelo de referencia")).toBeInTheDocument();
    const dest = screen.getByText("Por destino").closest("div")!.parentElement!;
    expect(within(dest).getByText("Local UE")).toBeInTheDocument();
    const url = calls.find(c => c.url.startsWith("/api/v1/redirect/cost-comparison"))!.url;
    expect(url).toContain("scope=tenant");
    expect(url).toMatch(/from=\d{4}-\d{2}-\d{2}T00%3A00%3A00\.000Z/);
  });

  it("costos: período inválido no llama al backend", async () => {
    const calls = mockFetch();
    await openTab("Costos");
    fireEvent.change(screen.getByLabelText("Hasta"), { target: { value: "2000-01-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Comparar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("El período no es válido");
    await waitFor(() => expect(calls.some(c => c.url.startsWith("/api/v1/redirect/cost-comparison"))).toBe(false));
  });
});
