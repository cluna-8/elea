import { canWrite, canView } from "./roleMatrix";

const TOKEN_KEY = "sentinel_session_token";
const USER_KEY = "sentinel_current_user";

export interface SessionUser {
  id: string;
  username: string;
  role:
    | "admin" | "compliance_officer" | "clinician" | "developer" // legacy (pre-013)
    | "super_admin" | "tenant_admin" | "client" | "lectura"; // canónicos post-013 (lectura: 017)
  display_label?: string | null;
  email: string;
}

// Shim de compatibilidad post-013 (espejo de backend/src/auth/rbac.py, transicional
// hasta el refactor RBAC de la spec 017): el backend ahora devuelve roles canónicos
// (tenant_admin / client + display_label); los gates de esta UI siguen escritos con
// el vocabulario legacy. Se normaliza al guardar la sesión para no tocar cada gate.
export function toLegacyRole(user: { role: string; display_label?: string | null }): SessionUser["role"] {
  if (user.role === "tenant_admin" || user.role === "super_admin") return "admin";
  if (user.role === "client" && (user.display_label === "clinician" || user.display_label === "developer")) {
    return user.display_label;
  }
  return user.role as SessionUser["role"];
}

export const authStorage = {
  save: (token: string, user: SessionUser) => {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify({ ...user, role: toLegacyRole(user) }));
  },
  clear: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  },
  getToken: (): string | null => localStorage.getItem(TOKEN_KEY),
  getUser: (): SessionUser | null => {
    const raw = localStorage.getItem(USER_KEY);
    if (!raw) return null;
    try { return JSON.parse(raw); } catch { return null; }
  },
  isLoggedIn: (): boolean => !!localStorage.getItem(TOKEN_KEY),
};

// Etiqueta VISIBLE de cada rol. `compliance_officer` se muestra como «Auditor» porque es
// el nombre con el que lo pide el cliente; el rol técnico guardado sigue siendo el mismo,
// acá no se renombra nada en la base ni cambian los permisos. Lo que ese rol puede y no
// puede hacer hoy está escrito en el alta de usuarios (UsersPage) y en la documentación de
// administración: NO es un rol de solo lectura todavía.
export const ROLE_LABELS: Record<string, string> = {
  admin: "Administrador",
  compliance_officer: "Auditor",
  clinician: "Especialista",
  developer: "Desarrollador",
  // Canónicos post-013 (por si llegan sin normalizar)
  super_admin: "Super Admin",
  tenant_admin: "Administrador",
  client: "Cliente",
  // `lectura` (017): rol de solo-vitrinas. Exercible cuando el backend emita `role=lectura`
  // (T009, aún no en main); se deja el label listo — que no aparezca todavía es esperado.
  lectura: "Solo Lectura",
};

// Permisos DERIVADOS de la matriz canónica (`roleMatrix.ts`, espejo del contrato) — no se
// hardcodean acá. `role` es el rol ya normalizado por `toLegacyRole`; `roleMatrix` lo traduce al
// canónico. Gestión = `canWrite` del grupo; lectura/inventario = `canView`. Reconciliación 017:
//   canManageCompliance pierde compliance_officer (matriz le saca W) · canManageKeys deja de
//   colgar del label `developer` (solo admin gestiona) · canApproveReviews = admin||compliance
//   (antes dejaba aprobar a client/clinician) · canViewAudit suma `lectura` · + helpers de
//   LECTURA nuevos para que el auditor VEA inventario (users/keys/config) sin botones de escritura.
export const ROLE_PERMISSIONS = {
  // Escritura / gestión (botones de mutación)
  canManageUsers: (role: string) => canWrite(role, "gestion_iam"),
  canManageKeys: (role: string) => canWrite(role, "gestion_iam"),
  canManageCompliance: (role: string) => canWrite(role, "compliance_config"),
  canManageConfig: (role: string) => canWrite(role, "config_producto"),
  canApproveReviews: (role: string) => canWrite(role, "human_reviews_resolver"),
  // Lectura / vitrinas / inventario
  canViewAudit: (role: string) => canView(role, "vitrinas_lectura"),
  canExportReports: (role: string) => canView(role, "vitrinas_lectura"),
  canViewUsers: (role: string) => canView(role, "gestion_iam"),
  canViewKeys: (role: string) => canView(role, "gestion_iam"),
  canViewConfig: (role: string) => canView(role, "config_producto"),
};
