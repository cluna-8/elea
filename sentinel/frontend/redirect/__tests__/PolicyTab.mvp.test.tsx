// MVP de la política (057 T029; FR-005, FR-010; research R15): dos estados, *apagada* y *encendida*
// (el estado *sombra* queda reservado para la fase F6 y NO se ofrece), y la pantalla «Modelos» que la
// administra queda en el menú junto a Gobernanza.
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
// El código de la consola como texto: de ahí salen los ítems base del menú, en su orden real.
import appSource from "../../../../frontend/src/App.tsx?raw";
import { collectPluginPages, mergeNav } from "../../../../frontend/src/plugins/registry";
import { PolicyTab } from "../PolicyTab";
import { permissionsFor } from "../helpers";

const LOOKUPS = { groups: [{ id: "g-1", name: "Ventas" }], users: [], keys: [] };
const noop = async () => {};

function renderTab(policy: unknown[] = []) {
  return render(
    <PolicyTab perms={permissionsFor("tenant_admin")} lookups={LOOKUPS} reload={noop}
      policy={policy as React.ComponentProps<typeof PolicyTab>["policy"]} />,
  );
}

describe("Política: solo apagada y encendida", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("el selector de estado ofrece exactamente «Apagada» y «Encendida»", () => {
    renderTab();
    const select = screen.getByRole("combobox", { name: "Estado" }) as HTMLSelectElement;
    expect(within(select).getAllByRole("option").map(o => o.textContent)).toEqual(["Apagada", "Encendida"]);
  });

  it("no hay formas de elegir sombra y el estado inicial no es sombra", () => {
    renderTab();
    const select = screen.getByRole("combobox", { name: "Estado" }) as HTMLSelectElement;
    expect([...select.options].map(o => o.value)).toEqual(["off", "on"]);
    expect(select.value).not.toBe("shadow");
    expect(screen.queryByText(/sombra/i)).toBeNull();            // ni en las opciones ni en el texto de ayuda
  });

  it("guardar sin tocar el selector manda un estado válido del MVP, nunca sombra", async () => {
    const calls: { url: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
      return new Response(JSON.stringify({}), { status: 200 });
    }));
    renderTab();
    fireEvent.change(screen.getByLabelText("Motivo"), { target: { value: "alta de prueba" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar estado" }));
    await vi.waitFor(() => expect(calls.length).toBe(1));
    expect(["off", "on"]).toContain((calls[0].body as { state: string }).state);
  });

  it("una fila heredada en sombra se sigue mostrando como lo que es (no se oculta un dato real)", () => {
    renderTab([{ id: "p", scope_type: "tenant", scope_value: "*", state: "shadow", reason: "piloto", changed_at: null }]);
    expect(screen.getByText("Sombra (solo registra)")).toBeInTheDocument();
  });
});

describe("Menú: «Modelos» junto a Gobernanza", () => {
  // Los ítems base del menú, en el orden real de la consola (frontend/src/App.tsx).
  const navBlock = appSource.slice(appSource.indexOf("const navigation"), appSource.indexOf("// Pantalla de retorno del IdP"));
  const base = [...navBlock.matchAll(/\{ id: "([a-z-]+)", name:/g)].map(m => ({ id: m[1] }));

  it("la página declara que va después de Gobernanza y sustituye al ítem base «models»", () => {
    const pages = collectPluginPages(import.meta.glob("../../pages/*.tsx", { eager: true }));
    expect(pages.find(p => p.path === "/modelos")).toMatchObject({
      menu: { label: "Modelos", section: "governance" }, replaces: "models",
    });
    expect(base.map(b => b.id)).toEqual(expect.arrayContaining(["models", "governance"]));
  });

  it("en el menú resultante «Modelos» queda inmediatamente después de Gobernanza y el ítem base ya no está", () => {
    const [page] = collectPluginPages(import.meta.glob("../../pages/*.tsx", { eager: true }));
    const merged = mergeNav(base, [{ item: { id: `plugin:${page.path}` }, section: page.menu!.section, replaces: page.replaces }]);
    const ids = merged.map(n => n.id);
    expect(ids).not.toContain("models");
    expect(ids.indexOf("plugin:/modelos")).toBe(ids.indexOf("governance") + 1);
    expect(ids).toHaveLength(base.length);                        // sustituye, no suma
  });
});
