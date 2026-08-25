import React, { useState, useEffect, useRef } from "react";
import { api } from "../services/api";
import type { RouterConfig, RouterRoute, EngineApplyStatus } from "../services/api";
import { authStorage } from "../services/auth";
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
  Toggle,
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

// ─────────────────────────────────────────────────────────────────────────────
// Auto-router semántico (spec 030) — helpers puros del panel «Ruteo inteligente»
// ─────────────────────────────────────────────────────────────────────────────

/** Config vacía servible: el panel siempre tiene una forma completa que editar aunque el
 *  GET devuelva un objeto parcial. Sin esto, un `routes` ausente reventaría el `.map` y el
 *  admin se quedaría sin la única pantalla desde la que puede arreglar la config. */
function normalizarRouter(cfg: any): RouterConfig {
  const rutas = Array.isArray(cfg?.routes) ? cfg.routes : [];
  return {
    enabled: !!cfg?.enabled,
    default_model: typeof cfg?.default_model === "string" ? cfg.default_model : "",
    timeout_seconds: typeof cfg?.timeout_seconds === "number" ? cfg.timeout_seconds : 5,
    embedding_model: typeof cfg?.embedding_model === "string" ? cfg.embedding_model : "",
    routes: rutas.map((r: any) => ({
      name: typeof r?.name === "string" ? r.name : "",
      // Los opcionales se normalizan a "" y `routerConfigPayload` los OMITE si siguen
      // vacíos al guardar: nunca viajan como null (rompería los `.get(campo, default)`).
      description: typeof r?.description === "string" ? r.description : "",
      target_model: typeof r?.target_model === "string" ? r.target_model : "",
      score_threshold: typeof r?.score_threshold === "number" ? r.score_threshold : 0.45,
      tier: typeof r?.tier === "string" ? r.tier : "",
      utterances: Array.isArray(r?.utterances)
        ? r.utterances.filter((u: any) => typeof u === "string" && u.trim())
        : [],
      // Sólo un `false` EXPLÍCITO señala rotura: si el backend no mandó el computado, no
      // se pinta una alarma roja inventada.
      target_ok: r?.target_ok !== false,
    })),
    default_model_ok: cfg?.default_model_ok !== false,
    embedding_model_ok: cfg?.embedding_model_ok !== false,
    config_error: !!cfg?.config_error,
  };
}

const timeoutValido = (t: number) => Number.isFinite(t) && t > 0 && t <= 60;

/** Espejo LIVIANO de la validación del backend (data-model §1): señala el campo exacto
 *  antes del viaje. La autoridad sigue siendo el PUT, que responde 422 con su detalle. */
function erroresDeRuta(ruta: RouterRoute): {
  name?: string;
  target?: string;
  umbral?: string;
  utterances?: string;
} {
  const errores: { name?: string; target?: string; umbral?: string; utterances?: string } = {};
  if (!ruta.name?.trim()) errores.name = "El nombre es obligatorio.";
  if (!ruta.target_model?.trim()) errores.target = "Elegí el modelo destino.";
  if (!(ruta.score_threshold > 0 && ruta.score_threshold <= 1))
    errores.umbral = "El umbral debe estar entre 0.05 y 1.";
  if (!ruta.utterances?.length)
    errores.utterances = "Generá o agregá al menos una frase de ejemplo.";
  return errores;
}

export const ModelsPage: React.FC = () => {
  const [allModels, setAllModels] = useState<ModelDetail[]>([]);
  const [fallbacks, setFallbacks] = useState<Record<string, string>>({});
  const [pricing, setPricing] = useState<Record<string, { input: number; output: number; max_tokens?: number }>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");
  const [actionLoading, setActionLoading] = useState(false);

  // ── Motor IA: estado del supervisor + botón «Aplicar cambios» (spec 033) ──
  const [engineStatus, setEngineStatus] = useState<EngineApplyStatus | null>(null);
  const [engineStatusLoading, setEngineStatusLoading] = useState(true);
  // Mensaje del GET de estado (p.ej. 403 de rol): se muestra tal cual, no se traga.
  const [engineStatusError, setEngineStatusError] = useState("");
  const [applyingEngine, setApplyingEngine] = useState(false);
  const [applyEngineError, setApplyEngineError] = useState("");
  // Timer del polling: vive fuera del estado porque un `setTimeout` en una var de estado
  // dispararía un re-render de más; sólo hace falta para poder cancelarlo en el cleanup.
  const engineStatusTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  // ── Panel «Ruteo inteligente» (spec 030) ──
  const [routerCfg, setRouterCfg] = useState<RouterConfig | null>(null);
  const [routerLoading, setRouterLoading] = useState(true);
  const [routerSaving, setRouterSaving] = useState(false);
  const [routerDirty, setRouterDirty] = useState(false);
  // Borrador del input de frases POR RUTA (índice → texto a medio escribir). Vive FUERA del
  // config a propósito: un tipeo sin confirmar no ensucia la config ni viaja en el PUT.
  const [utteranceDraft, setUtteranceDraft] = useState<Record<number, string>>({});
  // Acordeón: UNA ruta abierta a la vez (null = todas plegadas). El panel entero tiene que
  // entrar en una pantalla con la lista plegada; abrir todo a la vez era la queja concreta.
  const [rutaAbierta, setRutaAbierta] = useState<number | null>(null);
  // La calibración es el bloque LARGO (chips de frases): dentro de la ruta abierta arranca
  // colapsada, porque el flujo objetivo no la necesita — se generan y listo.
  const [calibracionAbierta, setCalibracionAbierta] = useState(false);
  // Índice generando (null = ninguno) y el error de ESA generación, mostrado al lado del
  // botón y no en la banda global de arriba: el admin está mirando acá abajo.
  const [generandoRuta, setGenerandoRuta] = useState<number | null>(null);
  const [errorGeneracion, setErrorGeneracion] = useState("");
  // Ruta recién creada: le pone el foco al nombre (autoFocus se dispara al montarse el
  // bloque expandido) sin necesidad de forwardRef en Field.
  const [rutaNueva, setRutaNueva] = useState<number | null>(null);

  // El pseudo-modelo «auto» lo INYECTA `GET /chat/models` para el dropdown del chat
  // (contrato 030): no es una entrada del catálogo del motor, así que no se gestiona ni se
  // activa desde esta página — se filtra de la tabla y del catálogo.
  const realModels = allModels.filter((m) => m.provider !== "auto");

  const activeModels = realModels.filter((m) => m.is_configured);

  const catalogModels = realModels.filter((m) => {
    if (catalogFilter === "eu") return m.is_eu_compliant;
    if (catalogFilter === "local") return m.provider === "ollama" || m.provider === "local";
    return true;
  });

  /** Plegar todo y limpiar lo que sólo tiene sentido con una ruta abierta. */
  const cerrarAcordeon = () => {
    setRutaAbierta(null);
    setCalibracionAbierta(false);
    setErrorGeneracion("");
    setRutaNueva(null);
  };

  /** Abre la ruta `i` (y cierra la que estuviera abierta) o la pliega si ya lo estaba. */
  const alternarRuta = (i: number) => {
    if (rutaAbierta === i) {
      cerrarAcordeon();
      return;
    }
    setRutaAbierta(i);
    setCalibracionAbierta(false);
    setErrorGeneracion("");
    setRutaNueva(null);
  };

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

  /** Carga APARTE de la de modelos: el ruteo caído no puede dejar sin tabla al admin, ni
   *  un catálogo caído sin panel de ruteo. Son dos endpoints y dos fallos distintos. */
  const loadRouter = async () => {
    setRouterLoading(true);
    try {
      setRouterCfg(normalizarRouter(await api.getRouterConfig()));
      setRouterDirty(false);
      setUtteranceDraft({});
      cerrarAcordeon();
    } catch (err: any) {
      setError(err?.message || "No se pudo cargar la configuración del ruteo inteligente.");
    } finally {
      setRouterLoading(false);
    }
  };

  useEffect(() => { load(); loadRouter(); }, []);

  /** Carga TERCERA y aparte: el estado del motor no depende del catálogo ni del ruteo, y un
   *  403 acá (rol sin permiso — ver `getEngineApplyStatus`) no puede tumbar las otras dos.
   *  Mientras el supervisor esté `applying`, se re-encola sola cada 3s: el POST de abajo no
   *  devuelve el resultado del ciclo, sólo lo dispara, así que este es el único lugar que se
   *  entera de si terminó bien (`idle`) o mal (`error`). */
  const cargarEstadoMotor = async () => {
    try {
      const estado = await api.getEngineApplyStatus();
      setEngineStatus(estado);
      setEngineStatusError("");
      if (estado.state === "applying") {
        engineStatusTimer.current = setTimeout(cargarEstadoMotor, 3000);
      }
    } catch (err: any) {
      setEngineStatus(null);
      setEngineStatusError(err?.message || "No se pudo consultar el estado del motor IA.");
    } finally {
      setEngineStatusLoading(false);
    }
  };

  useEffect(() => {
    cargarEstadoMotor();
    // Cleanup: si el admin cambia de página con un ciclo en curso, el polling no debe seguir
    // escribiendo estado de un componente ya desmontado.
    return () => {
      if (engineStatusTimer.current) clearTimeout(engineStatusTimer.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Dispara un ciclo nuevo (gate: sólo `admin`, ver botón condicionado abajo) y fuerza un
   *  re-chequeo inmediato en vez de esperar los 3s del polling — el admin que acaba de
   *  clickear quiere ver "Aplicando..." ya, no en la próxima vuelta del timer. */
  const handleApplyEngine = async () => {
    setApplyingEngine(true);
    setApplyEngineError("");
    try {
      await api.applyEngineChanges();
      if (engineStatusTimer.current) clearTimeout(engineStatusTimer.current);
      await cargarEstadoMotor();
    } catch (err: any) {
      setApplyEngineError(err?.message || "No se pudo disparar la aplicación de cambios del motor IA.");
    } finally {
      setApplyingEngine(false);
    }
  };

  const formatTs = (ts: number | null): string | null => (ts ? new Date(ts * 1000).toLocaleString() : null);

  // Esconder el botón para quien el backend igual rechazaría es UX, no el gate: la autoridad
  // es el `require_role("admin")` del propio POST. Si el rol quedó stale (sesión vieja) y de
  // toda forma llega un 403, `applyEngineError` lo muestra tal cual — no es una precondición
  // inventada, es sólo no ofrecer un botón que sabemos que el backend va a rechazar.
  const puedeAplicarMotor = authStorage.getUser()?.role === "admin";

  const mutarRouter = (fn: (cfg: RouterConfig) => RouterConfig) => {
    setRouterCfg((prev) => (prev ? fn(prev) : prev));
    setRouterDirty(true);
  };

  const mutarRuta = (indice: number, cambios: Partial<RouterRoute>) =>
    mutarRouter((cfg) => ({
      ...cfg,
      routes: cfg.routes.map((ruta, i) => (i === indice ? { ...ruta, ...cambios } : ruta)),
    }));

  const agregarUtterance = (indice: number) => {
    const texto = (utteranceDraft[indice] || "").trim();
    if (!texto) return;
    const actuales = routerCfg?.routes[indice]?.utterances || [];
    if (!actuales.includes(texto)) mutarRuta(indice, { utterances: [...actuales, texto] });
    setUtteranceDraft((prev) => ({ ...prev, [indice]: "" }));
  };

  const quitarUtterance = (indice: number, posicion: number) =>
    mutarRuta(indice, {
      utterances: (routerCfg?.routes[indice]?.utterances || []).filter((_, p) => p !== posicion),
    });

  /** Nace YA EXPANDIDA y con el foco en el nombre: el flujo es nombre → descripción →
   *  modelo → «Generar ejemplos» → guardar, sin un solo clic de más para empezar. */
  const agregarRuta = () => {
    const indice = routerCfg?.routes.length ?? 0;
    mutarRouter((cfg) => ({
      ...cfg,
      routes: [
        ...cfg.routes,
        {
          name: "",
          description: "",
          target_model: activeModels[0]?.model_name || "",
          score_threshold: 0.45,
          tier: "",
          utterances: [],
          target_ok: true,
        },
      ],
    }));
    setRutaAbierta(indice);
    setCalibracionAbierta(false);
    setErrorGeneracion("");
    setRutaNueva(indice);
  };

  const eliminarRuta = (indice: number) => {
    if (!confirm(`¿Eliminar la ruta "${routerCfg?.routes[indice]?.name || "sin nombre"}"?`)) return;
    // Los borradores están indexados por posición: al correrse los índices, el que quede
    // a medio escribir pertenecería a otra ruta. Se descartan todos.
    setUtteranceDraft({});
    // Mismo motivo para el acordeón: si se borra una ruta ANTERIOR a la abierta, el índice
    // guardado pasaría a señalar a su vecina y se vería expandida la ruta equivocada.
    setRutaAbierta((prev) =>
      prev === null || prev === indice ? null : prev > indice ? prev - 1 : prev
    );
    if (rutaAbierta === indice) setCalibracionAbierta(false);
    setErrorGeneracion("");
    setRutaNueva(null);
    mutarRouter((cfg) => ({ ...cfg, routes: cfg.routes.filter((_, i) => i !== indice) }));
  };

  /** Redacta las frases con el modelo local a partir de nombre + descripción y las MEZCLA
   *  con las que ya haya, sin duplicados (comparación laxa: espacios y mayúsculas no hacen
   *  frase nueva). No pisa lo escrito a mano — sólo agrega. */
  const generarEjemplos = async (indice: number) => {
    const ruta = routerCfg?.routes[indice];
    if (!ruta) return;
    setGenerandoRuta(indice);
    setErrorGeneracion("");
    try {
      const generadas = await api.generateUtterances(
        ruta.name.trim(),
        (ruta.description || "").trim(),
        ruta.utterances
      );
      const vistas = new Set(ruta.utterances.map((u) => u.trim().toLowerCase()));
      const nuevas = generadas.filter((frase) => {
        const clave = frase.trim().toLowerCase();
        if (!clave || vistas.has(clave)) return false;
        vistas.add(clave);
        return true;
      });
      if (nuevas.length === 0) {
        setErrorGeneracion(
          "El modelo no devolvió ninguna frase nueva. Probá con una descripción más específica."
        );
        return;
      }
      mutarRuta(indice, { utterances: [...ruta.utterances, ...nuevas] });
    } catch (err: any) {
      // El detalle del backend tal cual (p.ej. «no hay modelo local disponible»): una causa
      // genérica mandaría al admin a buscar el problema donde no está.
      setErrorGeneracion(err?.message || "No se pudieron generar frases de ejemplo.");
    } finally {
      setGenerandoRuta(null);
    }
  };

  const routerInvalido =
    !!routerCfg &&
    (!routerCfg.default_model.trim() ||
      !timeoutValido(routerCfg.timeout_seconds) ||
      routerCfg.routes.some((ruta) => Object.keys(erroresDeRuta(ruta)).length > 0));

  /** Un solo botón para TODO el panel (switch incluido) y no auto-guardado por control:
   *  el PUT escribe la config ENTERA, así que un toggle "inmediato" persistiría también
   *  las rutas a medio editar. El estado sucio se avisa en la cabecera de la tarjeta. */
  const guardarRouter = async () => {
    if (!routerCfg) return;
    setRouterSaving(true);
    setError("");
    setSuccessMsg("");
    try {
      setRouterCfg(normalizarRouter(await api.putRouterConfig(routerCfg)));
      setRouterDirty(false);
      setUtteranceDraft({});
      setSuccessMsg("Ruteo inteligente guardado. Aplica en la próxima consulta, sin reiniciar el motor IA.");
    } catch (err: any) {
      setError(err?.message || "No se pudo guardar la configuración del ruteo inteligente.");
    } finally {
      setRouterSaving(false);
    }
  };

  /** Opciones del catálogo REAL + la selección actual si ya no existe en él. Sin esa opción
   *  fantasma el <select> quedaría en blanco y el admin no vería QUÉ modelo apunta a la
   *  nada — justo el caso que la señal «ruta rota» existe para mostrar. */
  const opcionesModelo = (seleccionado: string) => {
    const nombres = activeModels.map((m) => m.model_name);
    const faltante = seleccionado && !nombres.includes(seleccionado) ? seleccionado : null;
    return (
      <>
        {faltante && (
          <option value={faltante}>{faltante} (ya no está en el catálogo)</option>
        )}
        {nombres.map((nombre) => (
          <option key={nombre} value={nombre}>{nombre}</option>
        ))}
      </>
    );
  };

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

      {/* ─── Motor IA: estado del supervisor + aplicar cambios (spec 033) ─── */}
      <Card title="Motor IA — aplicar cambios">
        {engineStatusLoading ? (
          <div className="flex justify-center py-6 font-mono text-xs text-text-secondary">
            Consultando estado del motor...
          </div>
        ) : engineStatusError ? (
          // 403 de rol (p.ej. `developer`, que ve el nav pero no este endpoint) o corte de
          // red: se muestra el texto real, no una pantalla en blanco ni un estado inventado.
          <div className="rounded-md border border-warn/30 bg-warn-bg px-4 py-2.5 text-xs leading-relaxed text-warn">
            No se pudo consultar el estado del motor IA: {engineStatusError}
          </div>
        ) : (
          <div className="space-y-3">
            {engineStatus?.state === "applying" && (
              <div className="flex items-center gap-2 rounded-md border border-primary/30 bg-primary-tint px-4 py-2.5 text-xs text-primary">
                <span className="h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-primary/40 border-t-primary" />
                Aplicando cambios del motor…
              </div>
            )}

            {engineStatus?.state === "error" && (
              <div className="rounded-md border border-danger/30 bg-danger-bg px-4 py-2.5 text-xs leading-relaxed text-danger">
                <p className="font-semibold">
                  El último ciclo de aplicación falló
                  {formatTs(engineStatus.ts) ? ` (${formatTs(engineStatus.ts)})` : ""}.
                </p>
                {/* `last_error` real del supervisor, sin maquillar (contrato T004): es
                    justamente lo que esta pantalla existe para mostrar. */}
                <p className="mt-1 font-mono text-[11px]">
                  {engineStatus.last_error || "El motor no reportó un motivo."}
                </p>
              </div>
            )}

            {engineStatus?.state === "unknown" && (
              <div className="rounded-md border border-border bg-surface-2 px-4 py-2.5 text-xs leading-relaxed text-text-secondary">
                Estado del motor no disponible
                {engineStatus.last_error ? `: ${engineStatus.last_error}` : "."}
              </div>
            )}

            {engineStatus?.state === "idle" && (
              <p className="text-[11px] text-text-secondary">
                Motor al día
                {formatTs(engineStatus.ts) ? ` · último ciclo aplicado ${formatTs(engineStatus.ts)}` : ""}
                {engineStatus.config_hash ? ` · config ${engineStatus.config_hash.slice(0, 8)}` : ""}.
              </p>
            )}

            {applyEngineError && (
              <div className="rounded-md border border-danger/30 bg-danger-bg px-4 py-2.5 text-xs text-danger">
                {applyEngineError}
              </div>
            )}

            <div className="flex items-center gap-3">
              {puedeAplicarMotor ? (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={handleApplyEngine}
                  disabled={applyingEngine || engineStatus?.state === "applying"}
                >
                  {applyingEngine ? "Disparando..." : "Aplicar cambios del motor"}
                </Button>
              ) : (
                <p className="text-[11px] text-text-tertiary">
                  Tu rol puede ver el estado del motor pero no aplicar cambios.
                </p>
              )}
            </div>
          </div>
        )}
      </Card>

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
                        if (!px) return <span className="text-[10px] text-text-tertiary">sin dato</span>;
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

      {/* ─── Ruteo inteligente (auto-router semántico, spec 030) ─── */}
      <Card
        title="Ruteo inteligente"
        actions={
          <>
            {routerDirty && <StatusBadge tone="warn">Cambios sin guardar</StatusBadge>}
            <Button
              variant="primary"
              size="sm"
              onClick={guardarRouter}
              disabled={routerSaving || routerLoading || !routerCfg || !routerDirty || routerInvalido}
            >
              {routerSaving ? "Guardando..." : "Guardar ruteo"}
            </Button>
            {routerCfg && (
              <div
                className="ml-1 flex items-center gap-2 border-l border-border pl-3"
                title="Con «Auto» elegido en el chat, cada consulta se clasifica en esta misma máquina (embeddings locales: el texto nunca sale del servidor para decidir) y va al modelo de la ruta ganadora. Apagado, «Auto» se sirve siempre por el modelo por defecto."
              >
                <span className="text-xs font-medium text-text-secondary">
                  {routerCfg.enabled ? "Activo" : "Inactivo"}
                </span>
                <Toggle
                  checked={routerCfg.enabled}
                  onChange={(valor) => mutarRouter((cfg) => ({ ...cfg, enabled: valor }))}
                  label="Ruteo automático"
                  size="sm"
                />
              </div>
            )}
          </>
        }
      >
        {routerLoading ? (
          <div className="flex justify-center py-12 font-mono text-xs text-text-secondary">
            Cargando configuración de ruteo...
          </div>
        ) : !routerCfg ? (
          <div className="py-8 text-center text-xs text-text-secondary">
            No se pudo cargar la configuración del ruteo.{" "}
            <button className="text-primary underline" onClick={loadRouter}>
              Reintentar
            </button>
          </div>
        ) : (
          <div className="space-y-4">
            {routerCfg.config_error && (
              <div className="rounded-md border border-warn/30 bg-warn-bg px-4 py-2.5 text-xs leading-relaxed text-warn">
                <span className="font-semibold">Configuración de ruteo no legible.</span> El archivo
                del servidor falta o está corrupto, así que abajo se muestran los valores por defecto
                (ruteo apagado, sin rutas). Las consultas con «Auto» se sirven mientras tanto por el
                modelo por defecto. Al guardar se reescribe el archivo con lo que veas acá.
              </div>
            )}

            {/* Modelo por defecto + timeout */}
            <div className="grid gap-4 sm:grid-cols-2">
              <Field
                label="Modelo por defecto"
                hint="Se usa con el ruteo apagado, cuando ninguna ruta supera su umbral y cuando el ruteo falla."
              >
                <>
                  <select
                    value={routerCfg.default_model}
                    onChange={(e) => mutarRouter((cfg) => ({ ...cfg, default_model: e.target.value }))}
                    className={cn(inputBaseClass, "border-border")}
                  >
                    <option value="">Elegir modelo…</option>
                    {opcionesModelo(routerCfg.default_model)}
                  </select>
                  {/* Sin modelo elegido el backend computa `default_model_ok: false` igual;
                      la alarma se guarda para el caso real (apunta a algo inexistente), que
                      es el que el admin tiene que corregir. */}
                  {routerCfg.default_model && !routerCfg.default_model_ok && (
                    <StatusBadge tone="danger" className="self-start">
                      «{routerCfg.default_model}» no está en el catálogo
                    </StatusBadge>
                  )}
                </>
              </Field>

              <Field
                label="Timeout del ruteo (segundos)"
                type="number"
                min={1}
                max={60}
                step={1}
                value={routerCfg.timeout_seconds}
                onChange={(e) => {
                  const valor = Number(e.target.value);
                  mutarRouter((cfg) => ({
                    ...cfg,
                    timeout_seconds: e.target.value === "" || !Number.isFinite(valor) ? 0 : valor,
                  }));
                }}
                error={timeoutValido(routerCfg.timeout_seconds) ? undefined : "Debe ser un número entre 1 y 60."}
                hint="Si la clasificación tarda más, la consulta se sirve igual por el modelo por defecto y queda registrada como ruteo degradado."
              />
            </div>

            {/* Estado del modelo de embeddings: una línea discreta, no una tarjeta. El caso
                normal es «anda» y no merece un bloque; el roto se ve igual en rojo. */}
            <p className="flex flex-wrap items-center gap-x-1.5 text-[11px] leading-relaxed text-text-secondary">
              <span className={cn("text-sm leading-none", routerCfg.embedding_model_ok ? "text-ok" : "text-danger")}>
                ●
              </span>
              <span>Embeddings locales:</span>
              <span className="font-mono text-text-primary">
                {routerCfg.embedding_model || "sin configurar"}
              </span>
              <span className={routerCfg.embedding_model_ok ? undefined : "text-danger"}>
                {routerCfg.embedding_model_ok
                  ? ": la clasificación corre en esta máquina y el texto de la consulta no sale para decidir."
                  : "no disponible: falta en el catálogo del motor IA o en Ollama (ollama pull). Mientras tanto «Auto» va por el modelo por defecto y queda registrado como ruteo degradado."}
              </span>
            </p>

            {/* Editor de rutas: lista plegada, se abre UNA a la vez */}
            <div className="space-y-2">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="min-w-0 text-[11px] leading-relaxed text-text-secondary">
                  <span className="text-xs font-semibold text-text-primary">Rutas semánticas</span>
                  {" · "}
                  Gana la de mayor parecido que supere su propio umbral; con empate, la primera.
                  Si ninguna llega, va al modelo por defecto.
                </p>
                <Button variant="secondary" size="sm" onClick={agregarRuta}>
                  + Agregar ruta
                </Button>
              </div>

              {routerCfg.routes.length === 0 ? (
                <div className="rounded-md border border-dashed border-border py-6 text-center text-xs text-text-secondary">
                  Sin rutas configuradas: «Auto» sirve siempre por el modelo por defecto.
                </div>
              ) : (
                <div className="divide-y divide-border overflow-hidden rounded-md border border-border">
                  {routerCfg.routes.map((ruta, i) => {
                    const errores = erroresDeRuta(ruta);
                    const incompleta = Object.keys(errores).length > 0;
                    const abierta = rutaAbierta === i;
                    const generandoEsta = generandoRuta === i;
                    // Sin las dos cosas el modelo no tiene de dónde sacar las frases: mejor
                    // botón apagado con motivo que una generación que devuelve cualquier cosa.
                    const puedeGenerar = !!ruta.name.trim() && !!(ruta.description || "").trim();
                    return (
                      <div key={i} className={cn(abierta ? "bg-surface-2" : "bg-surface")}>
                        {/* Renglón plegado: altura de fila de tabla, todo lo decisivo de un vistazo */}
                        <div className="flex items-center gap-2 px-3 py-1.5">
                          <button
                            type="button"
                            onClick={() => alternarRuta(i)}
                            aria-expanded={abierta}
                            className="flex min-w-0 flex-1 items-center gap-2 text-left"
                          >
                            <span className="w-6 shrink-0 font-mono text-[10px] text-text-tertiary">
                              #{i + 1}
                            </span>
                            {ruta.tier && (
                              <StatusBadge tone="neutral" className="shrink-0 uppercase">
                                {ruta.tier}
                              </StatusBadge>
                            )}
                            <span
                              className={cn(
                                "shrink-0 text-xs font-semibold",
                                ruta.name.trim() ? "text-text-primary" : "text-text-tertiary"
                              )}
                            >
                              {ruta.name.trim() || "Ruta sin nombre"}
                            </span>
                            <span className="min-w-0 flex-1 truncate text-[11px] text-text-secondary">
                              {ruta.description?.trim() ? `· ${ruta.description.trim()}` : ""}
                            </span>
                            <span className="shrink-0 text-[11px] text-text-secondary">
                              →{" "}
                              <span
                                className={cn(
                                  "font-mono",
                                  ruta.target_model ? "text-text-primary" : "text-danger"
                                )}
                              >
                                {ruta.target_model || "sin modelo"}
                              </span>
                            </span>
                            <span
                              className="shrink-0 text-[11px] text-text-tertiary"
                              title="Frases de ejemplo con las que se calibra esta ruta"
                            >
                              🏷 {ruta.utterances.length}{" "}
                              {ruta.utterances.length === 1 ? "frase" : "frases"}
                            </span>
                            {ruta.target_ok === false && (
                              <StatusBadge tone="danger" className="shrink-0">Ruta rota</StatusBadge>
                            )}
                            {/* La validación espejo tiene que verse TAMBIÉN plegada: si no, el
                                botón «Guardar ruteo» queda gris sin decir por culpa de cuál. */}
                            {!abierta && incompleta && (
                              <StatusBadge tone="warn" className="shrink-0">Incompleta</StatusBadge>
                            )}
                          </button>
                          <div className="flex shrink-0 items-center gap-1">
                            <Button variant="ghost" size="sm" onClick={() => alternarRuta(i)}>
                              {abierta ? "Cerrar" : "Editar"}
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => eliminarRuta(i)}
                              className="text-danger hover:bg-danger-bg hover:text-danger"
                            >
                              Eliminar
                            </Button>
                          </div>
                        </div>

                        {abierta && (
                          <div className="space-y-3 border-t border-border px-3 py-3">
                            <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_7rem]">
                              <Field
                                label="Nombre"
                                value={ruta.name}
                                onChange={(e) => mutarRuta(i, { name: e.target.value })}
                                placeholder="ej: Código y análisis"
                                error={errores.name}
                                autoFocus={rutaNueva === i}
                              />
                              <Field label="Modelo destino" error={errores.target}>
                                <select
                                  value={ruta.target_model}
                                  onChange={(e) => mutarRuta(i, { target_model: e.target.value })}
                                  className={cn(
                                    inputBaseClass,
                                    errores.target ? "border-danger" : "border-border"
                                  )}
                                >
                                  <option value="">Elegir modelo…</option>
                                  {opcionesModelo(ruta.target_model)}
                                </select>
                              </Field>
                              {/* La ayuda del umbral va en el tooltip, no en un párrafo: es el
                                  campo que menos se toca y el que más alto ocupaba. */}
                              <Field
                                label={
                                  <span title="Parecido mínimo (0.05 a 1) para que una consulta caiga en esta ruta. Más alto = más exigente.">
                                    Umbral ⓘ
                                  </span>
                                }
                                type="number"
                                min={0.05}
                                max={1}
                                step={0.05}
                                value={ruta.score_threshold}
                                onChange={(e) => {
                                  const valor = Number(e.target.value);
                                  mutarRuta(i, {
                                    score_threshold:
                                      e.target.value === "" || !Number.isFinite(valor) ? 0 : valor,
                                  });
                                }}
                                error={errores.umbral}
                                title="Parecido mínimo (0.05 a 1) para que una consulta caiga en esta ruta. Más alto = más exigente."
                              />
                            </div>

                            <Field
                              label="Descripción"
                              value={ruta.description || ""}
                              onChange={(e) => mutarRuta(i, { description: e.target.value })}
                              placeholder="Para qué sirve esta ruta: de acá salen las frases de ejemplo"
                            />

                            {/* Calibración: colapsada por defecto. El flujo objetivo del admin
                                (nombre + descripción + modelo + generar + guardar) no la abre. */}
                            <div className="rounded-md border border-border bg-surface">
                              <button
                                type="button"
                                onClick={() => setCalibracionAbierta((v) => !v)}
                                aria-expanded={calibracionAbierta}
                                className="flex w-full items-center gap-2 px-3 py-2 text-left"
                              >
                                <span className="w-3 shrink-0 text-[10px] text-text-tertiary">
                                  {calibracionAbierta ? "▾" : "▸"}
                                </span>
                                <span className="shrink-0 text-xs font-semibold text-text-primary">
                                  Calibración (frases de ejemplo)
                                </span>
                                <StatusBadge
                                  tone={errores.utterances ? "danger" : "neutral"}
                                  className="shrink-0"
                                >
                                  {ruta.utterances.length}{" "}
                                  {ruta.utterances.length === 1 ? "frase" : "frases"}
                                </StatusBadge>
                                {errores.utterances && !calibracionAbierta && (
                                  <span className="min-w-0 truncate text-[11px] text-danger">
                                    {errores.utterances}
                                  </span>
                                )}
                                <span className="ml-auto shrink-0 text-[11px] text-text-tertiary">
                                  {calibracionAbierta ? "Ocultar" : "Abrir"}
                                </span>
                              </button>

                              {calibracionAbierta && (
                                <div className="space-y-2 border-t border-border px-3 py-3">
                                  <div className="flex flex-wrap items-center gap-2">
                                    {/* El title va en el envoltorio: el botón deshabilitado
                                        tiene pointer-events:none y no mostraría su tooltip
                                        justo cuando hace falta explicar por qué está gris. */}
                                    <span
                                      title={
                                        puedeGenerar
                                          ? "Redacta frases típicas de esta ruta con el modelo local y las agrega abajo."
                                          : "Escribí nombre y descripción primero"
                                      }
                                    >
                                      <Button
                                        variant="primary"
                                        size="sm"
                                        onClick={() => generarEjemplos(i)}
                                        disabled={!puedeGenerar || generandoRuta !== null || routerSaving}
                                        leftIcon={
                                          generandoEsta ? (
                                            <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                                          ) : null
                                        }
                                      >
                                        {generandoEsta ? "Generando..." : "✨ Generar ejemplos"}
                                      </Button>
                                    </span>
                                    <span className="text-[11px] text-text-tertiary">
                                      Las escribe el modelo local a partir del nombre y la
                                      descripción. Puede tardar unos segundos.
                                    </span>
                                  </div>

                                  {errorGeneracion && (
                                    <div className="rounded-md border border-danger/30 bg-danger-bg px-3 py-2 text-[11px] leading-relaxed text-danger">
                                      {errorGeneracion}
                                    </div>
                                  )}

                                  {ruta.utterances.length > 0 && (
                                    <div className="flex flex-wrap gap-1.5">
                                      {ruta.utterances.map((frase, posicion) => (
                                        <span
                                          key={`${posicion}-${frase}`}
                                          className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-2 px-2 py-0.5 text-[11px] text-text-primary"
                                        >
                                          {frase}
                                          <button
                                            type="button"
                                            onClick={() => quitarUtterance(i, posicion)}
                                            aria-label={`Quitar la frase "${frase}"`}
                                            className="leading-none text-text-tertiary transition-colors hover:text-danger"
                                          >
                                            ×
                                          </button>
                                        </span>
                                      ))}
                                    </div>
                                  )}

                                  <input
                                    value={utteranceDraft[i] || ""}
                                    onChange={(e) =>
                                      setUtteranceDraft((prev) => ({ ...prev, [i]: e.target.value }))
                                    }
                                    onKeyDown={(e) => {
                                      if (e.key === "Enter") {
                                        e.preventDefault();
                                        agregarUtterance(i);
                                      }
                                    }}
                                    placeholder="¿Falta un caso? Escribilo y presioná Enter"
                                    className={cn(
                                      inputBaseClass,
                                      "h-8 text-xs",
                                      errores.utterances ? "border-danger" : "border-border"
                                    )}
                                  />
                                </div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
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
