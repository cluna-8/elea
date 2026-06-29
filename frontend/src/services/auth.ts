const TOKEN_KEY = "basa_session_token";
const USER_KEY = "basa_current_user";

export interface SessionUser {
  id: string;
  username: string;
  role: "admin" | "compliance_officer" | "clinician" | "developer";
  email: string;
}

export const authStorage = {
  save: (token: string, user: SessionUser) => {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
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
  clinician: "Clínico",
  developer: "Desarrollador",
};

export const ROLE_PERMISSIONS = {
  canManageUsers: (role: string) => role === "admin",
  canManageCompliance: (role: string) => role === "admin" || role === "compliance_officer",
  canExportReports: (role: string) => role === "admin" || role === "compliance_officer",
  canApproveReviews: (role: string) => role !== "developer",
  canManageKeys: (role: string) => role === "admin" || role === "developer",
  canViewAudit: (role: string) => role === "admin" || role === "compliance_officer",
};
