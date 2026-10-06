// Registry de páginas de plugins — resuelto EN BUILD, sin editar App.tsx.
//
// Un plugin es un módulo `*.tsx`/`*.ts` dentro del directorio al que apunta el alias
// `@plugin-pages` (vite.config.ts: `VITE_PLUGIN_PAGES_DIR`, o `src/plugins/pages/`, vacío,
// por defecto). Cada módulo exporta por default una página o una lista de páginas:
//
//   export default { path: "/reportes", Component: ReportesPage,
//                    menu: { label: "Reportes", section: "audit" }, roles: ["admin"] };
//
// Sin plugins, el glob no encuentra nada, el registry es `[]` y la consola queda idéntica.
import type React from "react";

export type PluginMenu = {
  label: string;
  // `id` del ítem existente del nav DESPUÉS del cual va la entrada (p. ej. "audit").
  // Ausente o desconocido → al final del nav.
  section?: string;
  icon?: React.ComponentType<{ className?: string; "aria-hidden"?: boolean | "true" | "false" }>;
};

export type PluginPage = {
  path: string;
  Component: React.ComponentType;
  menu?: PluginMenu;
  // Roles (legacy, los de `SessionUser.role`) que ven la página. Fail-closed: sin
  // declarar, sólo `admin` — un plugin no se abre a toda la consola por omisión.
  roles?: string[];
  // `id` de un ítem BASE del nav al que esta página sustituye (p. ej. "models"): el ítem base se oculta
  // para TODOS los roles y la entrada del plugin ocupa su lugar para quienes la pueden ver (quien no
  // tiene permiso sobre la página no ve la pantalla: es la decisión de roles de la spec). Sin el plugin
  // instalado no se oculta nada: la consola nunca queda sin esa pantalla. Un id que no existe se ignora.
  replaces?: string;
};

const DEFAULT_ROLES = ["admin"];

function isPluginPage(value: unknown): value is PluginPage {
  if (!value || typeof value !== "object") return false;
  const v = value as Partial<PluginPage>;
  const componentOk = typeof v.Component === "function" || (typeof v.Component === "object" && v.Component !== null);
  const replacesOk = v.replaces === undefined || typeof v.replaces === "string";
  return typeof v.path === "string" && v.path.startsWith("/") && v.path.length > 1 && componentOk && replacesOk;
}

/** Normaliza los módulos que devuelve `import.meta.glob` (eager) en páginas válidas.
 *  Descarta —con aviso— lo que no cumple el contrato y los `path` repetidos: un plugin
 *  roto no puede tumbar la consola. Orden estable: por nombre de archivo. */
export function collectPluginPages(modules: Record<string, unknown>, reserved: string[] = []): PluginPage[] {
  const seen = new Set(reserved);
  const pages: PluginPage[] = [];
  for (const file of Object.keys(modules).sort()) {
    const mod = modules[file] as { default?: unknown } | undefined;
    const exported = mod?.default;
    const candidates = Array.isArray(exported) ? exported : [exported];
    for (const candidate of candidates) {
      if (!isPluginPage(candidate)) {
        console.warn(`[plugins] ${file}: export inválido (se espera { path: "/…", Component }), ignorado`);
        continue;
      }
      if (seen.has(candidate.path)) {
        console.warn(`[plugins] ${file}: path «${candidate.path}» repetido, ignorado`);
        continue;
      }
      seen.add(candidate.path);
      pages.push({ ...candidate, roles: candidate.roles ?? DEFAULT_ROLES });
    }
  }
  return pages;
}

export function canSeePluginPage(page: PluginPage, role: string): boolean {
  return (page.roles ?? DEFAULT_ROLES).includes(role);
}

/** Ids base que sustituye algún plugin instalado (para cualquier rol). */
export function replacedBaseIds(pages: PluginPage[]): Set<string> {
  return new Set(pages.flatMap(p => (p.replaces ? [p.replaces] : [])));
}

/** Inserta cada `item` después del ítem cuyo `id` es su `section` (o al final). Un `item` con
 *  `replaces` ocupa el lugar del ítem base con ese id (el primero que lo pide gana; si el id no existe,
 *  se trata como un `item` normal). */
export function mergeNav<T extends { id: string }>(
  base: T[], extra: { item: T; section?: string; replaces?: string }[],
): T[] {
  const out = [...base];
  // Varios plugins en la misma `section` quedan en su orden, no invertidos.
  const lastAfter = new Map<string, string>();
  for (const { item, section, replaces } of extra) {
    if (replaces) {
      const at = out.findIndex(n => n.id === replaces);
      if (at !== -1) {
        out.splice(at, 1, item);
        continue;
      }
    }
    const anchor = section ? lastAfter.get(section) ?? section : undefined;
    const idx = anchor ? out.findIndex(n => n.id === anchor) : -1;
    if (idx === -1) {
      out.push(item);
    } else {
      out.splice(idx + 1, 0, item);
      lastAfter.set(section as string, item.id);
    }
  }
  return out;
}

export const pluginPages: PluginPage[] = collectPluginPages(
  import.meta.glob("@plugin-pages/*.{ts,tsx}", { eager: true }),
);
