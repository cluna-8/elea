import React, { useState, useEffect } from "react";
import { api, SecurityPolicy } from "../services/api";

export const SecurityPage: React.FC = () => {
  const [policy, setPolicy] = useState<SecurityPolicy | null>(null);
  const [guardians, setGuardians] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

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

  // Guardians changes
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

  const handleSave = async () => {
    if (!policy) return;
    try {
      setSaving(true);
      // 1. Save general policy
      await api.updateSecurityPolicy(policy);
      
      // 2. Save all guardians
      for (const g of guardians) {
        await api.updateGuardian(g.id, {
          name: g.name,
          guardian_type: g.guardian_type,
          is_active: g.is_active,
          config: g.config
        });
      }

      setSaveSuccess(true);
      setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      alert("Error al guardar la política y los guardianes de seguridad.");
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
            Configure las reglas de enmascaramiento PHI/PII, guardianes activos y optimización de contexto.
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
          <span>¡Políticas y guardianes de seguridad actualizados con éxito!</span>
        </div>
      )}

      {/* SECTION: Guardianes de Seguridad */}
      <div className="space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
          Catálogo de Guardianes de Seguridad
        </h2>

        <div className="grid grid-cols-1 gap-4">
          {guardians.map((g) => {
            const isPii = g.guardian_type === "pii_masking";
            const isSecret = g.guardian_type === "secret_detection";
            const isRouting = g.guardian_type === "sensitive_routing";
            const isModOpenAI = g.guardian_type === "openai_moderation";
            const isLakera = g.guardian_type === "lakera_prompt_injection";
            const isAzureSafety = g.guardian_type === "azure_content_safety";
            const isLlamaGuard = g.guardian_type === "llamaguard_moderations";
            const isBedrock = g.guardian_type === "bedrock_guardrails";

            return (
              <div key={g.id} className="bg-panel border border-slate-700/40 rounded-lg p-5 space-y-4">
                <div className="flex justify-between items-start">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-bold text-white">{g.name}</h3>
                      {(isPii || isSecret || isRouting) ? (
                        <span className="text-[9px] bg-primary/10 text-primary border border-primary/20 px-2 py-0.5 rounded font-mono">
                          Local
                        </span>
                      ) : (
                        <span className="text-[9px] bg-slate-800 text-text-secondary border border-slate-700 px-2 py-0.5 rounded font-mono">
                          Nube / Simulación
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-text-secondary">
                      {isPii && "Escanea el texto y aplica enmascaramiento o bloqueo sobre entidades sensibles."}
                      {isSecret && "Detecta claves privadas de API o tokens de seguridad y los redacta o bloquea."}
                      {isRouting && "Enruta de forma transparente prompts específicos a un modelo local (on-premise)."}
                      {isModOpenAI && "Moderación de contenido en la nube utilizando las categorías oficiales de OpenAI (odio, violencia, etc.)."}
                      {isLakera && "Defensa en tiempo real contra ataques de jailbreak e inyecciones de prompts adversarias."}
                      {isAzureSafety && "Filtro de seguridad de Microsoft Azure para clasificar y mitigar contenido inapropiado o violento."}
                      {isLlamaGuard && "Clasificador de seguridad local basado en la taxonomía oficial de LlamaGuard (Meta)."}
                      {isBedrock && "Aplicación de temas prohibidos y filtros de seguridad en las peticiones de AWS Bedrock."}
                    </p>
                  </div>
                  <button
                    onClick={() => handleToggleGuardian(g.id)}
                    className={`px-3 py-1 rounded text-xs font-semibold border transition-all ${
                      g.is_active
                        ? "bg-success/10 border-success/30 text-success"
                        : "bg-slate-800 border-slate-700 text-text-secondary"
                    }`}
                  >
                    {g.is_active ? "Activo" : "Inactivo"}
                  </button>
                </div>

                {g.is_active && (
                  <div className="bg-background/20 border border-slate-700/30 rounded p-4 space-y-4 text-xs text-white">
                    {/* PII Masking Guardian Config */}
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
                              <option value="MASK">Enmascarar (Reemplazar con tokens de marcadores)</option>
                              <option value="BLOCK">Bloquear petición entera (Lanza error inmediato)</option>
                            </select>
                          </div>
                        </div>

                        {/* Custom Names list input */}
                        <div className="space-y-1">
                          <label className="text-xs text-text-secondary flex items-center gap-1">
                            Nombres y Términos Personalizados a Capturar
                          </label>
                          <textarea
                            rows={2}
                            placeholder="Ingrese nombres separados por comas (ej: Juan Pérez, María Rodríguez, Carlos Gómez)"
                            value={(g.config.custom_names || []).join(", ")}
                            onChange={(e) => {
                              const list = e.target.value.split(",").map(n => n.trim()).filter(n => n !== "");
                              handleGuardianConfigChange(g.id, "custom_names", list);
                            }}
                            className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white placeholder-text-secondary focus:ring-1 focus:ring-primary"
                          />
                          <p className="text-[10px] text-text-secondary">
                            * Estos nombres serán capturados de forma 100% determinista y enmascarados como <code>&lt;PERSON_N&gt;</code> sin depender de modelos predictivos.
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
                          <option value="BLOCK">Bloquear (Impedir el envío del prompt con llaves de API)</option>
                          <option value="REDACT">Redactar (Reemplazar con [SECRETO_REDACTADO])</option>
                        </select>
                      </div>
                    )}

                    {/* Sensitive Routing Config */}
                    {isRouting && (
                      <div className="space-y-3">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          <div className="space-y-1">
                            <span className="text-xs text-text-secondary">Enrutar al Modelo Local (On-Premise)</span>
                            <input
                              type="text"
                              value={g.config.on_premise_model || "ollama-llama3"}
                              onChange={(e) => handleGuardianConfigChange(g.id, "on_premise_model", e.target.value)}
                              className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white focus:outline-none focus:border-primary"
                            />
                          </div>
                          <div className="space-y-1">
                            <span className="text-xs text-text-secondary">Sesión Persistente (Sticky Session)</span>
                            <select
                              value={g.config.sticky_session ? "true" : "false"}
                              onChange={(e) => handleGuardianConfigChange(g.id, "sticky_session", e.target.value === "true")}
                              className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white focus:outline-none focus:border-primary"
                            >
                              <option value="true">Activa (Toda la sesión se queda en local tras detectar datos)</option>
                              <option value="false">Inactiva (Solo se enruta el prompt que contiene los datos)</option>
                            </select>
                          </div>
                        </div>

                        <div className="space-y-1">
                          <span className="text-xs text-text-secondary">Términos Clave Clínicos a Monitorear (Separados por comas)</span>
                          <textarea
                            rows={2}
                            value={(g.config.keywords || []).join(", ")}
                            onChange={(e) => {
                              const list = e.target.value.split(",").map(k => k.trim()).filter(k => k !== "");
                              handleGuardianConfigChange(g.id, "keywords", list);
                            }}
                            className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white focus:outline-none focus:border-primary"
                          />
                        </div>
                      </div>
                    )}

                    {/* Lakera Prompt Injection Config */}
                    {isLakera && (
                      <div className="space-y-2">
                        <span className="text-xs text-text-secondary">Umbral de Detección de Inyección (Threshold)</span>
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

                    {/* AWS Bedrock Guardrails Config */}
                    {isBedrock && (
                      <div className="space-y-2">
                        <span className="text-xs text-text-secondary">Temas Restringidos a Bloquear (Separados por comas)</span>
                        <textarea
                          rows={2}
                          placeholder="Ej: consejo financiero, asesoría legal no autorizada"
                          value={(g.config.blocked_topics || []).join(", ")}
                          onChange={(e) => {
                            const list = e.target.value.split(",").map(t => t.trim()).filter(t => t !== "");
                            handleGuardianConfigChange(g.id, "blocked_topics", list);
                          }}
                          className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white focus:outline-none focus:border-primary"
                        />
                      </div>
                    )}

                    {/* General info for other simulation guardians */}
                    {(!isPii && !isSecret && !isRouting && !isLakera && !isBedrock) && (
                      <div className="text-xs text-text-secondary bg-background/40 p-3 rounded border border-slate-700/20">
                        <span>Este guardián está activo en modo simulado para demostración técnica. Palabras clave prohibidas como <code>"bomba"</code> o <code>"matar"</code> en el Playground gatillará este bloqueo.</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* SECTION: Context Optimization Card (Headroom) */}
      <div className="bg-panel border border-slate-700/40 rounded-lg p-5 space-y-4">
        <div className="flex justify-between items-start">
          <div className="space-y-1">
            <h2 className="text-sm font-bold uppercase tracking-wider text-text-secondary">
              Optimización de Contexto (Headroom)
            </h2>
            <p className="text-xs text-text-secondary">
              Comprime automáticamente prompts largos y código antes de enviarlos al LLM.
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
            Al activar **Headroom**, los textos redundantes, espacios extra y comentarios de código se limpian localmente en la pasarela. Los prompts muy extensos (como contextos de RAG) se optimizan logrando ahorrar entre un **60% y 95% de tokens**, reduciendo la factura mensual de APIs y acelerando la velocidad de respuesta del modelo.
          </p>
        </div>
      </div>
    </div>
  );
};
export default SecurityPage;
