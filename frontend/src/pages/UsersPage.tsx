import React, { useState, useEffect } from "react";
import { api, User, Budget, Group, SpendInfo } from "../services/api";

const LEGAL_BASIS_SHORT: Record<string, string> = {
  art_9_2_h: "Art. 9(2)(h) Sanitario",
  art_9_2_j: "Art. 9(2)(j) Investigación",
  art_9_2_a: "Art. 9(2)(a) Consentimiento",
  art_6_1_c: "Art. 6(1)(c) Obligación legal",
  art_6_1_e: "Art. 6(1)(e) Interés público",
};

const RISK_BADGE: Record<string, { label: string; cls: string }> = {
  minimal:           { label: "Mínimo",         cls: "text-slate-400 border-slate-700" },
  limited:           { label: "Limitado",        cls: "text-primary border-primary/30" },
  high_risk_annex3:  { label: "Alto — Annex III", cls: "text-warning border-warning/30" },
  high_risk_annex1:  { label: "Alto — MDR",       cls: "text-danger border-danger/30" },
};

interface VirtualKey {
  id: string;
  name: string;
  key_preview: string;
  user_id?: string;
  group_id?: string;
  is_active: boolean;
  created_at: string;
}

type Tab = "overview" | "teams" | "keys" | "budgets" | "auth";

export const UsersPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [users, setUsers] = useState<User[]>([]);
  const [budgets, setBudgets] = useState<Budget[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [keys, setKeys] = useState<VirtualKey[]>([]);
  const [groupSpend, setGroupSpend] = useState<Record<string, SpendInfo>>({});
  const [keySpend, setKeySpend] = useState<Record<string, SpendInfo>>({});
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Modals
  const [showUserModal, setShowUserModal] = useState(false);
  const [showTeamModal, setShowTeamModal] = useState(false);
  const [showKeyModal, setShowKeyModal] = useState(false);
  const [showBudgetModal, setShowBudgetModal] = useState(false);
  const [generatedKey, setGeneratedKey] = useState<string | null>(null);

  // Form States
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("clinician");
  const [groupId, setGroupId] = useState("");

  const [teamName, setTeamName] = useState("");
  const [teamDesc, setTeamDesc] = useState("");

  // Assign group modal
  const [assignGroupUser, setAssignGroupUser] = useState<any | null>(null);
  const [assignGroupId, setAssignGroupId] = useState("");

  // Edit budget modal
  const [editingBudget, setEditingBudget] = useState<any | null>(null);
  const [editBudgetUsd, setEditBudgetUsd] = useState("");
  const [editBudgetTokens, setEditBudgetTokens] = useState("");

  // Per-user compliance
  const [userLegalBasis, setUserLegalBasis] = useState("");
  const [userRiskLevel, setUserRiskLevel] = useState("");
  const [userComplianceProjectId, setUserComplianceProjectId] = useState("");

  // Per-key compliance
  const [keyComplianceProjectId, setKeyComplianceProjectId] = useState("");

  const [keyName, setKeyName] = useState("");
  const [keyUserId, setKeyUserId] = useState("");
  const [keyGroupId, setKeyGroupId] = useState("");
  const [keyMaxBudget, setKeyMaxBudget] = useState("");
  const [keyBudgetDuration, setKeyBudgetDuration] = useState("30d");
  const [keyRpmLimit, setKeyRpmLimit] = useState("60");
  const [keyTpmLimit, setKeyTpmLimit] = useState("100000");

  const [budgetUserId, setBudgetUserId] = useState("");
  const [budgetGroupId, setBudgetGroupId] = useState("");
  const [maxSpend, setMaxSpend] = useState("100.00");
  const [maxTokens, setMaxTokens] = useState("1000000");
  const [resetPeriod, setResetPeriod] = useState("monthly");

  const [copied, setCopied] = useState(false);

  // Compliance profile state
  const [complianceGroups, setComplianceGroups] = useState<any[]>([]);
  const [complianceProjects, setComplianceProjects] = useState<any[]>([]);
  const [showComplianceModal, setShowComplianceModal] = useState(false);
  const [editingGroup, setEditingGroup] = useState<any | null>(null);
  const [complianceForm, setComplianceForm] = useState({ default_legal_basis: "", default_risk_level: "", compliance_project_id: "" });
  const [complianceMsg, setComplianceMsg] = useState("");

  const fetchComplianceData = async () => {
    try {
      const [cGroups, cProjects] = await Promise.all([
        api.getGroupsCompliance(),
        api.getComplianceProjects(),
      ]);
      setComplianceGroups(cGroups);
      setComplianceProjects(cProjects);
    } catch {}
  };

  const fetchData = async () => {
    try {
      setLoading(true);
      const [fetchedUsers, fetchedBudgets, fetchedGroups, fetchedKeys] = await Promise.all([
        api.getUsers(),
        api.getBudgets(),
        api.getGroups(),
        api.getKeys(),
      ]);
      setUsers(fetchedUsers);
      setBudgets(fetchedBudgets);
      setGroups(fetchedGroups);
      setKeys(fetchedKeys);
      setError(null);

      const spendResults = await Promise.allSettled([
        ...fetchedGroups
          .filter((g) => g.engine_team_id)
          .map((g) => api.getGroupSpend(g.id).then((s) => ({ id: g.id, spend: s }))),
        ...fetchedKeys
          .filter((k: any) => k.engine_key_token)
          .map((k: any) => api.getKeySpend(k.id).then((s) => ({ id: k.id, spend: s }))),
      ]);

      const newGroupSpend: Record<string, SpendInfo> = {};
      const newKeySpend: Record<string, SpendInfo> = {};

      spendResults.forEach((r) => {
        if (r.status === "fulfilled") {
          const { id, spend } = r.value as { id: string; spend: SpendInfo };
          const isGroup = fetchedGroups.some((g) => g.id === id);
          if (isGroup) newGroupSpend[id] = spend;
          else newKeySpend[id] = spend;
        }
      });

      setGroupSpend(newGroupSpend);
      setKeySpend(newKeySpend);
    } catch (err) {
      setError("Error al cargar datos de la pasarela.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    fetchComplianceData();
  }, []);

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      await api.createUser({
        username,
        email,
        role,
        group_id: groupId || undefined,
        is_active: true,
        legal_basis: userLegalBasis || undefined,
        risk_level: userRiskLevel || undefined,
        compliance_project_id: userComplianceProjectId || undefined,
      });
      setShowUserModal(false);
      setUsername(""); setEmail(""); setGroupId("");
      setUserLegalBasis(""); setUserRiskLevel(""); setUserComplianceProjectId("");
      await fetchData();
    } catch {
      alert("Error al crear el usuario.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleCreateTeam = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      await api.createGroup({ name: teamName, description: teamDesc });
      setShowTeamModal(false);
      setTeamName(""); setTeamDesc("");
      await fetchData();
    } catch {
      alert("Error al crear el equipo.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleCreateKey = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      const payload: any = { name: keyName };
      if (keyUserId) payload.user_id = keyUserId;
      if (keyGroupId) payload.group_id = keyGroupId;
      if (keyMaxBudget) payload.max_budget = parseFloat(keyMaxBudget);
      if (keyBudgetDuration) payload.budget_duration = keyBudgetDuration;
      if (keyComplianceProjectId) payload.compliance_project_id = keyComplianceProjectId;
      if (keyRpmLimit) payload.rpm_limit = parseInt(keyRpmLimit, 10);
      if (keyTpmLimit) payload.tpm_limit = parseInt(keyTpmLimit, 10);

      const res = await api.createKey(payload);
      setGeneratedKey(res.plain_key);
      setShowKeyModal(false);
      setKeyName(""); setKeyUserId(""); setKeyGroupId(""); setKeyMaxBudget("");
      setKeyBudgetDuration("30d"); setKeyComplianceProjectId("");
      setKeyRpmLimit("60"); setKeyTpmLimit("100000");
      await fetchData();
    } catch {
      alert("Error al generar la llave virtual.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleCreateBudget = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      const payload: any = {
        max_spend_usd: parseFloat(maxSpend),
        max_tokens: parseInt(maxTokens),
        reset_period: resetPeriod,
      };
      if (budgetUserId) payload.user_id = budgetUserId;
      if (budgetGroupId) payload.group_id = budgetGroupId;

      await api.createBudget(payload);
      setShowBudgetModal(false);
      setBudgetUserId(""); setBudgetGroupId("");
      setMaxSpend("100.00"); setMaxTokens("1000000");
      await fetchData();
    } catch {
      alert("Error al asignar el presupuesto.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleRevokeKey = async (id: string) => {
    if (!confirm("¿Está seguro de que desea revocar esta llave virtual? Dejará de funcionar inmediatamente.")) return;
    setActionLoading(true);
    try {
      await api.deleteKey(id);
      await fetchData();
    } catch {
      alert("Error al revocar la llave.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleDeleteBudget = async (id: string) => {
    if (!confirm("¿Eliminar este presupuesto? Esta acción no se puede deshacer.")) return;
    setActionLoading(true);
    try {
      await api.deleteBudget(id);
      await fetchData();
    } catch {
      alert("Error al eliminar el presupuesto.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleCopyKey = () => {
    if (generatedKey) {
      navigator.clipboard.writeText(generatedKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleUpdateBudget = async () => {
    if (!editingBudget) return;
    try {
      await api.updateBudget(editingBudget.id, {
        max_spend_usd: parseFloat(editBudgetUsd),
        max_tokens: parseInt(editBudgetTokens),
        reset_period: editingBudget.reset_period,
        user_id: editingBudget.user_id || undefined,
        group_id: editingBudget.group_id || undefined,
      });
      setEditingBudget(null);
      await fetchData();
    } catch (err: any) {
      alert(err.message || "Error al actualizar presupuesto.");
    }
  };

  const handleAssignGroup = async () => {
    if (!assignGroupUser) return;
    try {
      await api.updateUser(assignGroupUser.id, assignGroupUser, { group_id: assignGroupId || null });
      setAssignGroupUser(null);
      await fetchData();
    } catch (err: any) {
      alert(err.message || "Error al asignar equipo.");
    }
  };

  const openComplianceModal = (g: any) => {
    setEditingGroup(g);
    setComplianceForm({
      default_legal_basis: g.default_legal_basis || "",
      default_risk_level: g.default_risk_level || "",
      compliance_project_id: g.compliance_project_id || "",
    });
    setShowComplianceModal(true);
  };

  const saveComplianceProfile = async () => {
    if (!editingGroup) return;
    try {
      await api.updateGroupCompliance(editingGroup.id, {
        default_legal_basis: complianceForm.default_legal_basis || undefined,
        default_risk_level: complianceForm.default_risk_level || undefined,
        compliance_project_id: complianceForm.compliance_project_id || null,
      });
      setComplianceMsg("Perfil actualizado correctamente.");
      setShowComplianceModal(false);
      fetchComplianceData();
      setTimeout(() => setComplianceMsg(""), 3000);
    } catch (e: any) {
      alert(e.message);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center py-24 text-xs font-mono text-text-secondary">
        Cargando datos...
      </div>
    );
  }

  // ── KPI helpers ────────────────────────────────────────────────────────────
  const totalSpendUsd = budgets.reduce((acc, b) => acc + Number(b.current_spend_usd), 0);
  const nearLimitBudgets = budgets.filter((b) => {
    const pct = (Number(b.current_spend_usd) / Number(b.max_spend_usd)) * 100;
    return pct >= 80;
  });

  const TABS: { id: Tab; label: string }[] = [
    { id: "overview", label: "Resumen" },
    { id: "teams",    label: "Usuarios & Equipos" },
    { id: "keys",     label: "Llaves Virtuales" },
    { id: "budgets",  label: "Presupuestos" },
    { id: "auth",     label: "Autenticación & SSO" },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center pb-4 border-b border-slate-700/30">
        <div>
          <h1 className="text-2xl font-bold text-white">Administración</h1>
          <p className="text-xs text-text-secondary mt-1">
            Usuarios, equipos, llaves virtuales, presupuestos y autenticación.
          </p>
        </div>
      </div>

      {error && (
        <div className="bg-danger/10 border border-danger/20 text-danger px-4 py-2.5 rounded-lg text-xs">
          {error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-slate-700/50 text-xs font-bold gap-6">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => { setActiveTab(t.id); if (t.id === "teams") fetchComplianceData(); }}
            className={`pb-2.5 border-b-2 transition-all ${
              activeTab === t.id ? "border-primary text-primary" : "border-transparent text-text-secondary hover:text-white"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Tab: Resumen ──────────────────────────────────────────────────── */}
      {activeTab === "overview" && (
        <div className="space-y-6">
          {/* KPI Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: "Usuarios activos", value: users.filter((u) => u.is_active).length, cls: "text-primary" },
              { label: "Llaves activas", value: keys.filter((k) => k.is_active).length, cls: "text-success" },
              { label: "Presupuestos", value: budgets.length, cls: "text-warning" },
              { label: "Gasto total acum.", value: `$${totalSpendUsd.toFixed(4)}`, cls: "text-white" },
            ].map((kpi) => (
              <div key={kpi.label} className="bg-panel border border-slate-700/40 rounded-lg p-4 space-y-1">
                <p className="text-[10px] text-text-secondary uppercase tracking-wider">{kpi.label}</p>
                <p className={`text-2xl font-bold font-mono ${kpi.cls}`}>{kpi.value}</p>
              </div>
            ))}
          </div>

          {/* Near-limit budgets */}
          {nearLimitBudgets.length > 0 && (
            <div className="bg-panel border border-warning/30 rounded-lg p-5 space-y-3">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-warning">
                Presupuestos cerca del límite (&ge;80%)
              </h2>
              <div className="space-y-3">
                {nearLimitBudgets.map((b) => {
                  const name = b.user_id
                    ? `Usuario: ${users.find((u) => u.id === b.user_id)?.username}`
                    : b.group_id
                    ? `Equipo: ${groups.find((g) => g.id === b.group_id)?.name}`
                    : "Global";
                  const pct = Math.min(100, (Number(b.current_spend_usd) / Number(b.max_spend_usd)) * 100);
                  return (
                    <div key={b.id} className="space-y-1 text-xs">
                      <div className="flex justify-between items-center">
                        <span className="text-white font-semibold">{name}</span>
                        <span className={`font-mono font-bold ${pct >= 100 ? "text-danger" : "text-warning"}`}>
                          {pct.toFixed(1)}% — ${Number(b.current_spend_usd).toFixed(4)} / ${Number(b.max_spend_usd).toFixed(4)}
                        </span>
                      </div>
                      <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${pct >= 100 ? "bg-danger" : "bg-warning"}`}
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {nearLimitBudgets.length === 0 && (
            <div className="bg-panel border border-slate-700/40 rounded-lg p-5 text-xs text-text-secondary text-center">
              Todos los presupuestos están dentro del límite.
            </div>
          )}

          {/* Quick stats table */}
          <div className="bg-panel border border-slate-700/40 rounded-lg p-5">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-text-secondary mb-4">Equipos</h2>
            {groups.length === 0 ? (
              <p className="text-xs text-text-secondary">No hay equipos.</p>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                {groups.map((g) => {
                  const count = users.filter((u) => u.group_id === g.id).length;
                  const budget = budgets.find((b) => b.group_id === g.id);
                  return (
                    <div key={g.id} className="border border-slate-700/40 rounded p-3 bg-background/15 text-xs space-y-1">
                      <p className="font-semibold text-white">{g.name}</p>
                      <p className="text-text-secondary">{count} miembro{count !== 1 ? "s" : ""}</p>
                      {budget ? (
                        <p className="font-mono text-success text-[11px]">
                          ${Number(budget.current_spend_usd).toFixed(4)} / ${Number(budget.max_spend_usd).toFixed(4)}
                        </p>
                      ) : (
                        <p className="text-slate-600 text-[11px]">Sin presupuesto</p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Tab: Usuarios & Equipos ───────────────────────────────────────── */}
      {activeTab === "teams" && (
        <div className="space-y-6">
          {complianceMsg && (
            <div className="bg-success/10 border border-success/20 text-success px-4 py-2.5 rounded-lg text-xs">{complianceMsg}</div>
          )}

          {/* Groups */}
          <div className="bg-panel border border-slate-700/40 rounded-lg p-5">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">Equipos de Trabajo</h2>
              <button
                onClick={() => setShowTeamModal(true)}
                className="bg-slate-800 hover:bg-slate-700 text-white font-medium px-3 py-1.5 rounded text-xs border border-slate-700 transition-colors"
              >
                Nuevo Equipo
              </button>
            </div>

            {groups.length === 0 ? (
              <p className="text-xs text-text-secondary">No hay equipos registrados.</p>
            ) : (
              <div className="border border-slate-700/30 rounded overflow-hidden">
                <table className="w-full text-left text-xs">
                  <thead className="bg-background/40 border-b border-slate-700/50 text-text-secondary">
                    <tr>
                      <th className="p-3">Equipo</th>
                      <th className="p-3">Miembros</th>
                      <th className="p-3">Base Legal</th>
                      <th className="p-3">Riesgo AI Act</th>
                      <th className="p-3">Proyecto Compliance</th>
                      <th className="p-3">Consumo</th>
                      <th className="p-3"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700/30 text-white">
                    {groups.map((g) => {
                      const membersCount = users.filter((u) => u.group_id === g.id).length;
                      const cg = complianceGroups.find((x: any) => x.id === g.id);
                      const risk = cg?.default_risk_level ? RISK_BADGE[cg.default_risk_level] : null;
                      const spend = groupSpend[g.id];
                      return (
                        <tr key={g.id} className="hover:bg-background/20 transition-colors">
                          <td className="p-3">
                            <p className="font-semibold">{g.name}</p>
                            <p className="text-[10px] text-text-secondary mt-0.5">{g.description || "—"}</p>
                          </td>
                          <td className="p-3 text-text-secondary">{membersCount}</td>
                          <td className="p-3 text-[11px] text-primary">
                            {cg?.default_legal_basis ? (LEGAL_BASIS_SHORT[cg.default_legal_basis] || cg.default_legal_basis) : <span className="text-slate-600">—</span>}
                          </td>
                          <td className="p-3">
                            {risk ? (
                              <span className={`text-[9px] font-mono font-semibold px-1.5 py-0.5 rounded border ${risk.cls}`}>{risk.label}</span>
                            ) : <span className="text-slate-600 text-[10px]">—</span>}
                          </td>
                          <td className="p-3 text-[11px] text-text-secondary">
                            {cg?.compliance_project_name || <span className="text-slate-600">—</span>}
                          </td>
                          <td className="p-3 font-mono text-[11px]">
                            {spend?.spend_usd != null ? (
                              <span className="text-success">${spend.spend_usd.toFixed(4)}</span>
                            ) : <span className="text-slate-600">—</span>}
                          </td>
                          <td className="p-3">
                            <button
                              onClick={() => openComplianceModal(cg ?? g)}
                              className="text-primary hover:underline text-xs font-semibold"
                            >
                              Editar perfil
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Users */}
          <div className="bg-panel border border-slate-700/40 rounded-lg p-5">
            <div className="flex justify-between items-center mb-4">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">Miembros / Usuarios</h2>
              <button
                onClick={() => setShowUserModal(true)}
                className="bg-slate-800 hover:bg-slate-700 text-white font-medium px-3 py-1.5 rounded text-xs border border-slate-700 transition-colors"
              >
                Registrar Miembro
              </button>
            </div>

            {users.length === 0 ? (
              <p className="text-xs text-text-secondary">No hay usuarios registrados.</p>
            ) : (
              <div className="border border-slate-700/30 rounded overflow-hidden">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="bg-background/40 border-b border-slate-700/50 text-xs text-text-secondary">
                      <th className="p-3">Usuario</th>
                      <th className="p-3">Email</th>
                      <th className="p-3">Rol</th>
                      <th className="p-3">Equipo</th>
                      <th className="p-3">Riesgo AI Act</th>
                      <th className="p-3"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700/30 text-xs text-white">
                    {users.map((u: any) => {
                      const groupName = groups.find((g) => g.id === u.group_id)?.name || "Sin Equipo";
                      const effectiveRisk = u.risk_level ||
                        complianceGroups.find((g: any) => g.id === u.group_id)?.default_risk_level;
                      const risk = effectiveRisk ? RISK_BADGE[effectiveRisk] : null;
                      return (
                        <tr key={u.id} className="hover:bg-background/20 transition-colors">
                          <td className="p-3 font-semibold">{u.username}</td>
                          <td className="p-3 text-text-secondary">{u.email}</td>
                          <td className="p-3 uppercase text-[10px] font-mono text-primary font-semibold">{u.role}</td>
                          <td className="p-3 text-text-secondary">{groupName}</td>
                          <td className="p-3">
                            {risk ? (
                              <span className={`text-[9px] font-mono font-semibold px-1.5 py-0.5 rounded border ${risk.cls}`}>
                                {risk.label}{u.risk_level ? "" : " ↑"}
                              </span>
                            ) : <span className="text-slate-600 text-[10px]">—</span>}
                          </td>
                          <td className="p-3">
                            <button
                              onClick={() => { setAssignGroupUser(u); setAssignGroupId(u.group_id || ""); }}
                              className="text-xs text-primary hover:underline font-semibold"
                            >
                              Asignar equipo
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Tab: Llaves Virtuales ─────────────────────────────────────────── */}
      {activeTab === "keys" && (
        <div className="bg-panel border border-slate-700/40 rounded-lg p-5">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
              Llaves Virtuales Activas (Bearer Tokens)
            </h2>
            <button
              onClick={() => setShowKeyModal(true)}
              className="bg-primary hover:bg-primary/95 text-background font-bold px-4 py-2 rounded text-xs transition-all"
            >
              Generar Llave Virtual
            </button>
          </div>

          {keys.length === 0 ? (
            <p className="text-xs text-text-secondary">No hay llaves virtuales activas.</p>
          ) : (
            <div className="border border-slate-700/30 rounded overflow-hidden">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-background/40 border-b border-slate-700/50 text-xs text-text-secondary">
                    <th className="p-3">Nombre / Identificador</th>
                    <th className="p-3">Asociado a</th>
                    <th className="p-3">Compliance</th>
                    <th className="p-3">Token Preview</th>
                    <th className="p-3">Límites RPM/TPM</th>
                    <th className="p-3">Consumo Real</th>
                    <th className="p-3">Fecha Creación</th>
                    <th className="p-3 text-right">Acciones</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/30 text-xs text-white">
                  {keys.map((k) => {
                    const owner = k.user_id
                      ? `Usuario: ${users.find((u) => u.id === k.user_id)?.username}`
                      : k.group_id
                      ? `Equipo: ${groups.find((g) => g.id === k.group_id)?.name}`
                      : "Global / Sin Asignar";
                    return (
                      <tr key={k.id} className="hover:bg-background/20 transition-colors">
                        <td className="p-3 font-semibold">{k.name}</td>
                        <td className="p-3">
                          <span className="px-2 py-0.5 rounded text-[10px] bg-slate-800 border border-slate-700/50 text-text-secondary">
                            {owner}
                          </span>
                        </td>
                        <td className="p-3 text-[10px]">
                          {(k as any).compliance_project_id
                            ? <span className="text-primary font-semibold">{complianceProjects.find((p: any) => p.id === (k as any).compliance_project_id)?.name || "Proyecto asignado"}</span>
                            : <span className="text-slate-600">Heredado</span>}
                        </td>
                        <td className="p-3 font-mono text-text-secondary text-[11px]">{k.key_preview}</td>
                        <td className="p-3 text-[10px]">
                          <span className="text-text-secondary">{(k as any).rpm_limit ?? 60} rpm</span>
                          <span className="text-slate-600 mx-1">/</span>
                          <span className="text-text-secondary">{((k as any).tpm_limit ?? 100000).toLocaleString()} tpm</span>
                        </td>
                        <td className="p-3 font-mono text-xs">
                          {(() => {
                            const s = keySpend[k.id];
                            if (!s || s.spend_usd == null) return <span className="text-slate-500">—</span>;
                            const pct = s.max_budget ? Math.min(100, (s.spend_usd / s.max_budget) * 100) : null;
                            return (
                              <span className={pct != null && pct > 90 ? "text-danger" : pct != null && pct > 70 ? "text-warning" : "text-success"}>
                                ${s.spend_usd.toFixed(4)}
                                {s.max_budget != null && <span className="text-slate-500"> / ${s.max_budget.toFixed(2)}</span>}
                              </span>
                            );
                          })()}
                        </td>
                        <td className="p-3 text-text-secondary">
                          {new Date(k.created_at).toLocaleDateString("es-AR", { day: "numeric", month: "short", year: "numeric" })}
                        </td>
                        <td className="p-3 text-right">
                          <button
                            onClick={() => handleRevokeKey(k.id)}
                            disabled={actionLoading}
                            className="text-danger hover:text-danger/80 font-semibold text-xs transition-all"
                          >
                            Revocar
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Tab: Presupuestos ────────────────────────────────────────────── */}
      {activeTab === "budgets" && (
        <div className="space-y-5">
          <div className="flex justify-between items-center">
            <div>
              <h2 className="text-sm font-semibold text-white">Límites de Consumo</h2>
              <p className="text-xs text-text-secondary mt-0.5">
                Presupuestos máximos en USD y tokens para usuarios y equipos. Doble capa activa: se verifican ambos (personal + equipo) simultáneamente.
              </p>
            </div>
            <button
              onClick={() => setShowBudgetModal(true)}
              className="bg-primary hover:bg-primary/95 text-background font-bold px-3 py-1.5 rounded text-xs transition-all"
            >
              Asignar Límite
            </button>
          </div>

          {budgets.length === 0 ? (
            <div className="bg-panel border border-slate-700/40 rounded-lg p-8 text-center text-xs text-text-secondary">
              No hay presupuestos configurados. Usa "Asignar Límite" para crear el primero.
            </div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {budgets.map((b) => {
                const isPersonal = !!b.user_id;
                const targetName = b.user_id
                  ? users.find((u) => u.id === b.user_id)?.username ?? "Usuario desconocido"
                  : b.group_id
                  ? groups.find((g) => g.id === b.group_id)?.name ?? "Equipo desconocido"
                  : "Global";
                const progressPercent = Math.min(100, (Number(b.current_spend_usd) / Number(b.max_spend_usd)) * 100);

                return (
                  <div key={b.id} className="bg-panel border border-slate-700/40 rounded-lg p-4 space-y-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2">
                          <span className={`text-[9px] font-mono font-bold px-1.5 py-0.5 rounded border ${isPersonal ? "text-primary border-primary/30 bg-primary/5" : "text-warning border-warning/30 bg-warning/5"}`}>
                            {isPersonal ? "Personal" : "Equipo"}
                          </span>
                        </div>
                        <p className="text-xs font-bold text-white mt-1">{targetName}</p>
                      </div>
                      <span className="text-[10px] font-mono text-text-secondary uppercase">{b.reset_period}</span>
                    </div>

                    {/* Spend */}
                    <div className="space-y-1.5">
                      <div className="flex justify-between text-xs font-mono">
                        <span className={progressPercent > 85 ? "text-danger font-bold" : progressPercent > 50 ? "text-warning" : "text-success"}>
                          ${Number(b.current_spend_usd).toFixed(4)}
                        </span>
                        <span className="text-text-secondary">${Number(b.max_spend_usd).toFixed(4)}</span>
                      </div>
                      <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                        <div
                          className={`h-full rounded-full transition-all ${progressPercent > 85 ? "bg-danger" : progressPercent > 50 ? "bg-warning" : "bg-primary"}`}
                          style={{ width: `${progressPercent}%` }}
                        />
                      </div>
                      <div className="text-[10px] text-text-secondary font-mono">
                        Tokens: {b.current_tokens.toLocaleString()} / {b.max_tokens.toLocaleString()}
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex gap-3 pt-1 border-t border-slate-700/40">
                      <button
                        onClick={() => { setEditingBudget(b); setEditBudgetUsd(String(b.max_spend_usd)); setEditBudgetTokens(String(b.max_tokens)); }}
                        className="text-xs text-primary hover:underline font-semibold"
                      >
                        Editar
                      </button>
                      <button
                        onClick={() => handleDeleteBudget(b.id)}
                        disabled={actionLoading}
                        className="text-xs text-danger hover:text-danger/80 font-semibold"
                      >
                        Eliminar
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── Tab: Autenticación & SSO ─────────────────────────────────────── */}
      {activeTab === "auth" && (
        <div className="space-y-6">
          <div className="bg-panel border border-slate-700/40 rounded-lg p-5">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary mb-1">
              Métodos de Autenticación Disponibles
            </h2>
            <p className="text-xs text-text-secondary mb-5">
              Métodos de login soportados por la plataforma. Los marcados como "Próximamente" están en roadmap
              y pueden activarse como feature adicional.
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {[
                {
                  name: "Azure AD / Microsoft Entra ID",
                  type: "OIDC / OAuth 2.0",
                  target: "Enterprise",
                  description: "Integración con el directorio corporativo de Microsoft. Ideal para hospitales y grandes organizaciones con licencias Microsoft 365.",
                  badge: "Próximamente",
                  badgeCls: "text-warning border-warning/30 bg-warning/5",
                  icon: "🔷",
                },
                {
                  name: "Google Workspace",
                  type: "OIDC / OAuth 2.0",
                  target: "SME / Clínicas",
                  description: "Login con cuentas Google corporativas. Recomendado para organizaciones medianas que usan Google Workspace.",
                  badge: "Próximamente",
                  badgeCls: "text-warning border-warning/30 bg-warning/5",
                  icon: "🔴",
                },
                {
                  name: "Okta",
                  type: "OIDC / SAML 2.0",
                  target: "Enterprise",
                  description: "Proveedor de identidad enterprise líder. Soporta MFA avanzado, políticas de acceso condicional y auditoría detallada.",
                  badge: "Próximamente",
                  badgeCls: "text-warning border-warning/30 bg-warning/5",
                  icon: "⚡",
                },
                {
                  name: "Auth0",
                  type: "OIDC / OAuth 2.0",
                  target: "Universal",
                  description: "Plataforma de identidad flexible. Soporta múltiples proveedores sociales y enterprise simultáneamente.",
                  badge: "Próximamente",
                  badgeCls: "text-warning border-warning/30 bg-warning/5",
                  icon: "🔐",
                },
                {
                  name: "Keycloak",
                  type: "OIDC / SAML 2.0",
                  target: "Self-hosted",
                  description: "Solución open source autohospedada para gestión de identidad. Sin dependencias externas, ideal para entornos de alta seguridad.",
                  badge: "Próximamente",
                  badgeCls: "text-warning border-warning/30 bg-warning/5",
                  icon: "🗝️",
                },
                {
                  name: "SAML 2.0 genérico",
                  type: "SAML 2.0",
                  target: "Enterprise heredado",
                  description: "Protocolo estándar para integración con sistemas legacy (AD FS, Shibboleth, PingFederate). Compatible con cualquier IdP SAML.",
                  badge: "Próximamente",
                  badgeCls: "text-warning border-warning/30 bg-warning/5",
                  icon: "🏛️",
                },
                {
                  name: "Usuario & Contraseña (JWT)",
                  type: "JWT HS256 / 24h TTL",
                  target: "Usuarios internos",
                  description: "Autenticación local integrada. Gestión de usuarios desde el panel de administración. Sin dependencias externas.",
                  badge: "Activo",
                  badgeCls: "text-success border-success/30 bg-success/5",
                  icon: "✓",
                },
              ].map((p) => (
                <div key={p.name} className="border border-slate-700/40 rounded-lg p-4 space-y-3 bg-background/10">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="text-lg">{p.icon}</span>
                      <span className="font-semibold text-white text-xs">{p.name}</span>
                    </div>
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold border flex-shrink-0 ${p.badgeCls}`}>
                      {p.badge}
                    </span>
                  </div>
                  <div className="flex gap-2 flex-wrap">
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-800 border border-slate-700 text-text-secondary">{p.type}</span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] bg-slate-800 border border-slate-700 text-text-secondary">{p.target}</span>
                  </div>
                  <p className="text-[11px] text-text-secondary leading-relaxed">{p.description}</p>
                </div>
              ))}
            </div>

            <div className="mt-5 p-3 rounded-lg bg-background/30 border border-slate-700/30 text-xs text-text-secondary">
              Para habilitar un proveedor SSO, contactá al equipo de Basa o abrí un ticket indicando el proveedor
              elegido y el dominio corporativo. La integración tarda típicamente 1–2 días de configuración.
            </div>
          </div>
        </div>
      )}

      {/* ── Compliance Profile Modal ─────────────────────────────────────── */}
      {showComplianceModal && editingGroup && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-panel border border-slate-700/50 rounded-xl w-full max-w-md p-6 space-y-4">
            <h2 className="text-sm font-bold text-white">Perfil de Compliance — {editingGroup.name}</h2>

            <div className="space-y-1">
              <label className="text-xs text-text-secondary">Base legal GDPR por defecto</label>
              <select
                value={complianceForm.default_legal_basis}
                onChange={e => setComplianceForm(f => ({ ...f, default_legal_basis: e.target.value }))}
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary"
              >
                <option value="">Sin configurar</option>
                <option value="art_9_2_h">Art. 9(2)(h) — Prestación sanitaria</option>
                <option value="art_9_2_j">Art. 9(2)(j) — Investigación / interés público</option>
                <option value="art_9_2_a">Art. 9(2)(a) — Consentimiento explícito</option>
                <option value="art_6_1_c">Art. 6(1)(c) — Obligación legal</option>
                <option value="art_6_1_e">Art. 6(1)(e) — Misión de interés público</option>
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-xs text-text-secondary">Nivel de riesgo AI Act</label>
              <select
                value={complianceForm.default_risk_level}
                onChange={e => setComplianceForm(f => ({ ...f, default_risk_level: e.target.value }))}
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary"
              >
                <option value="">Sin configurar</option>
                <option value="minimal">Riesgo Mínimo</option>
                <option value="limited">Riesgo Limitado</option>
                <option value="high_risk_annex3">Alto Riesgo — Annex III (farmacovigilancia / evaluación de personas)</option>
                <option value="high_risk_annex1">Alto Riesgo — Annex I (MDR, producto sanitario)</option>
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-xs text-text-secondary">Proyecto de compliance asignado</label>
              <select
                value={complianceForm.compliance_project_id}
                onChange={e => setComplianceForm(f => ({ ...f, compliance_project_id: e.target.value }))}
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary"
              >
                <option value="">Sin asignar (usa política global)</option>
                {complianceProjects.map((p: any) => (
                  <option key={p.id} value={p.id}>{p.name}{p.is_active ? "" : " (inactivo)"}</option>
                ))}
              </select>
              <p className="text-[10px] text-text-secondary mt-1">
                Si se asigna un proyecto, sus reglas se aplicarán a las llamadas de los miembros de este equipo.
              </p>
            </div>

            <div className="flex gap-2 justify-end pt-2">
              <button
                onClick={() => setShowComplianceModal(false)}
                className="px-4 py-2 text-xs text-text-secondary hover:text-white border border-slate-700 rounded-lg"
              >
                Cancelar
              </button>
              <button
                onClick={saveComplianceProfile}
                className="bg-primary text-background font-semibold px-4 py-2 rounded-lg text-xs"
              >
                Guardar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Key Creation Modal ───────────────────────────────────────────── */}
      {showKeyModal && (
        <div className="fixed inset-0 bg-background/85 backdrop-blur-sm flex justify-center items-center p-4 z-50">
          <div className="bg-panel border border-slate-700 rounded-xl max-w-md w-full p-6 space-y-4 text-white text-xs">
            <h3 className="text-sm font-bold uppercase tracking-wider">Generar Llave Virtual</h3>
            <form onSubmit={handleCreateKey} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-text-secondary font-medium">Nombre de la Llave</label>
                <input
                  type="text"
                  required
                  value={keyName}
                  onChange={(e) => setKeyName(e.target.value)}
                  placeholder="ej: cardiologia-produccion"
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <span className="text-[10px] text-text-secondary font-medium block">Equipo</span>
                  <select
                    value={keyGroupId}
                    onChange={(e) => { setKeyGroupId(e.target.value); if (e.target.value) setKeyUserId(""); }}
                    className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white"
                  >
                    <option value="">Seleccionar Equipo</option>
                    {groups.filter((g) => g.engine_team_id).map((g) => (
                      <option key={g.id} value={g.id}>{g.name}</option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1.5">
                  <span className="text-[10px] text-text-secondary font-medium block">O Usuario</span>
                  <select
                    value={keyUserId}
                    onChange={(e) => { setKeyUserId(e.target.value); if (e.target.value) setKeyGroupId(""); }}
                    className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white"
                  >
                    <option value="">Seleccionar Usuario</option>
                    {users.filter((u) => u.engine_user_id).map((u) => (
                      <option key={u.id} value={u.id}>{u.username}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-text-secondary font-medium">Presupuesto Máx. (USD)</label>
                  <input
                    type="number" step="0.01" min="0"
                    value={keyMaxBudget}
                    onChange={(e) => setKeyMaxBudget(e.target.value)}
                    placeholder="ej: 50.00"
                    className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-text-secondary font-medium">Período de Reinicio</label>
                  <select
                    value={keyBudgetDuration}
                    onChange={(e) => setKeyBudgetDuration(e.target.value)}
                    className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none"
                  >
                    <option value="1d">Diario</option>
                    <option value="7d">Semanal</option>
                    <option value="30d">Mensual</option>
                    <option value="365d">Anual</option>
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-text-secondary font-medium">Límite RPM <span className="text-slate-500">(solicitudes/min)</span></label>
                  <input
                    type="number" min="1" max="10000"
                    value={keyRpmLimit}
                    onChange={(e) => setKeyRpmLimit(e.target.value)}
                    className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none focus:border-primary text-xs"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-text-secondary font-medium">Límite TPM <span className="text-slate-500">(tokens/min)</span></label>
                  <input
                    type="number" min="1000" max="10000000"
                    value={keyTpmLimit}
                    onChange={(e) => setKeyTpmLimit(e.target.value)}
                    className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none focus:border-primary text-xs"
                  />
                </div>
              </div>
              <div className="space-y-1.5">
                <label className="text-text-secondary font-medium">Proyecto de compliance (Opcional)</label>
                <select
                  value={keyComplianceProjectId}
                  onChange={(e) => setKeyComplianceProjectId(e.target.value)}
                  className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white"
                >
                  <option value="">Sin asignar (hereda del usuario/equipo)</option>
                  {complianceProjects.map((p: any) => (
                    <option key={p.id} value={p.id}>{p.name}{p.is_active ? "" : " (inactivo)"}</option>
                  ))}
                </select>
              </div>
              <div className="flex justify-end gap-3 pt-4 border-t border-slate-700/50">
                <button type="button" onClick={() => setShowKeyModal(false)} className="px-4 py-2 rounded bg-slate-800 hover:bg-slate-700 text-white">Cancelar</button>
                <button type="submit" disabled={actionLoading} className="px-4 py-2 rounded bg-primary hover:bg-primary/95 text-background font-bold transition-all">
                  {actionLoading ? "Generando..." : "Generar"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Generated Key Modal ──────────────────────────────────────────── */}
      {generatedKey && (
        <div className="fixed inset-0 bg-background/90 backdrop-blur-sm flex justify-center items-center p-4 z-50">
          <div className="bg-panel border border-slate-700 rounded-xl max-w-lg w-full p-6 space-y-4 text-white text-xs shadow-2xl">
            <h3 className="text-sm font-bold uppercase tracking-wider text-success">¡Llave Virtual Generada!</h3>
            <p className="text-text-secondary">Copie la clave ahora. Por motivos de seguridad, no se volverá a mostrar.</p>
            <div className="bg-background border border-slate-700/60 rounded p-4 flex justify-between items-center gap-4">
              <code className="text-[11px] font-mono text-success break-all select-all pr-2">{generatedKey}</code>
              <button
                onClick={handleCopyKey}
                className="shrink-0 bg-success/10 hover:bg-success/20 text-success border border-success/20 px-3 py-1.5 rounded font-semibold text-xs transition-all"
              >
                {copied ? "Copiado" : "Copiar"}
              </button>
            </div>
            <div className="bg-warning/5 border border-warning/20 text-warning rounded p-3.5 text-[11px]">
              Guarde esta credencial de forma segura. Cualquier persona con esta clave puede realizar consultas en la pasarela en nombre de los límites asignados.
            </div>
            <div className="flex justify-end pt-2">
              <button
                onClick={() => setGeneratedKey(null)}
                className="bg-success hover:bg-success/95 text-background font-bold px-5 py-2 rounded text-xs transition-all"
              >
                Entendido
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Team Creation Modal ──────────────────────────────────────────── */}
      {showTeamModal && (
        <div className="fixed inset-0 bg-background/85 backdrop-blur-sm flex justify-center items-center p-4 z-50">
          <div className="bg-panel border border-slate-700 rounded-xl max-w-md w-full p-6 space-y-4 text-white text-xs">
            <h3 className="text-sm font-bold uppercase tracking-wider">Crear Nuevo Equipo</h3>
            <form onSubmit={handleCreateTeam} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-text-secondary font-medium">Nombre del Equipo</label>
                <input
                  type="text" required
                  value={teamName}
                  onChange={(e) => setTeamName(e.target.value)}
                  placeholder="ej: Cardiología"
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-text-secondary font-medium">Descripción</label>
                <textarea
                  value={teamDesc}
                  onChange={(e) => setTeamDesc(e.target.value)}
                  placeholder="ej: Especialistas del departamento cardíaco del hospital."
                  rows={3}
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary resize-none"
                />
              </div>
              <div className="flex justify-end gap-3 pt-4 border-t border-slate-700/50">
                <button type="button" onClick={() => setShowTeamModal(false)} className="px-4 py-2 rounded bg-slate-800 hover:bg-slate-700 text-white">Cancelar</button>
                <button type="submit" disabled={actionLoading} className="px-4 py-2 rounded bg-primary hover:bg-primary/95 text-background font-bold transition-all">
                  {actionLoading ? "Creando..." : "Crear"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── User Creation Modal ──────────────────────────────────────────── */}
      {showUserModal && (
        <div className="fixed inset-0 bg-background/85 backdrop-blur-sm flex justify-center items-center p-4 z-50">
          <div className="bg-panel border border-slate-700 rounded-xl max-w-md w-full p-6 space-y-4 text-white text-xs">
            <h3 className="text-sm font-bold uppercase tracking-wider">Registrar Miembro</h3>
            <form onSubmit={handleCreateUser} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-text-secondary font-medium">Nombre de Usuario</label>
                <input
                  type="text" required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="ej: dr_perez"
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-text-secondary font-medium">Email</label>
                <input
                  type="email" required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="ej: perez@basa.com.ar"
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-text-secondary font-medium">Rol</label>
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none"
                >
                  <option value="clinician">Especialista</option>
                  <option value="researcher">Investigador</option>
                  <option value="developer">Desarrollador</option>
                  <option value="admin">Administrador</option>
                </select>
              </div>
              <div className="space-y-1.5">
                <label className="text-text-secondary font-medium">Asociar a Equipo (Opcional)</label>
                <select
                  value={groupId}
                  onChange={(e) => setGroupId(e.target.value)}
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none"
                >
                  <option value="">Ninguno / Sin Equipo</option>
                  {groups.map((g) => (
                    <option key={g.id} value={g.id}>{g.name}</option>
                  ))}
                </select>
              </div>

              <div className="border-t border-slate-700/40 pt-3 space-y-3">
                <p className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold">Perfil de compliance individual (sobreescribe el del equipo)</p>
                <div className="space-y-1.5">
                  <label className="text-text-secondary font-medium">Base legal GDPR</label>
                  <select
                    value={userLegalBasis}
                    onChange={(e) => setUserLegalBasis(e.target.value)}
                    className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none"
                  >
                    <option value="">Heredar del equipo</option>
                    <option value="art_9_2_h">Art. 9(2)(h) — Prestación sanitaria</option>
                    <option value="art_9_2_j">Art. 9(2)(j) — Investigación</option>
                    <option value="art_9_2_a">Art. 9(2)(a) — Consentimiento explícito</option>
                    <option value="art_6_1_c">Art. 6(1)(c) — Obligación legal</option>
                    <option value="art_6_1_e">Art. 6(1)(e) — Interés público</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-text-secondary font-medium">Nivel de riesgo AI Act</label>
                  <select
                    value={userRiskLevel}
                    onChange={(e) => setUserRiskLevel(e.target.value)}
                    className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none"
                  >
                    <option value="">Heredar del equipo</option>
                    <option value="minimal">Riesgo Mínimo</option>
                    <option value="limited">Riesgo Limitado</option>
                    <option value="high_risk_annex3">Alto Riesgo — Annex III</option>
                    <option value="high_risk_annex1">Alto Riesgo — MDR</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-text-secondary font-medium">Proyecto de compliance</label>
                  <select
                    value={userComplianceProjectId}
                    onChange={(e) => setUserComplianceProjectId(e.target.value)}
                    className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none"
                  >
                    <option value="">Heredar del equipo</option>
                    {complianceProjects.map((p: any) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-slate-700/50">
                <button type="button" onClick={() => setShowUserModal(false)} className="px-4 py-2 rounded bg-slate-800 hover:bg-slate-700 text-white">Cancelar</button>
                <button type="submit" disabled={actionLoading} className="px-4 py-2 rounded bg-primary hover:bg-primary/95 text-background font-bold transition-all">
                  {actionLoading ? "Registrando..." : "Registrar"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Budget Assignment Modal ──────────────────────────────────────── */}
      {showBudgetModal && (
        <div className="fixed inset-0 bg-background/85 backdrop-blur-sm flex justify-center items-center p-4 z-50">
          <div className="bg-panel border border-slate-700 rounded-xl max-w-md w-full p-6 space-y-4 text-white text-xs">
            <h3 className="text-sm font-bold uppercase tracking-wider">Asignar Límite / Presupuesto</h3>
            <form onSubmit={handleCreateBudget} className="space-y-4">
              <div className="space-y-3">
                <span className="text-text-secondary font-medium block">Asignar a</span>
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <span className="text-[10px] text-text-secondary">Equipo</span>
                    <select
                      value={budgetGroupId}
                      onChange={(e) => { setBudgetGroupId(e.target.value); if (e.target.value) setBudgetUserId(""); }}
                      className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white"
                    >
                      <option value="">Seleccionar Equipo</option>
                      {groups.map((g) => (
                        <option key={g.id} value={g.id}>{g.name}</option>
                      ))}
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <span className="text-[10px] text-text-secondary">O Usuario Individual</span>
                    <select
                      value={budgetUserId}
                      onChange={(e) => { setBudgetUserId(e.target.value); if (e.target.value) setBudgetGroupId(""); }}
                      className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white"
                    >
                      <option value="">Seleccionar Usuario</option>
                      {users.map((u) => (
                        <option key={u.id} value={u.id}>{u.username}</option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-text-secondary font-medium">Límite Máximo (USD)</label>
                  <input
                    type="number" step="0.01" required
                    value={maxSpend}
                    onChange={(e) => setMaxSpend(e.target.value)}
                    className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-text-secondary font-medium">Límite Máximo (Tokens)</label>
                  <input
                    type="number" required
                    value={maxTokens}
                    onChange={(e) => setMaxTokens(e.target.value)}
                    className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="text-text-secondary font-medium">Período de Reinicio</label>
                <select
                  value={resetPeriod}
                  onChange={(e) => setResetPeriod(e.target.value)}
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white"
                >
                  <option value="daily">Diario</option>
                  <option value="weekly">Semanal</option>
                  <option value="monthly">Mensual</option>
                  <option value="yearly">Anual</option>
                </select>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-slate-700/50">
                <button type="button" onClick={() => setShowBudgetModal(false)} className="px-4 py-2 rounded bg-slate-800 hover:bg-slate-700 text-white">Cancelar</button>
                <button type="submit" disabled={actionLoading} className="px-4 py-2 rounded bg-primary hover:bg-primary/95 text-background font-bold transition-all">
                  {actionLoading ? "Asignando..." : "Asignar"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── Edit Budget Modal ────────────────────────────────────────────── */}
      {editingBudget && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-panel border border-slate-700/50 rounded-xl w-full max-w-sm p-6 space-y-4">
            <h2 className="text-sm font-bold text-white">Editar presupuesto</h2>
            <div className="space-y-3">
              <div className="space-y-1">
                <label className="text-xs text-text-secondary">Límite USD</label>
                <input
                  type="number" step="0.001"
                  value={editBudgetUsd}
                  onChange={e => setEditBudgetUsd(e.target.value)}
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary"
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-text-secondary">Límite Tokens</label>
                <input
                  type="number"
                  value={editBudgetTokens}
                  onChange={e => setEditBudgetTokens(e.target.value)}
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary"
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <button onClick={() => setEditingBudget(null)} className="px-4 py-2 rounded border border-slate-700 text-xs text-text-secondary hover:text-white transition-colors">Cancelar</button>
              <button onClick={handleUpdateBudget} className="px-4 py-2 rounded bg-primary hover:bg-primary/95 text-background text-xs font-bold transition-all">Guardar</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Assign Group Modal ───────────────────────────────────────────── */}
      {assignGroupUser && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-panel border border-slate-700/50 rounded-xl w-full max-w-sm p-6 space-y-4">
            <h2 className="text-sm font-bold text-white">Asignar equipo — {assignGroupUser.username}</h2>
            <div className="space-y-1">
              <label className="text-xs text-text-secondary">Equipo</label>
              <select
                value={assignGroupId}
                onChange={e => setAssignGroupId(e.target.value)}
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary"
              >
                <option value="">Sin equipo</option>
                {groups.map((g: any) => (
                  <option key={g.id} value={g.id}>{g.name}</option>
                ))}
              </select>
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <button onClick={() => setAssignGroupUser(null)} className="px-4 py-2 rounded border border-slate-700 text-xs text-text-secondary hover:text-white transition-colors">Cancelar</button>
              <button onClick={handleAssignGroup} className="px-4 py-2 rounded bg-primary hover:bg-primary/95 text-background text-xs font-bold transition-all">Guardar</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
