import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { AccessTab } from "../AccessTab";

const P = (o: Record<string, unknown>) => ({ archived: false, seeded: false, allows: 3, version: 1, rules: [], ...o });
const PROFILES = [
  P({ id: "p-all", kind: "company", name: "Todos salvo bloqueados", seeded: true, allows: 12, rules: [{ effect: "include", selector: "semaforo", value: "standard" }, { effect: "include", selector: "semaforo", value: "eu_ok" }] }),
  P({ id: "p-ue", kind: "company", name: "Solo admisibles UE", seeded: true, allows: 1, rules: [{ effect: "include", selector: "semaforo", value: "eu_ok" }, { effect: "exclude", selector: "capacidad", value: "frontier" }] }),
  P({ id: "c-strict", kind: "ceiling", name: "Techo estricto", allows: 1, rules: [{ effect: "include", selector: "semaforo", value: "eu_ok" }] }),
  P({ id: "c-open", kind: "ceiling", name: "Techo abierto", allows: 12, rules: [{ effect: "include", selector: "semaforo", value: "standard" }] }),
  P({ id: "k-small", kind: "key", name: "Llave chica", allows: 1, rules: [{ effect: "include", selector: "capacidad", value: "small" }] }),
  P({ id: "p-old", kind: "company", name: "Perfil viejo", archived: true }),
];
const ENTRIES = [
  { id: "e-1", public_id: "mistral-ue", name: "Mistral UE", status: "active", semaforo: { estado: "eu_ok", motivos: [] } },
  { id: "e-2", public_id: "gpt-x", name: "GPT X", status: "active", semaforo: { estado: "standard", motivos: [] } },
];
const GROUPS = [{ id: "g-1", name: "Ventas" }];
const USERS = [{ id: "u-1", username: "ana" }];
const KEYS = [{ id: "k-1", name: "Conexión Claude Desktop" }];
const EFFECTIVE = {
  permitidos: [{ id: "e-1", public_id: "mistral-ue", name: "Mistral UE", provider: "mistral", semaforo: { estado: "eu_ok" } }],
  restringe: true,
  techo: { risk_level: "high_risk_annex3", origen: "tenant", count: 1 },
  perfiles: [{ id: "p-ue", name: "Solo admisibles UE", origen: "group" }, { id: "p-all", name: "Todos salvo bloqueados", origen: "tenant" }],
  llave: { profile_id: null }, version: 7,
};

interface Opts { profiles?: "ok" | "404" | "500"; emptyOnce?: boolean; warnings?: string[] }
type Call = { url: string; method: string; body: any };

function setup(role: string, opts: Opts = {}) {
  const token = `h.${btoa(JSON.stringify({ role })).replace(/=+$/, "")}.s`;
  localStorage.setItem("sentinel_session_token", token);
  localStorage.setItem("sentinel_current_user", JSON.stringify({ id: "1", username: "u", role: "admin", email: "" }));
  const calls: Call[] = [];
  let emptyPending = opts.emptyOnce ?? false;
  const ceilings: Record<string, string | null> = { minimal: "c-open", limited: "c-open", high_risk_annex1: null, high_risk_annex3: "c-strict" };
  const ok = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    if (url.startsWith("/api/v1/access/profiles") && method === "GET") {
      if (opts.profiles === "404") return ok({ detail: "Not Found" }, 404);
      if (opts.profiles === "500") return ok({ detail: "boom" }, 500);
      return ok({ data: PROFILES });
    }
    if (url === "/api/v1/access/profiles" && method === "POST") return ok({ ...P({ id: "new" }), ...body }, 201);
    if (url.startsWith("/api/v1/access/profiles/") && method === "PATCH") return ok({ ...PROFILES[0], ...body });
    if (url.endsWith("/archive")) return ok({ ...PROFILES[0], archived: true });
    if (url === "/api/v1/access/ceilings" && method === "GET") return ok({ data: ceilings });
    if (url === "/api/v1/access/ceilings" && method === "PUT") return ok({ data: { ...ceilings, ...body } });
    if (url.startsWith("/api/v1/access/assignments/") && method === "GET") {
      return ok({ subject_type: url.split("/")[5], subject_id: url.split("/")[6], profiles: ["p-ue"] });
    }
    if (url.startsWith("/api/v1/access/assignments/") && method === "PUT") {
      if (emptyPending && !body.confirm_empty && body.profiles.length === 0) {
        return ok({ detail: "el sujeto quedaría sin modelos", empty: true }, 422);
      }
      return ok({ subject_type: url.split("/")[5], subject_id: url.split("/")[6], profiles: body.profiles });
    }
    if (url === "/api/v1/access/keys/k-1/profile" && method === "GET") return ok({ key_id: "k-1", profile_id: null });
    if (url === "/api/v1/access/keys/k-1/profile" && method === "PUT") {
      return ok({ key_id: "k-1", profile_id: body.profile_id, ...(opts.warnings ? { warnings: opts.warnings } : {}) });
    }
    if (url.startsWith("/api/v1/access/effective")) return ok(EFFECTIVE);
    if (url === "/api/v1/access/preview") {
      return ok(body.model === "gpt-x"
        ? { allowed: false, motivo: "profile_not_allowed", permitidos_origen: "group" }
        : { allowed: true, motivo: null, permitidos_origen: "tenant" });
    }
    if (url.startsWith("/api/v1/catalog/entries")) return ok({ data: ENTRIES });
    if (url === "/api/v1/users/groups") return ok(GROUPS);
    if (url === "/api/v1/users") return ok(USERS);
    if (url === "/api/v1/keys") return ok(KEYS);
    return ok({ detail: "Not Found" }, 404);
  }));
  return { calls, emptyDone: () => { emptyPending = false; } };
}

const sub = (name: string) => fireEvent.click(screen.getByRole("tab", { name }));
const writes = (calls: Call[]) => calls.filter(c => c.method !== "GET");

describe("pestaña Acceso", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("si /access/profiles responde 404 muestra el estado honesto y ninguna sub-sección", async () => {
    setup("admin", { profiles: "404" });
    render(<AccessTab />);
    expect(await screen.findByText(/todavía no está disponible en esta instalación/)).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Perfiles" })).toBeNull();
    expect(screen.queryByRole("button", { name: /nuevo perfil/i })).toBeNull();
  });

  it("un error del servidor se muestra en castellano y permite reintentar", async () => {
    setup("admin", { profiles: "500" });
    render(<AccessTab />);
    expect(await screen.findByText(/Boom|El servidor tuvo un problema/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });

  it("ofrece las cinco sub-secciones como pestañas accesibles", async () => {
    setup("admin");
    render(<AccessTab />);
    await screen.findByText("Solo admisibles UE");
    const tabs = within(screen.getByRole("tablist", { name: "Secciones de Acceso" })).getAllByRole("tab");
    expect(tabs.map(t => t.textContent)).toEqual(["Perfiles", "Techos por riesgo AI Act", "Asignaciones", "Llaves", "Efectivos"]);
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
  });

  describe("Perfiles", () => {
    it("lista tipo, reglas legibles, cantidad de modelos y sembrados; los archivados no aparecen", async () => {
      setup("admin");
      render(<AccessTab />);
      const ue = (await screen.findByText("Solo admisibles UE")).closest("li")!;
      expect(within(ue).getByText("Incluye: semáforo = dentro de la región")).toBeInTheDocument();
      expect(within(ue).getByText("Excluye: capacidad = de frontera")).toBeInTheDocument();
      expect(within(ue).getByText("permite 1 modelo")).toBeInTheDocument();
      expect(within(ue).getByText("Sembrado")).toBeInTheDocument();
      expect(within(ue).getByText("Perfil de empresa")).toBeInTheDocument();
      expect(screen.getAllByText("permite 12 modelos")).toHaveLength(2);
      expect(screen.getAllByText("Techo de riesgo")).toHaveLength(2);
      expect(screen.queryByText("Perfil viejo")).toBeNull();
      fireEvent.click(screen.getByRole("checkbox", { name: "Ver archivados" }));
      expect(screen.getByText("Perfil viejo")).toBeInTheDocument();
    });

    it("el admin crea un perfil con reglas y se envía el contrato exacto", async () => {
      const { calls } = setup("admin");
      render(<AccessTab />);
      fireEvent.click(await screen.findByRole("button", { name: "Nuevo perfil" }));
      const dlg = screen.getByRole("dialog");
      fireEvent.change(within(dlg).getByLabelText("Nombre"), { target: { value: "Solo Mistral" } });
      fireEvent.click(within(dlg).getByRole("button", { name: "Agregar regla" }));
      fireEvent.change(within(dlg).getByLabelText("Selector de la regla 1"), { target: { value: "proveedor" } });
      fireEvent.change(within(dlg).getByLabelText("Valor de la regla 1"), { target: { value: "mistral" } });
      fireEvent.click(within(dlg).getByRole("button", { name: "Crear perfil" }));
      await waitFor(() => expect(writes(calls)).toHaveLength(1));
      expect(writes(calls)[0]).toMatchObject({
        url: "/api/v1/access/profiles", method: "POST",
        body: { kind: "company", name: "Solo Mistral", rules: [{ effect: "include", selector: "proveedor", value: "mistral" }] },
      });
    });

    it("el valor sugerido depende del selector: semáforo y capacidad con etiquetas, modelo desde el catálogo", async () => {
      setup("admin");
      render(<AccessTab />);
      fireEvent.click(await screen.findByRole("button", { name: "Nuevo perfil" }));
      const dlg = screen.getByRole("dialog");
      fireEvent.click(within(dlg).getByRole("button", { name: "Agregar regla" }));
      const val = () => within(dlg).getByLabelText("Valor de la regla 1");
      expect(within(val()).getByRole("option", { name: "dentro de la región" })).toHaveValue("eu_ok");
      fireEvent.change(within(dlg).getByLabelText("Selector de la regla 1"), { target: { value: "capacidad" } });
      expect(within(val()).getByRole("option", { name: "de frontera" })).toHaveValue("frontier");
      fireEvent.change(within(dlg).getByLabelText("Selector de la regla 1"), { target: { value: "entrada" } });
      expect(await within(val()).findByRole("option", { name: "Mistral UE" })).toHaveValue("e-1");
    });

    it("edita un perfil con PATCH y lo archiva pidiendo motivo de 3 o más caracteres", async () => {
      const { calls } = setup("admin");
      render(<AccessTab />);
      const row = (await screen.findByText("Solo admisibles UE")).closest("li")!;
      fireEvent.click(within(row).getByRole("button", { name: "Editar" }));
      fireEvent.change(within(screen.getByRole("dialog")).getByLabelText("Nombre"), { target: { value: "Solo UE" } });
      fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Guardar" }));
      await waitFor(() => expect(writes(calls).some(c => c.method === "PATCH" && c.url.endsWith("/profiles/p-ue"))).toBe(true));
      expect(writes(calls).find(c => c.method === "PATCH")!.body).toMatchObject({ name: "Solo UE" });

      fireEvent.click(await screen.findByRole("button", { name: "Archivar Solo admisibles UE" }));
      const dlg = screen.getByRole("dialog");
      const confirm = within(dlg).getByRole("button", { name: "Archivar" });
      expect(confirm).toBeDisabled();
      fireEvent.change(within(dlg).getByRole("textbox"), { target: { value: "ya no se usa" } });
      fireEvent.click(confirm);
      await waitFor(() => expect(writes(calls).some(c => c.url === "/api/v1/access/profiles/p-ue/archive")).toBe(true));
      expect(writes(calls).find(c => c.url.endsWith("/archive"))!.body).toEqual({ reason: "ya no se usa" });
    });

    it("un 409 al archivar (perfil asignado) se explica en el diálogo", async () => {
      setup("admin");
      const base = globalThis.fetch as unknown as (u: string, i?: RequestInit) => Promise<Response>;
      vi.stubGlobal("fetch", vi.fn(async (u: string, i?: RequestInit) =>
        u.endsWith("/archive") ? new Response(JSON.stringify({ detail: "el perfil está asignado" }), { status: 409 }) : base(u, i)));
      render(<AccessTab />);
      fireEvent.click(await screen.findByRole("button", { name: "Archivar Solo admisibles UE" }));
      fireEvent.change(within(screen.getByRole("dialog")).getByRole("textbox"), { target: { value: "limpieza" } });
      fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Archivar" }));
      expect(await screen.findByText("El perfil está asignado.")).toBeInTheDocument();
    });

    it("cumplimiento solo escribe techos: ve «Nuevo perfil» con tipo techo y sin editar los de empresa", async () => {
      setup("compliance_officer");
      render(<AccessTab />);
      const emp = (await screen.findByText("Solo admisibles UE")).closest("li")!;
      expect(within(emp).queryByRole("button", { name: "Editar" })).toBeNull();
      const techo = screen.getByText("Techo estricto").closest("li")!;
      expect(within(techo).getByRole("button", { name: "Editar" })).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Nuevo perfil" }));
      const kind = within(screen.getByRole("dialog")).getByLabelText("Tipo") as HTMLSelectElement;
      expect([...kind.options].map(o => o.value)).toEqual(["ceiling"]);
    });

    it("lectura no ve ningún botón de escritura", async () => {
      setup("lectura");
      render(<AccessTab />);
      await screen.findByText("Solo admisibles UE");
      expect(screen.queryByRole("button", { name: /nuevo perfil|editar|archivar/i })).toBeNull();
    });
  });

  describe("Techos por riesgo AI Act", () => {
    it("una fila por nivel con su perfil de techo; el resto de los perfiles no se ofrecen", async () => {
      setup("compliance_officer");
      render(<AccessTab />);
      await screen.findByText("Solo admisibles UE");
      sub("Techos por riesgo AI Act");
      for (const l of ["Mínimo", "Limitado", "Alto riesgo (Anexo I)", "Alto riesgo (Anexo III)"]) {
        expect(await screen.findByLabelText(l)).toBeInTheDocument();
      }
      const a3 = screen.getByLabelText("Alto riesgo (Anexo III)") as HTMLSelectElement;
      await waitFor(() => expect(a3.value).toBe("c-strict"));
      expect([...a3.options].map(o => o.textContent)).toEqual(["Sin techo asignado", "Techo estricto", "Techo abierto"]);
    });

    it("cumplimiento guarda solo lo que cambió (PUT parcial)", async () => {
      const { calls } = setup("compliance_officer");
      render(<AccessTab />);
      await screen.findByText("Solo admisibles UE");
      sub("Techos por riesgo AI Act");
      const a1 = await screen.findByLabelText("Alto riesgo (Anexo I)");
      fireEvent.change(a1, { target: { value: "c-strict" } });
      fireEvent.click(screen.getByRole("button", { name: "Guardar techos" }));
      await waitFor(() => expect(writes(calls)).toHaveLength(1));
      expect(writes(calls)[0]).toMatchObject({ url: "/api/v1/access/ceilings", method: "PUT", body: { high_risk_annex1: "c-strict" } });
      expect(await screen.findByText("Techos guardados.")).toBeInTheDocument();
    });

    it("el admin los ve pero no los edita", async () => {
      setup("admin");
      render(<AccessTab />);
      await screen.findByText("Solo admisibles UE");
      sub("Techos por riesgo AI Act");
      expect(await screen.findByLabelText("Mínimo")).toBeDisabled();
      expect(screen.queryByRole("button", { name: "Guardar techos" })).toBeNull();
      expect(screen.getByText(/Solo el rol de cumplimiento/)).toBeInTheDocument();
    });
  });

  describe("Asignaciones", () => {
    async function open(role = "admin", opts: Opts = {}) {
      const s = setup(role, opts);
      render(<AccessTab />);
      await screen.findByText("Solo admisibles UE");
      sub("Asignaciones");
      return s;
    }

    it("elige el sujeto por nombre, marca perfiles de empresa (solo esos) y guarda", async () => {
      const { calls } = await open();
      fireEvent.change(await screen.findByLabelText("Aplica a"), { target: { value: "group" } });
      fireEvent.change(screen.getByLabelText("Grupo"), { target: { value: "g-1" } });
      const ue = await screen.findByRole("checkbox", { name: "Solo admisibles UE" });
      await waitFor(() => expect(ue).toBeChecked());
      expect(screen.queryByRole("checkbox", { name: "Techo estricto" })).toBeNull();
      fireEvent.click(screen.getByRole("checkbox", { name: "Todos salvo bloqueados" }));
      fireEvent.click(screen.getByRole("button", { name: "Guardar asignación" }));
      await waitFor(() => expect(writes(calls)).toHaveLength(1));
      expect(writes(calls)[0]).toMatchObject({ url: "/api/v1/access/assignments/group/g-1", method: "PUT", body: { profiles: ["p-ue", "p-all"] } });
      expect(await screen.findByText("Asignación guardada.")).toBeInTheDocument();
    });

    it("la organización usa el sujeto «*»", async () => {
      const { calls } = await open();
      await screen.findByRole("checkbox", { name: "Solo admisibles UE" });
      expect(calls.some(c => c.url === "/api/v1/access/assignments/tenant/*")).toBe(true);
    });

    it("ante 422 «sin modelos» pide confirmación explícita y recién ahí reenvía confirm_empty", async () => {
      const { calls } = await open("admin", { emptyOnce: true });
      const ue = await screen.findByRole("checkbox", { name: "Solo admisibles UE" });
      await waitFor(() => expect(ue).toBeChecked());
      fireEvent.click(ue);
      fireEvent.click(screen.getByRole("button", { name: "Guardar asignación" }));
      const dlg = await screen.findByRole("dialog");
      expect(within(dlg).getByText("Este sujeto quedaría sin modelos")).toBeInTheDocument();
      expect(writes(calls)).toHaveLength(1);
      expect(writes(calls)[0].body).toEqual({ profiles: [] });
      fireEvent.click(within(dlg).getByRole("button", { name: "Dejar sin modelos" }));
      await waitFor(() => expect(writes(calls)).toHaveLength(2));
      expect(writes(calls)[1].body).toEqual({ profiles: [], confirm_empty: true });
    });

    it("cancelar la confirmación no escribe nada más", async () => {
      const { calls } = await open("admin", { emptyOnce: true });
      const ue = await screen.findByRole("checkbox", { name: "Solo admisibles UE" });
      await waitFor(() => expect(ue).toBeChecked());
      fireEvent.click(ue);
      fireEvent.click(screen.getByRole("button", { name: "Guardar asignación" }));
      fireEvent.click(await screen.findByRole("button", { name: "Cancelar" }));
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(writes(calls)).toHaveLength(1);
    });

    it("sin permiso de escritura (cumplimiento, lectura) los perfiles se ven pero no se editan", async () => {
      await open("lectura");
      const ue = await screen.findByRole("checkbox", { name: "Solo admisibles UE" });
      expect(ue).toBeDisabled();
      expect(screen.queryByRole("button", { name: "Guardar asignación" })).toBeNull();
    });
  });

  describe("Llaves", () => {
    async function open(role = "admin", opts: Opts = {}) {
      const s = setup(role, opts);
      render(<AccessTab />);
      await screen.findByText("Solo admisibles UE");
      sub("Llaves");
      return s;
    }

    it("elige la conexión por nombre, ofrece solo perfiles de llave y guarda", async () => {
      const { calls } = await open();
      fireEvent.change(await screen.findByLabelText("Conexión"), { target: { value: "k-1" } });
      const sel = (await screen.findByLabelText("Perfil de la llave")) as HTMLSelectElement;
      expect([...sel.options].map(o => o.textContent)).toEqual(["Sin perfil de llave", "Llave chica"]);
      fireEvent.change(sel, { target: { value: "k-small" } });
      fireEvent.click(screen.getByRole("button", { name: "Guardar perfil de la llave" }));
      await waitFor(() => expect(writes(calls)).toHaveLength(1));
      expect(writes(calls)[0]).toMatchObject({ url: "/api/v1/access/keys/k-1/profile", method: "PUT", body: { profile_id: "k-small" } });
      expect(await screen.findByText("Perfil de la llave guardado.")).toBeInTheDocument();
    });

    it("muestra las advertencias del backend (la llave solo achica)", async () => {
      await open("admin", { warnings: ["La llave pretendía ampliar: se recortó al perfil del usuario."] });
      fireEvent.change(await screen.findByLabelText("Conexión"), { target: { value: "k-1" } });
      fireEvent.change(await screen.findByLabelText("Perfil de la llave"), { target: { value: "k-small" } });
      fireEvent.click(screen.getByRole("button", { name: "Guardar perfil de la llave" }));
      const w = await screen.findByText("La llave pretendía ampliar: se recortó al perfil del usuario.");
      expect(w.closest("[role=status],[role=alert]")).not.toBeNull();
    });

    it("sin permiso de escritura no hay botón de guardar", async () => {
      await open("lectura");
      fireEvent.change(await screen.findByLabelText("Conexión"), { target: { value: "k-1" } });
      expect(await screen.findByLabelText("Perfil de la llave")).toBeDisabled();
      expect(screen.queryByRole("button", { name: "Guardar perfil de la llave" })).toBeNull();
    });
  });

  describe("Efectivos", () => {
    async function open(role = "compliance_officer") {
      const s = setup(role);
      render(<AccessTab />);
      await screen.findByText("Solo admisibles UE");
      sub("Efectivos");
      return s;
    }

    it("muestra modelos permitidos, techo con su origen y perfiles con su origen", async () => {
      const { calls } = await open();
      fireEvent.change(await screen.findByLabelText("Ver acceso de"), { target: { value: "user" } });
      fireEvent.change(screen.getByLabelText("Usuario"), { target: { value: "u-1" } });
      expect(await screen.findByText("Mistral UE", { selector: "td *, td" })).toBeInTheDocument();
      expect(calls.some(c => c.url === "/api/v1/access/effective?user=u-1")).toBe(true);
      const techo = screen.getByText(/Alto riesgo \(Anexo III\)/);
      expect(techo.textContent).toMatch(/Alto riesgo \(Anexo III\)/);
      expect(techo.textContent).toMatch(/Organización/);
      expect(techo.textContent).toMatch(/1 modelo/);
      const lista = screen.getByRole("list", { name: "Perfiles aplicados" });
      expect(within(lista).getByText("Solo admisibles UE").closest("li")!.textContent).toMatch(/Grupo/);
      expect(within(lista).getByText("Todos salvo bloqueados").closest("li")!.textContent).toMatch(/Organización/);
    });

    it("el probador pregunta por un modelo y explica el motivo", async () => {
      const { calls } = await open();
      fireEvent.change(await screen.findByLabelText("Ver acceso de"), { target: { value: "group" } });
      fireEvent.change(screen.getByLabelText("Grupo"), { target: { value: "g-1" } });
      await screen.findByLabelText("Modelo a probar");
      fireEvent.change(screen.getByLabelText("Modelo a probar"), { target: { value: "gpt-x" } });
      fireEvent.click(screen.getByRole("button", { name: "Probar" }));
      expect(await screen.findByText("No puede usar este modelo")).toBeInTheDocument();
      expect(screen.getByText("Ningún perfil asignado permite este modelo.")).toBeInTheDocument();
      const post = calls.find(c => c.url === "/api/v1/access/preview")!;
      expect(post.body).toEqual({ group: "g-1", model: "gpt-x" });
      fireEvent.change(screen.getByLabelText("Modelo a probar"), { target: { value: "mistral-ue" } });
      fireEvent.click(screen.getByRole("button", { name: "Probar" }));
      expect(await screen.findByText("Puede usar este modelo")).toBeInTheDocument();
    });

    it("también funciona por llave", async () => {
      const { calls } = await open();
      fireEvent.change(await screen.findByLabelText("Ver acceso de"), { target: { value: "key" } });
      fireEvent.change(screen.getByLabelText("Conexión"), { target: { value: "k-1" } });
      await screen.findByText("Mistral UE", { selector: "td *, td" });
      expect(calls.some(c => c.url === "/api/v1/access/effective?key=k-1")).toBe(true);
    });
  });
});
