import React, { useState, useEffect } from "react";
import { api } from "../services/api";
import {
  Button,
  Card,
  Field,
  PageHeader,
  StatusBadge,
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD,
  cn,
  inputBaseClass,
} from "../components/ui";

// Select con tokens del kit (no hay componente Select propio): mismo lenguaje que inputBaseClass.
const selectClass =
  "h-8 rounded-md border border-border bg-surface px-2 text-xs text-text-primary " +
  "focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2 focus:ring-offset-canvas";

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

interface ProviderField {
  key: string;
  label: string;
  placeholder: string;
  type?: "text" | "password" | "url";
  hint?: string;
}

const PROVIDER_FIELDS: Record<string, ProviderField[]> = {
  openai: [
    { key: "api_key", label: "API Key", placeholder: "sk-...", type: "password" },
  ],
  anthropic: [
    { key: "api_key", label: "API Key", placeholder: "sk-ant-...", type: "password" },
  ],
  gemini: [
    { key: "api_key", label: "API Key", placeholder: "AIza...", type: "password" },
  ],
  groq: [
    { key: "api_key", label: "API Key", placeholder: "gsk_...", type: "password" },
  ],
  cloudflare: [
    { key: "api_key", label: "API Token", placeholder: "...", type: "password" },
    { key: "api_base", label: "Account URL", placeholder: "https://api.cloudflare.com/client/v4/accounts/ACCOUNT_ID/ai/v1", type: "url", hint: "Reemplazá ACCOUNT_ID con tu ID de cuenta de Cloudflare" },
  ],
  azure: [
    { key: "api_key", label: "Azure API Key", placeholder: "...", type: "password" },
    { key: "api_base", label: "Azure Endpoint", placeholder: "https://my-resource.openai.azure.com/", type: "url" },
    { key: "api_version", label: "API Version", placeholder: "2024-02-01" },
  ],
  bedrock: [
    { key: "aws_access_key_id", label: "AWS Access Key ID", placeholder: "AKIA...", type: "password" },
    { key: "aws_secret_access_key", label: "AWS Secret Access Key", placeholder: "...", type: "password" },
    { key: "aws_region_name", label: "Región AWS", placeholder: "us-east-1", hint: "Elegí una región con data center en la UE para compliance: eu-west-1, eu-central-1" },
  ],
  vertex_ai: [
    { key: "vertex_project", label: "GCP Project ID", placeholder: "my-project-123" },
    { key: "vertex_location", label: "Región GCP", placeholder: "us-central1", hint: "Para compliance UE: europe-west1, europe-west4" },
    { key: "vertex_credentials", label: "Service Account JSON (path)", placeholder: "/secrets/gcp-credentials.json", hint: "Path al archivo JSON de credenciales dentro del contenedor" },
  ],
  watsonx: [
    { key: "ibm_api_key", label: "IBM API Key", placeholder: "...", type: "password" },
    { key: "ibm_project_id", label: "Project ID", placeholder: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" },
    { key: "ibm_url", label: "WatsonX URL", placeholder: "https://us-south.ml.cloud.ibm.com", type: "url" },
  ],
  ollama: [
    { key: "api_base", label: "API Base URL", placeholder: "http://host.docker.internal:11434", type: "url", hint: "Usá host.docker.internal para acceder a Ollama corriendo en el host desde Docker" },
  ],
};

type CatalogFilter = "all" | "eu" | "local";

export const ModelsPage: React.FC = () => {
  const [allModels, setAllModels] = useState<ModelDetail[]>([]);
  const [fallbacks, setFallbacks] = useState<Record<string, string>>({});
  const [pricing, setPricing] = useState<Record<string, { input: number; output: number; max_tokens?: number }>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");
  const [actionLoading, setActionLoading] = useState(false);

  // Catalog modal
  const [showCatalog, setShowCatalog] = useState(false);
  const [catalogFilter, setCatalogFilter] = useState<CatalogFilter>("all");

  // Activate modal (for a specific unconfigured model)
  const [activatingModel, setActivatingModel] = useState<ModelDetail | null>(null);
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({});

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
      const [models, fb, px] = await Promise.all([api.getModels(), api.getFallbacks(), api.getModelsPricing()]);
      setAllModels(models);
      setFallbacks(fb);
      const pxMap: Record<string, { input: number; output: number; max_tokens?: number }> = {};
      for (const p of px) pxMap[p.model_name] = { input: p.input_cost_per_million, output: p.output_cost_per_million, max_tokens: p.max_tokens };
      setPricing(pxMap);
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
      const params: Record<string, string> = {};
      for (const [k, v] of Object.entries(fieldValues)) {
        if (v.trim()) params[k] = v.trim();
      }
      await api.updateModelCredential(activatingModel.model_name, params);
      setSuccessMsg(`Modelo ${activatingModel.model_name} configurado. Reiniciá el motor IA para aplicar los cambios.`);
      setActivatingModel(null);
      setFieldValues({});
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
      <PageHeader
        title="Modelos de IA & Proveedores"
        subtitle="Gestione los modelos activos, configure fallbacks automáticos y active nuevos proveedores."
        actions={
          <Button variant="primary" size="sm" onClick={() => setShowCatalog(true)}>
            + Agregar Modelo
          </Button>
        }
      />

      {error && (
        <div className="rounded-md border border-danger/30 bg-danger-bg px-4 py-2.5 text-xs text-danger">{error}</div>
      )}
      {successMsg && (
        <div className="rounded-md border border-ok/30 bg-ok-bg px-4 py-2.5 text-xs text-ok">{successMsg}</div>
      )}

      {/* Active Models Table */}
      <Card title="Modelos Activos en la Pasarela">
        {loading ? (
          <div className="flex justify-center py-12 font-mono text-xs text-text-secondary">Cargando modelos...</div>
        ) : activeModels.length === 0 ? (
          <div className="py-8 text-center text-xs text-text-secondary">
            No hay modelos configurados.{" "}
            <button className="text-primary underline" onClick={() => setShowCatalog(true)}>
              Agregar uno desde el catálogo
            </button>
          </div>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Nombre</TH>
                <TH>Proveedor</TH>
                <TH>Compliance</TH>
                <TH>Precio / 1M tokens</TH>
                <TH>Fallback automático</TH>
                <TH className="text-right">Acción</TH>
              </TR>
            </THead>
            <TBody>
              {activeModels.map((m) => {
                const otherActive = activeModels.filter((x) => x.model_name !== m.model_name);
                return (
                  <TR key={m.model_name} className="hover:bg-surface-2">
                    <TD className="font-semibold">{m.model_name}</TD>
                    <TD>
                      <StatusBadge tone="neutral" className="uppercase">
                        {PROVIDER_LABELS[m.provider] || m.provider}
                      </StatusBadge>
                    </TD>
                    <TD>
                      {m.is_eu_compliant ? (
                        <StatusBadge tone="ok">UE Compliant</StatusBadge>
                      ) : (
                        <StatusBadge tone="neutral">Cloud estándar</StatusBadge>
                      )}
                    </TD>
                    <TD>
                      {(() => {
                        const px = pricing[m.model_name];
                        if (!px) return <span className="text-[10px] text-text-tertiary">—</span>;
                        if (px.input === 0 && px.output === 0)
                          return <span className="font-mono text-[10px] font-bold text-ok">Gratis</span>;
                        return (
                          <div className="font-mono text-[10px] leading-tight">
                            <div className="text-text-secondary">IN <span className="text-text-primary">${px.input.toFixed(2)}</span></div>
                            <div className="text-text-secondary">OUT <span className="text-text-primary">${px.output.toFixed(2)}</span></div>
                          </div>
                        );
                      })()}
                    </TD>
                    <TD>
                      <select
                        value={fallbacks[m.model_name] || ""}
                        onChange={(e) => handleFallbackChange(m.model_name, e.target.value)}
                        className={selectClass}
                      >
                        <option value="">Sin fallback</option>
                        {otherActive.map((o) => (
                          <option key={o.model_name} value={o.model_name}>
                            {o.model_name}
                          </option>
                        ))}
                      </select>
                    </TD>
                    <TD className="text-right">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDelete(m.model_name)}
                        disabled={actionLoading}
                        className="text-danger hover:bg-danger-bg hover:text-danger"
                      >
                        Eliminar
                      </Button>
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        )}
      </Card>

      {/* ─── Catalog Modal ─── */}
      {showCatalog && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-16">
          <div className="flex max-h-[80vh] w-full max-w-3xl flex-col rounded-card border border-border bg-surface shadow-2xl">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-border p-5">
              <div>
                <h2 className="text-base font-semibold text-text-primary">Catálogo de Modelos</h2>
                <p className="mt-0.5 text-xs text-text-secondary">
                  Seleccione un modelo para activarlo en la pasarela. Los modelos marcados{" "}
                  <span className="font-semibold text-ok">UE Compliant</span> soportan residencia de datos en Europa.
                </p>
              </div>
              <button
                onClick={() => { setShowCatalog(false); setShowCustomForm(false); }}
                className="text-lg leading-none text-text-secondary hover:text-text-primary"
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
                  className={cn(
                    "rounded-full border px-3 py-1 text-xs font-semibold transition-colors",
                    catalogFilter === f
                      ? "border-primary/40 bg-primary-tint text-primary"
                      : "border-border text-text-secondary hover:bg-surface-2 hover:text-text-primary"
                  )}
                >
                  {f === "all" ? "Todos" : f === "eu" ? "Solo UE Compliant" : "Local (Ollama)"}
                </button>
              ))}
              <div className="flex-1" />
              <button
                onClick={() => setShowCustomForm(!showCustomForm)}
                className="rounded-md border border-border px-3 py-1 text-xs font-semibold text-text-secondary transition-colors hover:bg-surface-2 hover:text-text-primary"
              >
                {showCustomForm ? "← Volver al catálogo" : "+ Modelo personalizado"}
              </button>
            </div>

            {/* Body */}
            <div className="flex-1 space-y-2 overflow-y-auto p-5">
              {showCustomForm ? (
                <form onSubmit={handleCustomRegister} className="max-w-md space-y-4">
                  <Field
                    label="Nombre en pasarela"
                    required
                    value={customName}
                    onChange={(e) => setCustomName(e.target.value)}
                    placeholder="ej: mi-gpt4o"
                  />
                  <Field label="Proveedor">
                    <select
                      value={customProvider}
                      onChange={(e) => setCustomProvider(e.target.value)}
                      className={cn(inputBaseClass, "border-border")}
                    >
                      {Object.entries(PROVIDER_LABELS).map(([k, v]) => (
                        <option key={k} value={k}>{v}</option>
                      ))}
                    </select>
                  </Field>
                  <Field
                    label="ID del modelo en el proveedor"
                    required
                    value={customModelId}
                    onChange={(e) => setCustomModelId(e.target.value)}
                    placeholder="ej: gpt-4o, llama3, claude-3-5-sonnet"
                  />
                  <Field
                    label="API Key"
                    type="password"
                    value={customKey}
                    onChange={(e) => setCustomKey(e.target.value)}
                    placeholder="Dejar vacío si se configura en .env"
                  />
                  <Field
                    label="API Base (opcional)"
                    value={customBase}
                    onChange={(e) => setCustomBase(e.target.value)}
                    placeholder="ej: http://localhost:11434"
                  />
                  <Button type="submit" variant="primary" disabled={actionLoading} className="w-full">
                    {actionLoading ? "Registrando..." : "Registrar Modelo"}
                  </Button>
                </form>
              ) : (
                catalogModels.map((m) => {
                  const isActive = m.is_configured;
                  const hint = PROVIDER_CREDENTIAL_HINT[m.provider] || "";
                  return (
                    <div
                      key={m.model_name}
                      className={cn(
                        "flex items-center gap-4 rounded-lg border p-4 transition-colors",
                        isActive
                          ? "border-ok/30 bg-ok-bg"
                          : "border-border bg-surface hover:border-border-strong"
                      )}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs font-semibold text-text-primary">{m.model_name}</span>
                          <StatusBadge tone="neutral" className="uppercase">
                            {PROVIDER_LABELS[m.provider] || m.provider}
                          </StatusBadge>
                          {m.is_eu_compliant && <StatusBadge tone="ok">UE Compliant</StatusBadge>}
                        </div>
                        <p className="mt-1 font-mono text-[11px] text-text-secondary">{m.model_id}</p>
                        {!isActive && hint && (
                          <p className="mt-1 text-[11px] text-warn">Requiere: {hint}</p>
                        )}
                      </div>
                      <div className="flex-shrink-0">
                        {isActive ? (
                          <StatusBadge tone="ok">✓ Activo</StatusBadge>
                        ) : (
                          <Button
                            variant="secondary"
                            size="sm"
                            onClick={() => {
                              setActivatingModel(m);
                              // `setActivateKey`/`setActivateBase` quedaron de un refactor
                              // anterior: los estados ya no existen y el modal se llena con
                              // `fieldValues` (ver el cierre, que hace `setFieldValues({})`).
                              // Eran dos ReferenceError en el click de "Configurar", así que
                              // el modal NUNCA abría; no se detectaba porque el build oficial
                              // no chequeaba tipos (frontend sin tsconfig).
                              setFieldValues({});
                              setShowCatalog(false);
                            }}
                          >
                            Configurar
                          </Button>
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
      {activatingModel && (() => {
        const fields = PROVIDER_FIELDS[activatingModel.provider] || [
          { key: "api_key", label: "API Key", placeholder: "...", type: "password" as const },
        ];
        const isLocal = activatingModel.provider === "ollama" || activatingModel.provider === "local";
        const hasRequiredFields = isLocal || fields.some((f) => fieldValues[f.key]?.trim());

        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
            <div className="w-full max-w-md space-y-5 rounded-card border border-border bg-surface p-6 shadow-2xl">
              {/* Header */}
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-sm font-semibold text-text-primary">{activatingModel.model_name}</h2>
                  <p className="mt-0.5 text-[11px] text-text-secondary">
                    {PROVIDER_LABELS[activatingModel.provider] || activatingModel.provider}
                  </p>
                </div>
                <button onClick={() => { setActivatingModel(null); setFieldValues({}); }} className="text-text-secondary hover:text-text-primary">✕</button>
              </div>

              {/* Badges */}
              <div className="flex flex-wrap gap-2">
                <StatusBadge tone="neutral" className="uppercase">
                  {PROVIDER_LABELS[activatingModel.provider] || activatingModel.provider}
                </StatusBadge>
                {activatingModel.is_eu_compliant && <StatusBadge tone="ok">UE Compliant</StatusBadge>}
              </div>

              {isLocal ? (
                <div className="space-y-3 text-xs text-text-secondary">
                  <p>
                    Ollama no requiere API key. El servicio debe estar corriendo en{" "}
                    <span className="font-mono text-text-primary">{activatingModel.api_base || "http://host.docker.internal:11434"}</span>.
                  </p>
                  <p className="text-ok">Si Ollama está activo, este modelo debería aparecer como configurado automáticamente.</p>
                </div>
              ) : (
                <>
                  <div className="space-y-1 rounded-md border border-border bg-surface-2 p-3 text-[11px] text-text-secondary">
                    <p className="font-semibold text-text-primary">Credenciales requeridas</p>
                    <p>Los valores se guardan en el archivo de configuración del motor IA. También podés configurarlos en <span className="font-mono text-text-primary">.env</span> y reiniciar.</p>
                  </div>

                  <div className="space-y-3">
                    {fields.map((f) => (
                      <Field
                        key={f.key}
                        label={f.label}
                        type={f.type || "text"}
                        value={fieldValues[f.key] || ""}
                        onChange={(e) => setFieldValues((prev) => ({ ...prev, [f.key]: e.target.value }))}
                        placeholder={f.placeholder}
                        hint={f.hint}
                      />
                    ))}
                  </div>

                  <Button
                    onClick={handleActivate}
                    variant="primary"
                    disabled={actionLoading || !hasRequiredFields}
                    className="w-full"
                  >
                    {actionLoading ? "Guardando..." : "Guardar configuración"}
                  </Button>
                </>
              )}
            </div>
          </div>
        );
      })()}
    </div>
  );
};

export default ModelsPage;
