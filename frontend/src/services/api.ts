import { authStorage } from "./auth";

// Ruta RELATIVA al mismo origen: el ingress (Caddy) proxya /api/* al backend.
// Un host:puerto absoluto rompe HTTPS (mixed content) y ata el deploy a un
// puerto publicado — fix portado del install real del VPS (issue #35).
const API_BASE = "/api/v1";

function authHeaders(): Record<string, string> {
  const token = authStorage.getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function jsonHeaders(): Record<string, string> {
  return { "Content-Type": "application/json", ...authHeaders() };
}

function handleExpiredSession(res: Response): void {
  if (res.status === 401) {
    authStorage.clear();
    window.location.reload();
  }
}

export interface Group {
  id: string;
  name: string;
  description?: string;
  engine_team_id?: string;
  created_at: string;
}

export interface SpendInfo {
  spend_usd: number | null;
  max_budget: number | null;
  remaining: number | null;
}

export interface User {
  id: string;
  username: string;
  email: string;
  role: string;
  group_id?: string;
  engine_user_id?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface Budget {
  id: string;
  user_id?: string;
  group_id?: string;
  max_spend_usd: number;
  current_spend_usd: number;
  max_tokens: number;
  current_tokens: number;
  reset_period: string;
  last_reset_at: string;
  created_at: string;
  updated_at: string;
}

export interface ModelPricing {
  model_name: string;
  input_cost_per_million: number;
  output_cost_per_million: number;
  max_tokens?: number | null;
  max_input_tokens?: number | null;
}

export interface CostModelBreakdown {
  model: string;
  cost_usd: number;
  requests: number;
  tokens_saved: number;
}

export interface CostEntityBreakdown {
  name: string;
  cost_usd: number;
  requests: number;
  tokens_saved: number;
  cost_saved_usd?: number;
}

export interface CostSummary {
  range: string;
  total_cost_usd: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  tokens_saved: number;
  cost_saved_usd: number;
  total_requests: number;
  cost_saved_estimate_usd: number | null;
  top_models: CostModelBreakdown[];
  by_user: CostEntityBreakdown[];
  by_group: CostEntityBreakdown[];
}

export interface CostConfig {
  enabled: boolean;
  default_strategy: string;
  default_threshold: number;
  default_aggressiveness: string;
}

export interface GroupCompressionConfig {
  group_id: string;
  group_name: string;
  mode: "off" | "deterministic" | "headroom";
  strategy: "deterministic" | "headroom";
  threshold_tokens: number | null;
  aggressiveness: "low" | "medium" | "high";
  cache_enabled: boolean;
}

export type CompressionVeredicto = "conviene" | "no_conviene" | "usd_no_disponible";

export interface CompressionAnalysis {
  tokens_original: number;
  tokens_compressed: number;
  tokens_saved: number;
  cost_saved_usd: number | null;
  would_compress: boolean;
  veredicto: CompressionVeredicto;
  ratio: number;
  threshold: number;
  model: string | null;
  aggressiveness: string;
  strategy: string;
  strategy_applied?: string;
}

export interface SecurityPolicy {
  id?: string;
  name: string;
  is_active: boolean;
  entity_configs: Record<string, "MASK" | "BLOCK" | "ALLOW">;
  gdpr_mode: boolean;
  ai_act_mode: boolean;
  headroom_mode: boolean;
}

export interface AuditLog {
  id: string;
  timestamp: string;
  user_id?: string;
  api_key_id?: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  pii_detected: boolean;
  masked_entities?: Array<{ type: string; count: number }>;
  compliance_status: string;
  latency_ms: number;
  tokens_saved_by_optimization: number;
}

export const api = {
  // --- Auth ---
  login: async (username: string, password: string): Promise<{ access_token: string; user: any }> => {
    const res = await fetch(`${API_BASE}/users/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || "Credenciales incorrectas."); }
    return res.json();
  },

  // --- Users & Groups ---
  getUsers: async (): Promise<User[]> => {
    const res = await fetch(`${API_BASE}/users`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch users");
    return res.json();
  },

  createUser: async (user: Omit<User, "id" | "created_at" | "updated_at"> & { password?: string }): Promise<User> => {
    const res = await fetch(`${API_BASE}/users`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ ...user, password: user.password || "defaultpass123" }),
    });
    if (!res.ok) throw new Error("Failed to create user");
    return res.json();
  },

  updateUser: async (userId: string, current: User, patch: { group_id?: string | null; role?: string; compliance_project_id?: string | null }): Promise<User> => {
    const body = { username: current.username, email: current.email, role: current.role, is_active: current.is_active, ...patch };
    const res = await fetch(`${API_BASE}/users/${userId}`, {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error("Failed to update user");
    return res.json();
  },

  getGroups: async (): Promise<Group[]> => {
    const res = await fetch(`${API_BASE}/users/groups`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch groups");
    return res.json();
  },

  createGroup: async (group: Omit<Group, "id" | "created_at">): Promise<Group> => {
    const res = await fetch(`${API_BASE}/users/groups`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(group),
    });
    if (!res.ok) throw new Error("Failed to create group");
    return res.json();
  },

  // --- Budgets ---
  getBudgets: async (): Promise<Budget[]> => {
    const res = await fetch(`${API_BASE}/budgets`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch budgets");
    return res.json();
  },

  createBudget: async (budget: Omit<Budget, "id" | "current_spend_usd" | "current_tokens" | "last_reset_at" | "created_at" | "updated_at">): Promise<Budget> => {
    const res = await fetch(`${API_BASE}/budgets`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(budget),
    });
    if (!res.ok) throw new Error("Failed to create budget");
    return res.json();
  },

  updateBudget: async (budgetId: string, patch: { max_spend_usd?: number; max_tokens?: number; reset_period?: string; user_id?: string; group_id?: string }): Promise<Budget> => {
    const res = await fetch(`${API_BASE}/budgets/${budgetId}`, {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error("Failed to update budget");
    return res.json();
  },

  deleteBudget: async (budgetId: string): Promise<void> => {
    const res = await fetch(`${API_BASE}/budgets/${budgetId}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error("Failed to delete budget");
  },

  // --- Security Policy ---
  getSecurityPolicy: async (): Promise<SecurityPolicy> => {
    const res = await fetch(`${API_BASE}/security/policy`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch security policy");
    return res.json();
  },

  updateSecurityPolicy: async (policy: SecurityPolicy): Promise<SecurityPolicy> => {
    const res = await fetch(`${API_BASE}/security/policy`, {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify(policy),
    });
    if (!res.ok) throw new Error("Failed to update security policy");
    return res.json();
  },

  getPolicies: async (): Promise<SecurityPolicy[]> => {
    const res = await fetch(`${API_BASE}/security/policies`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch policies");
    return res.json();
  },

  createPolicy: async (policy: Omit<SecurityPolicy, "id" | "created_at" | "updated_at">): Promise<SecurityPolicy> => {
    const res = await fetch(`${API_BASE}/security/policies`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(policy),
    });
    if (!res.ok) throw new Error("Failed to create policy");
    return res.json();
  },

  updatePolicyById: async (id: string, policy: SecurityPolicy): Promise<SecurityPolicy> => {
    const res = await fetch(`${API_BASE}/security/policies/${id}`, {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify(policy),
    });
    if (!res.ok) throw new Error("Failed to update policy");
    return res.json();
  },

  deletePolicy: async (id: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/security/policies/${id}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error("Failed to delete policy");
    return res.json();
  },

  // --- Audit Logs ---
  getAuditLogs: async (params?: {
    limit?: number;
    offset?: number;
    pii_detected?: string;
    compliance_status?: string;
    from_date?: string;
    to_date?: string;
  }): Promise<{ total: number; logs: AuditLog[] }> => {
    const qs = new URLSearchParams();
    if (params?.limit != null) qs.append("limit", String(params.limit));
    if (params?.offset != null) qs.append("offset", String(params.offset));
    if (params?.pii_detected) qs.append("pii_detected", params.pii_detected);
    if (params?.compliance_status) qs.append("compliance_status", params.compliance_status);
    if (params?.from_date) qs.append("from_date", params.from_date);
    if (params?.to_date) qs.append("to_date", params.to_date);
    const query = qs.toString();
    const res = await fetch(`${API_BASE}/audit-logs${query ? `?${query}` : ""}`, { headers: authHeaders() });
    handleExpiredSession(res);
    if (!res.ok) throw new Error("Failed to fetch audit logs");
    return res.json();
  },

  // --- Chat / Playground ---
  sendChatMessage: async (
    message: string, 
    model: string, 
    virtualKey?: string,
    overrides?: {
      override_pii_masking?: boolean;
      override_gdpr_mode?: boolean;
      override_ai_act_mode?: boolean;
      override_headroom_mode?: boolean;
    }
  ): Promise<any> => {
    const headers: Record<string, string> = { "Content-Type": "application/json", ...authHeaders() };
    if (virtualKey) {
      headers["Authorization"] = `Bearer ${virtualKey}`;
    }
    const res = await fetch(`${API_BASE}/chat/completions`, {
      method: "POST",
      headers,
      body: JSON.stringify({ message, model, ...overrides }),
    });
    handleExpiredSession(res);
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "Failed to send chat message");
    }
    return res.json();
  },

  getModels: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/chat/models`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch models");
    return res.json();
  },

  createModel: async (model: { model_name: string; provider: string; model_id: string; api_key?: string; api_base?: string }): Promise<any> => {
    const res = await fetch(`${API_BASE}/chat/models`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(model),
    });
    if (!res.ok) throw new Error("Failed to create model");
    return res.json();
  },

  deleteModel: async (modelName: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/chat/models/${modelName}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!res.ok) throw new Error("Failed to delete model");
    return res.json();
  },

  updateModelCredential: async (modelName: string, litellmParams: Record<string, string>): Promise<void> => {
    const res = await fetch(`${API_BASE}/chat/models/${modelName}`, {
      method: "PATCH",
      headers: jsonHeaders(),
      body: JSON.stringify({ litellm_params: litellmParams }),
    });
    if (!res.ok) throw new Error("Failed to update model credential");
  },

  getFallbacks: async (): Promise<Record<string, string>> => {
    const res = await fetch(`${API_BASE}/chat/fallbacks`, { headers: authHeaders() });
    if (!res.ok) return {};
    return res.json();
  },

  setFallback: async (modelName: string, fallbackModel: string | null): Promise<void> => {
    await fetch(`${API_BASE}/chat/fallbacks/${modelName}`, {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify({ fallback_model: fallbackModel }),
    });
  },

  getModelsPricing: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/chat/models/pricing`, { headers: authHeaders() });
    if (!res.ok) return [];
    return res.json();
  },

  // --- Virtual Keys ---
  getKeys: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/keys`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch keys");
    return res.json();
  },

  createKey: async (key: {
    name: string;
    user_id?: string;
    group_id?: string;
    max_budget?: number;
    budget_duration?: string;
    models?: string[];
    expires_at?: string;
    rpm_limit?: number;
    tpm_limit?: number;
    compliance_project_id?: string;
  }): Promise<any> => {
    const res = await fetch(`${API_BASE}/keys`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(key),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to generate key");
    }
    return res.json();
  },

  deleteKey: async (id: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/keys/${id}`, { method: "DELETE", headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to revoke key");
    return res.json();
  },

  getKeySpend: async (keyId: string): Promise<SpendInfo> => {
    const res = await fetch(`${API_BASE}/keys/${keyId}/spend`, { headers: authHeaders() });
    if (!res.ok) return { spend_usd: null, max_budget: null, remaining: null };
    return res.json();
  },

  getGroupSpend: async (groupId: string): Promise<SpendInfo> => {
    const res = await fetch(`${API_BASE}/users/groups/${groupId}/spend`, { headers: authHeaders() });
    if (!res.ok) return { spend_usd: null, max_budget: null, remaining: null };
    return res.json();
  },

  getUserSpend: async (userId: string): Promise<SpendInfo> => {
    const res = await fetch(`${API_BASE}/users/${userId}/spend`, { headers: authHeaders() });
    if (!res.ok) return { spend_usd: null, max_budget: null, remaining: null };
    return res.json();
  },

  // --- Security Guardians ---
  getGuardians: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/guardians`, { headers: authHeaders() });
    handleExpiredSession(res);
    if (!res.ok) throw new Error("Failed to fetch guardians");
    return res.json();
  },

  updateGuardian: async (id: string, guardian: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/guardians/${id}`, {
      method: "PUT",
      headers: jsonHeaders(),
      body: JSON.stringify(guardian),
    });
    if (!res.ok) throw new Error("Failed to update guardian");
    return res.json();
  },

  testGuardian: async (id: string, text: string): Promise<{ blocked: boolean; reason: string | null }> => {
    const res = await fetch(`${API_BASE}/guardians/${id}/test`, {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al ejecutar el test del guardián.");
    }
    return res.json();
  },

  // --- Analytics ---
  getAnalyticsSummary: async (range: "day" | "week" | "month"): Promise<any> => {
    const res = await fetch(`${API_BASE}/analytics/summary?range=${range}`, { headers: authHeaders() });
    handleExpiredSession(res);
    if (!res.ok) throw new Error("Failed to fetch analytics summary");
    return res.json();
  },

  getEngineStatus: async (): Promise<{ status: "online" | "offline"; checked_at: string }> => {
    const res = await fetch(`${API_BASE}/analytics/engine-status`, { headers: authHeaders() });
    handleExpiredSession(res);
    if (!res.ok) return { status: "offline", checked_at: new Date().toISOString() };
    return res.json();
  },

  exportAuditLogs: async (filters: {
    pii_detected?: boolean;
    compliance_status?: string;
    from_date?: string;
    to_date?: string;
  }): Promise<void> => {
    const params = new URLSearchParams();
    if (filters.pii_detected !== undefined) params.append("pii_detected", String(filters.pii_detected));
    if (filters.compliance_status) params.append("compliance_status", filters.compliance_status);
    if (filters.from_date) params.append("from_date", filters.from_date);
    if (filters.to_date) params.append("to_date", filters.to_date);

    const res = await fetch(`${API_BASE}/audit-logs/export?${params.toString()}`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to export audit logs");

    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="(.+?)"/);
    const filename = match ? match[1] : "audit_export.csv";

    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  // --- Compliance ---
  getComplianceProjects: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/compliance/projects`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch compliance projects");
    return res.json();
  },

  createComplianceProject: async (project: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/projects`, {
      method: "POST", headers: jsonHeaders(), body: JSON.stringify(project),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || "Error al crear proyecto"); }
    return res.json();
  },

  updateComplianceProject: async (id: string, project: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/projects/${id}`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify(project),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || "Error al actualizar proyecto"); }
    return res.json();
  },

  deleteComplianceProject: async (id: string): Promise<void> => {
    await fetch(`${API_BASE}/compliance/projects/${id}`, { method: "DELETE", headers: authHeaders() });
  },

  getDPAs: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/compliance/dpas`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch DPAs");
    return res.json();
  },

  createDPA: async (dpa: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/dpas`, {
      method: "POST", headers: jsonHeaders(), body: JSON.stringify(dpa),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || "Error al registrar DPA"); }
    return res.json();
  },

  updateDPA: async (id: string, dpa: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/dpas/${id}`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify(dpa),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || "Error al actualizar DPA"); }
    return res.json();
  },

  deleteDPA: async (id: string): Promise<void> => {
    await fetch(`${API_BASE}/compliance/dpas/${id}`, { method: "DELETE", headers: authHeaders() });
  },

  getDSRs: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/compliance/dsr`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch DSRs");
    return res.json();
  },

  createDSR: async (dsr: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/dsr`, {
      method: "POST", headers: jsonHeaders(), body: JSON.stringify(dsr),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || "Error al crear solicitud"); }
    return res.json();
  },

  updateDSR: async (id: string, update: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/dsr/${id}`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify(update),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || "Error al actualizar solicitud"); }
    return res.json();
  },

  searchDSR: async (subjectId: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/dsr/search?subject_id=${encodeURIComponent(subjectId)}`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to search DSR");
    return res.json();
  },

  getRetentionPolicies: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/compliance/retention`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch retention policies");
    return res.json();
  },

  updateRetentionPolicies: async (policies: any[]): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/compliance/retention`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify(policies),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || "Error al guardar retención"); }
    return res.json();
  },

  getComplianceDashboard: async (): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/dashboard`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch compliance dashboard");
    return res.json();
  },

  // --- Groups compliance ---
  getGroupsCompliance: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/groups`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch groups");
    return res.json();
  },

  updateGroupCompliance: async (groupId: string, data: { default_legal_basis?: string; default_risk_level?: string; compliance_project_id?: string | null }): Promise<any> => {
    const res = await fetch(`${API_BASE}/groups/${groupId}/compliance`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify(data),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || "Error al actualizar perfil de compliance"); }
    return res.json();
  },

  assignUserGroup: async (userId: string, groupId: string | null): Promise<any> => {
    const res = await fetch(`${API_BASE}/groups/users/${userId}/group`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify({ group_id: groupId }),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || "Error al asignar grupo"); }
    return res.json();
  },

  // --- Consent ---
  getUserConsents: async (userId: string): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/compliance/consent/${userId}`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch consents");
    return res.json();
  },

  recordConsent: async (data: { user_id: string; consent_type: string; version?: string; notes?: string }): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/consent`, {
      method: "POST", headers: jsonHeaders(), body: JSON.stringify(data),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || "Error al registrar consentimiento"); }
    return res.json();
  },

  revokeConsent: async (consentId: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/consent/${consentId}`, { method: "DELETE", headers: authHeaders() });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || "Error al revocar consentimiento"); }
    return res.json();
  },

  getAllConsents: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/compliance/consent`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch consents");
    return res.json();
  },

  // --- Reports (GDPR Art. 30 / Audit Export) ---
  exportRAT: async (): Promise<void> => {
    const res = await fetch(`${API_BASE}/reports/rat`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Error al exportar el RAT");
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="(.+?)"/);
    const filename = match ? match[1] : "RAT_Art30_GDPR.csv";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  exportDSAR: async (subjectIdentifier: string): Promise<void> => {
    const res = await fetch(`${API_BASE}/reports/dsar/${encodeURIComponent(subjectIdentifier)}`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Error al exportar el DSAR");
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="(.+?)"/);
    const filename = match ? match[1] : "DSAR_export.csv";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  exportHumanReviewLog: async (): Promise<void> => {
    const res = await fetch(`${API_BASE}/reports/human-review-log`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Error al exportar revisiones");
    const blob = await res.blob();
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="(.+?)"/);
    const filename = match ? match[1] : "Revisiones_Humanas.csv";
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = filename;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  },

  getExecutiveSummary: async (): Promise<any> => {
    const res = await fetch(`${API_BASE}/reports/executive`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch executive summary");
    return res.json();
  },

  // --- Human Review Queue ---
  getPendingReviews: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/compliance/review/pending`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch pending reviews");
    return res.json();
  },

  submitReview: async (token: string, data: { reviewer_id?: string; action: string; notes?: string }): Promise<any> => {
    const res = await fetch(`${API_BASE}/compliance/review/${token}`, {
      method: "POST", headers: jsonHeaders(), body: JSON.stringify(data),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || "Error al procesar la revisión"); }
    return res.json();
  },

  // --- Costs (Ahorro de Costes IA) ---
  getCostsSummary: async (range: "day" | "week" | "month"): Promise<CostSummary> => {
    const res = await fetch(`${API_BASE}/costs/summary?range=${range}`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch costs summary");
    return res.json();
  },

  calculateCompression: async (req: {
    prompt: string;
    model?: string | null;
    threshold?: number | null;
    aggressiveness?: string;
    strategy?: string;
  }): Promise<CompressionAnalysis> => {
    const res = await fetch(`${API_BASE}/costs/calculator`, {
      method: "POST", headers: jsonHeaders(), body: JSON.stringify(req),
    });
    if (!res.ok) throw new Error("Failed to run compression calculator");
    return res.json();
  },

  // --- Costs config (US4) ---
  getCostConfig: async (): Promise<CostConfig> => {
    const res = await fetch(`${API_BASE}/costs/config`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch cost config");
    return res.json();
  },

  updateCostConfig: async (enabled: boolean): Promise<{ enabled: boolean }> => {
    const res = await fetch(`${API_BASE}/costs/config`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify({ enabled }),
    });
    if (!res.ok) throw new Error("Failed to update cost config");
    return res.json();
  },

  getGroupCompression: async (groupId: string): Promise<GroupCompressionConfig> => {
    const res = await fetch(`${API_BASE}/costs/groups/${groupId}/compression`, { headers: authHeaders() });
    if (!res.ok) throw new Error("Failed to fetch group compression config");
    return res.json();
  },

  updateGroupCompression: async (groupId: string, cfg: Omit<GroupCompressionConfig, "group_id" | "group_name">): Promise<GroupCompressionConfig> => {
    const res = await fetch(`${API_BASE}/costs/groups/${groupId}/compression`, {
      method: "PUT", headers: jsonHeaders(), body: JSON.stringify(cfg),
    });
    if (!res.ok) throw new Error("Failed to update group compression config");
    return res.json();
  },
};
