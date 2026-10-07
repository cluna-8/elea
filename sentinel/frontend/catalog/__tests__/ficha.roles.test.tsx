// Ficha: los campos de residencia y retención son solo de cumplimiento (057 T099; FR-023, QA A7): el admin de
// empresa los ve en solo lectura y edita el resto; cumplimiento y super-admin los editan.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { CatalogPage } from "../CatalogPage";

const SHEET = {
  provider_legal_entity: "Operadora Ejemplo S.A.", entity_jurisdiction: "AR", control_jurisdiction: "AR", inference_jurisdiction: "AR",
  logs_jurisdiction: "AR", zero_data_retention: true, trains_on_data: false, transfer_mechanism: "n/a", dpa_registry_id: null,
  eu_region_contracted: null, notes: "nota", classification_version: "console:1", classified_by: null, classified_at: null,
};
const ENTRY = {
  id: "e-1", level: "tenant", tenant_id: "t", name: "Modelo A", public_id: "modelo-a", provider: "anthropic", real_model: "m",
  protocol_family: "anthropic_messages", api_base: null, is_aggregator: false, role: "text", capability: "standard", features: {},
  context_window: null, max_output: null, blocked_by_default: false, enabled_at: null, status: "active", source: "console",
  has_credential: true, sheet: SHEET, in_region: true, semaforo: { estado: "standard", motivos: [] },
};

function setup(role: string) {
  const token = `h.${btoa(JSON.stringify({ role })).replace(/=+$/, "")}.s`;
  localStorage.setItem("sentinel_session_token", token);
  localStorage.setItem("sentinel_current_user", JSON.stringify({ id: "1", username: "u", role: "admin", email: "" }));
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    if (url.startsWith("/api/v1/catalog/entries") && method === "GET") return new Response(JSON.stringify({ data: [ENTRY] }), { status: 200 });
    if (url === "/api/v1/catalog/credentials") return new Response(JSON.stringify({ data: [] }), { status: 200 });
    if (url === "/api/v1/catalog/dpas") return new Response(JSON.stringify({ data: [] }), { status: 200 });
    if (url === "/api/v1/redirect/capabilities") return new Response(JSON.stringify({ operator: false }), { status: 200 });
    return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 });
  }));
}

const abrir = async () => {
  fireEvent.click(await screen.findByRole("button", { name: "Ficha de Modelo A" }));
  return screen.findByRole("dialog");
};
const RESTRINGIDOS = ["Entidad responsable", "Jurisdicción de la entidad", "Jurisdicción de control", "Jurisdicción de inferencia", "Retención cero"];
const LIBRES = ["Jurisdicción de registros", "Entrena con datos", "Mecanismo de transferencia", "Notas"];

describe("ficha: roles sobre residencia y retención", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("el admin de empresa ve esos campos en solo lectura y edita el resto", async () => {
    setup("tenant_admin");
    render(<CatalogPage />);
    const dialog = await abrir();
    for (const l of RESTRINGIDOS) expect(within(dialog).getByLabelText(l), l).toBeDisabled();
    for (const l of LIBRES) expect(within(dialog).getByLabelText(l), l).toBeEnabled();
    expect(within(dialog).getByRole("button", { name: "Guardar ficha" })).toBeEnabled();      // puede guardar lo suyo
    expect(within(dialog).getByText(/solo cumplimiento/i)).toBeInTheDocument();                // y entiende por qué
  });

  it.each(["compliance_officer", "super_admin"])("%s edita todos los campos", async role => {
    setup(role);
    render(<CatalogPage />);
    const dialog = await abrir();
    for (const l of [...RESTRINGIDOS, ...LIBRES]) expect(within(dialog).getByLabelText(l), l).toBeEnabled();
    expect(within(dialog).queryByText(/solo cumplimiento/i)).toBeNull();
  });

  it("lectura ve todo en solo lectura", async () => {
    setup("lectura");
    render(<CatalogPage />);
    const dialog = await abrir();
    for (const l of [...RESTRINGIDOS, ...LIBRES]) expect(within(dialog).getByLabelText(l), l).toBeDisabled();
  });
});
