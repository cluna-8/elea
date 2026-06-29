const API_BASE = "http://localhost:8081/api/v1";

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
  // --- Users & Groups ---
  getUsers: async (): Promise<User[]> => {
    const res = await fetch(`${API_BASE}/users`);
    if (!res.ok) throw new Error("Failed to fetch users");
    return res.json();
  },

  createUser: async (user: Omit<User, "id" | "created_at" | "updated_at"> & { password?: string }): Promise<User> => {
    const res = await fetch(`${API_BASE}/users`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...user, password: user.password || "defaultpass123" }),
    });
    if (!res.ok) throw new Error("Failed to create user");
    return res.json();
  },

  getGroups: async (): Promise<Group[]> => {
    const res = await fetch(`${API_BASE}/users/groups`);
    if (!res.ok) throw new Error("Failed to fetch groups");
    return res.json();
  },

  createGroup: async (group: Omit<Group, "id" | "created_at">): Promise<Group> => {
    const res = await fetch(`${API_BASE}/users/groups`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(group),
    });
    if (!res.ok) throw new Error("Failed to create group");
    return res.json();
  },

  // --- Budgets ---
  getBudgets: async (): Promise<Budget[]> => {
    const res = await fetch(`${API_BASE}/budgets`);
    if (!res.ok) throw new Error("Failed to fetch budgets");
    return res.json();
  },

  createBudget: async (budget: Omit<Budget, "id" | "current_spend_usd" | "current_tokens" | "last_reset_at" | "created_at" | "updated_at">): Promise<Budget> => {
    const res = await fetch(`${API_BASE}/budgets`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(budget),
    });
    if (!res.ok) throw new Error("Failed to create budget");
    return res.json();
  },

  // --- Security Policy ---
  getSecurityPolicy: async (): Promise<SecurityPolicy> => {
    const res = await fetch(`${API_BASE}/security/policy`);
    if (!res.ok) throw new Error("Failed to fetch security policy");
    return res.json();
  },

  updateSecurityPolicy: async (policy: SecurityPolicy): Promise<SecurityPolicy> => {
    const res = await fetch(`${API_BASE}/security/policy`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(policy),
    });
    if (!res.ok) throw new Error("Failed to update security policy");
    return res.json();
  },

  getPolicies: async (): Promise<SecurityPolicy[]> => {
    const res = await fetch(`${API_BASE}/security/policies`);
    if (!res.ok) throw new Error("Failed to fetch policies");
    return res.json();
  },

  createPolicy: async (policy: Omit<SecurityPolicy, "id" | "created_at" | "updated_at">): Promise<SecurityPolicy> => {
    const res = await fetch(`${API_BASE}/security/policies`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(policy),
    });
    if (!res.ok) throw new Error("Failed to create policy");
    return res.json();
  },

  updatePolicyById: async (id: string, policy: SecurityPolicy): Promise<SecurityPolicy> => {
    const res = await fetch(`${API_BASE}/security/policies/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(policy),
    });
    if (!res.ok) throw new Error("Failed to update policy");
    return res.json();
  },

  deletePolicy: async (id: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/security/policies/${id}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error("Failed to delete policy");
    return res.json();
  },

  // --- Audit Logs ---
  getAuditLogs: async (): Promise<{ total: number; logs: AuditLog[] }> => {
    const res = await fetch(`${API_BASE}/audit-logs`);
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
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (virtualKey) {
      headers["Authorization"] = `Bearer ${virtualKey}`;
    }
    const res = await fetch(`${API_BASE}/chat/completions`, {
      method: "POST",
      headers,
      body: JSON.stringify({ message, model, ...overrides }),
    });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || "Failed to send chat message");
    }
    return res.json();
  },

  getModels: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/chat/models`);
    if (!res.ok) throw new Error("Failed to fetch models");
    return res.json();
  },

  createModel: async (model: { model_name: string; provider: string; model_id: string; api_key?: string; api_base?: string }): Promise<any> => {
    const res = await fetch(`${API_BASE}/chat/models`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(model),
    });
    if (!res.ok) throw new Error("Failed to create model");
    return res.json();
  },

  deleteModel: async (modelName: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/chat/models/${modelName}`, {
      method: "DELETE",
    });
    if (!res.ok) throw new Error("Failed to delete model");
    return res.json();
  },

  // --- Virtual Keys ---
  getKeys: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/keys`);
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
  }): Promise<any> => {
    const res = await fetch(`${API_BASE}/keys`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(key),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to generate key");
    }
    return res.json();
  },

  deleteKey: async (id: string): Promise<any> => {
    const res = await fetch(`${API_BASE}/keys/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error("Failed to revoke key");
    return res.json();
  },

  getKeySpend: async (keyId: string): Promise<SpendInfo> => {
    const res = await fetch(`${API_BASE}/keys/${keyId}/spend`);
    if (!res.ok) return { spend_usd: null, max_budget: null, remaining: null };
    return res.json();
  },

  getGroupSpend: async (groupId: string): Promise<SpendInfo> => {
    const res = await fetch(`${API_BASE}/users/groups/${groupId}/spend`);
    if (!res.ok) return { spend_usd: null, max_budget: null, remaining: null };
    return res.json();
  },

  getUserSpend: async (userId: string): Promise<SpendInfo> => {
    const res = await fetch(`${API_BASE}/users/${userId}/spend`);
    if (!res.ok) return { spend_usd: null, max_budget: null, remaining: null };
    return res.json();
  },

  // --- Security Guardians ---
  getGuardians: async (): Promise<any[]> => {
    const res = await fetch(`${API_BASE}/guardians`);
    if (!res.ok) throw new Error("Failed to fetch guardians");
    return res.json();
  },

  updateGuardian: async (id: string, guardian: any): Promise<any> => {
    const res = await fetch(`${API_BASE}/guardians/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(guardian),
    });
    if (!res.ok) throw new Error("Failed to update guardian");
    return res.json();
  },

  testGuardian: async (id: string, text: string): Promise<{ blocked: boolean; reason: string | null }> => {
    const res = await fetch(`${API_BASE}/guardians/${id}/test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al ejecutar el test del guardián.");
    }
    return res.json();
  },
};
