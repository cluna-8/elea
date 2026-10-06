// Verificación del despliegue de Azure (057 T022; FR-020): una entrada cuyo modelo real no es un despliegue del recurso
// queda inactiva con un mensaje claro (no el «Resource not found» opaco) y se puede verificar de nuevo.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CatalogPage } from "../CatalogPage";

const SHEET = {
  provider_legal_entity: null, entity_jurisdiction: null, control_jurisdiction: null, inference_jurisdiction: "unknown",
  logs_jurisdiction: "unknown", zero_data_retention: null, trains_on_data: null, transfer_mechanism: "unknown",
  dpa_registry_id: null, eu_region_contracted: null, notes: null, classification_version: "console:0", classified_by: null, classified_at: null,
};
const base = {
  level: "installation", tenant_id: null, api_base: "https://recurso.openai.azure.com", role: "text", capability: "standard",
  features: {}, context_window: 400000, max_output: null, blocked_by_default: false, enabled_at: null, source: "seed",
  has_credential: true, sheet: SHEET, is_aggregator: false, provider: "azure", protocol_family: "openai_chat",
  semaforo: { estado: "unclassified", motivos: [] },
};
const SIN_DESPLIEGUE = {
  ...base, id: "e-1", name: "gpt-5.6-luna", public_id: "gpt-5.6-luna", real_model: "gpt-5.6-luna", status: "inactive",
  deployment_check: { status: "not_found", checked_at: "2026-10-06T00:00:00Z", message: "El despliegue gpt-5.6-luna no existe en el recurso configurado" },
};
const OK = { ...base, id: "e-2", name: "gpt-5.1-chat", public_id: "gpt-5.1-chat", real_model: "gpt-5.1-chat", status: "active",
  deployment_check: { status: "ok", checked_at: "2026-10-06T00:00:00Z" } };

function setup(role: string, entries: unknown[], checked: unknown = { ...SIN_DESPLIEGUE, status: "active", deployment_check: OK.deployment_check }) {
  const token = `h.${btoa(JSON.stringify({ role })).replace(/=+$/, "")}.s`;
  localStorage.setItem("sentinel_session_token", token);
  localStorage.setItem("sentinel_current_user", JSON.stringify({ id: "1", username: "u", role: "admin", email: "" }));
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const method = init?.method ?? "GET";
    if (url.endsWith("/check") && method === "POST") return new Response(JSON.stringify(checked), { status: 200 });
    if (url.startsWith("/api/v1/catalog/entries") && method === "GET") return new Response(JSON.stringify({ data: entries }), { status: 200 });
    if (url === "/api/v1/catalog/credentials") return new Response(JSON.stringify({ data: [] }), { status: 200 });
    if (url === "/api/v1/redirect/capabilities") return new Response(JSON.stringify({ operator: true }), { status: 200 });
    return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 });
  }));
  return calls;
}

describe("catálogo de Azure: verificación del despliegue", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("una entrada sin despliegue se ve inactiva con el motivo claro", async () => {
    setup("super_admin", [SIN_DESPLIEGUE, OK]);
    render(<CatalogPage />);
    expect(await screen.findByText("El despliegue gpt-5.6-luna no existe en el recurso configurado")).toBeInTheDocument();
    expect(screen.getByText("Inactivo")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Resource not found/i);
  });

  it("«Verificar despliegue» llama a /check y avisa el resultado", async () => {
    const calls = setup("super_admin", [SIN_DESPLIEGUE]);
    render(<CatalogPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Verificar despliegue de gpt-5.6-luna" }));
    await waitFor(() => expect(calls.find(c => c.url === "/api/v1/catalog/entries/e-1/check" && c.init?.method === "POST")).toBeDefined());
    expect(await screen.findByText("El despliegue de «gpt-5.6-luna» existe en el recurso.")).toBeInTheDocument();
  });

  it("si sigue sin existir, muestra el mensaje del backend", async () => {
    setup("super_admin", [SIN_DESPLIEGUE], SIN_DESPLIEGUE);
    render(<CatalogPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Verificar despliegue de gpt-5.6-luna" }));
    expect((await screen.findAllByText("El despliegue gpt-5.6-luna no existe en el recurso configurado")).length).toBeGreaterThan(0);
  });

  it("lectura no ve el botón y las entradas que no son de Azure tampoco", async () => {
    setup("lectura", [SIN_DESPLIEGUE]);
    const { unmount } = render(<CatalogPage />);
    expect((await screen.findAllByText("gpt-5.6-luna")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /^Verificar despliegue/ })).toBeNull();
    unmount();
    vi.unstubAllGlobals();
    localStorage.clear();
    setup("super_admin", [{ ...OK, provider: "anthropic", deployment_check: undefined }]);
    render(<CatalogPage />);
    expect((await screen.findAllByText("gpt-5.1-chat")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /^Verificar despliegue/ })).toBeNull();
  });
});
