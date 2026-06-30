import React, { useState, useEffect } from "react";
import { api } from "../services/api";

type Tab = "projects" | "dpas" | "dsr" | "retention" | "dpo" | "consents";

const LEGAL_BASIS_LABELS: Record<string, string> = {
  art_9_2_h: "Art. 9(2)(h) — Prestación sanitaria",
  art_9_2_j: "Art. 9(2)(j) — Interés público / investigación",
  art_9_2_a: "Art. 9(2)(a) — Consentimiento explícito",
  art_6_1_c: "Art. 6(1)(c) — Obligación legal",
  art_6_1_e: "Art. 6(1)(e) — Misión de interés público",
};

const RISK_LABELS: Record<string, { label: string; color: string }> = {
  minimal: { label: "Riesgo Mínimo", color: "text-success" },
  limited: { label: "Riesgo Limitado", color: "text-primary" },
  high_risk_annex3: { label: "Alto Riesgo — Annex III", color: "text-warning" },
  high_risk_annex1: { label: "Alto Riesgo — Annex I (MDR)", color: "text-danger" },
};

const DPA_STATUS: Record<string, { label: string; color: string }> = {
  active: { label: "Activo", color: "text-success" },
  expiring_soon: { label: "Por vencer", color: "text-warning" },
  expired: { label: "Expirado", color: "text-danger" },
};

const DSR_TYPES = ["access", "rectification", "erasure", "portability", "restriction"];
const DSR_TYPE_LABELS: Record<string, string> = {
  access: "Acceso (Art. 15)",
  rectification: "Rectificación (Art. 16)",
  erasure: "Supresión (Art. 17)",
  portability: "Portabilidad (Art. 20)",
  restriction: "Limitación (Art. 18)",
};

const LOG_TYPE_LABELS: Record<string, string> = {
  prompt_content: "Contenido de prompts y respuestas",
  usage_metadata: "Metadatos de uso (tokens, coste, modelo)",
  security_events: "Eventos de guardianes y seguridad",
  config_audit: "Cambios de configuración del sistema",
};

const emptyProject = {
  name: "", description: "", legal_basis: "art_9_2_h", legal_basis_notes: "",
  data_category: "health_data", ai_act_risk_level: "limited", is_active: false,
  eu_region_required: false, human_review_required: false, ai_disclosure_enabled: true,
  ai_disclosure_message: "", dpia_reference: "", dpia_version: "", dpia_last_reviewed: "",
};

const emptyDPA = {
  provider_name: "", dpa_type: "standard", signed_date: "", expiration_date: "",
  covers_special_categories: false, processing_region: "eu", document_reference: "", notes: "", is_active: true,
};

export const CompliancePage: React.FC = () => {
  const [tab, setTab] = useState<Tab>("dpo");
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState("");
  const [error, setError] = useState("");

  // Projects
  const [projects, setProjects] = useState<any[]>([]);
  const [showProjectModal, setShowProjectModal] = useState(false);
  const [editingProject, setEditingProject] = useState<any | null>(null);
  const [projectForm, setProjectForm] = useState<any>(emptyProject);

  // DPAs
  const [dpas, setDPAs] = useState<any[]>([]);
  const [showDPAModal, setShowDPAModal] = useState(false);
  const [editingDPA, setEditingDPA] = useState<any | null>(null);
  const [dpaForm, setDPAForm] = useState<any>(emptyDPA);

  // DSR
  const [dsrs, setDSRs] = useState<any[]>([]);
  const [showDSRModal, setShowDSRModal] = useState(false);
  const [dsrForm, setDSRForm] = useState({ request_type: "access", subject_identifier: "", date_received: new Date().toISOString().split("T")[0], handled_by: "" });
  const [dsrSearch, setDSRSearch] = useState("");
  const [dsrSearchResult, setDSRSearchResult] = useState<any | null>(null);

  // Retention
  const [retention, setRetention] = useState<any[]>([]);

  // DPO Dashboard
  const [dashboard, setDashboard] = useState<any | null>(null);

  // Human Review Queue
  const [pendingReviews, setPendingReviews] = useState<any[]>([]);
  const [reviewModal, setReviewModal] = useState<{ token: string; action: "approved" | "rejected" } | null>(null);
  const [reviewNotes, setReviewNotes] = useState("");
  const [reviewSubmitting, setReviewSubmitting] = useState(false);

  // Consents
  const [consents, setConsents] = useState<any[]>([]);
  const [users, setUsers] = useState<any[]>([]);
  const [showConsentModal, setShowConsentModal] = useState(false);
  const [consentForm, setConsentForm] = useState({ user_id: "", consent_type: "ai_use", notes: "" });
  const [consentSubmitting, setConsentSubmitting] = useState(false);

  const showMsg = (msg: string, isErr = false) => {
    if (isErr) setError(msg); else setSuccess(msg);
    setTimeout(() => { setSuccess(""); setError(""); }, 3000);
  };

  useEffect(() => {
    loadAll();
  }, []);

  const loadAll = async () => {
    setLoading(true);
    try {
      const [p, d, r, ds, db, pr, cs, us] = await Promise.all([
        api.getComplianceProjects(),
        api.getDPAs(),
        api.getRetentionPolicies(),
        api.getDSRs(),
        api.getComplianceDashboard(),
        api.getPendingReviews(),
        api.getAllConsents(),
        api.getUsers(),
      ]);
      setProjects(p);
      setDPAs(d);
      setRetention(r);
      setDSRs(ds);
      setDashboard(db);
      setPendingReviews(pr);
      setConsents(cs);
      setUsers(us);
    } catch (e: any) {
      showMsg(e.message || "Error al cargar datos de compliance.", true);
    } finally {
      setLoading(false);
    }
  };

  const openReviewModal = (token: string, action: "approved" | "rejected") => {
    setReviewNotes("");
    setReviewModal({ token, action });
  };

  const submitReview = async () => {
    if (!reviewModal) return;
    setReviewSubmitting(true);
    try {
      await api.submitReview(reviewModal.token, { action: reviewModal.action, notes: reviewNotes });
      showMsg(reviewModal.action === "approved" ? "Respuesta aprobada." : "Respuesta rechazada.");
      setReviewModal(null);
      const pr = await api.getPendingReviews();
      setPendingReviews(pr);
    } catch (e: any) {
      showMsg(e.message, true);
    } finally {
      setReviewSubmitting(false);
    }
  };

  // ── Projects ────────────────────────────────────────────────────────────────

  const openCreateProject = () => { setEditingProject(null); setProjectForm(emptyProject); setShowProjectModal(true); };
  const openEditProject = (p: any) => { setEditingProject(p); setProjectForm({ ...p, dpia_last_reviewed: p.dpia_last_reviewed || "" }); setShowProjectModal(true); };

  const saveProject = async () => {
    try {
      const payload = { ...projectForm, dpia_last_reviewed: projectForm.dpia_last_reviewed || null };
      if (editingProject) {
        await api.updateComplianceProject(editingProject.id, payload);
        showMsg("Proyecto actualizado.");
      } else {
        await api.createComplianceProject(payload);
        showMsg("Proyecto creado.");
      }
      setShowProjectModal(false);
      loadAll();
    } catch (e: any) { showMsg(e.message, true); }
  };

  const deleteProject = async (id: string) => {
    if (!confirm("¿Eliminar este proyecto de compliance?")) return;
    await api.deleteComplianceProject(id);
    showMsg("Proyecto eliminado.");
    loadAll();
  };

  // ── DPAs ────────────────────────────────────────────────────────────────────

  const openCreateDPA = () => { setEditingDPA(null); setDPAForm(emptyDPA); setShowDPAModal(true); };
  const openEditDPA = (d: any) => { setEditingDPA(d); setDPAForm({ ...d, signed_date: d.signed_date || "", expiration_date: d.expiration_date || "" }); setShowDPAModal(true); };

  const saveDPA = async () => {
    try {
      const payload = { ...dpaForm, signed_date: dpaForm.signed_date || null, expiration_date: dpaForm.expiration_date || null };
      if (editingDPA) { await api.updateDPA(editingDPA.id, payload); showMsg("DPA actualizado."); }
      else { await api.createDPA(payload); showMsg("DPA registrado."); }
      setShowDPAModal(false);
      loadAll();
    } catch (e: any) { showMsg(e.message, true); }
  };

  const deleteDPA = async (id: string) => {
    if (!confirm("¿Eliminar este DPA?")) return;
    await api.deleteDPA(id);
    showMsg("DPA eliminado.");
    loadAll();
  };

  // ── DSR ─────────────────────────────────────────────────────────────────────

  const saveDSR = async () => {
    try {
      await api.createDSR(dsrForm);
      showMsg("Solicitud creada.");
      setShowDSRModal(false);
      loadAll();
    } catch (e: any) { showMsg(e.message, true); }
  };

  const completeDSR = async (id: string) => {
    await api.updateDSR(id, { status: "completed", date_completed: new Date().toISOString().split("T")[0] });
    showMsg("Solicitud marcada como completada.");
    loadAll();
  };

  const handleDSRSearch = async () => {
    if (!dsrSearch.trim()) return;
    try {
      const result = await api.searchDSR(dsrSearch.trim());
      setDSRSearchResult(result);
    } catch (e: any) { showMsg(e.message, true); }
  };

  // ── Consents ─────────────────────────────────────────────────────────────────

  const saveConsent = async () => {
    if (!consentForm.user_id) { showMsg("Selecciona un usuario.", true); return; }
    setConsentSubmitting(true);
    try {
      await api.recordConsent({ user_id: consentForm.user_id, consent_type: consentForm.consent_type, notes: consentForm.notes || undefined });
      showMsg("Consentimiento registrado.");
      setShowConsentModal(false);
      setConsentForm({ user_id: "", consent_type: "ai_use", notes: "" });
      const cs = await api.getAllConsents();
      setConsents(cs);
    } catch (e: any) { showMsg(e.message, true); }
    finally { setConsentSubmitting(false); }
  };

  const revokeConsent = async (consentId: string) => {
    if (!confirm("¿Revocar este consentimiento?")) return;
    try {
      await api.revokeConsent(consentId);
      showMsg("Consentimiento revocado.");
      const cs = await api.getAllConsents();
      setConsents(cs);
    } catch (e: any) { showMsg(e.message, true); }
  };

  // ── Retention ────────────────────────────────────────────────────────────────

  const saveRetention = async () => {
    try {
      await api.updateRetentionPolicies(retention);
      showMsg("Políticas de retención guardadas.");
      loadAll();
    } catch (e: any) { showMsg(e.message, true); }
  };

  const tabs: { id: Tab; label: string }[] = [
    { id: "dpo", label: "Panel DPO" },
    { id: "projects", label: "Proyectos" },
    { id: "dpas", label: "DPAs" },
    { id: "dsr", label: "Derechos del Interesado" },
    { id: "consents", label: "Consentimientos" },
    { id: "retention", label: "Retención de Datos" },
  ];

  return (
    <div className="space-y-6 p-6 max-w-6xl mx-auto pb-16">
      {/* Header */}
      <div className="pb-4 border-b border-slate-700/30">
        <h1 className="text-2xl font-bold tracking-tight text-white">Políticas de Cumplimiento</h1>
        <p className="text-xs text-text-secondary mt-1">
          Gestión de compliance GDPR y EU AI Act para despliegues sanitarios.
        </p>
      </div>

      {success && <div className="bg-success/10 border border-success/20 text-success px-4 py-2.5 rounded-lg text-xs">{success}</div>}
      {error && <div className="bg-danger/10 border border-danger/20 text-danger px-4 py-2.5 rounded-lg text-xs">{error}</div>}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-slate-700/40 overflow-x-auto">
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-xs font-semibold whitespace-nowrap border-b-2 transition-all ${tab === t.id ? "border-primary text-primary" : "border-transparent text-text-secondary hover:text-white"}`}>
            {t.label}
          </button>
        ))}
      </div>

      {loading && <div className="text-xs text-text-secondary text-center py-8">Cargando...</div>}

      {/* ── Panel DPO ─────────────────────────────────────────────────────── */}
      {tab === "dpo" && dashboard && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: "Proyectos Activos", value: dashboard.projects.active, sub: `${dashboard.projects.warnings} con alertas`, warn: dashboard.projects.warnings > 0 },
              { label: "DPAs Vigentes", value: dashboard.dpas.active, sub: `${dashboard.dpas.expiring_soon} por vencer / ${dashboard.dpas.expired} expirados`, warn: dashboard.dpas.expired > 0 || dashboard.dpas.expiring_soon > 0 },
              { label: "DPIAs Pendientes", value: dashboard.dpias.missing + dashboard.dpias.review_due, sub: `${dashboard.dpias.missing} faltantes · ${dashboard.dpias.review_due} para revisar`, warn: (dashboard.dpias.missing + dashboard.dpias.review_due) > 0 },
              { label: "Solicitudes DSR Abiertas", value: dashboard.data_subject_requests.open, sub: `de ${dashboard.data_subject_requests.total} totales`, warn: dashboard.data_subject_requests.open > 0 },
            ].map((card, i) => (
              <div key={i} className={`bg-panel border rounded-lg p-4 space-y-1 ${card.warn ? "border-warning/40" : "border-slate-700/40"}`}>
                <p className="text-xs text-text-secondary uppercase tracking-wider">{card.label}</p>
                <p className={`text-3xl font-bold ${card.warn ? "text-warning" : "text-white"}`}>{card.value}</p>
                <p className="text-[10px] text-text-secondary">{card.sub}</p>
              </div>
            ))}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="bg-panel border border-slate-700/40 rounded-lg p-4 space-y-2">
              <p className="text-xs font-semibold text-text-secondary uppercase tracking-wider">Enmascaramiento PHI</p>
              <p className="text-2xl font-bold text-white">{dashboard.audit_stats.pii_masking_rate}%</p>
              <div className="w-full bg-slate-700 rounded-full h-1.5">
                <div className="bg-primary h-1.5 rounded-full" style={{ width: `${dashboard.audit_stats.pii_masking_rate}%` }} />
              </div>
              <p className="text-[10px] text-text-secondary">de {dashboard.audit_stats.total_logs} llamadas totales</p>
            </div>

            <div className="bg-panel border border-slate-700/40 rounded-lg p-4 space-y-2">
              <p className="text-xs font-semibold text-text-secondary uppercase tracking-wider">Notificación IA (Art. 50)</p>
              <p className="text-2xl font-bold text-white">{dashboard.audit_stats.ai_disclosure_rate}%</p>
              <div className="w-full bg-slate-700 rounded-full h-1.5">
                <div className="bg-success h-1.5 rounded-full" style={{ width: `${dashboard.audit_stats.ai_disclosure_rate}%` }} />
              </div>
              <p className="text-[10px] text-text-secondary">de sesiones con disclosure entregado</p>
            </div>

            <div className="bg-panel border border-slate-700/40 rounded-lg p-4 space-y-2">
              <p className="text-xs font-semibold text-text-secondary uppercase tracking-wider">Revisión Humana</p>
              <p className="text-2xl font-bold text-white">{dashboard.human_review.completion_rate}%</p>
              <div className="w-full bg-slate-700 rounded-full h-1.5">
                <div className="bg-warning h-1.5 rounded-full" style={{ width: `${dashboard.human_review.completion_rate}%` }} />
              </div>
              <p className="text-[10px] text-text-secondary">{dashboard.human_review.pending} pendientes · {dashboard.human_review.completed} completadas</p>
            </div>
          </div>

          {/* ── Processing Purpose Distribution ─────────────────────── */}
          {dashboard.processing_purpose_distribution && Object.keys(dashboard.processing_purpose_distribution).length > 0 && (() => {
            const PURPOSE_LABELS: Record<string, string> = {
              clinical_decision: "Decisión clínica",
              administrative: "Administrativo",
              research: "Investigación",
              training: "Formación",
              sin_especificar: "Sin especificar",
            };
            const PURPOSE_COLORS: Record<string, string> = {
              clinical_decision: "bg-primary",
              administrative: "bg-success",
              research: "bg-warning",
              training: "bg-purple-400",
              sin_especificar: "bg-slate-600",
            };
            const dist = dashboard.processing_purpose_distribution as Record<string, number>;
            const total = Object.values(dist).reduce((a, b) => a + b, 0);
            return (
              <div className="bg-panel border border-slate-700/40 rounded-lg p-4 space-y-3">
                <p className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
                  Distribución por Propósito de Tratamiento
                </p>
                <div className="space-y-2">
                  {Object.entries(dist).sort((a, b) => b[1] - a[1]).map(([purpose, count]) => {
                    const pct = total > 0 ? Math.round((count / total) * 100) : 0;
                    return (
                      <div key={purpose} className="space-y-1">
                        <div className="flex justify-between items-center">
                          <span className="text-xs text-text-secondary">{PURPOSE_LABELS[purpose] || purpose}</span>
                          <span className="text-xs font-mono text-white">{count} ({pct}%)</span>
                        </div>
                        <div className="w-full bg-slate-700 rounded-full h-1.5">
                          <div className={`${PURPOSE_COLORS[purpose] || "bg-slate-400"} h-1.5 rounded-full transition-all`} style={{ width: `${pct}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
                <p className="text-[10px] text-text-secondary">{total} transacciones totales clasificadas</p>
              </div>
            );
          })()}

          {/* ── Human Review Toggle ──────────────────────────────────── */}
          <div className="bg-panel border border-slate-700/40 rounded-xl p-5 space-y-3">
            <div>
              <p className="text-sm font-bold text-white">Control de Revisión Humana</p>
              <p className="text-[10px] text-text-secondary mt-0.5">Activar o desactivar la cola de revisión por proyecto. Cuando está activo, cada respuesta de IA requiere validación antes de considerarse definitiva.</p>
            </div>
            {projects.filter((p: any) => p.is_active).length === 0 ? (
              <p className="text-xs text-text-secondary">No hay proyectos activos.</p>
            ) : (
              <div className="space-y-2">
                {projects.filter((p: any) => p.is_active).map((p: any) => (
                  <div key={p.id} className="flex items-center justify-between bg-background/40 border border-slate-700/30 rounded-lg px-4 py-2.5">
                    <div>
                      <p className="text-xs font-semibold text-white">{p.name}</p>
                      <p className="text-[10px] text-text-secondary">{RISK_LABELS[p.ai_act_risk_level]?.label || p.ai_act_risk_level}</p>
                    </div>
                    <button
                      onClick={async () => {
                        try {
                          await api.updateComplianceProject(p.id, { ...p, human_review_required: !p.human_review_required });
                          showMsg(p.human_review_required ? "Revisión humana desactivada." : "Revisión humana activada.");
                          loadAll();
                        } catch (e: any) { showMsg(e.message, true); }
                      }}
                      className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${p.human_review_required ? "bg-warning" : "bg-slate-700"}`}
                      title={p.human_review_required ? "Desactivar revisión humana" : "Activar revisión humana"}
                    >
                      <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transform transition-transform ${p.human_review_required ? "translate-x-4" : "translate-x-0"}`} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* ── Export buttons ───────────────────────────────────────── */}
          <div className="bg-panel border border-slate-700/40 rounded-xl p-4">
            <p className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-3">Exportar documentos GDPR</p>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={async () => { try { await api.exportRAT(); } catch (e: any) { showMsg(e.message, true); } }}
                className="px-3 py-1.5 text-xs border border-primary/40 text-primary rounded hover:bg-primary/10 transition-colors">
                ↓ RAT — Art. 30 GDPR (CSV)
              </button>
              <button
                onClick={async () => { try { await api.exportHumanReviewLog(); } catch (e: any) { showMsg(e.message, true); } }}
                className="px-3 py-1.5 text-xs border border-warning/40 text-warning rounded hover:bg-warning/10 transition-colors">
                ↓ Log Revisiones Humanas (CSV)
              </button>
              <button
                onClick={async () => {
                  const id = prompt("Identificador del sujeto (username o ID):");
                  if (!id) return;
                  try { await api.exportDSAR(id); } catch (e: any) { showMsg(e.message, true); }
                }}
                className="px-3 py-1.5 text-xs border border-slate-600 text-text-secondary rounded hover:text-white hover:border-slate-500 transition-colors">
                ↓ DSAR por sujeto (CSV)
              </button>
            </div>
          </div>

          {/* ── Review Queue ──────────────────────────────────────────── */}
          <div className="bg-panel border border-slate-700/40 rounded-xl p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-bold text-white">Cola de Revisión Humana</p>
                <p className="text-[10px] text-text-secondary mt-0.5">Respuestas de IA pendientes de validación sanitaria</p>
              </div>
              <div className="flex items-center gap-3">
                {pendingReviews.length > 0 && (
                  <span className="text-[9px] font-mono px-2 py-0.5 rounded border border-warning/40 text-warning bg-warning/10">
                    {pendingReviews.length} PENDIENTE{pendingReviews.length > 1 ? "S" : ""}
                  </span>
                )}
                <button onClick={async () => { const pr = await api.getPendingReviews(); setPendingReviews(pr); }}
                  className="text-xs text-text-secondary hover:text-white border border-slate-700 rounded px-3 py-1.5">
                  Actualizar
                </button>
              </div>
            </div>

            {pendingReviews.length === 0 ? (
              <div className="text-center py-8 text-xs text-text-secondary">
                No hay respuestas pendientes de revisión.
              </div>
            ) : (
              <div className="space-y-3">
                {pendingReviews.map((r: any) => {
                  const ctx = r.context;
                  const PURPOSE_LABELS: Record<string, string> = {
                    clinical_decision: "Decisión clínica",
                    administrative: "Administrativo",
                    research: "Investigación",
                    training: "Formación",
                  };
                  return (
                    <div key={r.review_token} className="border border-warning/20 bg-warning/5 rounded-lg overflow-hidden">
                      {/* Header row */}
                      <div className="flex items-center justify-between px-4 py-3 border-b border-warning/10">
                        <div className="flex items-center gap-3 flex-wrap">
                          <span className="text-[10px] font-mono text-text-secondary">
                            {r.created_at ? new Date(r.created_at).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" }) : "—"}
                          </span>
                          {ctx?.processing_purpose && (
                            <span className="text-[9px] px-2 py-0.5 rounded bg-primary/10 border border-primary/30 text-primary font-semibold">
                              {PURPOSE_LABELS[ctx.processing_purpose] || ctx.processing_purpose}
                            </span>
                          )}
                          {ctx?.pii_detected && (
                            <span className="text-[9px] px-2 py-0.5 rounded bg-warning/10 border border-warning/30 text-warning font-semibold">
                              PHI detectado
                            </span>
                          )}
                          {ctx?.guardian_events?.length > 0 && (
                            <span className="text-[9px] px-2 py-0.5 rounded bg-danger/10 border border-danger/30 text-danger font-semibold">
                              {ctx.guardian_events.length} evento{ctx.guardian_events.length > 1 ? "s" : ""} guardián
                            </span>
                          )}
                        </div>
                        <div className="flex gap-2 shrink-0">
                          <button onClick={() => openReviewModal(r.review_token, "approved")}
                            className="px-3 py-1 text-[10px] font-semibold rounded border border-success/40 text-success bg-success/10 hover:bg-success/20 transition-colors">
                            ✓ Aprobar
                          </button>
                          <button onClick={() => openReviewModal(r.review_token, "rejected")}
                            className="px-3 py-1 text-[10px] font-semibold rounded border border-danger/40 text-danger bg-danger/10 hover:bg-danger/20 transition-colors">
                            ✗ Rechazar
                          </button>
                        </div>
                      </div>

                      {/* Context detail */}
                      <div className="px-4 py-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-[10px]">
                        <div>
                          <p className="text-text-secondary uppercase tracking-wider mb-0.5">Modelo</p>
                          <p className="text-white font-mono">{ctx?.model || "—"}</p>
                        </div>
                        <div>
                          <p className="text-text-secondary uppercase tracking-wider mb-0.5">Tokens (prompt / resp.)</p>
                          <p className="text-white font-mono">
                            {ctx?.prompt_tokens ?? "—"} / {ctx?.completion_tokens ?? "—"}
                          </p>
                        </div>
                        <div>
                          <p className="text-text-secondary uppercase tracking-wider mb-0.5">Estado compliance</p>
                          <p className={`font-semibold ${ctx?.compliance_status === "passed" ? "text-success" : "text-warning"}`}>
                            {ctx?.compliance_status || "—"}
                          </p>
                        </div>
                        <div>
                          <p className="text-text-secondary uppercase tracking-wider mb-0.5">Disclosure IA</p>
                          <p className={ctx?.ai_disclosure_delivered ? "text-success" : "text-slate-500"}>
                            {ctx?.ai_disclosure_delivered ? "Entregado" : "No entregado"}
                          </p>
                        </div>
                        {ctx?.masked_entities?.length > 0 && (
                          <div className="col-span-2 md:col-span-4">
                            <p className="text-text-secondary uppercase tracking-wider mb-0.5">Entidades enmascaradas</p>
                            <p className="text-warning font-mono">
                              {ctx.masked_entities.map((e: any) => `${e.type} ×${e.count}`).join(" · ")}
                            </p>
                          </div>
                        )}
                      </div>

                      {/* AI Response text */}
                      <div className="px-4 pb-4">
                        <p className="text-[10px] text-text-secondary uppercase tracking-wider mb-2">Respuesta de IA a validar</p>
                        {r.response_text ? (
                          <div className="bg-background/60 border border-slate-700/50 rounded-lg p-3 text-xs text-white leading-relaxed whitespace-pre-wrap max-h-64 overflow-y-auto">
                            {r.response_text}
                          </div>
                        ) : (
                          <p className="text-xs text-slate-500 italic">
                            Texto no disponible — esta revisión fue generada antes de la actualización del sistema.
                          </p>
                        )}
                        <p className="text-[9px] text-slate-600 mt-1.5">
                          El prompt del paciente no se almacena (GDPR Art. 5 — minimización de datos).
                        </p>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Projects ──────────────────────────────────────────────────────── */}
      {tab === "projects" && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <p className="text-xs text-text-secondary">{projects.length} proyectos registrados</p>
            <button onClick={openCreateProject} className="bg-primary hover:bg-primary/90 text-background font-semibold px-4 py-2 rounded-lg text-xs">
              + Nuevo Proyecto
            </button>
          </div>

          {projects.length === 0 ? (
            <div className="bg-panel border border-slate-700/40 rounded-lg p-8 text-center text-xs text-text-secondary">
              No hay proyectos de compliance configurados. Crea uno para empezar.
            </div>
          ) : (
            <div className="space-y-3">
              {projects.map(p => {
                const risk = RISK_LABELS[p.ai_act_risk_level] || RISK_LABELS.limited;
                return (
                  <div key={p.id} className="bg-panel border border-slate-700/40 rounded-lg p-4">
                    <div className="flex justify-between items-start">
                      <div className="space-y-1 flex-1">
                        <div className="flex items-center gap-2 flex-wrap">
                          <h3 className="text-sm font-bold text-white">{p.name}</h3>
                          <span className={`text-[9px] font-mono px-2 py-0.5 rounded border ${p.is_active ? "text-success border-success/30 bg-success/10" : "text-slate-500 border-slate-700 bg-slate-800"}`}>
                            {p.is_active ? "Activo" : "Inactivo"}
                          </span>
                          <span className={`text-[9px] font-mono px-2 py-0.5 rounded border border-slate-700 ${risk.color}`}>{risk.label}</span>
                        </div>
                        <p className="text-xs text-text-secondary">{LEGAL_BASIS_LABELS[p.legal_basis] || p.legal_basis}</p>
                        <div className="flex gap-4 text-[10px] text-text-secondary flex-wrap">
                          {p.eu_region_required && <span className="text-primary">⚑ Región EU obligatoria</span>}
                          {p.ai_disclosure_enabled && <span className="text-success">✓ Notificación IA</span>}
                          {p.human_review_required && <span className="text-warning">⊙ Revisión humana</span>}
                          {p.dpia_reference && <span>DPIA: {p.dpia_reference}</span>}
                          {!p.dpia_reference && p.ai_act_risk_level.startsWith("high") && (
                            <span className="text-danger">⚠ DPIA requerida</span>
                          )}
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <button onClick={() => openEditProject(p)} className="text-xs text-primary hover:underline">Editar</button>
                        <button onClick={() => deleteProject(p.id)} className="text-xs text-danger hover:underline">Eliminar</button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── DPAs ──────────────────────────────────────────────────────────── */}
      {tab === "dpas" && (
        <div className="space-y-4">
          <div className="flex justify-between items-center">
            <p className="text-xs text-text-secondary">{dpas.length} DPAs registrados</p>
            <button onClick={openCreateDPA} className="bg-primary hover:bg-primary/90 text-background font-semibold px-4 py-2 rounded-lg text-xs">
              + Registrar DPA
            </button>
          </div>

          {dpas.length === 0 ? (
            <div className="bg-panel border border-slate-700/40 rounded-lg p-8 text-center text-xs text-text-secondary">
              Sin DPAs registrados. Es obligatorio firmar un DPA con cada proveedor de LLM antes de enviarles datos de pacientes (GDPR Art. 28).
            </div>
          ) : (
            <div className="bg-panel border border-slate-700/40 rounded-lg overflow-hidden">
              <table className="w-full text-xs text-left">
                <thead className="bg-background/40 border-b border-slate-700/50 text-text-secondary">
                  <tr>
                    <th className="p-3">Proveedor</th>
                    <th className="p-3">Tipo</th>
                    <th className="p-3">Región</th>
                    <th className="p-3">Art. 9</th>
                    <th className="p-3">Vencimiento</th>
                    <th className="p-3">Estado</th>
                    <th className="p-3"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/30 text-white font-mono">
                  {dpas.map(d => {
                    const st = DPA_STATUS[d.dpa_status] || DPA_STATUS.active;
                    return (
                      <tr key={d.id} className="hover:bg-background/20">
                        <td className="p-3 font-bold font-sans">{d.provider_name}</td>
                        <td className="p-3 text-text-secondary">{d.dpa_type}</td>
                        <td className="p-3">{d.processing_region.toUpperCase()}</td>
                        <td className="p-3">{d.covers_special_categories ? <span className="text-success">Sí</span> : <span className="text-danger">No</span>}</td>
                        <td className="p-3 text-text-secondary">{d.expiration_date || "—"}</td>
                        <td className="p-3"><span className={`font-semibold ${st.color}`}>{st.label}</span></td>
                        <td className="p-3 flex gap-2">
                          <button onClick={() => openEditDPA(d)} className="text-primary hover:underline">Editar</button>
                          <button onClick={() => deleteDPA(d.id)} className="text-danger hover:underline">Eliminar</button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          <div className="bg-warning/5 border border-warning/20 rounded-lg p-3 text-xs text-warning">
            <strong>Obligación GDPR Art. 28:</strong> Debe existir un DPA firmado con cada proveedor antes de enviarles datos de categoría especial (salud). Los DPAs de OpenAI y Google estándar no cubren Art. 9. Para PHI, use proveedores con DPA específico o Azure OpenAI (Microsoft Online Services DPA incluye Art. 9).
          </div>
        </div>
      )}

      {/* ── DSR ───────────────────────────────────────────────────────────── */}
      {tab === "dsr" && (
        <div className="space-y-6">
          {/* Search */}
          <div className="bg-panel border border-slate-700/40 rounded-lg p-4 space-y-3">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-text-secondary">Búsqueda por Identificador de Sujeto</h2>
            <div className="flex gap-2">
              <input type="text" value={dsrSearch} onChange={e => setDSRSearch(e.target.value)}
                placeholder="ID de paciente o usuario (pseudonimizado)"
                className="flex-1 bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary" />
              <button onClick={handleDSRSearch} className="bg-primary text-background font-semibold px-4 py-2 rounded text-xs">Buscar</button>
            </div>
            {dsrSearchResult && (
              <div className="space-y-2">
                <p className="text-xs text-white">Sujeto: <span className="font-mono text-primary">{dsrSearchResult.subject_identifier}</span></p>
                <p className="text-xs text-text-secondary">{dsrSearchResult.audit_log_count} registros en audit log · {dsrSearchResult.dsr_requests.length} solicitudes previas</p>
                {dsrSearchResult.audit_logs.slice(0, 5).map((l: any) => (
                  <div key={l.id} className="text-[10px] font-mono text-text-secondary bg-background/40 px-3 py-1 rounded">
                    {l.timestamp?.slice(0, 19)} — {l.model} — {l.compliance_status} — PII: {l.pii_detected ? "sí" : "no"}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* DSR list */}
          <div className="flex justify-between items-center">
            <p className="text-xs text-text-secondary">{dsrs.length} solicitudes registradas</p>
            <button onClick={() => setShowDSRModal(true)} className="bg-primary hover:bg-primary/90 text-background font-semibold px-4 py-2 rounded-lg text-xs">
              + Nueva Solicitud
            </button>
          </div>

          {dsrs.length === 0 ? (
            <div className="bg-panel border border-slate-700/40 rounded-lg p-8 text-center text-xs text-text-secondary">Sin solicitudes de derechos del interesado registradas.</div>
          ) : (
            <div className="bg-panel border border-slate-700/40 rounded-lg overflow-hidden">
              <table className="w-full text-xs text-left">
                <thead className="bg-background/40 border-b border-slate-700/50 text-text-secondary">
                  <tr>
                    <th className="p-3">Tipo</th>
                    <th className="p-3">Sujeto</th>
                    <th className="p-3">Recibida</th>
                    <th className="p-3">Responsable</th>
                    <th className="p-3">Estado</th>
                    <th className="p-3">Acciones</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/30 text-white font-mono">
                  {dsrs.map(d => (
                    <tr key={d.id} className="hover:bg-background/20">
                      <td className="p-3 font-sans">{DSR_TYPE_LABELS[d.request_type] || d.request_type}</td>
                      <td className="p-3 text-primary">{d.subject_identifier}</td>
                      <td className="p-3 text-text-secondary">{d.date_received}</td>
                      <td className="p-3 text-text-secondary">{d.handled_by || "—"}</td>
                      <td className="p-3">
                        <span className={`font-semibold ${d.status === "completed" ? "text-success" : d.status === "open" ? "text-warning" : "text-text-secondary"}`}>
                          {d.status === "open" ? "Abierta" : d.status === "completed" ? "Completada" : d.status}
                        </span>
                      </td>
                      <td className="p-3 flex gap-3 items-center">
                        {d.status === "open" && (
                          <button onClick={() => completeDSR(d.id)} className="text-success hover:underline text-[10px]">Completar</button>
                        )}
                        <button
                          onClick={async () => { try { await api.exportDSAR(d.subject_identifier); } catch (e: any) { showMsg(e.message, true); } }}
                          className="text-primary hover:underline text-[10px]"
                          title="Exportar datos del sujeto (DSAR)">
                          ↓ Exportar
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Retention ─────────────────────────────────────────────────────── */}
      {tab === "retention" && (
        <div className="space-y-4">
          <div className="bg-primary/5 border border-primary/20 rounded-lg p-3 text-xs text-primary">
            <strong>GDPR Art. 5(1)(e):</strong> Los datos personales no se conservarán más tiempo del necesario para los fines del tratamiento. Configure los períodos de retención con la justificación documentada para su DPIA.
          </div>

          <div className="bg-panel border border-slate-700/40 rounded-lg divide-y divide-slate-700/30">
            {retention.map((r, i) => (
              <div key={r.id} className="p-4 space-y-2">
                <div className="flex justify-between items-start">
                  <div>
                    <p className="text-sm font-semibold text-white">{LOG_TYPE_LABELS[r.log_type] || r.log_type}</p>
                    <p className="text-[10px] font-mono text-text-secondary">Última actualización: {r.last_updated?.slice(0, 19) || "—"} {r.updated_by ? `por ${r.updated_by}` : ""}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="number" min={r.log_type === "config_audit" ? 365 : 30} max={2190}
                      value={r.retention_days}
                      onChange={e => setRetention(prev => prev.map((x, j) => j === i ? { ...x, retention_days: parseInt(e.target.value) } : x))}
                      className="w-20 bg-background border border-slate-700 rounded px-2 py-1 text-xs text-white text-center focus:outline-none focus:border-primary"
                    />
                    <span className="text-xs text-text-secondary">días</span>
                  </div>
                </div>
                <textarea rows={2} value={r.justification || ""}
                  onChange={e => setRetention(prev => prev.map((x, j) => j === i ? { ...x, justification: e.target.value } : x))}
                  placeholder="Justificación documentada para la DPIA..."
                  className="w-full bg-background/40 border border-slate-700/40 rounded px-3 py-2 text-xs text-text-secondary focus:outline-none focus:border-primary"
                />
                {r.log_type === "config_audit" && (
                  <p className="text-[10px] text-warning">Mínimo no reducible: 365 días (trazabilidad de decisiones administrativas).</p>
                )}
              </div>
            ))}
          </div>

          <button onClick={saveRetention} className="bg-primary hover:bg-primary/90 text-background font-semibold px-5 py-2 rounded-lg text-xs">
            Guardar Políticas de Retención
          </button>
        </div>
      )}

      {/* ── Consents ──────────────────────────────────────────────────────── */}
      {tab === "consents" && (
        <div className="space-y-4">
          <div className="bg-primary/5 border border-primary/20 rounded-lg p-3 text-xs text-primary">
            <strong>GDPR Art. 7 y 9:</strong> El consentimiento para el uso de IA en datos de salud debe ser explícito, revocable en cualquier momento y documentado con marca temporal e IP de origen.
          </div>

          <div className="flex justify-between items-center">
            <p className="text-xs text-text-secondary">{consents.length} registros de consentimiento</p>
            <button onClick={() => { setConsentForm({ user_id: "", consent_type: "ai_use", notes: "" }); setShowConsentModal(true); }}
              className="bg-primary hover:bg-primary/90 text-background font-semibold px-4 py-2 rounded-lg text-xs">
              + Registrar Consentimiento
            </button>
          </div>

          {consents.length === 0 ? (
            <div className="bg-panel border border-slate-700/40 rounded-lg p-8 text-center text-xs text-text-secondary">
              No hay registros de consentimiento. Registra el primero para comenzar el seguimiento.
            </div>
          ) : (
            <div className="bg-panel border border-slate-700/40 rounded-lg overflow-hidden">
              <table className="w-full text-xs text-left">
                <thead className="bg-background/40 border-b border-slate-700/50 text-text-secondary">
                  <tr>
                    <th className="p-3">Usuario</th>
                    <th className="p-3">Tipo</th>
                    <th className="p-3">Versión</th>
                    <th className="p-3">Otorgado</th>
                    <th className="p-3">Estado</th>
                    <th className="p-3">Revocado</th>
                    <th className="p-3"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-700/30 text-white">
                  {consents.map((c: any) => {
                    const user = users.find((u: any) => u.id === c.user_id);
                    const CONSENT_LABELS: Record<string, string> = {
                      ai_use: "Uso de IA",
                      data_processing: "Tratamiento de datos",
                      special_category: "Categoría especial (Art. 9)",
                    };
                    return (
                      <tr key={c.id} className="hover:bg-background/20">
                        <td className="p-3 font-semibold">{user?.username || <span className="font-mono text-text-secondary text-[10px]">{String(c.user_id).slice(0, 8)}…</span>}</td>
                        <td className="p-3 text-text-secondary">{CONSENT_LABELS[c.consent_type] || c.consent_type}</td>
                        <td className="p-3 font-mono text-text-secondary">{c.version}</td>
                        <td className="p-3 font-mono text-text-secondary text-[10px]">{c.granted_at ? new Date(c.granted_at).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" }) : "—"}</td>
                        <td className="p-3">
                          {c.is_active
                            ? <span className="text-success font-semibold">Activo</span>
                            : <span className="text-slate-500">Revocado</span>}
                        </td>
                        <td className="p-3 font-mono text-text-secondary text-[10px]">{c.revoked_at ? new Date(c.revoked_at).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" }) : "—"}</td>
                        <td className="p-3">
                          {c.is_active && (
                            <button onClick={() => revokeConsent(String(c.id))} className="text-danger hover:underline text-[10px]">Revocar</button>
                          )}
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

      {/* ── Modal: Project ─────────────────────────────────────────────────── */}
      {showProjectModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-panel border border-slate-700/50 rounded-xl w-full max-w-lg max-h-[90vh] overflow-y-auto p-6 space-y-4">
            <h2 className="text-sm font-bold text-white">{editingProject ? "Editar Proyecto" : "Nuevo Proyecto de Compliance"}</h2>

            <div className="space-y-1">
              <label className="text-xs text-text-secondary">Nombre del proyecto *</label>
              <input value={projectForm.name} onChange={e => setProjectForm((p: any) => ({ ...p, name: e.target.value }))}
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary" />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-text-secondary">Descripción</label>
              <textarea rows={2} value={projectForm.description || ""} onChange={e => setProjectForm((p: any) => ({ ...p, description: e.target.value }))}
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary" />
            </div>

            <div className="space-y-1">
              <label className="text-xs text-text-secondary">Base legal (GDPR) *</label>
              <select value={projectForm.legal_basis} onChange={e => setProjectForm((p: any) => ({ ...p, legal_basis: e.target.value }))}
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary">
                {Object.entries(LEGAL_BASIS_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-xs text-text-secondary">Nivel de riesgo AI Act</label>
              <select value={projectForm.ai_act_risk_level} onChange={e => setProjectForm((p: any) => ({ ...p, ai_act_risk_level: e.target.value }))}
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary">
                {Object.entries(RISK_LABELS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs text-text-secondary">Referencia DPIA</label>
                <input value={projectForm.dpia_reference || ""} onChange={e => setProjectForm((p: any) => ({ ...p, dpia_reference: e.target.value }))}
                  placeholder="ej: DPIA-2026-001"
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary" />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-text-secondary">Última revisión DPIA</label>
                <input type="date" value={projectForm.dpia_last_reviewed || ""} onChange={e => setProjectForm((p: any) => ({ ...p, dpia_last_reviewed: e.target.value }))}
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary" />
              </div>
            </div>

            <div className="space-y-2">
              {[
                { key: "is_active", label: "Proyecto activo" },
                { key: "eu_region_required", label: "Forzar procesamiento en región EU" },
                { key: "ai_disclosure_enabled", label: "Notificación IA (Art. 50 — ya obligatoria)" },
                { key: "human_review_required", label: "Revisión humana obligatoria en respuestas clínicas" },
              ].map(({ key, label }) => (
                <label key={key} className="flex items-center gap-2 cursor-pointer">
                  <input type="checkbox" checked={!!(projectForm as any)[key]} onChange={e => setProjectForm((p: any) => ({ ...p, [key]: e.target.checked }))}
                    className="w-3 h-3 accent-primary" />
                  <span className="text-xs text-white">{label}</span>
                </label>
              ))}
            </div>

            {projectForm.ai_disclosure_enabled && (
              <div className="space-y-1">
                <label className="text-xs text-text-secondary">Mensaje de notificación IA (dejar en blanco para usar el predeterminado)</label>
                <textarea rows={2} value={projectForm.ai_disclosure_message || ""}
                  onChange={e => setProjectForm((p: any) => ({ ...p, ai_disclosure_message: e.target.value }))}
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary" />
              </div>
            )}

            <div className="flex gap-2 justify-end pt-2">
              <button onClick={() => setShowProjectModal(false)} className="px-4 py-2 text-xs text-text-secondary hover:text-white border border-slate-700 rounded-lg">Cancelar</button>
              <button onClick={saveProject} className="bg-primary text-background font-semibold px-4 py-2 rounded-lg text-xs">Guardar</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Modal: DPA ────────────────────────────────────────────────────── */}
      {showDPAModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-panel border border-slate-700/50 rounded-xl w-full max-w-lg p-6 space-y-4">
            <h2 className="text-sm font-bold text-white">{editingDPA ? "Editar DPA" : "Registrar nuevo DPA"}</h2>

            <div className="space-y-1">
              <label className="text-xs text-text-secondary">Proveedor *</label>
              <input value={dpaForm.provider_name} onChange={e => setDPAForm((d: any) => ({ ...d, provider_name: e.target.value }))}
                placeholder="ej: Azure OpenAI (Microsoft)"
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary" />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs text-text-secondary">Tipo de DPA</label>
                <select value={dpaForm.dpa_type} onChange={e => setDPAForm((d: any) => ({ ...d, dpa_type: e.target.value }))}
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary">
                  <option value="standard">Estándar</option>
                  <option value="custom_addendum">Adenda personalizada</option>
                  <option value="enterprise">Enterprise</option>
                </select>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-text-secondary">Región de procesamiento</label>
                <select value={dpaForm.processing_region} onChange={e => setDPAForm((d: any) => ({ ...d, processing_region: e.target.value }))}
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary">
                  <option value="eu">EU</option>
                  <option value="us">US</option>
                  <option value="global">Global</option>
                </select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs text-text-secondary">Fecha de firma</label>
                <input type="date" value={dpaForm.signed_date || ""} onChange={e => setDPAForm((d: any) => ({ ...d, signed_date: e.target.value }))}
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary" />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-text-secondary">Fecha de vencimiento</label>
                <input type="date" value={dpaForm.expiration_date || ""} onChange={e => setDPAForm((d: any) => ({ ...d, expiration_date: e.target.value }))}
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary" />
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs text-text-secondary">Referencia del documento</label>
              <input value={dpaForm.document_reference || ""} onChange={e => setDPAForm((d: any) => ({ ...d, document_reference: e.target.value }))}
                placeholder="URL o número de referencia"
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary" />
            </div>

            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={dpaForm.covers_special_categories} onChange={e => setDPAForm((d: any) => ({ ...d, covers_special_categories: e.target.checked }))}
                className="w-3 h-3 accent-primary" />
              <span className="text-xs text-white">Cubre datos de categoría especial (Art. 9 GDPR — datos de salud)</span>
            </label>

            <div className="flex gap-2 justify-end pt-2">
              <button onClick={() => setShowDPAModal(false)} className="px-4 py-2 text-xs text-text-secondary hover:text-white border border-slate-700 rounded-lg">Cancelar</button>
              <button onClick={saveDPA} className="bg-primary text-background font-semibold px-4 py-2 rounded-lg text-xs">Guardar</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Modal: Human Review ───────────────────────────────────────────── */}
      {reviewModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-panel border border-slate-700/50 rounded-xl w-full max-w-md p-6 space-y-4">
            <h2 className="text-sm font-bold text-white">
              {reviewModal.action === "approved" ? "Aprobar respuesta de IA" : "Rechazar respuesta de IA"}
            </h2>
            <p className="text-xs text-text-secondary">
              Token: <span className="font-mono text-white">{reviewModal.token.slice(0, 8)}…</span>
            </p>
            {reviewModal.action === "rejected" && (
              <p className="text-[10px] text-warning bg-warning/10 border border-warning/20 rounded px-3 py-2">
                Al rechazar, la respuesta quedará marcada como no validada. El solicitante deberá ser notificado manualmente.
              </p>
            )}
            <div className="space-y-1">
              <label className="text-xs text-text-secondary">Notas del revisor {reviewModal.action === "rejected" && "*"}</label>
              <textarea rows={3} value={reviewNotes} onChange={e => setReviewNotes(e.target.value)}
                placeholder={reviewModal.action === "approved" ? "Opcional — observaciones clínicas" : "Motivo del rechazo"}
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary resize-none" />
            </div>
            <div className="flex gap-2 justify-end pt-1">
              <button onClick={() => setReviewModal(null)} disabled={reviewSubmitting}
                className="px-4 py-2 text-xs text-text-secondary hover:text-white border border-slate-700 rounded-lg disabled:opacity-50">
                Cancelar
              </button>
              <button onClick={submitReview} disabled={reviewSubmitting || (reviewModal.action === "rejected" && !reviewNotes.trim())}
                className={`font-semibold px-4 py-2 rounded-lg text-xs disabled:opacity-50 ${reviewModal.action === "approved" ? "bg-success text-background" : "bg-danger text-white"}`}>
                {reviewSubmitting ? "Procesando…" : reviewModal.action === "approved" ? "Confirmar aprobación" : "Confirmar rechazo"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Modal: Consent ────────────────────────────────────────────────── */}
      {showConsentModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-panel border border-slate-700/50 rounded-xl w-full max-w-md p-6 space-y-4">
            <h2 className="text-sm font-bold text-white">Registrar Consentimiento</h2>
            <p className="text-[10px] text-text-secondary">El consentimiento quedará registrado con la IP de origen y marca temporal. Si ya existe uno activo del mismo tipo, será revocado automáticamente.</p>

            <div className="space-y-1">
              <label className="text-xs text-text-secondary">Usuario *</label>
              <select value={consentForm.user_id} onChange={e => setConsentForm(f => ({ ...f, user_id: e.target.value }))}
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary">
                <option value="">— Seleccionar usuario —</option>
                {users.map((u: any) => <option key={u.id} value={u.id}>{u.username} ({u.email})</option>)}
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-xs text-text-secondary">Tipo de consentimiento *</label>
              <select value={consentForm.consent_type} onChange={e => setConsentForm(f => ({ ...f, consent_type: e.target.value }))}
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary">
                <option value="ai_use">Uso de IA</option>
                <option value="data_processing">Tratamiento de datos</option>
                <option value="special_category">Categoría especial (Art. 9 — datos de salud)</option>
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-xs text-text-secondary">Notas (opcional)</label>
              <textarea rows={2} value={consentForm.notes} onChange={e => setConsentForm(f => ({ ...f, notes: e.target.value }))}
                placeholder="ej: Consentimiento verbal recogido durante consulta del 30/06/2026"
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary resize-none" />
            </div>

            <div className="flex gap-2 justify-end pt-2">
              <button onClick={() => setShowConsentModal(false)} disabled={consentSubmitting}
                className="px-4 py-2 text-xs text-text-secondary hover:text-white border border-slate-700 rounded-lg disabled:opacity-50">
                Cancelar
              </button>
              <button onClick={saveConsent} disabled={consentSubmitting || !consentForm.user_id}
                className="bg-primary text-background font-semibold px-4 py-2 rounded-lg text-xs disabled:opacity-50">
                {consentSubmitting ? "Registrando…" : "Registrar"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Modal: DSR ────────────────────────────────────────────────────── */}
      {showDSRModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-panel border border-slate-700/50 rounded-xl w-full max-w-md p-6 space-y-4">
            <h2 className="text-sm font-bold text-white">Nueva Solicitud de Derecho del Interesado</h2>

            <div className="space-y-1">
              <label className="text-xs text-text-secondary">Tipo de solicitud *</label>
              <select value={dsrForm.request_type} onChange={e => setDSRForm(d => ({ ...d, request_type: e.target.value }))}
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary">
                {DSR_TYPES.map(t => <option key={t} value={t}>{DSR_TYPE_LABELS[t]}</option>)}
              </select>
            </div>

            <div className="space-y-1">
              <label className="text-xs text-text-secondary">Identificador del sujeto (pseudonimizado) *</label>
              <input value={dsrForm.subject_identifier} onChange={e => setDSRForm(d => ({ ...d, subject_identifier: e.target.value }))}
                placeholder="ID de paciente o usuario"
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary" />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-xs text-text-secondary">Fecha de recepción</label>
                <input type="date" value={dsrForm.date_received} onChange={e => setDSRForm(d => ({ ...d, date_received: e.target.value }))}
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary" />
              </div>
              <div className="space-y-1">
                <label className="text-xs text-text-secondary">Responsable</label>
                <input value={dsrForm.handled_by} onChange={e => setDSRForm(d => ({ ...d, handled_by: e.target.value }))}
                  placeholder="Nombre / email"
                  className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-primary" />
              </div>
            </div>

            <p className="text-[10px] text-warning">El GDPR Art. 12 exige respuesta en 30 días. Esta solicitud quedará en estado "Abierta" hasta que se complete.</p>

            <div className="flex gap-2 justify-end pt-2">
              <button onClick={() => setShowDSRModal(false)} className="px-4 py-2 text-xs text-text-secondary hover:text-white border border-slate-700 rounded-lg">Cancelar</button>
              <button onClick={saveDSR} className="bg-primary text-background font-semibold px-4 py-2 rounded-lg text-xs">Registrar</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default CompliancePage;
