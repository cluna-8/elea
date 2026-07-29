import React, { useState, useEffect } from "react";
import {
  api,
  User,
  Budget,
  Group,
  SpendInfo,
  MIN_PASSWORD_LEN,
  validarPassword,
  GOVERNANCE_SURFACES,
} from "../services/api";
import {
  Card,
  PageHeader,
  StatusBadge,
  Button,
  Table,
  Field,
  PasswordField,
  inputBaseClass,
  cn,
} from "../components/ui";
import type { BadgeTone } from "../components/ui";

const LEGAL_BASIS_SHORT: Record<string, string> = {
  art_9_2_h: "Art. 9(2)(h) Sanitario",
  art_9_2_j: "Art. 9(2)(j) Investigación",
  art_9_2_a: "Art. 9(2)(a) Consentimiento",
  art_6_1_c: "Art. 6(1)(c) Obligación legal",
  art_6_1_e: "Art. 6(1)(e) Interés público",
};

const RISK_BADGE: Record<string, { label: string; tone: BadgeTone }> = {
  minimal:           { label: "Mínimo",          tone: "neutral" },
  limited:           { label: "Limitado",         tone: "info" },
  high_risk_annex3:  { label: "Alto (Annex III)", tone: "warn" },
  high_risk_annex1:  { label: "Alto (MDR)",       tone: "danger" },
};

// Overlay compartido de modales (tema claro Foundry).
const ModalShell: React.FC<{
  title: React.ReactNode;
  maxW?: string;
  children: React.ReactNode;
}> = ({ title, maxW = "max-w-md", children }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
    <div className={cn("w-full", maxW)}>
      <Card title={title}>{children}</Card>
    </div>
  </div>
);

const selectClass = inputBaseClass;
const textareaClass = cn(inputBaseClass, "h-auto py-2 resize-none");

interface VirtualKey {
  id: string;
  name: string;
  key_preview: string;
  user_id?: string;
  group_id?: string;
  tool_type?: string;
  is_active: boolean;
  created_at: string;
  // Gasto acumulado del presupuesto de NUESTRA base para el dueño de la llave
  // (issue #76, `KeyResponseSchema.spend_usd`). Es el mismo contador que dispara
  // el 402 del motor, no una estimación paralela.
  spend_usd?: number;
}

// Copy por superficie del catálogo cerrado (GOVERNANCE_SURFACES es el espejo del
// CHECK de la tabla): la llave declara persona + herramienta, y esta etiqueta es
// la que muestran el monitor y la auditoría.
const TOOL_LABELS: Record<string, string> = {
  "claude-code": "Claude Code (terminal)",
  "copilot": "VS Code · Copilot",
  "cursor": "Cursor",
  "claude-desktop": "Claude Desktop",
  "chatgpt": "Navegador · ChatGPT",
  "chat-ui": "Chat interno (playground)",
};

type Tab = "overview" | "teams" | "keys" | "budgets" | "auth";

export const UsersPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [users, setUsers] = useState<User[]>([]);
  const [budgets, setBudgets] = useState<Budget[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [keys, setKeys] = useState<VirtualKey[]>([]);
  const [groupSpend, setGroupSpend] = useState<Record<string, SpendInfo>>({});
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
  // La contraseña del alta la define quien registra: el producto ya no tiene ninguna por
  // defecto, así que sin este campo no hay usuario nuevo.
  const [password, setPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);

  // Restablecer la contraseña de otra persona (acción de administrador)
  const [resetUser, setResetUser] = useState<User | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetMsg, setResetMsg] = useState("");

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
  const [keyToolType, setKeyToolType] = useState("claude-code");
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

      // El consumo por Connection YA VIENE en el listado (`spend_usd` de
      // `KeyResponseSchema`, issue #76): no se pide más por llave. La consulta
      // por-llave que había acá (`GET /keys/{id}/spend`) preguntaba al provisionador
      // de keys del MOTOR y sólo se disparaba si `engine_key_token` existía — en
      // selfhosted ese token es NULL, así que no se pedía nunca y la columna
      // «Consumo Real» mostraba «—» para todo el mundo. Los equipos siguen leyendo
      // del motor porque su gasto sí vive ahí (`engine_team_id`).
      const spendResults = await Promise.allSettled(
        fetchedGroups
          .filter((g) => g.engine_team_id)
          .map((g) => api.getGroupSpend(g.id).then((s) => ({ id: g.id, spend: s }))),
      );

      const newGroupSpend: Record<string, SpendInfo> = {};

      spendResults.forEach((r) => {
        if (r.status === "fulfilled") {
          const { id, spend } = r.value as { id: string; spend: SpendInfo };
          newGroupSpend[id] = spend;
        }
      });

      setGroupSpend(newGroupSpend);
    } catch (err) {
      setError("No se pudieron cargar los datos de la pasarela.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    fetchComplianceData();
  }, []);

  // Cerrar el alta descarta la contraseña tipeada: una credencial no tiene por qué seguir
  // en memoria —ni reaparecer al volver a abrir el formulario— después de cancelar.
  const closeUserModal = () => {
    setShowUserModal(false);
    setPassword("");
    setPasswordError(null);
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    const invalida = validarPassword(password);
    if (invalida) {
      setPasswordError(invalida);
      return;
    }
    setPasswordError(null);
    setActionLoading(true);
    try {
      await api.createUser({
        username,
        email,
        role,
        password,
        group_id: groupId || undefined,
        is_active: true,
        legal_basis: userLegalBasis || undefined,
        risk_level: userRiskLevel || undefined,
        compliance_project_id: userComplianceProjectId || undefined,
      });
      closeUserModal();
      setUsername(""); setEmail(""); setGroupId("");
      setUserLegalBasis(""); setUserRiskLevel(""); setUserComplianceProjectId("");
      await fetchData();
    } catch (err: any) {
      alert(err?.message || "Error al crear el usuario.");
    } finally {
      setActionLoading(false);
    }
  };

  const openResetModal = (u: User) => {
    setResetUser(u);
    setResetPassword("");
    setResetError(null);
  };

  const closeResetModal = () => {
    setResetUser(null);
    setResetPassword("");
    setResetError(null);
  };

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resetUser) return;
    const invalida = validarPassword(resetPassword);
    if (invalida) {
      setResetError(invalida);
      return;
    }
    if (!confirm(`Se va a cambiar la contraseña de ${resetUser.username}. La anterior deja de funcionar de inmediato. ¿Continuar?`)) return;
    setResetError(null);
    setActionLoading(true);
    try {
      await api.resetUserPassword(resetUser.id, resetPassword);
      setResetMsg(`Contraseña actualizada para ${resetUser.username}. Entréguesela por un canal seguro.`);
      setResetUser(null);
      setResetPassword("");
      setTimeout(() => setResetMsg(""), 8000);
    } catch (err: any) {
      // El error se muestra dentro del modal, no en un alert: el administrador conserva lo
      // que escribió y puede corregir sin volver a tipear la contraseña.
      setResetError(err?.message || "No se pudo cambiar la contraseña.");
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
      const payload: any = { name: keyName, tool_type: keyToolType };
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
      setKeyName(""); setKeyToolType("claude-code"); setKeyUserId(""); setKeyGroupId(""); setKeyMaxBudget("");
      setKeyBudgetDuration("30d"); setKeyComplianceProjectId("");
      setKeyRpmLimit("60"); setKeyTpmLimit("100000");
      await fetchData();
    } catch (e) {
      // El motivo REAL importa: el caso más probable es que se hayan agotado los
      // asientos de la licencia (402), y con un "Error al generar la llave" genérico
      // el administrador del cliente concluye que el producto está roto.
      alert(e instanceof Error ? e.message : "No se pudo generar la llave virtual.");
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
      <PageHeader
        title="Administración"
        subtitle="Usuarios, equipos, llaves virtuales, presupuestos y autenticación."
        className="mb-0 pb-4 border-b border-border"
      />

      {error && (
        <div className="bg-danger-bg border border-danger/20 text-danger px-4 py-2.5 rounded-md text-xs">
          {error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-border text-xs font-semibold gap-6">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => { setActiveTab(t.id); if (t.id === "teams") fetchComplianceData(); }}
            className={cn(
              "pb-2.5 border-b-2 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded-t",
              activeTab === t.id
                ? "border-primary text-primary"
                : "border-transparent text-text-secondary hover:text-text-primary"
            )}
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
              { label: "Llaves activas", value: keys.filter((k) => k.is_active).length, cls: "text-ok" },
              { label: "Presupuestos", value: budgets.length, cls: "text-warn" },
              { label: "Gasto total acumulado", value: `$${totalSpendUsd.toFixed(4)}`, cls: "text-text-primary" },
            ].map((kpi) => (
              <Card key={kpi.label} className="p-4 space-y-1">
                <p className="text-[10px] text-text-secondary uppercase tracking-wider">{kpi.label}</p>
                <p className={cn("text-2xl font-bold font-mono", kpi.cls)}>{kpi.value}</p>
              </Card>
            ))}
          </div>

          {/* Near-limit budgets */}
          {nearLimitBudgets.length > 0 && (
            <div className="bg-surface border border-warn/40 rounded-card shadow-card p-5 space-y-3">
              <h2 className="text-xs font-semibold uppercase tracking-wider text-warn">
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
                        <span className="text-text-primary font-semibold">{name}</span>
                        <span className={cn("font-mono font-bold", pct >= 100 ? "text-danger" : "text-warn")}>
                          {pct.toFixed(1)}% (${Number(b.current_spend_usd).toFixed(4)} de ${Number(b.max_spend_usd).toFixed(4)})
                        </span>
                      </div>
                      <div className="w-full bg-surface-2 rounded-full h-1.5 overflow-hidden">
                        <div
                          className={cn("h-full rounded-full transition-all", pct >= 100 ? "bg-danger" : "bg-warn")}
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
            <Card className="p-5 text-xs text-text-secondary text-center">
              Todos los presupuestos están dentro del límite.
            </Card>
          )}

          {/* Quick stats */}
          <Card title="Equipos">
            {groups.length === 0 ? (
              <p className="text-xs text-text-secondary">No hay equipos.</p>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                {groups.map((g) => {
                  const count = users.filter((u) => u.group_id === g.id).length;
                  const budget = budgets.find((b) => b.group_id === g.id);
                  return (
                    <div key={g.id} className="border border-border rounded-md p-3 bg-surface-2 text-xs space-y-1">
                      <p className="font-semibold text-text-primary">{g.name}</p>
                      <p className="text-text-secondary">{count} miembro{count !== 1 ? "s" : ""}</p>
                      {budget ? (
                        <p className="font-mono text-ok text-[11px]">
                          ${Number(budget.current_spend_usd).toFixed(4)} / ${Number(budget.max_spend_usd).toFixed(4)}
                        </p>
                      ) : (
                        <p className="text-text-tertiary text-[11px]">Sin presupuesto</p>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        </div>
      )}

      {/* ── Tab: Usuarios & Equipos ───────────────────────────────────────── */}
      {activeTab === "teams" && (
        <div className="space-y-6">
          {complianceMsg && (
            <div className="bg-ok-bg border border-ok/20 text-ok px-4 py-2.5 rounded-md text-xs">{complianceMsg}</div>
          )}

          {/* Groups */}
          <Card
            title="Equipos de Trabajo"
            actions={
              <Button variant="secondary" size="sm" onClick={() => setShowTeamModal(true)}>
                Nuevo Equipo
              </Button>
            }
          >
            {groups.length === 0 ? (
              <p className="text-xs text-text-secondary">No hay equipos registrados.</p>
            ) : (
              <Table className="text-xs">
                <Table.Head>
                  <Table.Row>
                    <Table.HeaderCell>Equipo</Table.HeaderCell>
                    <Table.HeaderCell>Miembros</Table.HeaderCell>
                    <Table.HeaderCell>Base Legal</Table.HeaderCell>
                    <Table.HeaderCell>Riesgo AI Act</Table.HeaderCell>
                    <Table.HeaderCell>Proyecto Compliance</Table.HeaderCell>
                    <Table.HeaderCell>Consumo</Table.HeaderCell>
                    <Table.HeaderCell />
                  </Table.Row>
                </Table.Head>
                <Table.Body>
                  {groups.map((g) => {
                    const membersCount = users.filter((u) => u.group_id === g.id).length;
                    const cg = complianceGroups.find((x: any) => x.id === g.id);
                    const risk = cg?.default_risk_level ? RISK_BADGE[cg.default_risk_level] : null;
                    const spend = groupSpend[g.id];
                    return (
                      <Table.Row key={g.id} className="hover:bg-surface-2 transition-colors">
                        <Table.Cell>
                          <p className="font-semibold text-text-primary">{g.name}</p>
                          <p className="text-[10px] text-text-secondary mt-0.5">{g.description || "Sin descripción"}</p>
                        </Table.Cell>
                        <Table.Cell className="text-text-secondary">{membersCount}</Table.Cell>
                        <Table.Cell className="text-[11px] text-primary">
                          {cg?.default_legal_basis ? (LEGAL_BASIS_SHORT[cg.default_legal_basis] || cg.default_legal_basis) : <span className="text-text-tertiary">sin dato</span>}
                        </Table.Cell>
                        <Table.Cell>
                          {risk ? (
                            <StatusBadge tone={risk.tone}>{risk.label}</StatusBadge>
                          ) : <span className="text-text-tertiary text-[10px]">sin dato</span>}
                        </Table.Cell>
                        <Table.Cell className="text-[11px] text-text-secondary">
                          {cg?.compliance_project_name || <span className="text-text-tertiary">sin dato</span>}
                        </Table.Cell>
                        <Table.Cell className="font-mono text-[11px]">
                          {spend?.spend_usd != null ? (
                            <span className="text-ok">${spend.spend_usd.toFixed(4)}</span>
                          ) : <span className="text-text-tertiary">sin dato</span>}
                        </Table.Cell>
                        <Table.Cell>
                          <button
                            onClick={() => openComplianceModal(cg ?? g)}
                            className="text-primary hover:text-primary-hover hover:underline text-xs font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
                          >
                            Editar perfil
                          </button>
                        </Table.Cell>
                      </Table.Row>
                    );
                  })}
                </Table.Body>
              </Table>
            )}
          </Card>

          {/* Users */}
          <Card
            title="Miembros / Usuarios"
            actions={
              <Button variant="secondary" size="sm" onClick={() => setShowUserModal(true)}>
                Registrar Miembro
              </Button>
            }
          >
            {resetMsg && (
              <div className="bg-ok-bg border border-ok/20 text-ok px-4 py-2.5 rounded-md text-xs mb-4">{resetMsg}</div>
            )}
            {users.length === 0 ? (
              <p className="text-xs text-text-secondary">No hay usuarios registrados.</p>
            ) : (
              <Table className="text-xs">
                <Table.Head>
                  <Table.Row>
                    <Table.HeaderCell>Usuario</Table.HeaderCell>
                    <Table.HeaderCell>Email</Table.HeaderCell>
                    <Table.HeaderCell>Rol</Table.HeaderCell>
                    <Table.HeaderCell>Equipo</Table.HeaderCell>
                    <Table.HeaderCell>Riesgo AI Act</Table.HeaderCell>
                    <Table.HeaderCell />
                  </Table.Row>
                </Table.Head>
                <Table.Body>
                  {users.map((u: any) => {
                    const groupName = groups.find((g) => g.id === u.group_id)?.name || "Sin Equipo";
                    const effectiveRisk = u.risk_level ||
                      complianceGroups.find((g: any) => g.id === u.group_id)?.default_risk_level;
                    const risk = effectiveRisk ? RISK_BADGE[effectiveRisk] : null;
                    return (
                      <Table.Row key={u.id} className="hover:bg-surface-2 transition-colors">
                        <Table.Cell className="font-semibold text-text-primary">{u.username}</Table.Cell>
                        <Table.Cell className="text-text-secondary">{u.email}</Table.Cell>
                        <Table.Cell className="uppercase text-[10px] font-mono text-primary font-semibold">{u.role}</Table.Cell>
                        <Table.Cell className="text-text-secondary">{groupName}</Table.Cell>
                        <Table.Cell>
                          {risk ? (
                            <StatusBadge tone={risk.tone}>
                              {risk.label}{u.risk_level ? "" : " ↑"}
                            </StatusBadge>
                          ) : <span className="text-text-tertiary text-[10px]">sin dato</span>}
                        </Table.Cell>
                        <Table.Cell>
                          <div className="flex items-center gap-4">
                            <button
                              onClick={() => { setAssignGroupUser(u); setAssignGroupId(u.group_id || ""); }}
                              className="text-xs text-primary hover:text-primary-hover hover:underline font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
                            >
                              Asignar equipo
                            </button>
                            <button
                              onClick={() => openResetModal(u)}
                              className="text-xs text-primary hover:text-primary-hover hover:underline font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded whitespace-nowrap"
                            >
                              Restablecer contraseña
                            </button>
                          </div>
                        </Table.Cell>
                      </Table.Row>
                    );
                  })}
                </Table.Body>
              </Table>
            )}
          </Card>
        </div>
      )}

      {/* ── Tab: Llaves Virtuales ─────────────────────────────────────────── */}
      {activeTab === "keys" && (
        <Card
          title="Llaves virtuales activas"
          actions={
            <Button variant="primary" size="sm" onClick={() => setShowKeyModal(true)}>
              Generar Llave Virtual
            </Button>
          }
        >
          {keys.length === 0 ? (
            <p className="text-xs text-text-secondary">No hay llaves virtuales activas.</p>
          ) : (
            <Table className="text-xs">
              <Table.Head>
                <Table.Row>
                  <Table.HeaderCell>Nombre / Identificador</Table.HeaderCell>
                  <Table.HeaderCell>Asociado a</Table.HeaderCell>
                  <Table.HeaderCell>Herramienta</Table.HeaderCell>
                  <Table.HeaderCell>Compliance</Table.HeaderCell>
                  <Table.HeaderCell>Vista previa</Table.HeaderCell>
                  <Table.HeaderCell>Límites RPM/TPM</Table.HeaderCell>
                  <Table.HeaderCell title="Gasto acumulado del presupuesto aplicable al dueño de la Connection. Es el mismo contador que bloquea la petición al superar el tope.">
                    Consumo
                  </Table.HeaderCell>
                  <Table.HeaderCell>Fecha Creación</Table.HeaderCell>
                  <Table.HeaderCell align="right">Acciones</Table.HeaderCell>
                </Table.Row>
              </Table.Head>
              <Table.Body>
                {keys.map((k) => {
                  const owner = k.user_id
                    ? `Usuario: ${users.find((u) => u.id === k.user_id)?.username}`
                    : k.group_id
                    ? `Equipo: ${groups.find((g) => g.id === k.group_id)?.name}`
                    : "Global / Sin Asignar";
                  return (
                    <Table.Row key={k.id} className="hover:bg-surface-2 transition-colors">
                      <Table.Cell className="font-semibold text-text-primary">{k.name}</Table.Cell>
                      <Table.Cell>
                        <StatusBadge tone="neutral" className="text-[10px]">{owner}</StatusBadge>
                      </Table.Cell>
                      <Table.Cell>
                        <StatusBadge tone="info" className="text-[10px]">
                          {TOOL_LABELS[k.tool_type ?? ""] ?? k.tool_type ?? "sin dato"}
                        </StatusBadge>
                      </Table.Cell>
                      <Table.Cell className="text-[10px]">
                        {(k as any).compliance_project_id
                          ? <span className="text-primary font-semibold">{complianceProjects.find((p: any) => p.id === (k as any).compliance_project_id)?.name || "Proyecto asignado"}</span>
                          : <span className="text-text-tertiary">Heredado</span>}
                      </Table.Cell>
                      <Table.Cell className="font-mono text-text-secondary text-[11px]">{k.key_preview}</Table.Cell>
                      <Table.Cell className="text-[10px]">
                        <span className="text-text-secondary">{(k as any).rpm_limit ?? 60} rpm</span>
                        <span className="text-text-tertiary mx-1">/</span>
                        <span className="text-text-secondary">{((k as any).tpm_limit ?? 100000).toLocaleString()} tpm</span>
                      </Table.Cell>
                      <Table.Cell className="font-mono text-xs">
                        {(() => {
                          // Issue #76. Esta celda mostraba «—» para TODAS las llaves porque leía
                          // `GET /keys/{id}/spend`, que consulta al provisionador de keys del
                          // MOTOR: en selfhosted ese provisionador no existe, `engine_key_token`
                          // es NULL y la respuesta era siempre `null`. El número honesto lo tiene
                          // nuestra base — `budgets.current_spend_usd`, el MISMO contador que
                          // dispara el rechazo 402 antes de salir al proveedor — y el backend ya
                          // lo resuelve con la precedencia del plano interno (`keys.py`,
                          // `_gasto_por_llave`). Que el admin vea acá exactamente el número que
                          // explica el corte de su usuario es el punto de todo el fix.
                          // null ≠ 0: «sin presupuesto aplicable» (nadie cuenta) no es lo
                          // mismo que «con presupuesto y gasto cero» (control activo).
                          if (k.spend_usd === null || k.spend_usd === undefined) {
                            return (
                              <span
                                className="text-text-tertiary italic"
                                title="El dueño de esta Connection no tiene ningún presupuesto asignado: el gasto no se está contando ni limitando."
                              >
                                sin presupuesto
                              </span>
                            );
                          }
                          const gasto = Number(k.spend_usd);
                          // 4 decimales a la vista: una llamada barata cuesta ~$0.0002, y con 2
                          // decimales el admin lee $0.00 y concluye que no se consumió nada. El
                          // tooltip da los 8 de la columna (`NUMERIC(14,8)`), que es la precisión
                          // real del contador — no un redondeo inventado.
                          return (
                            <span
                              className={gasto > 0 ? "text-ok" : "text-text-tertiary"}
                              title={`Gasto acumulado del presupuesto aplicable a esta Connection: $${gasto.toFixed(8)}`}
                            >
                              ${gasto.toFixed(4)}
                            </span>
                          );
                        })()}
                      </Table.Cell>
                      <Table.Cell className="text-text-secondary">
                        {new Date(k.created_at).toLocaleDateString("es-AR", { day: "numeric", month: "short", year: "numeric" })}
                      </Table.Cell>
                      <Table.Cell align="right" className="text-right">
                        <button
                          onClick={() => handleRevokeKey(k.id)}
                          disabled={actionLoading}
                          className="text-danger hover:opacity-80 font-semibold text-xs transition-opacity disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
                        >
                          Revocar
                        </button>
                      </Table.Cell>
                    </Table.Row>
                  );
                })}
              </Table.Body>
            </Table>
          )}
        </Card>
      )}

      {/* ── Tab: Presupuestos ────────────────────────────────────────────── */}
      {activeTab === "budgets" && (
        <div className="space-y-5">
          <div className="flex justify-between items-center gap-4">
            <div>
              <h2 className="text-[15px] font-semibold text-text-primary">Límites de Consumo</h2>
              <p className="text-xs text-text-secondary mt-0.5">
                Presupuestos máximos en USD y tokens. Si hay presupuesto personal y de equipo, se verifican los dos.
              </p>
            </div>
            <Button variant="primary" size="sm" onClick={() => setShowBudgetModal(true)}>
              Asignar Límite
            </Button>
          </div>

          {budgets.length === 0 ? (
            <Card className="p-8 text-center text-xs text-text-secondary">
              No hay presupuestos configurados. Usa "Asignar Límite" para crear el primero.
            </Card>
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
                  <Card key={b.id} className="p-4 space-y-3">
                    <div className="flex items-start justify-between gap-2">
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2">
                          <StatusBadge tone={isPersonal ? "info" : "warn"}>
                            {isPersonal ? "Personal" : "Equipo"}
                          </StatusBadge>
                        </div>
                        <p className="text-xs font-bold text-text-primary mt-1">{targetName}</p>
                      </div>
                      <span className="text-[10px] font-mono text-text-secondary uppercase">{b.reset_period}</span>
                    </div>

                    {/* Spend */}
                    <div className="space-y-1.5">
                      <div className="flex justify-between text-xs font-mono">
                        <span className={progressPercent > 85 ? "text-danger font-bold" : progressPercent > 50 ? "text-warn" : "text-ok"}>
                          ${Number(b.current_spend_usd).toFixed(4)}
                        </span>
                        <span className="text-text-secondary">${Number(b.max_spend_usd).toFixed(4)}</span>
                      </div>
                      <div className="w-full bg-surface-2 rounded-full h-1.5 overflow-hidden">
                        <div
                          className={cn("h-full rounded-full transition-all", progressPercent > 85 ? "bg-danger" : progressPercent > 50 ? "bg-warn" : "bg-primary")}
                          style={{ width: `${progressPercent}%` }}
                        />
                      </div>
                      <div className="text-[10px] text-text-secondary font-mono">
                        Tokens: {b.current_tokens.toLocaleString()} / {b.max_tokens.toLocaleString()}
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex gap-3 pt-1 border-t border-border">
                      <button
                        onClick={() => { setEditingBudget(b); setEditBudgetUsd(String(b.max_spend_usd)); setEditBudgetTokens(String(b.max_tokens)); }}
                        className="text-xs text-primary hover:text-primary-hover hover:underline font-semibold focus:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
                      >
                        Editar
                      </button>
                      <button
                        onClick={() => handleDeleteBudget(b.id)}
                        disabled={actionLoading}
                        className="text-xs text-danger hover:opacity-80 font-semibold disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded"
                      >
                        Eliminar
                      </button>
                    </div>
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── Tab: Autenticación & SSO ─────────────────────────────────────── */}
      {activeTab === "auth" && (
        <div className="space-y-6">
          <Card title="Métodos de Autenticación Disponibles">
            <p className="text-xs text-text-secondary mb-5">
              Métodos de acceso a la consola. Los marcados como «Próximamente» se habilitan como servicio adicional.
            </p>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {[
                {
                  name: "Azure AD / Microsoft Entra ID",
                  type: "OIDC / OAuth 2.0",
                  target: "Enterprise",
                  description: "Integración con el directorio corporativo de Microsoft. Ideal para hospitales y grandes organizaciones con licencias Microsoft 365.",
                  badge: "Próximamente",
                  badgeTone: "warn" as BadgeTone,
                  icon: "🔷",
                },
                {
                  name: "Google Workspace",
                  type: "OIDC / OAuth 2.0",
                  target: "SME / Clínicas",
                  description: "Login con cuentas Google corporativas. Recomendado para organizaciones medianas que usan Google Workspace.",
                  badge: "Próximamente",
                  badgeTone: "warn" as BadgeTone,
                  icon: "🔴",
                },
                {
                  name: "Okta",
                  type: "OIDC / SAML 2.0",
                  target: "Enterprise",
                  description: "Proveedor de identidad enterprise líder. Soporta MFA avanzado, políticas de acceso condicional y auditoría detallada.",
                  badge: "Próximamente",
                  badgeTone: "warn" as BadgeTone,
                  icon: "⚡",
                },
                {
                  name: "Auth0",
                  type: "OIDC / OAuth 2.0",
                  target: "Universal",
                  description: "Plataforma de identidad flexible. Soporta múltiples proveedores sociales y enterprise simultáneamente.",
                  badge: "Próximamente",
                  badgeTone: "warn" as BadgeTone,
                  icon: "🔐",
                },
                {
                  name: "Keycloak",
                  type: "OIDC / SAML 2.0",
                  target: "Self-hosted",
                  description: "Solución open source autohospedada para gestión de identidad. Sin dependencias externas, ideal para entornos de alta seguridad.",
                  badge: "Próximamente",
                  badgeTone: "warn" as BadgeTone,
                  icon: "🗝️",
                },
                {
                  name: "SAML 2.0 genérico",
                  type: "SAML 2.0",
                  target: "Enterprise heredado",
                  description: "Protocolo estándar para integración con sistemas legacy (AD FS, Shibboleth, PingFederate). Compatible con cualquier IdP SAML.",
                  badge: "Próximamente",
                  badgeTone: "warn" as BadgeTone,
                  icon: "🏛️",
                },
                {
                  name: "Usuario & Contraseña (JWT)",
                  type: "JWT HS256 / 24h TTL",
                  target: "Usuarios internos",
                  description: "Autenticación local integrada. Gestión de usuarios desde el panel de administración. Sin dependencias externas.",
                  badge: "Activo",
                  badgeTone: "ok" as BadgeTone,
                  icon: "✓",
                },
              ].map((p) => (
                <div key={p.name} className="border border-border rounded-card p-4 space-y-3 bg-surface-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-2">
                      <span className="text-lg">{p.icon}</span>
                      <span className="font-semibold text-text-primary text-xs">{p.name}</span>
                    </div>
                    <StatusBadge tone={p.badgeTone} className="text-[10px] flex-shrink-0">
                      {p.badge}
                    </StatusBadge>
                  </div>
                  <div className="flex gap-2 flex-wrap">
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-surface border border-border text-text-secondary">{p.type}</span>
                    <span className="px-1.5 py-0.5 rounded text-[10px] bg-surface border border-border text-text-secondary">{p.target}</span>
                  </div>
                  <p className="text-[11px] text-text-secondary leading-relaxed">{p.description}</p>
                </div>
              ))}
            </div>

            <div className="mt-5 p-3 rounded-card bg-surface-2 border border-border text-xs text-text-secondary">
              Para habilitar un proveedor SSO, contacte a su equipo de soporte indicando el proveedor
              de identidad elegido y el dominio corporativo. La configuración lleva entre 1 y 2 días.
            </div>
          </Card>
        </div>
      )}

      {/* ── Compliance Profile Modal ─────────────────────────────────────── */}
      {showComplianceModal && editingGroup && (
        <ModalShell title={`Perfil de compliance: ${editingGroup.name}`}>
          <div className="space-y-4">
            <Field label="Base legal GDPR por defecto">
              <select
                value={complianceForm.default_legal_basis}
                onChange={e => setComplianceForm(f => ({ ...f, default_legal_basis: e.target.value }))}
                className={selectClass}
              >
                <option value="">Sin configurar</option>
                <option value="art_9_2_h">Art. 9(2)(h): prestación sanitaria</option>
                <option value="art_9_2_j">Art. 9(2)(j): investigación o interés público</option>
                <option value="art_9_2_a">Art. 9(2)(a): consentimiento explícito</option>
                <option value="art_6_1_c">Art. 6(1)(c): obligación legal</option>
                <option value="art_6_1_e">Art. 6(1)(e): misión de interés público</option>
              </select>
            </Field>

            <Field label="Nivel de riesgo AI Act">
              <select
                value={complianceForm.default_risk_level}
                onChange={e => setComplianceForm(f => ({ ...f, default_risk_level: e.target.value }))}
                className={selectClass}
              >
                <option value="">Sin configurar</option>
                <option value="minimal">Riesgo Mínimo</option>
                <option value="limited">Riesgo Limitado</option>
                <option value="high_risk_annex3">Alto riesgo (Annex III: farmacovigilancia, evaluación de personas)</option>
                <option value="high_risk_annex1">Alto riesgo (Annex I: MDR, producto sanitario)</option>
              </select>
            </Field>

            <Field
              label="Proyecto de compliance asignado"
              hint="Si se asigna un proyecto, sus reglas se aplicarán a las llamadas de los miembros de este equipo."
            >
              <select
                value={complianceForm.compliance_project_id}
                onChange={e => setComplianceForm(f => ({ ...f, compliance_project_id: e.target.value }))}
                className={selectClass}
              >
                <option value="">Sin asignar (usa política global)</option>
                {complianceProjects.map((p: any) => (
                  <option key={p.id} value={p.id}>{p.name}{p.is_active ? "" : " (inactivo)"}</option>
                ))}
              </select>
            </Field>

            <div className="flex gap-2 justify-end pt-2">
              <Button variant="secondary" size="sm" onClick={() => setShowComplianceModal(false)}>
                Cancelar
              </Button>
              <Button variant="primary" size="sm" onClick={saveComplianceProfile}>
                Guardar
              </Button>
            </div>
          </div>
        </ModalShell>
      )}

      {/* ── Key Creation Modal ───────────────────────────────────────────── */}
      {showKeyModal && (
        <ModalShell title="Generar Llave Virtual">
          <form onSubmit={handleCreateKey} className="space-y-4 text-xs">
            <Field
              label="Nombre de la Llave"
              type="text"
              required
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
              placeholder="ej: cardiologia-produccion"
            />
            <Field label="Herramienta">
              <select
                value={keyToolType}
                onChange={(e) => setKeyToolType(e.target.value)}
                className={selectClass}
              >
                {GOVERNANCE_SURFACES.map((s) => (
                  <option key={s} value={s}>{TOOL_LABELS[s] ?? s}</option>
                ))}
              </select>
              <p className="mt-1 text-[10px] text-text-tertiary">
                Cada llave identifica a una persona y una herramienta. Se admite una llave activa
                por herramienta y usuario.
              </p>
            </Field>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Equipo">
                <select
                  value={keyGroupId}
                  onChange={(e) => { setKeyGroupId(e.target.value); if (e.target.value) setKeyUserId(""); }}
                  className={selectClass}
                >
                  <option value="">Seleccionar Equipo</option>
                  {groups.filter((g) => g.engine_team_id).map((g) => (
                    <option key={g.id} value={g.id}>{g.name}</option>
                  ))}
                </select>
              </Field>
              <Field label="O Usuario">
                <select
                  value={keyUserId}
                  onChange={(e) => { setKeyUserId(e.target.value); if (e.target.value) setKeyGroupId(""); }}
                  className={selectClass}
                >
                  <option value="">Seleccionar Usuario</option>
                  {users.filter((u) => u.engine_user_id).map((u) => (
                    <option key={u.id} value={u.id}>{u.username}</option>
                  ))}
                </select>
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field
                label="Presupuesto Máx. (USD)"
                type="number"
                step="0.01"
                min="0"
                value={keyMaxBudget}
                onChange={(e) => setKeyMaxBudget(e.target.value)}
                placeholder="ej: 50.00"
              />
              <Field label="Período de Reinicio">
                <select
                  value={keyBudgetDuration}
                  onChange={(e) => setKeyBudgetDuration(e.target.value)}
                  className={selectClass}
                >
                  <option value="1d">Diario</option>
                  <option value="7d">Semanal</option>
                  <option value="30d">Mensual</option>
                  <option value="365d">Anual</option>
                </select>
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <Field
                label={<>Límite RPM <span className="text-text-tertiary normal-case">(solicitudes/min)</span></>}
                type="number"
                min="1"
                max="10000"
                value={keyRpmLimit}
                onChange={(e) => setKeyRpmLimit(e.target.value)}
              />
              <Field
                label={<>Límite TPM <span className="text-text-tertiary normal-case">(tokens/min)</span></>}
                type="number"
                min="1000"
                max="10000000"
                value={keyTpmLimit}
                onChange={(e) => setKeyTpmLimit(e.target.value)}
              />
            </div>
            <Field label="Proyecto de compliance (Opcional)">
              <select
                value={keyComplianceProjectId}
                onChange={(e) => setKeyComplianceProjectId(e.target.value)}
                className={selectClass}
              >
                <option value="">Sin asignar (hereda del usuario/equipo)</option>
                {complianceProjects.map((p: any) => (
                  <option key={p.id} value={p.id}>{p.name}{p.is_active ? "" : " (inactivo)"}</option>
                ))}
              </select>
            </Field>
            <div className="flex justify-end gap-3 pt-4 border-t border-border">
              <Button type="button" variant="secondary" size="sm" onClick={() => setShowKeyModal(false)}>Cancelar</Button>
              <Button type="submit" variant="primary" size="sm" disabled={actionLoading}>
                {actionLoading ? "Generando..." : "Generar"}
              </Button>
            </div>
          </form>
        </ModalShell>
      )}

      {/* ── Generated Key Modal ──────────────────────────────────────────── */}
      {generatedKey && (
        <ModalShell title={<span className="text-ok">¡Llave Virtual Generada!</span>} maxW="max-w-lg">
          <div className="space-y-4 text-xs">
            <p className="text-text-secondary">Copie la clave ahora. Por motivos de seguridad, no se volverá a mostrar.</p>
            <div className="bg-surface-2 border border-border rounded-md p-4 flex justify-between items-center gap-4">
              <code className="text-[11px] font-mono text-ok break-all select-all pr-2">{generatedKey}</code>
              <button
                onClick={handleCopyKey}
                className="shrink-0 bg-ok-bg hover:opacity-90 text-ok border border-ok/20 px-3 py-1.5 rounded-md font-semibold text-xs transition-opacity focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                {copied ? "Copiado" : "Copiar"}
              </button>
            </div>
            <div className="bg-warn-bg border border-warn/20 text-warn rounded-md p-3.5 text-[11px]">
              Guarde esta credencial en un lugar seguro. Cualquiera que la tenga puede consultar la pasarela con los límites asignados.
            </div>
            <div className="flex justify-end pt-2">
              <Button variant="primary" size="sm" onClick={() => setGeneratedKey(null)}>
                Entendido
              </Button>
            </div>
          </div>
        </ModalShell>
      )}

      {/* ── Team Creation Modal ──────────────────────────────────────────── */}
      {showTeamModal && (
        <ModalShell title="Crear Nuevo Equipo">
          <form onSubmit={handleCreateTeam} className="space-y-4 text-xs">
            <Field
              label="Nombre del Equipo"
              type="text"
              required
              value={teamName}
              onChange={(e) => setTeamName(e.target.value)}
              placeholder="ej: Comercio Exterior"
            />
            <Field label="Descripción">
              <textarea
                value={teamDesc}
                onChange={(e) => setTeamDesc(e.target.value)}
                placeholder="ej: Equipo de certificados de origen y ferias internacionales."
                rows={3}
                className={textareaClass}
              />
            </Field>
            <div className="flex justify-end gap-3 pt-4 border-t border-border">
              <Button type="button" variant="secondary" size="sm" onClick={() => setShowTeamModal(false)}>Cancelar</Button>
              <Button type="submit" variant="primary" size="sm" disabled={actionLoading}>
                {actionLoading ? "Creando..." : "Crear"}
              </Button>
            </div>
          </form>
        </ModalShell>
      )}

      {/* ── User Creation Modal ──────────────────────────────────────────── */}
      {showUserModal && (
        <ModalShell title="Registrar Miembro">
          <form onSubmit={handleCreateUser} className="space-y-4 text-xs">
            <Field
              label="Nombre de Usuario"
              type="text"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="ej: dr_perez"
            />
            <Field
              label="Email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="ej: perez@basa.com.ar"
            />
            <PasswordField
              id="alta-password"
              label="Contraseña de acceso"
              value={password}
              onChange={(v) => { setPassword(v); if (passwordError) setPasswordError(null); }}
              error={passwordError}
              placeholder={`Mínimo ${MIN_PASSWORD_LEN} caracteres`}
              hint={`Mínimo ${MIN_PASSWORD_LEN} caracteres. Entréguesela a la persona por un canal seguro.`}
            />
            <Field label="Rol">
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className={selectClass}
              >
                <option value="clinician">Especialista</option>
                <option value="researcher">Investigador</option>
                <option value="developer">Desarrollador</option>
                <option value="admin">Administrador</option>
              </select>
            </Field>
            <Field label="Asociar a Equipo (Opcional)">
              <select
                value={groupId}
                onChange={(e) => setGroupId(e.target.value)}
                className={selectClass}
              >
                <option value="">Ninguno / Sin Equipo</option>
                {groups.map((g) => (
                  <option key={g.id} value={g.id}>{g.name}</option>
                ))}
              </select>
            </Field>

            <div className="border-t border-border pt-3 space-y-3">
              <p className="text-[10px] text-text-secondary uppercase tracking-wider font-semibold">Perfil de compliance individual (sobrescribe el del equipo)</p>
              <Field label="Base legal GDPR">
                <select
                  value={userLegalBasis}
                  onChange={(e) => setUserLegalBasis(e.target.value)}
                  className={selectClass}
                >
                  <option value="">Heredar del equipo</option>
                  <option value="art_9_2_h">Art. 9(2)(h): prestación sanitaria</option>
                  <option value="art_9_2_j">Art. 9(2)(j): investigación</option>
                  <option value="art_9_2_a">Art. 9(2)(a): consentimiento explícito</option>
                  <option value="art_6_1_c">Art. 6(1)(c): obligación legal</option>
                  <option value="art_6_1_e">Art. 6(1)(e): interés público</option>
                </select>
              </Field>
              <Field label="Nivel de riesgo AI Act">
                <select
                  value={userRiskLevel}
                  onChange={(e) => setUserRiskLevel(e.target.value)}
                  className={selectClass}
                >
                  <option value="">Heredar del equipo</option>
                  <option value="minimal">Riesgo Mínimo</option>
                  <option value="limited">Riesgo Limitado</option>
                  <option value="high_risk_annex3">Alto riesgo (Annex III)</option>
                  <option value="high_risk_annex1">Alto riesgo (MDR)</option>
                </select>
              </Field>
              <Field label="Proyecto de compliance">
                <select
                  value={userComplianceProjectId}
                  onChange={(e) => setUserComplianceProjectId(e.target.value)}
                  className={selectClass}
                >
                  <option value="">Heredar del equipo</option>
                  {complianceProjects.map((p: any) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              </Field>
            </div>

            <div className="flex justify-end gap-3 pt-4 border-t border-border">
              <Button type="button" variant="secondary" size="sm" onClick={closeUserModal}>Cancelar</Button>
              <Button type="submit" variant="primary" size="sm" disabled={actionLoading}>
                {actionLoading ? "Registrando..." : "Registrar"}
              </Button>
            </div>
          </form>
        </ModalShell>
      )}

      {/* ── Budget Assignment Modal ──────────────────────────────────────── */}
      {showBudgetModal && (
        <ModalShell title="Asignar Límite / Presupuesto">
          <form onSubmit={handleCreateBudget} className="space-y-4 text-xs">
            <div className="space-y-3">
              <span className="text-xs font-semibold uppercase tracking-wide text-text-secondary block">Asignar a</span>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Equipo">
                  <select
                    value={budgetGroupId}
                    onChange={(e) => { setBudgetGroupId(e.target.value); if (e.target.value) setBudgetUserId(""); }}
                    className={selectClass}
                  >
                    <option value="">Seleccionar Equipo</option>
                    {groups.map((g) => (
                      <option key={g.id} value={g.id}>{g.name}</option>
                    ))}
                  </select>
                </Field>
                <Field label="O Usuario Individual">
                  <select
                    value={budgetUserId}
                    onChange={(e) => { setBudgetUserId(e.target.value); if (e.target.value) setBudgetGroupId(""); }}
                    className={selectClass}
                  >
                    <option value="">Seleccionar Usuario</option>
                    {users.map((u) => (
                      <option key={u.id} value={u.id}>{u.username}</option>
                    ))}
                  </select>
                </Field>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <Field
                label="Límite Máximo (USD)"
                type="number"
                step="0.01"
                required
                value={maxSpend}
                onChange={(e) => setMaxSpend(e.target.value)}
              />
              <Field
                label="Límite Máximo (Tokens)"
                type="number"
                required
                value={maxTokens}
                onChange={(e) => setMaxTokens(e.target.value)}
              />
            </div>

            <Field label="Período de Reinicio">
              <select
                value={resetPeriod}
                onChange={(e) => setResetPeriod(e.target.value)}
                className={selectClass}
              >
                <option value="daily">Diario</option>
                <option value="weekly">Semanal</option>
                <option value="monthly">Mensual</option>
                <option value="yearly">Anual</option>
              </select>
            </Field>

            <div className="flex justify-end gap-3 pt-4 border-t border-border">
              <Button type="button" variant="secondary" size="sm" onClick={() => setShowBudgetModal(false)}>Cancelar</Button>
              <Button type="submit" variant="primary" size="sm" disabled={actionLoading}>
                {actionLoading ? "Asignando..." : "Asignar"}
              </Button>
            </div>
          </form>
        </ModalShell>
      )}

      {/* ── Edit Budget Modal ────────────────────────────────────────────── */}
      {editingBudget && (
        <ModalShell title="Editar presupuesto" maxW="max-w-sm">
          <div className="space-y-4">
            <div className="space-y-3">
              <Field
                label="Límite USD"
                type="number"
                step="0.001"
                value={editBudgetUsd}
                onChange={e => setEditBudgetUsd(e.target.value)}
              />
              <Field
                label="Límite Tokens"
                type="number"
                value={editBudgetTokens}
                onChange={e => setEditBudgetTokens(e.target.value)}
              />
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <Button variant="secondary" size="sm" onClick={() => setEditingBudget(null)}>Cancelar</Button>
              <Button variant="primary" size="sm" onClick={handleUpdateBudget}>Guardar</Button>
            </div>
          </div>
        </ModalShell>
      )}

      {/* ── Assign Group Modal ───────────────────────────────────────────── */}
      {assignGroupUser && (
        <ModalShell title={`Asignar equipo: ${assignGroupUser.username}`} maxW="max-w-sm">
          <div className="space-y-4">
            <Field label="Equipo">
              <select
                value={assignGroupId}
                onChange={e => setAssignGroupId(e.target.value)}
                className={selectClass}
              >
                <option value="">Sin equipo</option>
                {groups.map((g: any) => (
                  <option key={g.id} value={g.id}>{g.name}</option>
                ))}
              </select>
            </Field>
            <div className="flex justify-end gap-3 pt-2">
              <Button variant="secondary" size="sm" onClick={() => setAssignGroupUser(null)}>Cancelar</Button>
              <Button variant="primary" size="sm" onClick={handleAssignGroup}>Guardar</Button>
            </div>
          </div>
        </ModalShell>
      )}

      {/* ── Reset Password Modal (acción de administrador) ───────────────── */}
      {resetUser && (
        <ModalShell title={`Restablecer contraseña: ${resetUser.username}`} maxW="max-w-sm">
          <form onSubmit={handleResetPassword} className="space-y-4 text-xs">
            <p className="text-text-secondary leading-relaxed">
              Se define una contraseña nueva para esta persona. No hace falta conocer la anterior:
              al guardar, la anterior deja de funcionar.
            </p>
            <PasswordField
              id="reset-password"
              label="Contraseña nueva"
              value={resetPassword}
              onChange={(v) => { setResetPassword(v); if (resetError) setResetError(null); }}
              error={resetError}
              placeholder={`Mínimo ${MIN_PASSWORD_LEN} caracteres`}
              hint={`Mínimo ${MIN_PASSWORD_LEN} caracteres. Entréguesela por un canal seguro.`}
            />
            <div className="flex justify-end gap-3 pt-4 border-t border-border">
              <Button type="button" variant="secondary" size="sm" onClick={closeResetModal}>Cancelar</Button>
              <Button type="submit" variant="primary" size="sm" disabled={actionLoading}>
                {actionLoading ? "Guardando..." : "Restablecer"}
              </Button>
            </div>
          </form>
        </ModalShell>
      )}
    </div>
  );
};
