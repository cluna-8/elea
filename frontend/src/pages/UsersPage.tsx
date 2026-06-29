import React, { useState, useEffect } from "react";
import { api, User, Budget, Group, SpendInfo } from "../services/api";

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
  const [activeTab, setActiveTab] = useState<"teams" | "keys">("teams");
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

  const [keyName, setKeyName] = useState("");
  const [keyUserId, setKeyUserId] = useState("");
  const [keyGroupId, setKeyGroupId] = useState("");
  const [keyMaxBudget, setKeyMaxBudget] = useState("");
  const [keyBudgetDuration, setKeyBudgetDuration] = useState("30d");

  const [budgetUserId, setBudgetUserId] = useState("");
  const [budgetGroupId, setBudgetGroupId] = useState("");
  const [maxSpend, setMaxSpend] = useState("100.00");
  const [maxTokens, setMaxTokens] = useState("1000000");
  const [resetPeriod, setResetPeriod] = useState("monthly");

  const [copied, setCopied] = useState(false);

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
      });
      setShowUserModal(false);
      setUsername("");
      setEmail("");
      setGroupId("");
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

      const res = await api.createKey(payload);
      setGeneratedKey(res.plain_key);
      setShowKeyModal(false);
      setKeyName("");
      setKeyUserId("");
      setKeyGroupId("");
      setKeyMaxBudget("");
      setKeyBudgetDuration("30d");
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
                          <h3 className="text-xs font-bold text-white">{g.name}</h3>
                          <p className="text-[11px] text-text-secondary mt-0.5">{g.description || "Sin descripción."}</p>
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
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-700/30 text-xs text-white">
                      {users.map((u) => {
                        const groupName = groups.find((g) => g.id === u.group_id)?.name || "Sin Equipo";
                        return (
                          <tr key={u.id} className="hover:bg-background/20 transition-colors">
                            <td className="p-3 font-semibold">{u.username}</td>
                            <td className="p-3 text-text-secondary">{u.email}</td>
                            <td className="p-3 uppercase text-[10px] font-mono text-primary font-semibold">{u.role}</td>
                            <td className="p-3 text-text-secondary">{groupName}</td>
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
                    <th className="p-3">Token Preview</th>
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
                        <td className="p-3 font-mono text-text-secondary text-[11px]">{k.key_preview}</td>
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
