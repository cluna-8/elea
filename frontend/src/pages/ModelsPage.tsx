import React, { useState, useEffect } from "react";
import { api } from "../services/api";

interface ModelDetail {
  model_name: string;
  provider: string;
  model_id: string;
  api_base?: string;
  is_configured: boolean;
  is_eu_compliant: boolean;
}

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Google Gemini",
  groq: "Groq",
  azure: "Azure OpenAI",
  bedrock: "AWS Bedrock",
  vertex_ai: "Google Vertex AI",
  watsonx: "IBM WatsonX",
  cloudflare: "Cloudflare AI",
  ollama: "Ollama (Local)",
  local: "Local",
};

const PROVIDER_CREDENTIAL_HINT: Record<string, string> = {
  openai: "OPENAI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY",
  gemini: "GEMINI_API_KEY",
  groq: "GROQ_API_KEY",
  azure: "AZURE_API_KEY + AZURE_API_BASE + AZURE_API_VERSION",
  bedrock: "AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY + AWS_REGION_NAME",
  vertex_ai: "VERTEX_PROJECT + VERTEX_LOCATION + VERTEX_CREDENTIALS",
  watsonx: "WATSONX_API_KEY + WATSONX_PROJECT_ID + WATSONX_URL",
  cloudflare: "CLOUDFLARE_API_KEY + CLOUDFLARE_API_BASE",
  ollama: "Sin credencial (local)",
  local: "Sin credencial (local)",
};

type CatalogFilter = "all" | "eu" | "local";

export const ModelsPage: React.FC = () => {
  const [allModels, setAllModels] = useState<ModelDetail[]>([]);
  const [fallbacks, setFallbacks] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");
  const [actionLoading, setActionLoading] = useState(false);

  // Catalog modal
  const [showCatalog, setShowCatalog] = useState(false);
  const [catalogFilter, setCatalogFilter] = useState<CatalogFilter>("all");

  // Activate modal (for a specific unconfigured model)
  const [activatingModel, setActivatingModel] = useState<ModelDetail | null>(null);
  const [activateKey, setActivateKey] = useState("");
  const [activateBase, setActivateBase] = useState("");

  // Custom model form (inside catalog)
  const [showCustomForm, setShowCustomForm] = useState(false);
  const [customName, setCustomName] = useState("");
  const [customProvider, setCustomProvider] = useState("openai");
  const [customModelId, setCustomModelId] = useState("");
  const [customKey, setCustomKey] = useState("");
  const [customBase, setCustomBase] = useState("");

  const activeModels = allModels.filter((m) => m.is_configured);

  const catalogModels = allModels.filter((m) => {
    if (catalogFilter === "eu") return m.is_eu_compliant;
    if (catalogFilter === "local") return m.provider === "ollama" || m.provider === "local";
    return true;
  });

  const load = async () => {
    setLoading(true);
    try {
      const [models, fb] = await Promise.all([api.getModels(), api.getFallbacks()]);
      setAllModels(models);
      setFallbacks(fb);
    } catch {
      setError("Error al cargar configuración de modelos.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleFallbackChange = async (modelName: string, value: string) => {
    const fb = value === "" ? null : value;
    setFallbacks((prev) => ({ ...prev, [modelName]: value }));
    try {
      await api.setFallback(modelName, fb);
    } catch {
      setError("Error al guardar fallback.");
    }
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`¿Eliminar el modelo "${name}" de la pasarela?`)) return;
    setActionLoading(true);
    try {
      await api.deleteModel(name);
      setSuccessMsg(`Modelo ${name} eliminado.`);
      await load();
    } catch {
      setError("Error al eliminar el modelo.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleActivate = async () => {
    if (!activatingModel) return;
    setActionLoading(true);
    setError("");
    try {
      await api.updateModelCredential(activatingModel.model_name, activateKey, activateBase || undefined);
      setSuccessMsg(`Modelo ${activatingModel.model_name} configurado. Reinicia el motor para aplicar.`);
      setActivatingModel(null);
      setActivateKey("");
      setActivateBase("");
      await load();
    } catch {
      setError("Error al configurar el modelo.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleCustomRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!customName || !customModelId) return;
    setActionLoading(true);
    setError("");
    try {
      await api.createModel({
        model_name: customName,
        provider: customProvider,
        model_id: customModelId,
        api_key: customKey || undefined,
        api_base: customBase || undefined,
      });
      setSuccessMsg(`Modelo ${customName} registrado.`);
      setShowCustomForm(false);
      setCustomName(""); setCustomModelId(""); setCustomKey(""); setCustomBase("");
      await load();
    } catch (err: any) {
      setError(err.message || "Error al registrar el modelo.");
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center pb-4 border-b border-slate-700/30">
        <div>
          <h1 className="text-2xl font-bold text-white">Modelos de IA & Proveedores</h1>
          <p className="text-xs text-text-secondary mt-1">
            Gestione los modelos activos, configure fallbacks automáticos y active nuevos proveedores.
          </p>
        </div>
        <button
          onClick={() => setShowCatalog(true)}
          className="bg-primary hover:bg-primary/90 text-background font-bold px-4 py-2 rounded text-xs transition-all"
        >
          + Agregar Modelo
        </button>
      </div>

      {error && (
        <div className="bg-danger/10 border border-danger/20 text-danger px-4 py-2.5 rounded-lg text-xs">{error}</div>
      )}
      {successMsg && (
        <div className="bg-success/10 border border-success/20 text-success px-4 py-2.5 rounded-lg text-xs">{successMsg}</div>
      )}

      {/* Active Models Table */}
      <div className="bg-panel border border-slate-700/40 rounded-lg p-5">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary mb-4">
          Modelos Activos en la Pasarela
        </h2>

        {loading ? (
          <div className="py-12 flex justify-center text-xs font-mono text-text-secondary">Cargando modelos...</div>
        ) : activeModels.length === 0 ? (
          <div className="py-8 text-center text-xs text-text-secondary">
            No hay modelos configurados.{" "}
            <button className="text-primary underline" onClick={() => setShowCatalog(true)}>
              Agregar uno desde el catálogo
            </button>
          </div>
        ) : (
          <div className="border border-slate-700/30 rounded overflow-hidden">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-background/40 border-b border-slate-700/50">
                  <th className="p-3 text-xs font-semibold text-text-secondary">Nombre</th>
                  <th className="p-3 text-xs font-semibold text-text-secondary">Proveedor</th>
                  <th className="p-3 text-xs font-semibold text-text-secondary">Compliance</th>
                  <th className="p-3 text-xs font-semibold text-text-secondary">Fallback automático</th>
                  <th className="p-3 text-xs font-semibold text-text-secondary text-right">Acción</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-700/30 text-white text-xs">
                {activeModels.map((m) => {
                  const otherActive = activeModels.filter((x) => x.model_name !== m.model_name);
                  return (
                    <tr key={m.model_name} className="hover:bg-background/20 transition-colors">
                      <td className="p-3 font-semibold">{m.model_name}</td>
                      <td className="p-3">
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-slate-800 border border-slate-700 text-text-secondary">
                          {PROVIDER_LABELS[m.provider] || m.provider}
                        </span>
                      </td>
                      <td className="p-3">
                        {m.is_eu_compliant ? (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-success/10 border border-success/20 text-success">
                            UE Compliant
                          </span>
                        ) : (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-slate-800 border border-slate-700 text-text-secondary">
                            Cloud estándar
                          </span>
                        )}
                      </td>
                      <td className="p-3">
                        <select
                          value={fallbacks[m.model_name] || ""}
                          onChange={(e) => handleFallbackChange(m.model_name, e.target.value)}
                          className="bg-background border border-slate-700 rounded px-2 py-1 text-white text-[11px] focus:outline-none focus:border-primary"
                        >
                          <option value="">Sin fallback</option>
                          {otherActive.map((o) => (
                            <option key={o.model_name} value={o.model_name}>
                              {o.model_name}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="p-3 text-right">
                        <button
                          onClick={() => handleDelete(m.model_name)}
                          disabled={actionLoading}
                          className="text-danger hover:text-danger/80 font-semibold text-xs"
                        >
                          Eliminar
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

      {/* ─── Catalog Modal ─── */}
      {showCatalog && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/70 pt-16 px-4">
          <div className="bg-panel border border-slate-700/50 rounded-xl w-full max-w-3xl max-h-[80vh] flex flex-col shadow-2xl">
            {/* Header */}
            <div className="flex items-center justify-between p-5 border-b border-slate-700/40">
              <div>
                <h2 className="text-base font-bold text-white">Catálogo de Modelos</h2>
                <p className="text-xs text-text-secondary mt-0.5">
                  Seleccione un modelo para activarlo en la pasarela. Los modelos marcados{" "}
                  <span className="text-success font-semibold">UE Compliant</span> soportan residencia de datos en Europa.
                </p>
              </div>
              <button
                onClick={() => { setShowCatalog(false); setShowCustomForm(false); }}
                className="text-text-secondary hover:text-white text-lg leading-none"
              >
                ✕
              </button>
            </div>

            {/* Filter pills */}
            <div className="flex gap-2 px-5 pt-4">
              {(["all", "eu", "local"] as CatalogFilter[]).map((f) => (
                <button
                  key={f}
                  onClick={() => setCatalogFilter(f)}
                  className={`px-3 py-1 rounded-full text-xs font-semibold border transition-all ${
                    catalogFilter === f
                      ? "bg-primary/20 border-primary/40 text-primary"
                      : "border-slate-700 text-text-secondary hover:text-white"
                  }`}
                >
                  {f === "all" ? "Todos" : f === "eu" ? "Solo UE Compliant" : "Local (Ollama)"}
                </button>
              ))}
              <div className="flex-1" />
              <button
                onClick={() => setShowCustomForm(!showCustomForm)}
                className="px-3 py-1 rounded text-xs font-semibold border border-slate-700 text-text-secondary hover:text-white transition-all"
              >
                {showCustomForm ? "← Volver al catálogo" : "+ Modelo personalizado"}
              </button>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto p-5 space-y-2">
              {showCustomForm ? (
                <form onSubmit={handleCustomRegister} className="space-y-4 text-xs text-white max-w-md">
                  <div className="space-y-1.5">
                    <label className="text-text-secondary font-medium">Nombre en pasarela</label>
                    <input
                      required
                      value={customName}
                      onChange={(e) => setCustomName(e.target.value)}
                      placeholder="ej: mi-gpt4o"
                      className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-text-secondary font-medium">Proveedor</label>
                    <select
                      value={customProvider}
                      onChange={(e) => setCustomProvider(e.target.value)}
                      className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none focus:border-primary"
                    >
                      {Object.entries(PROVIDER_LABELS).map(([k, v]) => (
                        <option key={k} value={k}>{v}</option>
                      ))}
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-text-secondary font-medium">ID del modelo en el proveedor</label>
                    <input
                      required
                      value={customModelId}
                      onChange={(e) => setCustomModelId(e.target.value)}
                      placeholder="ej: gpt-4o, llama3, claude-3-5-sonnet"
                      className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-text-secondary font-medium">API Key</label>
                    <input
                      type="password"
                      value={customKey}
                      onChange={(e) => setCustomKey(e.target.value)}
                      placeholder="Dejar vacío si se configura en .env"
                      className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-text-secondary font-medium">API Base (opcional)</label>
                    <input
                      value={customBase}
                      onChange={(e) => setCustomBase(e.target.value)}
                      placeholder="ej: http://localhost:11434"
                      className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary"
                    />
                  </div>
                  <button
                    type="submit"
                    disabled={actionLoading}
                    className="bg-primary hover:bg-primary/90 text-background font-bold px-4 py-2 rounded text-xs w-full"
                  >
                    {actionLoading ? "Registrando..." : "Registrar Modelo"}
                  </button>
                </form>
              ) : (
                catalogModels.map((m) => {
                  const isActive = m.is_configured;
                  const hint = PROVIDER_CREDENTIAL_HINT[m.provider] || "";
                  return (
                    <div
                      key={m.model_name}
                      className={`border rounded-lg p-4 flex items-center gap-4 transition-all ${
                        isActive
                          ? "border-success/20 bg-success/5"
                          : "border-slate-700/40 bg-background/10 hover:border-slate-600"
                      }`}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-semibold text-white text-xs">{m.model_name}</span>
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-slate-800 border border-slate-700 text-text-secondary">
                            {PROVIDER_LABELS[m.provider] || m.provider}
                          </span>
                          {m.is_eu_compliant && (
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-success/10 border border-success/20 text-success">
                              UE Compliant
                            </span>
                          )}
                        </div>
                        <p className="text-[11px] text-text-secondary font-mono mt-1">{m.model_id}</p>
                        {!isActive && hint && (
                          <p className="text-[11px] text-warning/70 mt-1">Requiere: {hint}</p>
                        )}
                      </div>
                      <div className="flex-shrink-0">
                        {isActive ? (
                          <span className="px-2 py-1 rounded text-[10px] font-bold bg-success/10 border border-success/20 text-success">
                            ✓ Activo
                          </span>
                        ) : (
                          <button
                            onClick={() => {
                              setActivatingModel(m);
                              setActivateKey("");
                              setActivateBase(m.api_base || "");
                              setShowCatalog(false);
                            }}
                            className="px-3 py-1.5 rounded text-xs font-semibold bg-primary/10 hover:bg-primary/20 text-primary border border-primary/20 transition-all"
                          >
                            Configurar
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}

      {/* ─── Activate / Configure Model Modal ─── */}
      {activatingModel && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 px-4">
          <div className="bg-panel border border-slate-700/50 rounded-xl w-full max-w-md shadow-2xl p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold text-white">Configurar: {activatingModel.model_name}</h2>
              <button onClick={() => setActivatingModel(null)} className="text-text-secondary hover:text-white">✕</button>
            </div>

            <div className="flex gap-2 flex-wrap">
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-slate-800 border border-slate-700 text-text-secondary">
                {PROVIDER_LABELS[activatingModel.provider] || activatingModel.provider}
              </span>
              {activatingModel.is_eu_compliant && (
                <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-success/10 border border-success/20 text-success">
                  UE Compliant
                </span>
              )}
            </div>

            {PROVIDER_CREDENTIAL_HINT[activatingModel.provider] !== "Sin credencial (local)" ? (
              <>
                <div className="bg-background/30 rounded p-3 text-[11px] text-text-secondary">
                  <p className="font-semibold text-white mb-1">Credenciales requeridas</p>
                  <p className="font-mono text-warning/80">{PROVIDER_CREDENTIAL_HINT[activatingModel.provider]}</p>
                  <p className="mt-2">
                    Podés configurarlas aquí (se guardan en config) o en el archivo{" "}
                    <span className="font-mono text-white">.env</span> y reiniciar el motor.
                  </p>
                </div>
                <div className="space-y-3 text-xs">
                  <div className="space-y-1">
                    <label className="text-text-secondary font-medium">API Key</label>
                    <input
                      type="password"
                      value={activateKey}
                      onChange={(e) => setActivateKey(e.target.value)}
                      placeholder="sk-..."
                      className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary"
                    />
                  </div>
                  {(activatingModel.provider === "azure" || activatingModel.provider === "ollama" || activatingModel.provider === "cloudflare") && (
                    <div className="space-y-1">
                      <label className="text-text-secondary font-medium">API Base URL</label>
                      <input
                        value={activateBase}
                        onChange={(e) => setActivateBase(e.target.value)}
                        placeholder="https://..."
                        className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary"
                      />
                    </div>
                  )}
                </div>
                <button
                  onClick={handleActivate}
                  disabled={actionLoading || !activateKey}
                  className="w-full bg-primary hover:bg-primary/90 disabled:opacity-40 text-background font-bold py-2 rounded text-xs"
                >
                  {actionLoading ? "Guardando..." : "Guardar credencial"}
                </button>
              </>
            ) : (
              <>
                <p className="text-xs text-text-secondary">
                  Ollama no requiere credencial. Asegurate de tener el servidor corriendo en{" "}
                  <span className="font-mono text-white">{activatingModel.api_base || "http://localhost:11434"}</span>.
                </p>
                <p className="text-xs text-success">Este modelo debería aparecer como activo si Ollama está corriendo.</p>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default ModelsPage;
