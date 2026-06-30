import React, { useState, useEffect } from "react";
import { api, SecurityPolicy } from "../services/api";

const GUARDIAN_DESCRIPTIONS: Record<string, string> = {
  pii_masking: "Enmascaramiento local por expresiones regulares. Detecta DNI, CUIL, emails, teléfonos y personas sin depender de servicios externos.",
  secret_detection: "Detecta claves de API o tokens de seguridad y los redacta antes de enviarlos al modelo.",
  sensitive_routing: "Enruta prompts con términos clínicos sensibles a un modelo local on-premise de forma transparente.",
  presidio: "Detección NLP real de PII/PHI mediante Microsoft Presidio. Requiere los servicios Presidio Analyzer y Anonymizer.",
  openai_moderation: "Filtro de contenido: detecta odio, acoso, autolesiones, violencia y contenido sexual.",
  lakera_prompt_injection: "Defensa en tiempo real contra ataques de jailbreak e inyecciones de prompts adversarias.",
  azure_content_safety: "Clasificación y mitigación de contenido inapropiado mediante filtros de seguridad en la nube.",
  llamaguard_moderations: "Escudo anti-jailbreak que analiza el prompt antes de enviarlo al modelo.",
  bedrock_guardrails: "Aplicación de temas prohibidos y filtros de seguridad corporativos en las peticiones.",
};

const GUARDIAN_ICONS: Record<string, string> = {
  pii_masking: "⬡",
  secret_detection: "◈",
  sensitive_routing: "⇄",
  presidio: "⬡",
  openai_moderation: "◉",
  lakera_prompt_injection: "⚡",
  azure_content_safety: "◈",
  llamaguard_moderations: "◉",
  bedrock_guardrails: "◈",
};

const LOCAL_TYPES = new Set(["pii_masking", "secret_detection", "sensitive_routing"]);

export const SecurityPage: React.FC = () => {
  const [policy, setPolicy] = useState<SecurityPolicy | null>(null);
  const [guardians, setGuardians] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [testText, setTestText] = useState("");
  const [testResult, setTestResult] = useState<{ blocked: boolean; reason: string | null } | null>(null);
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const [policyData, guardiansData] = await Promise.all([
          api.getSecurityPolicy(),
          api.getGuardians(),
        ]);
        setPolicy(policyData);
        setGuardians(guardiansData);
      } catch {
        // silent
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleToggleGuardian = (id: string) => {
    setGuardians((prev) => prev.map((g) => (g.id === id ? { ...g, is_active: !g.is_active } : g)));
  };

  const handleGuardianConfigChange = (id: string, key: string, value: any) => {
    setGuardians((prev) =>
      prev.map((g) => (g.id === id ? { ...g, config: { ...g.config, [key]: value } } : g))
    );
  };

  const handleGuardianFieldChange = (id: string, field: string, value: any) => {
    setGuardians((prev) => prev.map((g) => (g.id === id ? { ...g, [field]: value } : g)));
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
    } catch {
      alert("Error al guardar la configuración de seguridad.");
    } finally {
      setSaving(false);
    }
  };

  const handleSelectCard = (id: string) => {
    if (selectedId === id) {
      setSelectedId(null);
    } else {
      setSelectedId(id);
      setTestText("");
      setTestResult(null);
      setTestError(null);
    }
  };

  const runTest = async (guardian: any) => {
    if (!testText.trim()) return;
    setTesting(true);
    setTestResult(null);
    setTestError(null);
    try {
      const res = await api.testGuardian(guardian.id, testText);
      setTestResult(res);
    } catch (e: any) {
      setTestError(e.message || "Error al ejecutar el test.");
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex justify-center items-center py-24 text-xs font-mono text-text-secondary">
        Cargando configuración...
      </div>
    );
  }

  const selected = guardians.find((g) => g.id === selectedId) || null;
  const isLocal = selected ? LOCAL_TYPES.has(selected.guardian_type) || selected.guardian_type === "presidio" : false;
  const isPii = selected?.guardian_type === "pii_masking";
  const isSecret = selected?.guardian_type === "secret_detection";
  const isRouting = selected?.guardian_type === "sensitive_routing";
  const isPresidio = selected?.guardian_type === "presidio";
  const isLakera = selected?.guardian_type === "lakera_prompt_injection";
  const isBedrock = selected?.guardian_type === "bedrock_guardrails";

  return (
    <div className="space-y-8 pb-16">
      {/* Header */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 pb-4 border-b border-slate-700/30">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white">Seguridad y Guardianes</h1>
          <p className="text-xs text-text-secondary mt-1">
            Configure guardianes de seguridad, enmascaramiento PHI/PII y optimización de contexto.
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
        <div className="bg-success/10 border border-success/20 text-success px-4 py-2.5 rounded-lg text-xs">
          ¡Configuración actualizada con éxito!
        </div>
      )}

      {/* ── Guardians card grid ── */}
      <div className="space-y-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary">
          Guardianes de Seguridad
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {guardians.map((g) => {
            const local = LOCAL_TYPES.has(g.guardian_type);
            const isSelected = selectedId === g.id;

            return (
              <div
                key={g.id}
                onClick={() => handleSelectCard(g.id)}
                className={`border rounded-lg p-4 space-y-3 cursor-pointer transition-all ${
                  isSelected
                    ? "border-primary/40 bg-primary/5 ring-1 ring-primary/20"
                    : g.is_active
                    ? "border-success/20 bg-success/5 hover:border-slate-600"
                    : "border-slate-700/40 bg-background/10 hover:border-slate-600"
                }`}
              >
                {/* Row 1: icon + name + status */}
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-text-secondary text-base leading-none flex-shrink-0">
                      {GUARDIAN_ICONS[g.guardian_type] || "◈"}
                    </span>
                    <span className="font-semibold text-white text-xs truncate">{g.name}</span>
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleToggleGuardian(g.id); }}
                    className={`flex-shrink-0 px-2 py-0.5 rounded text-[10px] font-bold border transition-all ${
                      g.is_active
                        ? "bg-success/10 border-success/30 text-success"
                        : "bg-slate-800 border-slate-700 text-text-secondary hover:border-slate-600"
                    }`}
                  >
                    {g.is_active ? "Activo" : "Inactivo"}
                  </button>
                </div>

                {/* Row 2: type chips */}
                <div className="flex gap-1.5 flex-wrap">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold border ${
                    local
                      ? "bg-primary/10 border-primary/20 text-primary"
                      : "bg-slate-800 border-slate-700 text-text-secondary"
                  }`}>
                    {local ? "Local" : "Motor IA"}
                  </span>
                  {!local && (
                    <span className="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-800 border border-slate-700 text-text-secondary">
                      {g.apply_on || "pre_call"}
                    </span>
                  )}
                </div>

                {/* Row 3: description */}
                <p className="text-[11px] text-text-secondary leading-relaxed line-clamp-2">
                  {GUARDIAN_DESCRIPTIONS[g.guardian_type] || "Guardián de seguridad configurable."}
                </p>

                {/* Row 4: configure hint */}
                <div className="flex items-center justify-between pt-0.5">
                  <span className={`text-[10px] transition-colors ${isSelected ? "text-primary" : "text-text-secondary"}`}>
                    {isSelected ? "▲ Configurando" : "▼ Configurar"}
                  </span>
                  {!local && (
                    <span className="text-[10px] text-text-secondary">Motor externo</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* ── Config panel (below grid, for selected guardian) ── */}
        {selected && (
          <div className="border border-primary/20 rounded-lg bg-background/30 p-5 space-y-5">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-sm font-bold text-white">{selected.name}</span>
                <span className="ml-2 text-xs text-text-secondary">— Configuración</span>
              </div>
              <button
                onClick={() => setSelectedId(null)}
                className="text-text-secondary hover:text-white text-xs"
              >
                Cerrar ✕
              </button>
            </div>

            <div className="space-y-4 text-xs text-white">
              {/* Engine: fail_mode + apply_on */}
              {!isLocal && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="space-y-1.5">
                    <label className="text-text-secondary font-medium">Modo de fallo</label>
                    <select
                      value={selected.fail_mode || "log"}
                      onChange={(e) => handleGuardianFieldChange(selected.id, "fail_mode", e.target.value)}
                      className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none focus:border-primary"
                    >
                      <option value="block">Bloquear petición</option>
                      <option value="log">Solo registrar</option>
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-text-secondary font-medium">Aplicar en</label>
                    <select
                      value={selected.apply_on || "pre_call"}
                      onChange={(e) => handleGuardianFieldChange(selected.id, "apply_on", e.target.value)}
                      className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none focus:border-primary"
                    >
                      <option value="pre_call">Antes del modelo (pre_call)</option>
                      <option value="post_call">Después del modelo (post_call)</option>
                      <option value="both">Ambos</option>
                    </select>
                  </div>
                </div>
              )}

              {/* Presidio (real NLP) */}
              {isPresidio && (
                <div className="space-y-4">
                  <div className="bg-background/30 border border-primary/20 rounded p-3 text-[11px] text-text-secondary space-y-1">
                    <p className="font-semibold text-white">Servicios requeridos</p>
                    <p>
                      Presidio corre como dos microservicios HTTP independientes. Podés agregarlos a{" "}
                      <span className="font-mono text-white">docker-compose.yml</span> usando las imágenes oficiales de Microsoft:
                    </p>
                    <div className="mt-2 font-mono text-[10px] text-warning/80 bg-black/30 rounded p-2 space-y-0.5">
                      <p>mcr.microsoft.com/presidio-analyzer → puerto 3000</p>
                      <p>mcr.microsoft.com/presidio-anonymizer → puerto 3001</p>
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <label className="text-text-secondary font-medium">Presidio Analyzer URL</label>
                      <input
                        type="url"
                        value={selected.config.analyzer_url || ""}
                        onChange={(e) => handleGuardianConfigChange(selected.id, "analyzer_url", e.target.value)}
                        placeholder="http://presidio-analyzer:3000"
                        className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-text-secondary font-medium">Presidio Anonymizer URL</label>
                      <input
                        type="url"
                        value={selected.config.anonymizer_url || ""}
                        onChange={(e) => handleGuardianConfigChange(selected.id, "anonymizer_url", e.target.value)}
                        placeholder="http://presidio-anonymizer:3001"
                        className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary"
                      />
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <label className="text-text-secondary font-medium">Idioma de análisis</label>
                      <select
                        value={selected.config.language || "es"}
                        onChange={(e) => handleGuardianConfigChange(selected.id, "language", e.target.value)}
                        className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none focus:border-primary"
                      >
                        <option value="es">Español</option>
                        <option value="en">English</option>
                      </select>
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-text-secondary font-medium">Acción al detectar</label>
                      <select
                        value={selected.config.action || "MASK"}
                        onChange={(e) => handleGuardianConfigChange(selected.id, "action", e.target.value)}
                        className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none focus:border-primary"
                      >
                        <option value="MASK">Anonimizar (Presidio Anonymizer)</option>
                        <option value="BLOCK">Bloquear petición entera</option>
                      </select>
                    </div>
                  </div>
                  <div className="text-[11px] text-text-secondary bg-background/20 rounded p-3">
                    <span className="font-semibold text-white">Sin URL configurada:</span>{" "}
                    el guardián <span className="text-warning">PII/PHI (regex)</span> sigue activo como fallback. Presidio solo toma precedencia cuando ambas URLs están configuradas.
                  </div>
                </div>
              )}

              {/* PII Masking */}
              {isPii && (
                <div className="space-y-3">
                  <div className="space-y-1.5">
                    <label className="text-text-secondary font-medium">Acción</label>
                    <select
                      value={selected.config.action || "MASK"}
                      onChange={(e) => handleGuardianConfigChange(selected.id, "action", e.target.value)}
                      className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none focus:border-primary"
                    >
                      <option value="MASK">Enmascarar (reemplazar con marcadores)</option>
                      <option value="BLOCK">Bloquear petición entera</option>
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-text-secondary font-medium">
                      Nombres personalizados a capturar
                    </label>
                    <textarea
                      rows={2}
                      placeholder="Ej: Juan Pérez, María Rodríguez"
                      value={(selected.config.custom_names || []).join(", ")}
                      onChange={(e) => {
                        const list = e.target.value.split(",").map((n: string) => n.trim()).filter(Boolean);
                        handleGuardianConfigChange(selected.id, "custom_names", list);
                      }}
                      className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary resize-none"
                    />
                    <p className="text-[10px] text-text-secondary">
                      Se enmascaran como <code>&lt;PERSON_N&gt;</code> de forma determinista.
                    </p>
                  </div>
                </div>
              )}

              {/* Secret Detection */}
              {isSecret && (
                <div className="space-y-1.5">
                  <label className="text-text-secondary font-medium">Acción</label>
                  <select
                    value={selected.config.action || "BLOCK"}
                    onChange={(e) => handleGuardianConfigChange(selected.id, "action", e.target.value)}
                    className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none focus:border-primary"
                  >
                    <option value="BLOCK">Bloquear (impedir envío con llaves detectadas)</option>
                    <option value="REDACT">Redactar (reemplazar con [SECRETO_REDACTADO])</option>
                  </select>
                </div>
              )}

              {/* Sensitive Routing */}
              {isRouting && (
                <div className="space-y-3">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="space-y-1.5">
                      <label className="text-text-secondary font-medium">Modelo local (on-premise)</label>
                      <input
                        type="text"
                        value={selected.config.on_premise_model || "ollama-llama3"}
                        onChange={(e) => handleGuardianConfigChange(selected.id, "on_premise_model", e.target.value)}
                        className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none focus:border-primary"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-text-secondary font-medium">Sesión persistente</label>
                      <select
                        value={selected.config.sticky_session ? "true" : "false"}
                        onChange={(e) => handleGuardianConfigChange(selected.id, "sticky_session", e.target.value === "true")}
                        className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none focus:border-primary"
                      >
                        <option value="true">Activa (toda la sesión en local)</option>
                        <option value="false">Inactiva (solo el prompt afectado)</option>
                      </select>
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-text-secondary font-medium">Términos clínicos sensibles</label>
                    <textarea
                      rows={2}
                      value={(selected.config.keywords || []).join(", ")}
                      onChange={(e) => {
                        const list = e.target.value.split(",").map((k: string) => k.trim()).filter(Boolean);
                        handleGuardianConfigChange(selected.id, "keywords", list);
                      }}
                      className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary resize-none"
                    />
                  </div>
                </div>
              )}

              {/* Lakera threshold */}
              {isLakera && (
                <div className="space-y-2">
                  <label className="text-text-secondary font-medium">Umbral de detección</label>
                  <input
                    type="range"
                    min="0.1"
                    max="1.0"
                    step="0.05"
                    value={selected.config.threshold || 0.7}
                    onChange={(e) => handleGuardianConfigChange(selected.id, "threshold", parseFloat(e.target.value))}
                    className="w-full accent-primary"
                  />
                  <div className="flex justify-between text-[10px] text-text-secondary font-mono">
                    <span>Sensible (0.1)</span>
                    <span className="text-primary font-bold">Actual: {selected.config.threshold || 0.7}</span>
                    <span>Estricto (1.0)</span>
                  </div>
                </div>
              )}

              {/* Bedrock blocked topics */}
              {isBedrock && (
                <div className="space-y-1.5">
                  <label className="text-text-secondary font-medium">Temas restringidos</label>
                  <textarea
                    rows={2}
                    placeholder="Ej: consejo financiero, asesoría legal no autorizada"
                    value={(selected.config.blocked_topics || []).join(", ")}
                    onChange={(e) => {
                      const list = e.target.value.split(",").map((t: string) => t.trim()).filter(Boolean);
                      handleGuardianConfigChange(selected.id, "blocked_topics", list);
                    }}
                    className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary resize-none"
                  />
                </div>
              )}

              {/* Test panel (engine-backed only) */}
              {!isLocal && (
                <div className="border-t border-slate-700/30 pt-4 space-y-3">
                  <label className="text-text-secondary font-medium">Panel de prueba</label>
                  <textarea
                    rows={3}
                    placeholder="Ingresá texto de prueba para este guardián..."
                    value={testText}
                    onChange={(e) => setTestText(e.target.value)}
                    className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary resize-none"
                  />
                  <button
                    onClick={() => runTest(selected)}
                    disabled={testing || !testText.trim()}
                    className="bg-primary hover:bg-primary/90 disabled:opacity-40 text-background font-semibold px-4 py-1.5 rounded text-xs transition-all"
                  >
                    {testing ? "Ejecutando..." : "Ejecutar test"}
                  </button>
                  {testError && (
                    <div className="bg-danger/10 border border-danger/20 text-danger px-3 py-2 rounded text-xs">{testError}</div>
                  )}
                  {testResult && (
                    <div className={`px-3 py-2 rounded text-xs border font-semibold ${
                      testResult.blocked
                        ? "bg-danger/10 border-danger/20 text-danger"
                        : "bg-success/10 border-success/20 text-success"
                    }`}>
                      {testResult.blocked ? "BLOQUEADO" : "PERMITIDO"}
                      {testResult.reason && (
                        <span className="ml-2 font-normal text-text-secondary">{testResult.reason}</span>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ── Headroom ── */}
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
            onClick={() => policy && setPolicy({ ...policy, headroom_mode: !policy.headroom_mode })}
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
          Al activar Headroom, los textos redundantes y comentarios de código se limpian localmente en la
          pasarela. Los prompts extensos se optimizan logrando ahorrar entre un 60% y 95% de tokens,
          reduciendo costos de API y acelerando la respuesta del modelo.
        </div>
      </div>
    </div>
  );
};

export default SecurityPage;
