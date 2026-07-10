const TOKEN_KEY = "basa_session_token";
const USER_KEY = "basa_current_user";

export interface SessionUser {
  id: string;
  username: string;
  role:
    | "admin" | "compliance_officer" | "clinician" | "developer" // legacy (pre-013)
    | "super_admin" | "tenant_admin" | "client"; // canónicos post-013
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

export const ROLE_LABELS: Record<string, string> = {
  admin: "Administrador",
  compliance_officer: "Oficial de Compliance",
  clinician: "Especialista",
  developer: "Desarrollador",
  // Canónicos post-013 (por si llegan sin normalizar)
  super_admin: "Super Admin",
  tenant_admin: "Administrador",
  client: "Cliente",
};

export const ROLE_PERMISSIONS = {
  canManageUsers: (role: string) => role === "admin",
  canManageCompliance: (role: string) => role === "admin" || role === "compliance_officer",
  canExportReports: (role: string) => role === "admin" || role === "compliance_officer",
  canApproveReviews: (role: string) => role !== "developer",
  canManageKeys: (role: string) => role === "admin" || role === "developer",
  canViewAudit: (role: string) => role === "admin" || role === "compliance_officer",
};
