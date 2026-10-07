import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { collectPluginPages } from "../../../../frontend/src/plugins/registry";
import { ModelsScreen } from "../ModelsScreen";

// Estas tres pestañas las construyen otras piezas: acá solo importa que el shell las monte.
vi.mock("../AccessTab", () => ({ AccessTab: () => <div>contenido-acceso</div> }));
vi.mock("../UsageTab", () => ({ UsageTab: () => <div>contenido-consumo</div> }));
vi.mock("../../routing/RoutingTab", () => ({
  RoutingTab: ({ onOpenModels }: { onOpenModels?: () => void }) => (
    <div>contenido-routing<button onClick={onOpenModels}>abrir-modelos</button></div>
  ),
}));

const SECRET = "sk-or-SUPER-SECRETO-123";
const SHEET = {
  provider_legal_entity: null, entity_jurisdiction: null, inference_jurisdiction: "unknown", logs_jurisdiction: "unknown",
  zero_data_retention: null, trains_on_data: null, transfer_mechanism: "unknown", dpa_registry_id: null,
  eu_region_contracted: null, notes: null, classification_version: "console:0", classified_by: null, classified_at: null,
};
const base = {
  level: "tenant", tenant_id: "t", api_base: null, role: "text", capability: "standard", features: {},
  context_window: null, max_output: null, blocked_by_default: false, enabled_at: null, status: "active",
  source: "console", has_credential: true, sheet: SHEET, is_aggregator: false,
};
const EU = {
  ...base, id: "e-1", public_id: "mistral-eu", name: "Mistral UE", provider: "mistral", real_model: "mistral-large", protocol_family: "openai_chat",
  region_ue: true, credential: { id: "c-1", name: "Clave Mistral", kind: "secret", fingerprint: "ab12" },
  semaforo: { estado: "eu_ok", motivos: [] },
};
const US = {
  ...base, id: "e-2", public_id: "claude", name: "Claude Sonnet", provider: "anthropic", real_model: "claude-sonnet", protocol_family: "anthropic_messages",
  region_ue: false, semaforo: { estado: "standard", motivos: ["inferencia_fuera_ue"] },
};
const EMB = {
  ...base, id: "e-3", public_id: "emb", name: "Embeddings UE", provider: "mistral", real_model: "mistral-embed", protocol_family: "openai_chat",
  role: "embeddings", region_ue: null, semaforo: { estado: "unclassified", motivos: [] },
};
const LEGACY = [{ model_name: "gpt-heredado", provider: "openai", real_model: "gpt-4o", role: "text" }];
const CREDS = [{ id: "c-1", name: "Clave Mistral", kind: "secret", level: "tenant", fingerprint: "ab12", status: "active", in_use_by: ["Mistral UE"] }];

function setup(role: string, opts: { legacy?: "ok" | "404" | "401"; operator?: boolean; status?: Record<string, unknown> } = {}) {
  const token = `h.${btoa(JSON.stringify({ role })).replace(/=+$/, "")}.s`;
  localStorage.setItem("sentinel_session_token", token);
  localStorage.setItem("sentinel_current_user", JSON.stringify({ id: "1", username: "u", role: "admin", email: "" }));
  const calls: { url: string; init?: RequestInit }[] = [];
  let adopted = false;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const method = init?.method ?? "GET";
    if (url.startsWith("/api/v1/catalog/entries") && method === "GET") {
      return new Response(JSON.stringify({ data: adopted ? [EU, US, EMB, { ...EMB, id: "e-9", name: "gpt-heredado" }] : [EU, US, EMB] }), { status: 200 });
    }
    if (url === "/api/v1/catalog/credentials") return new Response(JSON.stringify({ data: CREDS }), { status: 200 });
    if (url === "/api/v1/catalog/status" && opts.status) return new Response(JSON.stringify(opts.status), { status: 200 });
    if (url === "/api/v1/catalog/legacy-models/adopt-all" && method === "POST") {
      adopted = true;
      return new Response(JSON.stringify({ adopted: 1, skipped: 0, failed: 0 }), { status: 207 });
    }
    if (url === "/api/v1/redirect/capabilities") return new Response(JSON.stringify({ operator: opts.operator ?? false }), { status: 200 });
    if (url === "/api/v1/catalog/legacy-models" && method === "GET") {
      if (opts.legacy === "404") return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 });
      if (opts.legacy === "401") return new Response(JSON.stringify({ detail: "no" }), { status: 401 });
      return new Response(JSON.stringify({ data: adopted ? [] : LEGACY }), { status: 200 });
    }
    if (url === "/api/v1/catalog/legacy-models/gpt-heredado/adopt" && method === "POST") {
      adopted = true;
      return new Response(JSON.stringify({ ...EMB, id: "e-9" }), { status: 201 });
    }
    return new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 });
  }));
  return calls;
}

describe("pantalla única «Modelos»", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("el registry la toma en el lugar de la pantalla base, con los tres roles y sin las páginas viejas", () => {
    const pages = collectPluginPages(import.meta.glob("../../pages/*.tsx", { eager: true }));
    expect(pages.map(p => p.path)).toEqual(["/modelos"]);
    expect(pages[0]).toMatchObject({
      menu: { label: "Modelos", section: "governance" }, roles: ["admin", "compliance_officer", "lectura"], replaces: "models",
    });
  });

  it("tiene las cinco pestañas accesibles y cada una monta su contenido", async () => {
    setup("tenant_admin");
    render(<ModelsScreen />);
    expect(screen.getByRole("heading", { name: "Modelos" })).toBeInTheDocument();
    const tablist = screen.getByRole("tablist");
    expect(within(tablist).getAllByRole("tab").map(t => t.textContent))
      .toEqual(["Modelos", "Credenciales", "Acceso", "Consumo", "Routing"]);
    expect(screen.getByRole("tab", { name: "Modelos" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("Mistral UE")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Acceso" }));
    expect(screen.getByText("contenido-acceso")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Consumo" }));
    expect(screen.getByText("contenido-consumo")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Routing" }));
    expect(screen.getByText("contenido-routing")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Credenciales" }));
    expect(screen.getByText("ab12")).toBeInTheDocument();
  });

  it("Routing › Redirección › Destinos lleva de vuelta a la pestaña Modelos (069 E3)", async () => {
    setup("tenant_admin");
    render(<ModelsScreen />);
    expect(await screen.findByText("Mistral UE")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Routing" }));
    expect(screen.getByRole("tab", { name: "Routing" })).toHaveAttribute("aria-selected", "true");
    fireEvent.click(screen.getByRole("button", { name: "abrir-modelos" }));
    expect(screen.getByRole("tab", { name: "Modelos" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("Mistral UE")).toBeInTheDocument();
  });

  it("se navega con las flechas del teclado (un solo tab en el orden de tabulación)", async () => {
    setup("tenant_admin");
    render(<ModelsScreen />);
    await screen.findByText("Mistral UE");
    const first = screen.getByRole("tab", { name: "Modelos" });
    expect(first).toHaveAttribute("tabindex", "0");
    expect(screen.getByRole("tab", { name: "Acceso" })).toHaveAttribute("tabindex", "-1");
    fireEvent.keyDown(first, { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Credenciales" })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Credenciales" }), { key: "End" });
    expect(screen.getByRole("tab", { name: "Routing" })).toHaveAttribute("aria-selected", "true");
    fireEvent.keyDown(screen.getByRole("tab", { name: "Routing" }), { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Modelos" })).toHaveAttribute("aria-selected", "true");
  });

  it("una sola lista: catálogo con semáforo, región y tipo + fila heredada del motor", async () => {
    setup("tenant_admin");
    render(<ModelsScreen />);
    expect(await screen.findByText("Mistral UE")).toBeInTheDocument();
    expect(screen.getByText("Región UE")).toBeInTheDocument();
    expect(screen.getByText("Fuera de la UE")).toBeInTheDocument();
    expect(screen.getAllByText("Región sin determinar")).toHaveLength(2);   // el modelo sin dato y la fila heredada
    expect(screen.getByLabelText("Semáforo: Dentro de la región")).toBeInTheDocument();
    expect(screen.getByText("Embeddings")).toBeInTheDocument();
    const legacyRow = (await screen.findByText("gpt-heredado")).closest("tr") as HTMLElement;
    expect(within(legacyRow).getByText("Heredado del motor")).toBeInTheDocument();
    expect(within(legacyRow).getByText("OpenAI")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(SECRET);
  });

  it("«Pasar al catálogo» adopta la fila heredada y recarga la lista", async () => {
    const calls = setup("tenant_admin");
    render(<ModelsScreen />);
    fireEvent.click(await screen.findByRole("button", { name: "Pasar gpt-heredado al catálogo" }));
    await waitFor(() => expect(calls.some(c => c.url.endsWith("/legacy-models/gpt-heredado/adopt") && c.init?.method === "POST")).toBe(true));
    expect(await screen.findByText(/pasó al catálogo/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("Heredado del motor")).toBeNull());
    expect(screen.getAllByText("gpt-heredado").length).toBeGreaterThan(0);
  });

  it.each(["404", "401"] as const)("si la ruta de heredados responde %s, la lista sigue sin ellas", async status => {
    setup("tenant_admin", { legacy: status });
    render(<ModelsScreen />);
    expect(await screen.findByText("Mistral UE")).toBeInTheDocument();
    expect(screen.queryByText("Heredado del motor")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("«Solo región UE» deja únicamente los modelos con región UE confirmada", async () => {
    setup("tenant_admin");
    render(<ModelsScreen />);
    await screen.findByText("Claude Sonnet");
    fireEvent.click(screen.getByLabelText("Solo región UE"));
    expect(screen.getByText("Mistral UE")).toBeInTheDocument();
    expect(screen.queryByText("Claude Sonnet")).toBeNull();
    expect(screen.queryByText("Embeddings UE")).toBeNull();
    expect(screen.queryByText("gpt-heredado")).toBeNull();
  });

  it("el botón de alta abre el diálogo guiado (solo administración)", async () => {
    setup("tenant_admin");
    render(<ModelsScreen />);
    fireEvent.click(await screen.findByRole("button", { name: "Dar de alta modelos" }));
    expect(await screen.findByRole("dialog", { name: "Dar de alta modelos" })).toBeInTheDocument();
  });

  it("el rol lectura no ve ningún botón de escritura ni la pestaña de credenciales con datos", async () => {
    setup("lectura");
    render(<ModelsScreen />);
    expect(await screen.findByText("Mistral UE")).toBeInTheDocument();
    expect(await screen.findByText("gpt-heredado")).toBeInTheDocument();
    expect(screen.getByText(/modo consulta/)).toBeInTheDocument();
    for (const name of [/Dar de alta/, /^Editar/, /^Archivar/, /^Desactivar/, /^Ofrecer/, /^Pasar .* al catálogo/]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.getByRole("button", { name: "Ficha de Mistral UE" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Credenciales" }));
    expect(screen.getByText(/administra el rol de administración/)).toBeInTheDocument();
  });

  it("sin la extensión activa lo dice en castellano", async () => {
    localStorage.setItem("sentinel_session_token", "x");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })));
    render(<ModelsScreen />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });

  it("avisa de los modelos que viven solo en el motor y los pasa todos al catálogo con un botón", async () => {
    const calls = setup("admin", { status: { catalog_only: false, direct_enabled: false, legacy_total: 1, legacy_pending: 1 } });
    render(<ModelsScreen />);
    expect(await screen.findByText(/todavía viven solo en la configuración del motor/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pasar todos al catálogo" }));
    await screen.findByText(/pasaron al catálogo/);
    expect(calls.some(c => c.url.endsWith("/legacy-models/adopt-all") && c.init?.method === "POST")).toBe(true);
  });

  it("sin modelos pendientes no muestra el aviso; en modo solo catálogo lo aclara; lectura no ve el botón", async () => {
    setup("admin", { status: { catalog_only: true, direct_enabled: true, legacy_total: 0, legacy_pending: 0 } });
    const { unmount } = render(<ModelsScreen />);
    expect(await screen.findByText(/solo desde esta pantalla/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Pasar todos al catálogo" })).toBeNull();
    unmount();
    setup("lectura", { status: { catalog_only: false, direct_enabled: false, legacy_total: 2, legacy_pending: 2 } });
    render(<ModelsScreen />);
    await screen.findByText(/todavía viven solo en la configuración del motor/);
    expect(screen.queryByRole("button", { name: "Pasar todos al catálogo" })).toBeNull();
  });
});
