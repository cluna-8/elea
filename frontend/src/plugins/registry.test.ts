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
});
