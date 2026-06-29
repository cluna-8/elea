import React, { useState, useEffect } from "react";
import { api, SecurityPolicy } from "../services/api";

const GUARDIAN_DESCRIPTIONS: Record<string, string> = {
  pii_masking: "Escanea el texto y aplica enmascaramiento o bloqueo sobre entidades sensibles (personas, DNI, email, teléfono).",
  secret_detection: "Detecta claves privadas de API o tokens de seguridad y los redacta o bloquea antes de enviarlos.",
  sensitive_routing: "Enruta de forma transparente prompts con términos clínicos sensibles a un modelo local (on-premise).",
  openai_moderation: "Filtro de contenido inapropiado — detecta odio, acoso, autolesiones, violencia y contenido sexual.",
  lakera_prompt_injection: "Defensa en tiempo real contra ataques de jailbreak e inyecciones de prompts adversarias.",
  azure_content_safety: "Clasificación y mitigación de contenido inapropiado o violento mediante filtros de seguridad en la nube.",
  llamaguard_moderations: "Escudo anti-jailbreak que analiza el prompt antes de enviarlo al modelo.",
  bedrock_guardrails: "Aplicación de temas prohibidos y filtros de seguridad corporativos en las peticiones.",
};

const LOCAL_TYPES = new Set(["pii_masking", "secret_detection", "sensitive_routing"]);

function GuardianBadge({ g }: { g: any }) {
  if (LOCAL_TYPES.has(g.guardian_type)) {
    return (
      <span className="text-[9px] bg-primary/10 text-primary border border-primary/20 px-2 py-0.5 rounded font-mono">
        Local
      </span>
    );
  }
  if (g.is_active && g.has_service_key) {
    return (
      <span className="text-[9px] bg-success/10 text-success border border-success/20 px-2 py-0.5 rounded font-mono">
        Activo (con key)
      </span>
    );
  }
  if (g.is_active) {
    return (
      <span className="text-[9px] bg-success/10 text-success border border-success/20 px-2 py-0.5 rounded font-mono">
        Activo
      </span>
    );
  }
  return (
    <span className="text-[9px] bg-slate-800 text-text-secondary border border-slate-700 px-2 py-0.5 rounded font-mono">
      Inactivo
    </span>
  );
}

function GuardianTestPanel({ guardian, onClose }: { guardian: any; onClose: () => void }) {
  const [testText, setTestText] = useState("");
  const [result, setResult] = useState<{ blocked: boolean; reason: string | null } | null>(null);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const runTest = async () => {
    if (!testText.trim()) return;
    setTesting(true);
    setResult(null);
    setError(null);
    try {
      const res = await api.testGuardian(guardian.id, testText);
      setResult(res);
    } catch (e: any) {
      setError(e.message || "Error al ejecutar el test.");
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="bg-background/40 border border-slate-700/30 rounded p-4 space-y-3">
      <div className="flex justify-between items-center">
        <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider">Panel de Prueba</span>
        <button onClick={onClose} className="text-[10px] text-text-secondary hover:text-white">Cerrar</button>
      </div>
      <textarea
        rows={3}
        placeholder="Ingrese un texto de prueba para este guardián..."
        value={testText}
        onChange={(e) => setTestText(e.target.value)}
        className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white placeholder-text-secondary focus:ring-1 focus:ring-primary resize-none"
      />
      <button
        onClick={runTest}
        disabled={testing || !testText.trim()}
        className="bg-primary hover:bg-primary/90 disabled:opacity-50 text-background font-semibold px-4 py-1.5 rounded text-xs transition-all"
      >
        {testing ? "Ejecutando..." : "Ejecutar test"}
      </button>

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 text-red-400 px-3 py-2 rounded text-xs">
          {error}
        </div>
      )}
      {result && (
        <div className={`px-3 py-2 rounded text-xs border ${result.blocked ? "bg-red-500/10 border-red-500/20 text-red-400" : "bg-success/10 border-success/20 text-success"}`}>
          <span className="font-bold">{result.blocked ? "BLOQUEADO" : "PERMITIDO"}</span>
          {result.reason && <span className="ml-2 text-text-secondary">{result.reason}</span>}
        </div>
      )}
    </div>
  );
}

export const SecurityPage: React.FC = () => {
  const [policy, setPolicy] = useState<SecurityPolicy | null>(null);
  const [guardians, setGuardians] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [testPanelFor, setTestPanelFor] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const policyData = await api.getSecurityPolicy();
        setPolicy(policyData);
        const guardiansData = await api.getGuardians();
        setGuardians(guardiansData);
      } catch (err) {
        console.error("Error fetching security data:", err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const handleTogglePolicy = () => {
    if (!policy) return;
    setPolicy({ ...policy, is_active: !policy.is_active });
  };

  const handleToggleHeadroom = () => {
    if (!policy) return;
    setPolicy({ ...policy, headroom_mode: !policy.headroom_mode });
  };

  const handleToggleGuardian = (id: string) => {
    setGuardians((prev) =>
      prev.map((g) => (g.id === id ? { ...g, is_active: !g.is_active } : g))
    );
  };

  const handleGuardianConfigChange = (id: string, key: string, value: any) => {
    setGuardians((prev) =>
      prev.map((g) =>
        g.id === id ? { ...g, config: { ...g.config, [key]: value } } : g
      )
    );
  };

  const handleGuardianFieldChange = (id: string, field: string, value: any) => {
    setGuardians((prev) =>
      prev.map((g) => (g.id === id ? { ...g, [field]: value } : g))
    );
  };

  const handleSave = async () => {
    if (!policy) return;
    try {
      setSaving(true);
      await api.updateSecurityPolicy(policy);
      for (const g of guardians) {
        await api.updateGuardian(g.id, {
          name: g.name,
          guardian_type: g.guardian_type,
          is_active: g.is_active,
          config: g.config,
          fail_mode: g.fail_mode,
          apply_on: g.apply_on,
        });
      }
      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      alert("Error al guardar la configuración de seguridad.");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center py-24 text-xs font-mono text-text-secondary">
        Cargando configuración...
      </div>
    );
  }

  return (
    <div className="space-y-8 p-6 max-w-4xl mx-auto pb-16">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 pb-4 border-b border-slate-700/30">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">
            Seguridad y Guardianes
          </h1>
          <p className="text-xs text-text-secondary mt-1">
            Configure enmascaramiento PHI/PII, guardianes de seguridad activos y optimización de contexto.
          </p>
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className="bg-primary hover:bg-primary/90 text-background font-semibold px-5 py-2 rounded-lg text-xs transition-all"
        >
          {saving ? "Guardando..." : "Guardar Cambios"}
        </button>
      </div>

      {saveSuccess && (
        <div className="bg-success/10 border border-success/20 text-success px-4 py-2.5 rounded-lg text-xs flex items-center gap-2">
          <span>¡Configuración de seguridad actualizada con éxito!</span>
        </div>
      )}

      {/* SECTION: Guardianes */}
      <div className="space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
          Catálogo de Guardianes de Seguridad
        </h2>

        <div className="grid grid-cols-1 gap-4">
          {guardians.map((g) => {
            const isPii = g.guardian_type === "pii_masking";
            const isSecret = g.guardian_type === "secret_detection";
            const isRouting = g.guardian_type === "sensitive_routing";
            const isLocal = LOCAL_TYPES.has(g.guardian_type);
            const isLakera = g.guardian_type === "lakera_prompt_injection";
            const isBedrock = g.guardian_type === "bedrock_guardrails";
            const isEngineGuardian = !isLocal;
            const showTestPanel = testPanelFor === g.id;

            return (
              <div key={g.id} className="bg-panel border border-slate-700/40 rounded-lg p-5 space-y-4">
                <div className="flex justify-between items-start">
                  <div className="space-y-1 flex-1 mr-4">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="text-sm font-bold text-white">{g.name}</h3>
                      <GuardianBadge g={g} />
                    </div>
                    <p className="text-xs text-text-secondary">
                      {GUARDIAN_DESCRIPTIONS[g.guardian_type] || "Guardián de seguridad configurable."}
                    </p>
                  </div>
                  <div className="flex flex-col items-end gap-2">
                    <button
                      onClick={() => handleToggleGuardian(g.id)}
                      className={`px-3 py-1 rounded text-xs font-semibold border transition-all whitespace-nowrap ${
                        g.is_active
                          ? "bg-success/10 border-success/30 text-success"
                          : "bg-slate-800 border-slate-700 text-text-secondary"
                      }`}
                    >
                      {g.is_active ? "Activo" : "Inactivo"}
                    </button>
                    {isEngineGuardian && (
                      <button
                        onClick={() => setTestPanelFor(showTestPanel ? null : g.id)}
                        className="px-2 py-0.5 rounded text-[10px] border border-slate-600 text-text-secondary hover:text-white hover:border-primary transition-all"
                      >
                        {showTestPanel ? "Cerrar test" : "Probar"}
                      </button>
                    )}
                  </div>
                </div>

                {g.is_active && (
                  <div className="bg-background/20 border border-slate-700/30 rounded p-4 space-y-4 text-xs text-white">

                    {/* Engine-backed: fail_mode + apply_on */}
                    {isEngineGuardian && (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        <div className="space-y-1">
                          <span className="text-xs text-text-secondary">Modo de fallo</span>
                          <select
                            value={g.fail_mode || "log"}
                            onChange={(e) => handleGuardianFieldChange(g.id, "fail_mode", e.target.value)}
                            className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white focus:outline-none focus:border-primary"
                          >
                            <option value="block">Bloquear petición</option>
                            <option value="log">Solo registrar</option>
                          </select>
                        </div>
                        <div className="space-y-1">
                          <span className="text-xs text-text-secondary">Aplicar en</span>
                          <select
                            value={g.apply_on || "pre_call"}
                            onChange={(e) => handleGuardianFieldChange(g.id, "apply_on", e.target.value)}
                            className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white focus:outline-none focus:border-primary"
                          >
                            <option value="pre_call">Antes del modelo (pre_call)</option>
                            <option value="post_call">Después del modelo (post_call)</option>
                            <option value="both">Ambos</option>
                          </select>
                        </div>
                      </div>
                    )}

                    {/* PII Masking Config */}
                    {isPii && (
                      <div className="space-y-3">
                        <div className="flex flex-col md:flex-row gap-4">
                          <div className="flex-1 space-y-1">
                            <span className="text-xs text-text-secondary">Acción del Guardián</span>
                            <select
                              value={g.config.action || "MASK"}
                              onChange={(e) => handleGuardianConfigChange(g.id, "action", e.target.value)}
                              className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white focus:outline-none focus:border-primary"
                            >
                              <option value="MASK">Enmascarar (Reemplazar con marcadores)</option>
                              <option value="BLOCK">Bloquear petición entera</option>
                            </select>
                          </div>
                        </div>
                        <div className="space-y-1">
                          <label className="text-xs text-text-secondary">
                            Nombres y Términos Personalizados a Capturar
                          </label>
                          <textarea
                            rows={2}
                            placeholder="Ej: Juan Pérez, María Rodríguez, Carlos Gómez"
                            value={(g.config.custom_names || []).join(", ")}
                            onChange={(e) => {
                              const list = e.target.value.split(",").map((n: string) => n.trim()).filter((n: string) => n !== "");
                              handleGuardianConfigChange(g.id, "custom_names", list);
                            }}
                            className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white placeholder-text-secondary focus:ring-1 focus:ring-primary"
                          />
                          <p className="text-[10px] text-text-secondary">
                            Estos nombres se enmascaran como <code>&lt;PERSON_N&gt;</code> de forma determinista, sin modelos predictivos.
                          </p>
                        </div>
                      </div>
                    )}

                    {/* Secret Detection Config */}
                    {isSecret && (
                      <div className="space-y-1.5">
                        <span className="text-xs text-text-secondary">Acción del Guardián</span>
                        <select
                          value={g.config.action || "BLOCK"}
                          onChange={(e) => handleGuardianConfigChange(g.id, "action", e.target.value)}
                          className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white focus:outline-none focus:border-primary"
                        >
                          <option value="BLOCK">Bloquear (Impedir envío del prompt con llaves detectadas)</option>
                          <option value="REDACT">Redactar (Reemplazar con [SECRETO_REDACTADO])</option>
                        </select>
                      </div>
                    )}

                    {/* Sensitive Routing Config */}
                    {isRouting && (
                      <div className="space-y-3">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          <div className="space-y-1">
                            <span className="text-xs text-text-secondary">Modelo Local (On-Premise)</span>
                            <input
                              type="text"
                              value={g.config.on_premise_model || "ollama-llama3"}
                              onChange={(e) => handleGuardianConfigChange(g.id, "on_premise_model", e.target.value)}
                              className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white focus:outline-none focus:border-primary"
                            />
                          </div>
                          <div className="space-y-1">
                            <span className="text-xs text-text-secondary">Sesión Persistente</span>
                            <select
                              value={g.config.sticky_session ? "true" : "false"}
                              onChange={(e) => handleGuardianConfigChange(g.id, "sticky_session", e.target.value === "true")}
                              className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white focus:outline-none focus:border-primary"
                            >
                              <option value="true">Activa (toda la sesión en local)</option>
                              <option value="false">Inactiva (solo el prompt que contiene datos)</option>
                            </select>
                          </div>
                        </div>
                        <div className="space-y-1">
                          <span className="text-xs text-text-secondary">Términos Clínicos Sensibles (separados por comas)</span>
                          <textarea
                            rows={2}
                            value={(g.config.keywords || []).join(", ")}
                            onChange={(e) => {
                              const list = e.target.value.split(",").map((k: string) => k.trim()).filter((k: string) => k !== "");
                              handleGuardianConfigChange(g.id, "keywords", list);
                            }}
                            className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white focus:outline-none focus:border-primary"
                          />
                        </div>
                      </div>
                    )}

                    {/* Lakera / PromptGuard threshold */}
                    {isLakera && (
                      <div className="space-y-2">
                        <span className="text-xs text-text-secondary">Umbral de Detección (Threshold)</span>
                        <input
                          type="range"
                          min="0.1"
                          max="1.0"
                          step="0.05"
                          value={g.config.threshold || 0.7}
                          onChange={(e) => handleGuardianConfigChange(g.id, "threshold", parseFloat(e.target.value))}
                          className="w-full accent-primary bg-background border border-slate-700 rounded"
                        />
                        <div className="flex justify-between text-[9px] text-text-secondary font-mono">
                          <span>Sensible (0.1)</span>
                          <span className="text-primary font-bold">Actual: {g.config.threshold || 0.7}</span>
                          <span>Estricto (1.0)</span>
                        </div>
                      </div>
                    )}

                    {/* Bedrock: blocked topics */}
                    {isBedrock && (
                      <div className="space-y-2">
                        <span className="text-xs text-text-secondary">Temas Restringidos (separados por comas)</span>
                        <textarea
                          rows={2}
                          placeholder="Ej: consejo financiero, asesoría legal no autorizada"
                          value={(g.config.blocked_topics || []).join(", ")}
                          onChange={(e) => {
                            const list = e.target.value.split(",").map((t: string) => t.trim()).filter((t: string) => t !== "");
                            handleGuardianConfigChange(g.id, "blocked_topics", list);
                          }}
                          className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white focus:outline-none focus:border-primary"
                        />
                      </div>
                    )}
                  </div>
                )}

                {/* Test panel (only for engine-backed guardians) */}
                {showTestPanel && (
                  <GuardianTestPanel guardian={g} onClose={() => setTestPanelFor(null)} />
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* SECTION: Context Optimization (Headroom) */}
      <div className="bg-panel border border-slate-700/40 rounded-lg p-5 space-y-4">
        <div className="flex justify-between items-start">
          <div className="space-y-1">
            <h2 className="text-sm font-bold uppercase tracking-wider text-text-secondary">
              Optimización de Contexto (Headroom)
            </h2>
            <p className="text-xs text-text-secondary">
              Comprime automáticamente prompts largos y código antes de enviarlos al modelo.
            </p>
          </div>
          <button
            onClick={handleToggleHeadroom}
            className={`px-3 py-1 rounded text-xs font-semibold border transition-all ${
              policy?.headroom_mode
                ? "bg-success/10 border-success/30 text-success"
                : "bg-slate-800 border-slate-700 text-text-secondary"
            }`}
          >
            {policy?.headroom_mode ? "Activo" : "Inactivo"}
          </button>
        </div>

        <div className="bg-background/40 border border-slate-700/20 rounded p-4 text-xs text-text-secondary">
          <p>
            Al activar Headroom, los textos redundantes, espacios extra y comentarios de código se limpian localmente
            en la pasarela. Los prompts extensos (contextos RAG) se optimizan logrando ahorrar entre un 60% y 95% de tokens,
            reduciendo la factura mensual de APIs y acelerando la velocidad de respuesta del modelo.
          </p>
        </div>
      </div>
    </div>
  );
};

export default SecurityPage;
