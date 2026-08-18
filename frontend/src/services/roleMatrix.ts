// Espejo EXPLÍCITO de `specs/017-auth-rbac-sso/contracts/matriz-roles.md` (FR-001/002/003).
//
// Fuente ÚNICA de la visibilidad y los permisos del frontend, igual que
// `backend/src/auth/matrix.py` lo es del backend. El front NO puede importar el .py, así que
// mantiene su propio espejo. Regla 5 (contrato): cambiar la matriz = cambiar el contrato +
// `matrix.py` + ESTE archivo en el MISMO tramo. NO hardcodear permisos fuera de acá: `auth.ts`
// (`ROLE_PERMISSIONS`) y el nav de `App.tsx` DERIVAN de acá (anti-drift, patrón del backend).

// Roles CANÓNICOS post-013 — las columnas del contrato. En C2 `super_admin` es operativamente
// equivalente a `tenant_admin` (su semántica cross-tenant despierta con el multi-tenant real).
export type CanonicalRole =
  | "super_admin" | "tenant_admin" | "compliance_officer" | "client" | "lectura";

// Grupos de superficie — las filas del contrato. El comentario mapea a routers/páginas.
// NOTA: `models` (alta/baja de modelos & Ollama) NO está en ningún grupo del contrato 017 y se
// gatea EXPLÍCITO fuera de esta matriz (App.tsx) — mapearlo a config_producto le quitaba el nav a
// `developer`, que el backend sí deja gestionarlos (under-permit). Pendiente decisión de contrato.
export type SurfaceGroup =
  | "gestion_iam"             // users, keys, groups
  | "config_producto"        // guardians, policy, router_config, governance, budgets
  | "compliance_config"      // retention, security policies, consent admin
  | "artefactos_compliance"  // projects, DPAs, DSRs
  | "human_reviews_resolver" // aprobar/rechazar reviews (única W del auditor)
  | "vitrinas_lectura"       // audit, monitor, reports, costs-read, health detallado
  | "costs_config"           // budgets write, compresión por grupo
  | "chat_playground";       // POST /chat/completions (camino JWT)

export type Access = "RW" | "R" | "W" | "PROPIO" | "-";

// La matriz, 1:1 con `matriz-roles.md`. Revisable celda por celda contra el contrato.
export const MATRIZ: Record<SurfaceGroup, Record<CanonicalRole, Access>> = {
  gestion_iam:            { super_admin: "RW", tenant_admin: "RW", compliance_officer: "R",  client: "PROPIO", lectura: "-" },
  config_producto:        { super_admin: "RW", tenant_admin: "RW", compliance_officer: "R",  client: "-",      lectura: "-" },
  compliance_config:      { super_admin: "RW", tenant_admin: "RW", compliance_officer: "R",  client: "-",      lectura: "-" },
  artefactos_compliance:  { super_admin: "RW", tenant_admin: "RW", compliance_officer: "R",  client: "-",      lectura: "-" },
  human_reviews_resolver: { super_admin: "RW", tenant_admin: "RW", compliance_officer: "W",  client: "-",      lectura: "-" },
  vitrinas_lectura:       { super_admin: "R",  tenant_admin: "R",  compliance_officer: "R",  client: "PROPIO", lectura: "R" },
  costs_config:           { super_admin: "RW", tenant_admin: "RW", compliance_officer: "R",  client: "-",      lectura: "-" },
  chat_playground:        { super_admin: "RW", tenant_admin: "RW", compliance_officer: "RW", client: "RW",     lectura: "-" },
};

// El front trabaja con el rol YA normalizado por `toLegacyRole` (auth.ts): admin /
// compliance_officer / clinician / developer / client / lectura. Acá se traduce ESE vocabulario
// legacy al canónico de la matriz — inverso de `toLegacyRole`. `clinician`/`developer` son
// LABELS sectoriales de `client` (D9), NO roles: colapsan a `client`. Por eso `developer` deja
// de otorgar permisos de gestión (keys/models) — ése era justamente el drift a cerrar.
export type FrontRole =
  | "admin" | "compliance_officer" | "clinician" | "developer" | "client" | "lectura";

const LEGACY_TO_CANONICAL: Record<FrontRole, CanonicalRole> = {
  admin: "tenant_admin",                    // super_admin ≡ tenant_admin en C2 (misma fila)
  compliance_officer: "compliance_officer",
  clinician: "client",                      // label sectorial → client
  developer: "client",                      // label sectorial → client (NO rol de gestión)
  client: "client",
  lectura: "lectura",
};

function canonical(role: string): CanonicalRole | null {
  return (LEGACY_TO_CANONICAL as Record<string, CanonicalRole>)[role] ?? null;
}

// ¿El rol puede ESCRIBIR el grupo? Lo que un botón de mutación debe requerir.
export function canWrite(role: string, group: SurfaceGroup): boolean {
  const c = canonical(role);
  if (!c) return false;
  const a = MATRIZ[group][c];
  return a === "RW" || a === "W";
}

// ¿El rol puede VER/LEER el grupo? Visibilidad del nav y lectura de inventario. Excluye PROPIO:
// eso no es acceso al grupo entero sino a lo propio del `client`, que va al portal, no a la
// consola (W queda incluido: el auditor que resuelve reviews también las ve).
export function canView(role: string, group: SurfaceGroup): boolean {
  const c = canonical(role);
  if (!c) return false;
  const a = MATRIZ[group][c];
  return a === "RW" || a === "R" || a === "W";
}
