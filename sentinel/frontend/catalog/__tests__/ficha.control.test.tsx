// Entidad responsable y jurisdicción de control en la ficha (057 T087; FR-028a, D12): el formulario muestra
// «Entidad responsable», «Jurisdicción de la entidad» y «Jurisdicción de control», avisa cuando falta el control
// y lo manda en el PUT. Un destino sin control no cuenta como «en región».
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { CatalogPage } from "../CatalogPage";

const SHEET = {
  provider_legal_entity: null, entity_jurisdiction: null, control_jurisdiction: null, inference_jurisdiction: "unknown",
  logs_jurisdiction: "unknown", zero_data_retention: null, trains_on_data: null, transfer_mechanism: "unknown",
  dpa_registry_id: null, eu_region_contracted: null, notes: null, classification_version: "console:0",
  classified_by: null, classified_at: null,
};
const ENTRY = {
  id: "e-1", level: "tenant", tenant_id: "t", name: "Modelo A", public_id: "modelo-a", provider: "anthropic", real_model: "m",
  protocol_family: "anthropic_messages", api_base: null, is_aggregator: false, role: "text", capability: "standard", features: {},
  context_window: null, max_output: null, blocked_by_default: false, enabled_at: null, status: "active", source: "console",
  has_credential: true, sheet: SHEET, in_region: false, semaforo: { estado: "unclassified", motivos: [] },
};

function setup(role: string, entry: Record<string, unknown> = ENTRY) {
  const token = `h.${btoa(JSON.stringify({ role })).replace(/=+$/, "")}.s`;
  localStorage.setItem("sentinel_session_token", token);
  localStorage.setItem("sentinel_current_user", JSON.stringify({ id: "1", username: "u", role: "admin", email: "" }));
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const method = init?.method ?? "GET";
    if (url.startsWith("/api/v1/catalog/entries/e-1/sheet") && method === "PUT") {
      const sent = JSON.parse(String(init?.body));
      return new Response(JSON.stringify({ ...entry, sheet: { ...SHEET, ...sent, classification_version: "console:1" } }), { status: 200 });
    }
    if (url.startsWith("/api/v1/catalog/entries") && method === "GET") return new Response(JSON.stringify({ data: [entry] }), { status: 200 });
    if (url === "/api/v1/catalog/credentials") return new Response(JSON.stringify({ data: [] }), { status: 200 });
    if (url === "/api/v1/catalog/dpas") return new Response(JSON.stringify({ data: [] }), { status: 200 });
    if (url === "/api/v1/redirect/capabilities") return new Response(JSON.stringify({ operator: false }), { status: 200 });
    return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 });
  }));
  return calls;
}

const abrirFicha = async () => {
  fireEvent.click(await screen.findByRole("button", { name: "Ficha de Modelo A" }));
  return screen.findByRole("dialog");
};

describe("ficha: entidad responsable y jurisdicción de control", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("muestra «Entidad responsable», «Jurisdicción de la entidad» y «Jurisdicción de control»", async () => {
    setup("compliance_officer");
    render(<CatalogPage />);
    const dialog = await abrirFicha();
    expect(within(dialog).getByLabelText("Entidad responsable")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Jurisdicción de la entidad")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Jurisdicción de control")).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Entidad legal del proveedor")).toBeNull();      // el viejo nombre ya no
  });

  it("avisa cuando falta el control y deja de avisar al cargarlo", async () => {
    setup("compliance_officer");
    render(<CatalogPage />);
    const dialog = await abrirFicha();
    expect(within(dialog).getByText(/Falta la jurisdicción de control/)).toBeInTheDocument();
    fireEvent.change(within(dialog).getByLabelText("Jurisdicción de control"), { target: { value: "AR" } });
    expect(within(dialog).queryByText(/Falta la jurisdicción de control/)).toBeNull();
  });

  it("explica que sin el control el destino no cuenta como «en región»", async () => {
    setup("compliance_officer");
    render(<CatalogPage />);
    const dialog = await abrirFicha();
    expect(within(dialog).getByText(/no cuenta como «en región»/)).toBeInTheDocument();
  });

  it("guarda entidad responsable y control en el PUT", async () => {
    const calls = setup("compliance_officer");
    render(<CatalogPage />);
    const dialog = await abrirFicha();
    fireEvent.change(within(dialog).getByLabelText("Entidad responsable"), { target: { value: "Operadora Ejemplo S.A." } });
    fireEvent.change(within(dialog).getByLabelText("Jurisdicción de la entidad"), { target: { value: "AR" } });
    fireEvent.change(within(dialog).getByLabelText("Jurisdicción de control"), { target: { value: "AR" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar ficha" }));
    await waitFor(() => expect(calls.find(c => c.init?.method === "PUT")).toBeDefined());
    const body = JSON.parse(String(calls.find(c => c.init?.method === "PUT")?.init?.body));
    expect(body).toMatchObject({ provider_legal_entity: "Operadora Ejemplo S.A.", entity_jurisdiction: "AR", control_jurisdiction: "AR" });
  });

  it("sin control cargado la lista no marca al modelo como «en región»; con control sí", async () => {
    setup("tenant_admin");
    const { unmount } = render(<CatalogPage />);
    expect(await screen.findByText("Modelo A")).toBeInTheDocument();
    expect(screen.queryByText("En región")).toBeNull();
    unmount();
    vi.unstubAllGlobals();
    localStorage.clear();
    setup("tenant_admin", { ...ENTRY, in_region: true, sheet: { ...SHEET, inference_jurisdiction: "AR", entity_jurisdiction: "AR", control_jurisdiction: "AR" } });
    render(<CatalogPage />);
    expect(await screen.findByText("En región")).toBeInTheDocument();
  });
});
