import React, { useState, useEffect } from "react";
import { api } from "../services/api";
import { motion, AnimatePresence } from "framer-motion";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  metadata?: any;
}

export const PlaygroundPage: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [models, setModels] = useState<any[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [loading, setLoading] = useState(false);
  
  // Pipeline Animation & Details
  const [activeMetadata, setActiveMetadata] = useState<any>(null);
  const [animatingLayer, setAnimatingLayer] = useState<number>(-1);
  const [rightPanelTab, setRightPanelTab] = useState<"layers" | "debugger">("layers");

  // Virtual Keys & Overrides Configuration
  const [authMode, setAuthMode] = useState<"session" | "key">("session");
  const [customKey, setCustomKey] = useState("");
  const [showConfig, setShowConfig] = useState(false);

  // Policy overrides: "default" | "active" | "inactive"
  const [overridePii, setOverridePii] = useState<"default" | "active" | "inactive" >("default");
  const [overrideGdpr, setOverrideGdpr] = useState<"default" | "active" | "inactive" >("default");
  const [overrideAiAct, setOverrideAiAct] = useState<"default" | "active" | "inactive" >("default");
  const [overrideHeadroom, setOverrideHeadroom] = useState<"default" | "active" | "inactive" >("default");

  // Debugger Expandable Sections
  const [showRequestJson, setShowRequestJson] = useState(false);
  const [showResponseJson, setShowResponseJson] = useState(false);

  useEffect(() => {
    const loadData = async () => {
      try {
        const fetchedModels = await api.getModels();
        setModels(fetchedModels);
        if (fetchedModels.length > 0) {
          setSelectedModel(fetchedModels[0].model_name);
        }
      } catch (err) {
        console.error("Error al cargar datos del Playground:", err);
      }
    };
    loadData();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: input,
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setLoading(true);
    setActiveMetadata(null);
    setAnimatingLayer(0); // Start animation at Layer 0 (Input/Masking)

    // Build overrides object
    const overrides: any = {};
    if (overridePii !== "default") overrides.override_pii_masking = overridePii === "active";
    if (overrideGdpr !== "default") overrides.override_gdpr_mode = overrideGdpr === "active";
    if (overrideAiAct !== "default") overrides.override_ai_act_mode = overrideAiAct === "active";
    if (overrideHeadroom !== "default") overrides.override_headroom_mode = overrideHeadroom === "active";

    const keyToUse = authMode === "key" ? customKey : undefined;

    try {
      const steps = [0, 1, 2, 3, 4];
      const responsePromise = api.sendChatMessage(userMessage.content, selectedModel, keyToUse || undefined, overrides);
      
      for (const step of steps) {
        setAnimatingLayer(step);
        await new Promise((resolve) => setTimeout(resolve, 600));
      }

      const data = await responsePromise;

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: data.response,
        metadata: data.pipeline_metadata,
      };

      setMessages((prev) => [...prev, assistantMessage]);
      setActiveMetadata(data.pipeline_metadata);
      setRightPanelTab("debugger");
    } catch (err: any) {
      alert(err.message || "Error al enviar mensaje.");
    } finally {
      setLoading(false);
      setAnimatingLayer(-1);
    }
  };

  const layers = [
    {
      id: 0,
      step: "01",
      name: "Enmascaramiento PHI/PII",
      desc: "Escanea y enmascara datos médicos privados localmente en memoria.",
      getDetails: (meta: any) => {
        if (!meta?.layer_masking) return "Inactivo";
        const m = meta.layer_masking;
        if (!m.active) return "Desactivado por configuración de la petición.";
        if (m.entities_detected.length === 0) return "Activo. No se detectaron entidades sensibles.";
        return `Entidades enmascaradas: ${m.entities_detected.map((e: any) => e.type).join(", ")}`;
      }
    },
    {
      id: 1,
      step: "02",
      name: "Optimización de Contexto",
      desc: "Comprime el prompt usando Headroom para ahorrar tokens de contexto.",
      getDetails: (meta: any) => {
        if (!meta?.layer_optimization) return "Inactivo";
        const o = meta.layer_optimization;
        return o.active 
          ? `Compresión activa: Reducción de ${o.original_length} a ${o.optimized_length} caracteres. Ahorro: ${o.tokens_saved} tokens.`
          : "Saltado (Optimizador inactivo o desactivado en la petición)";
      }
    },
    {
      id: 2,
      step: "03",
      name: "Políticas de Cumplimiento",
      desc: "Evalúa normativas GDPR de residencia de datos y AI Act de la UE.",
      getDetails: (meta: any) => {
        if (!meta?.layer_compliance) return "Inactivo";
        const c = meta.layer_compliance;
        return `GDPR: ${c.gdpr_active ? "Enrutamiento EU" : "Estándar"} | AI Act: ${c.ai_act_status.toUpperCase()}`;
      }
    },
    {
      id: 3,
      step: "04",
      name: "Canal de Enrutamiento LLM",
      desc: "Enruta la petición de forma segura al proveedor LLM configurado.",
      getDetails: (meta: any) => {
        if (!meta?.layer_llm) return "Inactivo";
        const l = meta.layer_llm;
        return `Model: ${l.model_used} | Latencia: ${l.latency_ms}ms | Costo: $${Number(l.cost_usd).toFixed(6)}`;
      }
    },
    {
      id: 4,
      step: "05",
      name: "Restauración y Desenmascaramiento",
      desc: "Restaura en local los valores originales en la respuesta del LLM.",
      getDetails: (meta: any) => {
        if (!meta?.layer_unmasking) return "Inactivo";
        return "Tokens mapeados restaurados con éxito.";
      }
    }
  ];

  return (
    <div className="p-6 max-w-7xl mx-auto h-[calc(100vh-100px)] flex flex-col lg:flex-row gap-8">
      {/* Left Panel: Chat Interface */}
      <div className="flex-1 bg-panel border border-slate-700/50 rounded-xl flex flex-col overflow-hidden h-full">
        {/* Chat Header */}
        <div className="p-4 border-b border-slate-700/50 flex justify-between items-center bg-background/20">
          <h2 className="text-sm font-bold text-white uppercase tracking-wider">
            Playground Seguro
          </h2>
          
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowConfig(!showConfig)}
              className={`px-3 py-1.5 rounded text-xs font-semibold border transition-all ${
                showConfig 
                  ? "bg-primary/10 border-primary/30 text-primary" 
                  : "bg-background border-slate-700 text-text-secondary hover:text-white"
              }`}
            >
              {showConfig ? "Ocultar Configuración" : "Configuración de Petición"}
            </button>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              className="bg-background border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-primary"
            >
              {models.map((m) => (
                <option key={m.model_name} value={m.model_name}>
                  {m.model_name}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Collapsible Request Configuration */}
        <AnimatePresence>
          {showConfig && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="border-b border-slate-700/50 bg-slate-800/20 overflow-hidden"
            >
              <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Auth Mode Selector */}
                <div className="space-y-3">
                  <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider block">
                    Autenticación
                  </span>
                  <div className="flex rounded border border-slate-700 overflow-hidden text-xs">
                    <button
                      type="button"
                      onClick={() => setAuthMode("session")}
                      className={`flex-1 py-2 px-3 transition-colors font-semibold ${
                        authMode === "session"
                          ? "bg-primary text-background"
                          : "bg-background text-text-secondary hover:text-white"
                      }`}
                    >
                      Sesión actual
                    </button>
                    <button
                      type="button"
                      onClick={() => setAuthMode("key")}
                      className={`flex-1 py-2 px-3 transition-colors font-semibold border-l border-slate-700 ${
                        authMode === "key"
                          ? "bg-primary text-background"
                          : "bg-background text-text-secondary hover:text-white"
                      }`}
                    >
                      Llave virtual
                    </button>
                  </div>
                  {authMode === "session" ? (
                    <p className="text-[10px] text-text-secondary">
                      Usando el usuario logueado. El gasto se atribuye a tu cuenta.
                    </p>
                  ) : (
                    <>
                      <input
                        type="password"
                        placeholder="sk-..."
                        value={customKey}
                        onChange={(e) => setCustomKey(e.target.value)}
                        className="w-full bg-background border border-slate-700 rounded p-2 text-xs text-white focus:outline-none focus:border-primary font-mono"
                      />
                      <p className="text-[10px] text-text-secondary">
                        Probá como un usuario/integración específica. El gasto se atribuye a esa llave.
                      </p>
                    </>
                  )}
                </div>

                {/* Policy Overrides */}
                <div className="space-y-3">
                  <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider block">
                    Sobrescribir Políticas
                  </span>
                  <div className="grid grid-cols-2 gap-3">
                    {/* PII Override */}
                    <div className="flex flex-col space-y-1">
                      <span className="text-[10px] text-text-secondary">Enmascarar PII</span>
                      <select
                        value={overridePii}
                        onChange={(e: any) => setOverridePii(e.target.value)}
                        className="bg-background border border-slate-700 rounded p-1.5 text-[11px] text-white focus:outline-none focus:border-primary"
                      >
                        <option value="default">Usar Config. de Base</option>
                        <option value="active">Forzar Activo</option>
                        <option value="inactive">Forzar Inactivo</option>
                      </select>
                    </div>

                    {/* GDPR Override */}
                    <div className="flex flex-col space-y-1">
                      <span className="text-[10px] text-text-secondary">Residencia GDPR</span>
                      <select
                        value={overrideGdpr}
                        onChange={(e: any) => setOverrideGdpr(e.target.value)}
                        className="bg-background border border-slate-700 rounded p-1.5 text-[11px] text-white focus:outline-none focus:border-primary"
                      >
                        <option value="default">Usar Config. de Base</option>
                        <option value="active">Forzar Activo (EU)</option>
                        <option value="inactive">Forzar Inactivo (Global)</option>
                      </select>
                    </div>

                    {/* AI Act Override */}
                    <div className="flex flex-col space-y-1">
                      <span className="text-[10px] text-text-secondary">Filtros AI Act</span>
                      <select
                        value={overrideAiAct}
                        onChange={(e: any) => setOverrideAiAct(e.target.value)}
                        className="bg-background border border-slate-700 rounded p-1.5 text-[11px] text-white focus:outline-none focus:border-primary"
                      >
                        <option value="default">Usar Config. de Base</option>
                        <option value="active">Forzar Activo</option>
                        <option value="inactive">Forzar Inactivo</option>
                      </select>
                    </div>

                    {/* Headroom Override */}
                    <div className="flex flex-col space-y-1">
                      <span className="text-[10px] text-text-secondary">Optimización (Headroom)</span>
                      <select
                        value={overrideHeadroom}
                        onChange={(e: any) => setOverrideHeadroom(e.target.value)}
                        className="bg-background border border-slate-700 rounded p-1.5 text-[11px] text-white focus:outline-none focus:border-primary"
                      >
                        <option value="default">Usar Config. de Base</option>
                        <option value="active">Forzar Activo</option>
                        <option value="inactive">Forzar Inactivo</option>
                      </select>
                    </div>
                  </div>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Messages Area */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-[200px]">
          {messages.length === 0 ? (
            <div className="h-full flex flex-col items-center justify-center text-center p-6 space-y-2">
              <h3 className="text-sm font-bold text-white uppercase tracking-wider">Canal Seguro Activo</h3>
              <p className="text-xs text-text-secondary max-w-sm">
                Escriba un mensaje para ver cómo la pasarela procesa, enmascara y optimiza los datos clínicos en tiempo real.
              </p>
            </div>
          ) : (
            messages.map((msg) => (
              <div
                key={msg.id}
                onClick={() => msg.metadata && setActiveMetadata(msg.metadata)}
                className={`flex flex-col space-y-1 max-w-[85%] cursor-pointer group ${
                  msg.role === "user" ? "ml-auto items-end" : "mr-auto items-start"
                }`}
              >
                <div
                  className={`p-3 rounded-lg text-xs ${
                    msg.role === "user"
                      ? "bg-primary text-background font-semibold rounded-tr-none"
                      : "bg-background border border-slate-700 text-white rounded-tl-none hover:border-primary/50 transition-colors"
                  }`}
                >
                  {msg.content}
                </div>
                {msg.metadata && (
                  <div className="flex flex-wrap items-center gap-2 mt-1 px-1">
                    <span className="text-[9px] text-text-secondary group-hover:text-primary transition-colors">
                      Ver viaje de datos →
                    </span>
                    {msg.role === "assistant" && msg.metadata.layer_llm && (
                      <>
                        <span className="text-[9px] text-slate-600">•</span>
                        <span className="text-[9px] text-text-secondary">
                          Costo: <span className="text-success font-semibold font-mono">${Number(msg.metadata.layer_llm.cost_usd).toFixed(6)}</span>
                        </span>
                        <span className="text-[9px] text-slate-600">•</span>
                        <span className="text-[9px] text-text-secondary">
                          Tokens: <span className="text-slate-300 font-semibold font-mono">{msg.metadata.layer_llm.prompt_tokens + msg.metadata.layer_llm.completion_tokens}</span>
                        </span>
                        <span className="text-[9px] text-slate-600">•</span>
                        <span className="text-[9px] text-text-secondary">
                          Latencia: <span className="text-warning font-semibold font-mono">{msg.metadata.layer_llm.latency_ms}ms</span>
                        </span>
                      </>
                    )}
                  </div>
                )}
              </div>
            ))
          )}
          {loading && (
            <div className="bg-background border border-slate-700 p-3 rounded-lg rounded-tl-none mr-auto max-w-[80%] flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-primary animate-ping"></span>
              <span className="text-xs text-text-secondary font-mono">Procesando capas de seguridad...</span>
            </div>
          )}
        </div>

        {/* Input Area */}
        <form onSubmit={handleSubmit} className="p-4 border-t border-slate-700/50 bg-background/20">
          <div className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Escriba un mensaje (ej: Paciente Pedro DNI 123...)"
              className="flex-1 bg-background border border-slate-700 rounded-lg px-4 py-2 text-xs text-white placeholder-text-secondary focus:outline-none focus:border-primary"
            />
            <button
              type="submit"
              disabled={loading || !input.trim() || models.length === 0}
              className="bg-primary hover:bg-primary/90 text-background px-4 py-2 rounded-lg text-xs font-bold disabled:opacity-50 transition-colors"
            >
              Enviar
            </button>
          </div>
        </form>
      </div>

      {/* Right Panel: Layer Animation & Debugger */}
      <div className="w-full lg:w-80 bg-panel border border-slate-700/50 rounded-xl p-4 flex flex-col h-full overflow-hidden">
        {/* Tabs */}
        <div className="flex border-b border-slate-700/50 mb-4 text-xs font-bold">
          <button
            onClick={() => setRightPanelTab("layers")}
            className={`flex-1 pb-2 border-b-2 transition-all ${
              rightPanelTab === "layers"
                ? "border-primary text-primary"
                : "border-transparent text-text-secondary hover:text-white"
            }`}
          >
            Capas de Seguridad
          </button>
          <button
            onClick={() => setRightPanelTab("debugger")}
            className={`flex-1 pb-2 border-b-2 transition-all ${
              rightPanelTab === "debugger"
                ? "border-primary text-primary"
                : "border-transparent text-text-secondary hover:text-white"
            }`}
          >
            Debugger Técnico
          </button>
        </div>

        {rightPanelTab === "layers" ? (
          /* Layers view */
          <div className="flex-1 overflow-y-auto space-y-3 pr-1">
            {layers.map((layer) => {
              const isActive = animatingLayer === layer.id;
              const hasData = activeMetadata !== null;
              const detailText = hasData ? layer.getDetails(activeMetadata) : "";

              return (
                <motion.div
                  key={layer.id}
                  animate={{
                    scale: isActive ? 1.01 : 1,
                    borderColor: isActive ? "#00b4d8" : "rgba(51, 65, 85, 0.4)",
                  }}
                  className={`border rounded p-3 space-y-1.5 transition-all ${
                    isActive ? "bg-primary/5" : "bg-background/10"
                  } ${hasData ? "border-slate-700" : "border-slate-800/30"}`}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-primary font-bold">{layer.step}</span>
                    <h4 className="text-xs font-bold text-white">{layer.name}</h4>
                  </div>
                  <p className="text-[10px] text-text-secondary leading-normal">{layer.desc}</p>

                  <AnimatePresence>
                    {hasData && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        className="bg-background/50 rounded p-2 text-[10px] font-mono border border-slate-800 text-text-secondary break-words leading-relaxed"
                      >
                        {detailText}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </motion.div>
              );
            })}
          </div>
        ) : (
          /* Technical Debugger view */
          <div className="flex-1 overflow-y-auto space-y-4 pr-1 text-xs text-white">
            {!activeMetadata ? (
              <div className="h-full flex flex-col items-center justify-center text-center p-4 text-text-secondary">
                <p className="text-[11px]">Seleccione una respuesta o envíe un mensaje para inspeccionar los payloads JSON en tiempo real.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Metrics Grid */}
                <div className="space-y-2 bg-background/40 border border-slate-700/50 rounded p-3 text-xs">
                  <div className="border-b border-slate-700/40 pb-1.5 mb-1.5">
                    <span className="text-[9px] text-text-secondary uppercase font-bold tracking-wider">Métricas de Transacción</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-text-secondary">Modelo:</span>
                    <span className="font-mono text-white font-bold">{activeMetadata.layer_llm?.model_used || "Simulado"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-text-secondary">Latencia:</span>
                    <span className="font-mono text-warning font-bold">{activeMetadata.layer_llm?.latency_ms || 0}ms</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-text-secondary">Costo Est:</span>
                    <span className="font-mono text-success font-bold">${activeMetadata.layer_llm?.cost_usd?.toFixed(6) || "0.000000"}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-text-secondary">Tokens (Prompt/Comp):</span>
                    <span className="font-mono text-sky-400 font-bold">
                      {activeMetadata.layer_llm?.prompt_tokens || 0} / {activeMetadata.layer_llm?.completion_tokens || 0}
                    </span>
                  </div>
                </div>

                {/* Raw Request Payload JSON */}
                <div className="border border-slate-700/50 rounded overflow-hidden bg-background/10">
                  <button
                    onClick={() => setShowRequestJson(!showRequestJson)}
                    className="w-full flex justify-between items-center p-2.5 text-[10px] font-bold bg-background/20 hover:bg-background/40 transition-all border-b border-slate-700/20"
                  >
                    <span>JSON de la Petición (Request)</span>
                    <span>{showRequestJson ? "[-] " : "[+]"}</span>
                  </button>
                  <AnimatePresence>
                    {showRequestJson && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        className="p-2 bg-background/70 overflow-x-auto text-[9px] font-mono text-slate-300 whitespace-pre-wrap max-h-48"
                      >
                        {JSON.stringify(activeMetadata.layer_llm?.raw_request_json, null, 2)}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>

                {/* Raw Response JSON */}
                <div className="border border-slate-700/50 rounded overflow-hidden bg-background/10">
                  <button
                    onClick={() => setShowResponseJson(!showResponseJson)}
                    className="w-full flex justify-between items-center p-2.5 text-[10px] font-bold bg-background/20 hover:bg-background/40 transition-all border-b border-slate-700/20"
                  >
                    <span>JSON de la Respuesta (Response)</span>
                    <span>{showResponseJson ? "[-] " : "[+]"}</span>
                  </button>
                  <AnimatePresence>
                    {showResponseJson && (
                      <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        className="p-2 bg-background/70 overflow-x-auto text-[9px] font-mono text-slate-300 whitespace-pre-wrap max-h-48"
                      >
                        {JSON.stringify(activeMetadata.layer_llm?.raw_response_json, null, 2)}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
export default PlaygroundPage;
