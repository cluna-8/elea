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

export const UsersPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<"teams" | "keys" | "compliance">("teams");
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

      // Fetch real spend for groups and keys that have engine IDs
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
      setUsername("");
      setEmail("");
      setGroupId("");
      setUserLegalBasis("");
      setUserRiskLevel("");
      setUserComplianceProjectId("");
      await fetchData();
    } catch (err) {
      alert("Error al crear el usuario.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleCreateTeam = async (e: React.FormEvent) => {
    e.preventDefault();
    setActionLoading(true);
    try {
      await api.createGroup({
        name: teamName,
        description: teamDesc,
      });
      setShowTeamModal(false);
      setTeamName("");
      setTeamDesc("");
      await fetchData();
    } catch (err) {
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
      setKeyName("");
      setKeyUserId("");
      setKeyGroupId("");
      setKeyMaxBudget("");
      setKeyBudgetDuration("30d");
      setKeyComplianceProjectId("");
      setKeyRpmLimit("60");
      setKeyTpmLimit("100000");
      await fetchData();
    } catch (err) {
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
      setBudgetUserId("");
      setBudgetGroupId("");
      setMaxSpend("100.00");
      setMaxTokens("1000000");
      await fetchData();
    } catch (err) {
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
    } catch (err) {
      alert("Error al revocar la llave.");
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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center pb-4 border-b border-slate-700/30">
        <div>
          <h1 className="text-2xl font-bold text-white">Usuarios, Equipos & Presupuestos</h1>
          <p className="text-xs text-text-secondary mt-1">
            Administre las llaves de acceso virtuales, asigne presupuestos límites de consumo y registre usuarios.
          </p>
        </div>
      </div>

      {error && (
        <div className="bg-danger/10 border border-danger/20 text-danger px-4 py-2.5 rounded-lg text-xs">
          <span>{error}</span>
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-slate-700/50 text-xs font-bold gap-6">
        <button
          onClick={() => setActiveTab("teams")}
          className={`pb-2.5 border-b-2 transition-all ${
            activeTab === "teams" ? "border-primary text-primary" : "border-transparent text-text-secondary hover:text-white"
          }`}
        >
          Equipos, Miembros & Presupuestos
        </button>
        <button
          onClick={() => setActiveTab("keys")}
          className={`pb-2.5 border-b-2 transition-all ${
            activeTab === "keys" ? "border-primary text-primary" : "border-transparent text-text-secondary hover:text-white"
          }`}
        >
          Llaves Virtuales (Virtual Keys)
        </button>
        <button
          onClick={() => { setActiveTab("compliance"); fetchComplianceData(); }}
          className={`pb-2.5 border-b-2 transition-all ${
            activeTab === "compliance" ? "border-primary text-primary" : "border-transparent text-text-secondary hover:text-white"
          }`}
        >
          Perfiles de Compliance
        </button>
      </div>

      {activeTab === "teams" ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left 2 cols: Groups & Budgets */}
          <div className="lg:col-span-2 space-y-6">
            {/* Groups */}
            <div className="bg-panel border border-slate-700/40 rounded-lg p-5">
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
                  Equipos de Trabajo
                </h2>
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
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {groups.map((g) => {
                    const membersCount = users.filter((u) => u.group_id === g.id).length;
                    const spend = groupSpend[g.id];
                    const spendPercent = spend?.spend_usd != null && spend?.max_budget
                      ? Math.min(100, (spend.spend_usd / spend.max_budget) * 100)
                      : null;

                    return (
                      <div key={g.id} className="border border-slate-700/40 bg-background/15 rounded p-4 space-y-3">
                        <div>
                          <div className="flex items-start justify-between gap-2">
                            <h3 className="text-xs font-bold text-white">{g.name}</h3>
                            {(() => {
                              const cg = complianceGroups.find((x: any) => x.id === g.id);
                              const risk = cg?.default_risk_level ? RISK_BADGE[cg.default_risk_level] : null;
                              return risk ? (
                                <span className={`text-[9px] font-mono font-semibold px-1.5 py-0.5 rounded border shrink-0 ${risk.cls}`}>{risk.label}</span>
                              ) : null;
                            })()}
                          </div>
                          <p className="text-[11px] text-text-secondary mt-0.5">{g.description || "Sin descripción."}</p>
                          {(() => {
                            const cg = complianceGroups.find((x: any) => x.id === g.id);
                            return cg?.default_legal_basis ? (
                              <p className="text-[10px] text-primary mt-1">{LEGAL_BASIS_SHORT[cg.default_legal_basis] || cg.default_legal_basis}</p>
                            ) : null;
                          })()}
                        </div>
                        <div className="text-[11px] text-text-secondary space-y-2">
                          <div>Miembros activos: <span className="text-white font-semibold">{membersCount}</span></div>
                          <div>
                            Consumo real:{" "}
                            {spend?.spend_usd != null ? (
                              <span className={`font-bold font-mono ${spendPercent! > 90 ? "text-danger" : spendPercent! > 70 ? "text-warning" : "text-success"}`}>
                                ${spend.spend_usd.toFixed(4)}
                                {spend.max_budget != null && ` / $${spend.max_budget.toFixed(2)}`}
                              </span>
                            ) : (
                              <span className="text-slate-500 font-mono">
                                {g.engine_team_id ? "Cargando..." : "Sin presupuesto activo"}
                              </span>
                            )}
                          </div>
                          {spendPercent != null && (
                            <div className="w-full bg-slate-800 rounded-full h-1 overflow-hidden">
                              <div
                                className={`h-full rounded-full transition-all ${spendPercent > 90 ? "bg-danger" : spendPercent > 70 ? "bg-warning" : "bg-primary"}`}
                                style={{ width: `${spendPercent}%` }}
                              />
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Users */}
            <div className="bg-panel border border-slate-700/40 rounded-lg p-5">
              <div className="flex justify-between items-center mb-4">
                <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
                  Miembros / Usuarios
                </h2>
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
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>

          {/* Right col: Budgets Config */}
          <div className="bg-panel border border-slate-700/40 rounded-lg p-5 h-fit space-y-4">
            <div className="flex justify-between items-center">
              <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
                Límites de Consumo
              </h2>
              <button
                onClick={() => setShowBudgetModal(true)}
                className="bg-primary hover:bg-primary/95 text-background font-bold px-3 py-1.5 rounded text-xs transition-all"
              >
                Asignar Límite
              </button>
            </div>
            
            <p className="text-xs text-text-secondary leading-relaxed">
              Asigne presupuestos máximos en USD y límites de tokens para usuarios individuales o equipos completos.
            </p>

            <div className="space-y-3">
              {budgets.map((b) => {
                const targetName = b.user_id
                  ? `Usuario: ${users.find((u) => u.id === b.user_id)?.username}`
                  : b.group_id
                  ? `Equipo: ${groups.find((g) => g.id === b.group_id)?.name}`
                  : "Global";

                const progressPercent = Math.min(100, (Number(b.current_spend_usd) / Number(b.max_spend_usd)) * 100);

                return (
                  <div key={b.id} className="border border-slate-700/40 rounded p-3.5 bg-background/10 space-y-2 text-xs">
                    <div className="flex justify-between items-center font-semibold">
                      <span className="text-white truncate">{targetName}</span>
                      <span className="font-mono text-success">${Number(b.current_spend_usd).toFixed(2)} / ${Number(b.max_spend_usd).toFixed(2)}</span>
                    </div>
                    
                    {/* Progress Bar */}
                    <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${
                          progressPercent > 85 ? "bg-danger" : progressPercent > 50 ? "bg-warning" : "bg-primary"
                        }`}
                        style={{ width: `${progressPercent}%` }}
                      />
                    </div>

                    <div className="flex justify-between text-[10px] text-text-secondary font-mono">
                      <span>Tokens: {b.current_tokens} / {b.max_tokens}</span>
                      <span className="uppercase">{b.reset_period}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      ) : (
        /* Virtual Keys Tab */
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
                          {new Date(k.created_at).toLocaleDateString("es-AR", {
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                          })}
                        </td>
                        <td className="p-3 text-right">
                          <button
                            onClick={() => handleRevokeKey(k.id)}
                            disabled={actionLoading}
                            className="text-danger hover:text-danger/80 font-semibold text-xs transition-all"
                            title="Revocar Llave"
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

      {/* ── Compliance Tab ──────────────────────────────────────────────── */}
      {activeTab === "compliance" && (
        <div className="space-y-4">
          {complianceMsg && (
            <div className="bg-success/10 border border-success/20 text-success px-4 py-2.5 rounded-lg text-xs">{complianceMsg}</div>
          )}

          <div className="flex justify-between items-center">
            <div>
              <h2 className="text-sm font-semibold text-white">Perfiles de Compliance por Equipo</h2>
              <p className="text-xs text-text-secondary mt-0.5">Asigna base legal GDPR, nivel de riesgo AI Act y proyecto de compliance a cada equipo.</p>
            </div>
          </div>

          {complianceGroups.length === 0 ? (
            <div className="bg-panel border border-slate-700/40 rounded-lg p-8 text-center text-xs text-text-secondary">
              No hay equipos creados. Crea equipos en la pestaña "Equipos, Miembros & Presupuestos".
            </div>
          ) : (
            <div className="bg-panel border border-slate-700/40 rounded-lg overflow-hidden">
              <table className="w-full text-xs text-left">
                <thead className="bg-background/40 border-b border-slate-700/50 text-text-secondary uppercase tracking-wider">
                  <tr>
                    <th className="px-4 py-3">Equipo</th>
                    <th className="px-4 py-3">Base Legal GDPR</th>
                    <th className="px-4 py-3">Nivel Riesgo AI Act</th>
                    <th className="px-4 py-3">Proyecto Compliance</th>
                    <th className="px-4 py-3">Miembros</th>
                    <th className="px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/30 text-white">
                  {complianceGroups.map((g: any) => {
                    const risk = g.default_risk_level ? RISK_BADGE[g.default_risk_level] : null;
                    return (
                      <tr key={g.id} className="hover:bg-background/20">
                        <td className="px-4 py-3">
                          <p className="font-semibold">{g.name}</p>
                          <p className="text-[10px] text-text-secondary mt-0.5">{g.description || "—"}</p>
                        </td>
                        <td className="px-4 py-3 text-primary text-[11px]">
                          {g.default_legal_basis ? (LEGAL_BASIS_SHORT[g.default_legal_basis] || g.default_legal_basis) : <span className="text-slate-600">Sin configurar</span>}
                        </td>
                        <td className="px-4 py-3">
                          {risk ? (
                            <span className={`text-[10px] font-mono font-semibold px-2 py-0.5 rounded border ${risk.cls}`}>{risk.label}</span>
                          ) : <span className="text-slate-600 text-[10px]">Sin configurar</span>}
                        </td>
                        <td className="px-4 py-3 text-[11px] text-text-secondary">
                          {g.compliance_project_name || <span className="text-slate-600">Sin asignar</span>}
                        </td>
                        <td className="px-4 py-3 text-text-secondary">{g.user_count}</td>
                        <td className="px-4 py-3">
                          <button
                            onClick={() => openComplianceModal(g)}
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

          {/* Info box */}
          <div className="bg-primary/5 border border-primary/20 rounded-lg p-3 text-xs text-primary">
            <strong>¿Para qué sirve esto?</strong> Cada equipo puede tener una base legal GDPR y nivel de riesgo AI Act diferente.
            Cuando un usuario de ese equipo haga una llamada al chat, el sistema aplicará automáticamente el proyecto de compliance asignado — con sus reglas de notificación IA, revisión humana y región EU.
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
                <option value="high_risk_annex3">Alto Riesgo — Annex III (diagnóstico clínico)</option>
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
                Si se asigna un proyecto, sus reglas (notificación IA, región EU, revisión humana) se aplicarán a las llamadas de los miembros de este equipo.
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

      {/* Key Creation Modal */}
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
                    type="number"
                    step="0.01"
                    min="0"
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
                <p className="text-[10px] text-text-secondary">Si se asigna, esta llave usará las reglas de ese proyecto independientemente del usuario o equipo.</p>
              </div>
              <div className="flex justify-end gap-3 pt-4 border-t border-slate-700/50">
                <button type="button" onClick={() => setShowKeyModal(false)} className="px-4 py-2 rounded bg-slate-800 hover:bg-slate-700 text-white">
                  Cancelar
                </button>
                <button type="submit" disabled={actionLoading} className="px-4 py-2 rounded bg-primary hover:bg-primary/95 text-background font-bold transition-all">
                  {actionLoading ? "Generando..." : "Generar"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Generated Key Modal */}
      {generatedKey && (
        <div className="fixed inset-0 bg-background/90 backdrop-blur-sm flex justify-center items-center p-4 z-50">
          <div className="bg-panel border border-slate-700 rounded-xl max-w-lg w-full p-6 space-y-4 text-white text-xs shadow-2xl relative">
            <h3 className="text-sm font-bold uppercase tracking-wider text-success">¡Llave Virtual Generada!</h3>
            <p className="text-text-secondary">Copie la clave ahora. Por motivos de seguridad, no se volverá a mostrar.</p>

            <div className="bg-background border border-slate-700/60 rounded p-4 flex justify-between items-center gap-4">
              <code className="text-[11px] font-mono text-success break-all select-all pr-2">
                {generatedKey}
              </code>
              <button
                onClick={handleCopyKey}
                className="shrink-0 bg-success/10 hover:bg-success/20 text-success border border-success/20 px-3 py-1.5 rounded font-semibold text-xs transition-all"
              >
                {copied ? "Copiado" : "Copiar"}
              </button>
            </div>

            <div className="bg-warning/5 border border-warning/20 text-warning rounded p-3.5 text-[11px]">
              <p>
                Guarde esta credencial de forma segura. Cualquier persona con esta clave puede realizar consultas en la pasarela en nombre de los límites asignados.
              </p>
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

      {/* Team Creation Modal */}
      {showTeamModal && (
        <div className="fixed inset-0 bg-background/85 backdrop-blur-sm flex justify-center items-center p-4 z-50">
          <div className="bg-panel border border-slate-700 rounded-xl max-w-md w-full p-6 space-y-4 text-white text-xs">
            <h3 className="text-sm font-bold uppercase tracking-wider">Crear Nuevo Equipo</h3>
            <form onSubmit={handleCreateTeam} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-text-secondary font-medium">Nombre del Equipo</label>
                <input
                  type="text"
                  required
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
              <div className="flex justify-end gap-3 pt-4 border-t border-slate-750">
                <button
                  type="button"
                  onClick={() => setShowTeamModal(false)}
                  className="px-4 py-2 rounded bg-slate-850 hover:bg-slate-800 text-white"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-4 py-2 rounded bg-primary hover:bg-primary/95 text-background font-bold transition-all"
                >
                  {actionLoading ? "Creando..." : "Crear"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* User Creation Modal */}
      {showUserModal && (
        <div className="fixed inset-0 bg-background/85 backdrop-blur-sm flex justify-center items-center p-4 z-50">
          <div className="bg-panel border border-slate-700 rounded-xl max-w-md w-full p-6 space-y-4 text-white text-xs">
            <h3 className="text-sm font-bold uppercase tracking-wider">Registrar Miembro</h3>
            <form onSubmit={handleCreateUser} className="space-y-4">
              <div className="space-y-1.5">
                <label className="text-text-secondary font-medium">Nombre de Usuario</label>
                <input
                  type="text"
                  required
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  placeholder="ej: dr_perez"
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none"
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-text-secondary font-medium">Email</label>
                <input
                  type="email"
                  required
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
                  <option value="clinician">Clínico / Médico</option>
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
                    <option key={g.id} value={g.id}>
                      {g.name}
                    </option>
                  ))}
                </select>
              </div>

              {/* Compliance override */}
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

              <div className="flex justify-end gap-3 pt-4 border-t border-slate-750">
                <button
                  type="button"
                  onClick={() => setShowUserModal(false)}
                  className="px-4 py-2 rounded bg-slate-850 hover:bg-slate-800 text-white"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-4 py-2 rounded bg-primary hover:bg-primary/95 text-background font-bold transition-all"
                >
                  {actionLoading ? "Registrando..." : "Registrar"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Budget Assignment Modal */}
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
                      onChange={(e) => {
                        setBudgetGroupId(e.target.value);
                        if (e.target.value) setBudgetUserId("");
                      }}
                      className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white"
                    >
                      <option value="">Seleccionar Equipo</option>
                      {groups.map((g) => (
                        <option key={g.id} value={g.id}>
                          {g.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <span className="text-[10px] text-text-secondary">O Usuario Individual</span>
                    <select
                      value={budgetUserId}
                      onChange={(e) => {
                        setBudgetUserId(e.target.value);
                        if (e.target.value) setBudgetGroupId("");
                      }}
                      className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white"
                    >
                      <option value="">Seleccionar Usuario</option>
                      {users.map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.username}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-text-secondary font-medium">Límite Máximo (USD)</label>
                  <input
                    type="number"
                    step="0.01"
                    required
                    value={maxSpend}
                    onChange={(e) => setMaxSpend(e.target.value)}
                    className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-text-secondary font-medium">Límite Máximo (Tokens)</label>
                  <input
                    type="number"
                    required
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

              <div className="flex justify-end gap-3 pt-4 border-t border-slate-750">
                <button
                  type="button"
                  onClick={() => setShowBudgetModal(false)}
                  className="px-4 py-2 rounded bg-slate-850 hover:bg-slate-800 text-white"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={actionLoading}
                  className="px-4 py-2 rounded bg-primary hover:bg-primary/95 text-background font-bold transition-all"
                >
                  {actionLoading ? "Asignando..." : "Asignar"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
export default UsersPage;
