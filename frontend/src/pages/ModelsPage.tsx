import React, { useState, useEffect } from "react";
import { api } from "../services/api";

interface ModelDetail {
  model_name: string;
  provider: string;
  model_id: string;
  api_base?: string;
}

export const ModelsPage: React.FC = () => {
  const [models, setModels] = useState<ModelDetail[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  // Form State
  const [modelName, setModelName] = useState("");
  const [provider, setProvider] = useState("openai");
  const [modelId, setModelId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [apiBase, setApiBase] = useState("");

  const fetchModels = async () => {
    setLoading(true);
    try {
      const data = await api.getModels();
      setModels(data);
    } catch (err) {
      console.error(err);
      setError("Error al cargar la lista de modelos de la pasarela.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchModels();
  }, []);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!modelName || !modelId) return;

    setActionLoading(true);
    setError("");
    setSuccessMsg("");

    try {
      await api.createModel({
        model_name: modelName,
        provider,
        model_id: modelId,
        api_key: apiKey || undefined,
        api_base: apiBase || undefined,
      });

      setSuccessMsg(`Modelo ${modelName} registrado con éxito.`);
      // Clear form
      setModelName("");
      setModelId("");
      setApiKey("");
      setApiBase("");
      
      // Refresh list
      await fetchModels();
    } catch (err: any) {
      setError(err.message || "Error al registrar el modelo en la pasarela.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleDelete = async (name: string) => {
    if (!confirm(`¿Está seguro de que desea eliminar el modelo "${name}"?`)) return;

    setActionLoading(true);
    setError("");
    setSuccessMsg("");

    try {
      await api.deleteModel(name);
      setSuccessMsg(`Modelo ${name} eliminado con éxito.`);
      await fetchModels();
    } catch (err: any) {
      setError(err.message || "Error al eliminar el modelo.");
    } finally {
      setActionLoading(false);
    }
  };

  const handleQuickActivate = async (localModel: { name: string; provider: string; id: string; apiBase: string }) => {
    setActionLoading(true);
    setError("");
    setSuccessMsg("");

    try {
      await api.createModel({
        model_name: localModel.name,
        provider: localModel.provider,
        model_id: localModel.id,
        api_base: localModel.apiBase,
      });
      setSuccessMsg(`Modelo local ${localModel.name} activado con éxito.`);
      await fetchModels();
    } catch (err: any) {
      setError(err.message || "Error al activar el modelo local.");
    } finally {
      setActionLoading(false);
    }
  };

  const localRecommendations = [
    { name: "llama3-local", provider: "local", id: "llama3", apiBase: "http://localhost:11434" },
    { name: "mistral-local", provider: "local", id: "mistral", apiBase: "http://localhost:11434" },
    { name: "gemma2-local", provider: "local", id: "gemma2", apiBase: "http://localhost:11434" },
    { name: "phi3-local", provider: "local", id: "phi3", apiBase: "http://localhost:11434" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center pb-4 border-b border-slate-700/30">
        <div>
          <h1 className="text-2xl font-bold text-white">
            Modelos de IA & Proveedores
          </h1>
          <p className="text-xs text-text-secondary mt-1">
            Administre la lista de LLMs activos en la pasarela, incluyendo modelos en la nube y servidores locales (Ollama).
          </p>
        </div>
      </div>

      {error && (
        <div className="bg-danger/10 border border-danger/20 text-danger px-4 py-2.5 rounded-lg text-xs">
          <span>{error}</span>
        </div>
      )}

      {successMsg && (
        <div className="bg-success/10 border border-success/20 text-success px-4 py-2.5 rounded-lg text-xs">
          <span>{successMsg}</span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left 2 cols: Active Models list */}
        <div className="lg:col-span-2 space-y-6">
          <div className="bg-panel border border-slate-700/40 rounded-lg p-5">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary mb-4">
              Modelos Activos en la Pasarela
            </h2>

            {loading ? (
              <div className="py-12 flex justify-center items-center text-xs font-mono text-text-secondary">
                Cargando modelos...
              </div>
            ) : models.length === 0 ? (
              <p className="text-xs text-text-secondary">No hay modelos configurados en la pasarela.</p>
            ) : (
              <div className="border border-slate-700/30 rounded overflow-hidden">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="bg-background/40 border-b border-slate-700/50">
                      <th className="p-3 text-xs font-semibold text-text-secondary">Nombre de Pasarela</th>
                      <th className="p-3 text-xs font-semibold text-text-secondary">Proveedor / ID Real</th>
                      <th className="p-3 text-xs font-semibold text-text-secondary">Endpoint Base</th>
                      <th className="p-3 text-xs font-semibold text-text-secondary text-right">Acción</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-700/30 text-white text-xs">
                    {models.map((m) => (
                      <tr key={m.model_name} className="hover:bg-background/20 transition-colors">
                        <td className="p-3 font-semibold">{m.model_name}</td>
                        <td className="p-3">
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold mr-2 uppercase bg-slate-800 border border-slate-750 text-text-secondary">
                            {m.provider}
                          </span>
                          <span className="font-mono text-[11px] text-text-secondary">{m.model_id}</span>
                        </td>
                        <td className="p-3 text-[11px] text-text-secondary font-mono">
                          {m.api_base || "Default Cloud API"}
                        </td>
                        <td className="p-3 text-right">
                          <button
                            onClick={() => handleDelete(m.model_name)}
                            disabled={actionLoading}
                            className="text-danger hover:text-danger/80 font-semibold text-xs transition-all"
                            title="Eliminar modelo"
                          >
                            Eliminar
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Quick recommendations */}
          <div className="bg-panel border border-slate-700/40 rounded-lg p-5">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary mb-2">
              Activar Modelos Locales (Ollama)
            </h2>
            <p className="text-xs text-text-secondary mb-4">
              Haga clic para registrar instantáneamente modelos locales configurados en su puerto Ollama de desarrollo.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {localRecommendations.map((lm) => (
                <div key={lm.name} className="border border-slate-700/40 rounded p-3.5 flex justify-between items-center bg-background/10">
                  <div>
                    <h3 className="font-bold text-white text-xs">{lm.name}</h3>
                    <p className="text-[10px] text-text-secondary font-mono mt-0.5">{lm.id} @ {lm.apiBase}</p>
                  </div>
                  <button
                    onClick={() => handleQuickActivate(lm)}
                    disabled={actionLoading}
                    className="bg-primary/10 hover:bg-primary/20 text-primary px-3 py-1 rounded text-xs font-semibold border border-primary/20 transition-all"
                  >
                    Activar
                  </button>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right col: Add new model form */}
        <div className="bg-panel border border-slate-700/40 rounded-lg p-5 h-fit">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-text-secondary mb-4">
            Registrar Nuevo Modelo
          </h2>
          <form onSubmit={handleRegister} className="space-y-4 text-xs text-white">
            <div className="space-y-1.5">
              <label className="text-text-secondary font-medium">Nombre en Pasarela</label>
              <input
                type="text"
                required
                value={modelName}
                onChange={(e) => setModelName(e.target.value)}
                placeholder="ej: gpt-4o-basa"
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-text-secondary font-medium">Proveedor</label>
              <select
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white focus:outline-none focus:border-primary"
              >
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic (Claude)</option>
                <option value="bedrock">AWS Bedrock</option>
                <option value="vertex_ai">Google Vertex AI</option>
                <option value="azure">Azure OpenAI</option>
                <option value="watsonx">IBM WatsonX</option>
                <option value="cloudflare">Cloudflare AI</option>
                <option value="local">Ollama (Local / Autohospedado)</option>
                <option value="groq">Groq</option>
                <option value="cohere">Cohere</option>
              </select>
            </div>

            <div className="space-y-1.5">
              <label className="text-text-secondary font-medium">ID del Modelo en Proveedor</label>
              <input
                type="text"
                required
                value={modelId}
                onChange={(e) => setModelId(e.target.value)}
                placeholder="ej: gpt-4o, llama3, claude-3-5-sonnet"
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-text-secondary font-medium">API Key (Opcional)</label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Dejar en blanco para usar env var"
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-text-secondary font-medium">API Base Endpoint (Opcional)</label>
              <input
                type="text"
                value={apiBase}
                onChange={(e) => setApiBase(e.target.value)}
                placeholder="ej: http://localhost:11434"
                className="w-full bg-background border border-slate-700 rounded px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-primary"
              />
            </div>

            <button
              type="submit"
              disabled={actionLoading}
              className="w-full bg-primary hover:bg-primary/95 text-background font-bold py-2 px-4 rounded transition-all flex items-center justify-center gap-2 mt-2 text-xs"
            >
              <span>{actionLoading ? "Registrando..." : "Registrar Modelo"}</span>
            </button>
          </form>
        </div>
      </div>
    </div>
  );
};
export default ModelsPage;
