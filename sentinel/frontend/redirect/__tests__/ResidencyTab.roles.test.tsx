// Pestaña «Residencia» (057 T063; FR-023, FR-030, FR-031, FR-031a; QA A6, A8, re-análisis G1): la postura por
// defecto de la región y las relajaciones por destino se editan solo con rol real de cumplimiento o super-admin;
// el admin de empresa las ve en solo lectura y solo puede agregar filas de postura (que endurecen).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RedirectPage } from "../RedirectPage";
import { ResidencyTab } from "../ResidencyTab";
import { permissionsFor } from "../helpers";

const REGION = {
  source: "installation", health: "ok", default_posture: "masked_all",
  jurisdictions: ["US", "CA", "AR", "BR", "LATAM"],
  region: { id: "r-1", name: "AMERICAS", level: "installation", jurisdictions: ["US", "CA", "AR", "BR", "LATAM"],
    region_profiles: ["latam_ar"], default_posture: "masked_all", is_zone: true },
};
const RELAX = [
  { id: "x-1", entry_id: "d-1", entry_name: "Modelo alojado", level: "tenant", reason: "alojado en EE. UU. con retención cero",
    created_by_role: "compliance_officer", created_at: "2026-10-02T10:00:00Z", revoked_at: null, revoke_reason: null },
  { id: "x-2", entry_id: "d-2", entry_name: "Otro modelo", level: "installation", reason: "ficha incompleta",
    created_by_role: "super_admin", created_at: "2026-10-01T10:00:00Z", revoked_at: "2026-10-03T10:00:00Z",
    revoke_reason: "precondicion_incumplida" },
];
const DEST = [{ id: "d-1", name: "Modelo alojado", level: "tenant" }, { id: "d-3", name: "Modelo nuevo", level: "tenant" }];

function mockFetch(handler: (url: string, init?: RequestInit) => Response | undefined = () => undefined) {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    return handler(url, init) ?? new Response(JSON.stringify({}), { status: 200 });
  }));
  return calls;
}

function renderTab(role: string, opts: { managesRegions?: boolean; operator?: boolean; region?: unknown } = {}) {
  const perms = permissionsFor(role, opts.operator ?? false, opts.managesRegions);
  const reload = vi.fn(async () => undefined);
  render(
    <ResidencyTab perms={perms} postures={[]} effective={{ mode: "offregion_masked", jurisdictions: [], explicit: false }}
      lookups={{ groups: [], users: [], keys: [] }} reload={reload}
      region={(opts.region === undefined ? REGION : opts.region) as never} relaxations={RELAX as never}
      destinations={DEST as never} />,
  );
  return reload;
}

describe("ResidencyTab: región y postura por defecto", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("muestra la región, su etiqueta «Dentro de» y la postura por defecto, sin «Admisible» ni «Cumple»", () => {
    renderTab("tenant_admin");
    expect(screen.getByText("AMERICAS")).toBeInTheDocument();
    expect(screen.getByText("Dentro de AMERICAS")).toBeInTheDocument();
    expect(screen.getByText("Enmascarado en todo destino")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/Admisible|Cumple\b/);
  });

  it("texto neutro por cada valor de la postura por defecto", () => {
    const labels: Record<string, string> = {
      masked_offregion: "Enmascarado fuera de la región", reject_offregion: "Rechazar fuera de la región",
      allow: "Sin restricción",
    };
    for (const [value, text] of Object.entries(labels)) {
      const { unmount } = render(
        <ResidencyTab perms={permissionsFor("tenant_admin")} postures={[]} effective={null}
          lookups={{ groups: [], users: [], keys: [] }} reload={async () => undefined}
          region={{ ...REGION, default_posture: value, region: { ...REGION.region, default_posture: value } } as never}
          relaxations={[]} destinations={[]} />,
      );
      expect(screen.getAllByText(text).length).toBeGreaterThan(0);
      unmount();
    }
  });

  it("respaldo en código: avisa que falta la región configurada", () => {
    renderTab("tenant_admin", { region: { source: "fallback", health: "region_row_missing", default_posture: "code_fallback",
      jurisdictions: ["EU"], region: null } });
    expect(screen.getByText("Respaldo de seguridad: falta la región configurada")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(/Todo lo redirigido sale enmascarado/);
  });

  it("región sin resolver: el aviso lo dice", () => {
    renderTab("tenant_admin", { region: { source: "unresolved", health: "region_unresolved", default_posture: "code_fallback",
      jurisdictions: [], region: null } });
    expect(screen.getByRole("alert")).toHaveTextContent(/región de la instalación sin definir/i);
  });

  it("el admin de empresa lo ve en solo lectura: sin botón de postura por defecto ni de relajaciones", () => {
    renderTab("tenant_admin");
    for (const name of ["Cambiar postura por defecto", "Nueva relajación", "Revocar"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.getByText("alojado en EE. UU. con retención cero")).toBeInTheDocument();
    expect(screen.getByText("Modelo alojado")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Agregar postura" })).toBeInTheDocument();
  });

  it("el tenant operador (REDIRECT_OPERATOR_TENANT) tampoco edita: manages_regions viene del rol real", () => {
    renderTab("tenant_admin", { operator: true, managesRegions: false });
    expect(screen.queryByRole("button", { name: "Cambiar postura por defecto" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Nueva relajación" })).toBeNull();
  });

  it("cumplimiento y super-admin editan la postura por defecto y las relajaciones", () => {
    for (const role of ["compliance_officer", "super_admin"]) {
      const { unmount } = render(
        <ResidencyTab perms={permissionsFor(role, false, true)} postures={[]} effective={null}
          lookups={{ groups: [], users: [], keys: [] }} reload={async () => undefined}
          region={REGION as never} relaxations={RELAX as never} destinations={DEST as never} />,
      );
      expect(screen.getByRole("button", { name: "Cambiar postura por defecto" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Nueva relajación" })).toBeInTheDocument();
      unmount();
    }
  });

  it("sin el dato de capacidades, el rol de la sesión decide (compatibilidad con servidores viejos)", () => {
    expect(permissionsFor("compliance_officer").canManageRegion).toBe(true);
    expect(permissionsFor("super_admin").canManageRegion).toBe(true);
    expect(permissionsFor("tenant_admin").canManageRegion).toBe(false);
    expect(permissionsFor("tenant_admin", true).canManageRegion).toBe(false);
    expect(permissionsFor("compliance_officer", false, false).canManageRegion).toBe(false);
  });

  it("pre-completa «solo jurisdicciones permitidas» con las de la región efectiva", () => {
    renderTab("tenant_admin");
    fireEvent.click(screen.getByRole("button", { name: "Agregar postura" }));
    const group = screen.getByText("Jurisdicciones permitidas").closest("fieldset")!;
    for (const code of ["US", "CA", "AR", "BR", "LATAM"]) {
      expect(within(group).getByRole("checkbox", { name: new RegExp(`^${code}\\b`) })).toBeChecked();
    }
    expect(within(group).getByRole("checkbox", { name: /^EU\b/ })).not.toBeChecked();
  });
});

describe("ResidencyTab: escrituras", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  const manager = (role = "compliance_officer") => {
    const reload = vi.fn(async () => undefined);
    render(
      <ResidencyTab perms={permissionsFor(role, false, true)} postures={[]} effective={null}
        lookups={{ groups: [], users: [], keys: [] }} reload={reload}
        region={REGION as never} relaxations={RELAX as never} destinations={DEST as never} />,
    );
    return reload;
  };

  it("pasar de masked_all a masked_offregion es la relajación por región: advierte y exige motivo (super-admin: PATCH de la fila de instalación)", async () => {
    const calls = mockFetch();
    const reload = manager("super_admin");
    fireEvent.click(screen.getByRole("button", { name: "Cambiar postura por defecto" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Nueva postura por defecto"), { target: { value: "masked_offregion" } });
    expect(within(dialog).getByText(/Relajación por región/)).toBeInTheDocument();
    const confirm = within(dialog).getByRole("button", { name: "Guardar" });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Motivo"), { target: { value: "decisión de cumplimiento" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(reload).toHaveBeenCalled());
    const patch = calls.find(c => c.init?.method === "PATCH")!;
    expect(patch.url).toBe("/api/v1/redirect/regions/r-1");
    expect(JSON.parse(String(patch.init!.body))).toEqual({ default_posture: "masked_offregion", reason: "decisión de cumplimiento" });
  });

  it("cumplimiento de una empresa: la relajación por región es una fila de nivel empresa (POST), no un PATCH de la de instalación", async () => {
    const calls = mockFetch();
    const reload = manager("compliance_officer");
    fireEvent.click(screen.getByRole("button", { name: "Cambiar postura por defecto" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Nueva postura por defecto"), { target: { value: "masked_offregion" } });
    fireEvent.change(within(dialog).getByLabelText("Motivo"), { target: { value: "decisión de cumplimiento" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(reload).toHaveBeenCalled());
    expect(calls.some(c => c.init?.method === "PATCH")).toBe(false);
    const post = calls.find(c => c.init?.method === "POST")!;
    expect(post.url).toBe("/api/v1/redirect/regions");
    expect(JSON.parse(String(post.init!.body))).toEqual({
      name: "AMERICAS", level: "tenant", jurisdictions: ["US", "CA", "AR", "BR", "LATAM"], region_profiles: ["latam_ar"],
      default_posture: "masked_offregion", is_zone: true, reason: "decisión de cumplimiento" });
  });

  it("endurecer (a masked_all) no muestra la advertencia de relajación", () => {
    mockFetch();
    const reload = vi.fn(async () => undefined);
    render(
      <ResidencyTab perms={permissionsFor("super_admin", false, true)} postures={[]} effective={null}
        lookups={{ groups: [], users: [], keys: [] }} reload={reload}
        region={{ ...REGION, default_posture: "masked_offregion", region: { ...REGION.region, default_posture: "masked_offregion" } } as never}
        relaxations={[]} destinations={[]} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Cambiar postura por defecto" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Nueva postura por defecto"), { target: { value: "masked_all" } });
    expect(within(dialog).queryByText(/Relajación por región/)).toBeNull();
  });

  it("alta de una relajación por destino: motivo obligatorio y nivel empresa para cumplimiento", async () => {
    const calls = mockFetch();
    const reload = manager("compliance_officer");
    fireEvent.click(screen.getByRole("button", { name: "Nueva relajación" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).queryByRole("option", { name: /instalación/i })).toBeNull();
    fireEvent.change(within(dialog).getByLabelText("Destino"), { target: { value: "d-3" } });
    const confirm = within(dialog).getByRole("button", { name: "Crear relajación" });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText("Motivo"), { target: { value: "pesos abiertos alojados con retención cero" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(reload).toHaveBeenCalled());
    const post = calls.find(c => c.init?.method === "POST")!;
    expect(post.url).toBe("/api/v1/redirect/masking-relaxations");
    expect(JSON.parse(String(post.init!.body))).toEqual({
      entry_id: "d-3", level: "tenant", reason: "pesos abiertos alojados con retención cero" });
  });

  it("el super-admin puede elegir el nivel de instalación", () => {
    manager("super_admin");
    fireEvent.click(screen.getByRole("button", { name: "Nueva relajación" }));
    expect(within(screen.getByRole("dialog")).getByRole("option", { name: /instalación/i })).toBeInTheDocument();
  });

  it("422 de la API al crear: se muestra el motivo tal cual", async () => {
    mockFetch(() => new Response(JSON.stringify({ detail: "la ficha no tiene retención cero" }), { status: 422 }));
    manager();
    fireEvent.click(screen.getByRole("button", { name: "Nueva relajación" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Destino"), { target: { value: "d-3" } });
    fireEvent.change(within(dialog).getByLabelText("Motivo"), { target: { value: "motivo válido" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Crear relajación" }));
    expect(await within(dialog).findByText(/ficha no tiene retención cero/i)).toBeInTheDocument();
  });

  it("baja de una relajación vigente (con motivo); las revocadas no se pueden revocar de nuevo", async () => {
    const calls = mockFetch();
    const reload = manager();
    const revoke = screen.getAllByRole("button", { name: "Revocar" });
    expect(revoke).toHaveLength(1);                       // x-2 ya está revocada
    expect(screen.getByText(/Revocada/)).toBeInTheDocument();
    fireEvent.click(revoke[0]);
    const dialog = screen.getByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Motivo"), { target: { value: "ya no se usa" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Revocar" }));
    await waitFor(() => expect(reload).toHaveBeenCalled());
    const del = calls.find(c => c.init?.method === "DELETE")!;
    expect(del.url).toBe("/api/v1/redirect/masking-relaxations/x-1");
    expect(JSON.parse(String(del.init!.body))).toEqual({ reason: "ya no se usa" });
  });

  it("422 posture_less_strict del admin de empresa: mensaje claro, no el código", async () => {
    mockFetch(() => new Response(JSON.stringify({ detail: { code: "posture_less_strict" } }), { status: 422 }));
    renderTab("tenant_admin");
    fireEvent.click(screen.getByRole("button", { name: "Agregar postura" }));
    fireEvent.change(screen.getByLabelText("Motivo"), { target: { value: "prueba" } });
    fireEvent.click(screen.getByRole("button", { name: "Agregar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Esa postura es menos estricta que la vigente; el administrador de empresa solo puede endurecer.");
    expect(document.body.textContent).not.toContain("posture_less_strict");
  });
});

describe("RedirectPage: carga de región, relajaciones y capacidades", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  function setup(role: string, caps: Record<string, boolean>) {
    const token = `h.${btoa(JSON.stringify({ role })).replace(/=+$/, "")}.s`;
    localStorage.setItem("sentinel_session_token", token);
    localStorage.setItem("sentinel_current_user", JSON.stringify({ id: "1", username: "u", role: "admin", email: "" }));
    const routes: Record<string, unknown> = {
      "/api/v1/redirect/destinations": { data: [{ ...DEST[0], status: "active", provider: "openai_compatible", real_model: "m" }], warnings: [] },
      "/api/v1/redirect/published-models": { data: [] }, "/api/v1/redirect/rules": { data: [] },
      "/api/v1/redirect/policy": { data: [] },
      "/api/v1/redirect/postures": { data: [], effective_tenant_redirected: { mode: "offregion_masked", jurisdictions: [], explicit: false } },
      "/api/v1/users/groups": [], "/api/v1/users": [], "/api/v1/keys": [],
      "/api/v1/redirect/capabilities": { operator: false, ...caps },
      "/api/v1/redirect/regions/effective": REGION,
      "/api/v1/redirect/masking-relaxations": { data: RELAX },
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string) =>
      routes[url] === undefined ? new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 })
        : new Response(JSON.stringify(routes[url]), { status: 200 })));
  }

  it("cumplimiento (manages_regions) ve los controles", async () => {
    setup("compliance_officer", { manages_regions: true });
    render(<RedirectPage />);
    await screen.findByText("Modelo alojado");
    fireEvent.click(screen.getByRole("tab", { name: "Residencia" }));
    expect(await screen.findByRole("button", { name: "Cambiar postura por defecto" })).toBeInTheDocument();
  });

  it("admin de empresa: solo lectura", async () => {
    setup("tenant_admin", { manages_regions: false });
    render(<RedirectPage />);
    await screen.findByText("Modelo alojado");
    fireEvent.click(screen.getByRole("tab", { name: "Residencia" }));
    expect(await screen.findByText("Enmascarado en todo destino")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cambiar postura por defecto" })).toBeNull();
  });

  it("un servidor sin las rutas nuevas (404) no tumba la pantalla", async () => {
    setup("tenant_admin", {});
    const f = globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
    const prev = f.getMockImplementation()!;
    f.mockImplementation(async (url: string) =>
      url.includes("regions") || url.includes("masking-relaxations")
        ? new Response(JSON.stringify({ detail: "Not Found" }), { status: 404 }) : prev(url));
    render(<RedirectPage />);
    await screen.findByText("Modelo alojado");
    fireEvent.click(screen.getByRole("tab", { name: "Residencia" }));
    expect(screen.getByText("Postura efectiva para pedidos redirigidos (toda la organización)")).toBeInTheDocument();
    expect(screen.queryByText("Región y postura por defecto")).toBeNull();
  });
});
