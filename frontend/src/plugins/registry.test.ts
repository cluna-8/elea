import { describe, expect, it, vi } from "vitest";
import { canSeePluginPage, collectPluginPages, mergeNav, pluginPages } from "./registry";

describe("registry de páginas de plugins", () => {
  it("sin plugins el registry es vacío (build por defecto)", () => {
    expect(pluginPages).toEqual([]);
  });

  it("con un fixture devuelve su página, con roles fail-closed", () => {
    const pages = collectPluginPages(import.meta.glob("./__fixtures__/*.tsx", { eager: true }));
    expect(pages).toHaveLength(1);
    expect(pages[0].path).toBe("/demo");
    expect(pages[0].menu).toEqual({ label: "Demo", section: "audit" });
    expect(pages[0].roles).toEqual(["admin"]);
    expect(canSeePluginPage(pages[0], "admin")).toBe(true);
    expect(canSeePluginPage(pages[0], "developer")).toBe(false);
  });

  it("descarta exports inválidos y paths repetidos o reservados sin romper", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const C = () => null;
    const pages = collectPluginPages({
      "a.tsx": { default: [{ path: "/uno", Component: C }, { path: "/uno", Component: C }] },
      "b.tsx": { default: { path: "sin-barra", Component: C } },
      "c.tsx": { default: { path: "/dos" } },
      "d.tsx": {},
      "e.tsx": { default: { path: "/reservado", Component: C } },
    }, ["/reservado"]);
    expect(pages.map(p => p.path)).toEqual(["/uno"]);
    expect(warn).toHaveBeenCalledTimes(5);
    warn.mockRestore();
  });

  it("mergeNav inserta después de la sección, en orden, y al final si no existe", () => {
    const base = [{ id: "a" }, { id: "b" }, { id: "c" }];
    const merged = mergeNav(base, [
      { item: { id: "p1" }, section: "a" },
      { item: { id: "p2" }, section: "a" },
      { item: { id: "p3" }, section: "zzz" },
      { item: { id: "p4" } },
    ]);
    expect(merged.map(n => n.id)).toEqual(["a", "p1", "p2", "b", "c", "p3", "p4"]);
    expect(mergeNav(base, [])).toEqual(base);
  });

  // ── `replaces` (spec 069, FR-045/FR-058/FR-059): una página de plugin sustituye un ítem base ──
  it("un plugin con `replaces` ocupa el lugar del ítem base y lo oculta", () => {
    const base = [{ id: "a" }, { id: "models" }, { id: "c" }];
    const merged = mergeNav(base, [{ item: { id: "plugin:/modelos" }, replaces: "models" }]);
    expect(merged.map(n => n.id)).toEqual(["a", "plugin:/modelos", "c"]);
  });

  it("`replaces` de un id que no existe en la base no oculta nada y la entrada se suma como siempre", () => {
    const base = [{ id: "a" }, { id: "b" }];
    const merged = mergeNav(base, [{ item: { id: "plugin:/x" }, replaces: "zzz", section: "a" }]);
    expect(merged.map(n => n.id)).toEqual(["a", "plugin:/x", "b"]);
  });

  it("dos plugins que reemplazan lo mismo: gana el primero, el segundo se suma sin ocultar nada", () => {
    const base = [{ id: "models" }, { id: "c" }];
    const merged = mergeNav(base, [
      { item: { id: "p1" }, replaces: "models" },
      { item: { id: "p2" }, replaces: "models" },
    ]);
    expect(merged.map(n => n.id)).toEqual(["p1", "c", "p2"]);
  });

  it("sin plugin visible el ítem base se conserva (la consola nunca queda sin pantalla)", () => {
    const base = [{ id: "models" }];
    expect(mergeNav(base, [])).toEqual(base);
  });

  it("`replaces` debe ser un texto: otro tipo invalida la página", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const C = () => null;
    const pages = collectPluginPages({
      "a.tsx": { default: { path: "/uno", Component: C, replaces: "models" } },
      "b.tsx": { default: { path: "/dos", Component: C, replaces: 42 } },
    });
    expect(pages.map(p => p.path)).toEqual(["/uno"]);
    expect(pages[0].replaces).toBe("models");
    warn.mockRestore();
  });

  it("replacedBaseIds devuelve los ids base que sustituye algún plugin instalado, para cualquier rol", async () => {
    const { replacedBaseIds } = await import("./registry");
    const C = () => null;
    const pages = [
      { path: "/m", Component: C, replaces: "models", roles: ["admin"] },
      { path: "/o", Component: C },
    ];
    expect([...replacedBaseIds(pages)]).toEqual(["models"]);
    expect(replacedBaseIds([]).size).toBe(0);
  });
});
