// Catálogo de la pantalla de redirección: espejo de los enums del backend
// (`sentinel/redirect/models.py` y `sentinel/engine/redirect_credentials.py`).
// La paridad la fija `sentinel/tests/unit/test_console_catalog_parity.py`: si el backend suma
// un proveedor o cambia la forma de una credencial, ese test falla hasta que esto se actualice.

export const PROVIDERS = [
  "anthropic", "azure", "azure_ai", "bedrock", "vertex_ai", "deepseek", "openrouter",
  "ollama", "openai_compatible", "openai", "gemini", "groq", "zai", "nvidia_nim", "mistral",
  "hosted_vllm",
] as const;
export type Provider = (typeof PROVIDERS)[number];

export const PROVIDER_LABELS: Record<Provider, string> = {
  anthropic: "Anthropic",
  azure: "Azure OpenAI",
  azure_ai: "Azure AI",
  bedrock: "AWS Bedrock",
  vertex_ai: "Google Vertex AI",
  deepseek: "DeepSeek API",
  openrouter: "OpenRouter",
  ollama: "Ollama (local)",
  openai_compatible: "Compatible OpenAI",
  openai: "OpenAI",
  gemini: "Gemini",
  groq: "Groq",
  zai: "Z.AI (GLM)",
  nvidia_nim: "NVIDIA NIM (Nemotron)",
  mistral: "Mistral",
  hosted_vllm: "Servidor vLLM",
};

export const PROTOCOL_FAMILIES = ["anthropic_messages", "openai_responses", "openai_chat"] as const;
export type ProtocolFamily = (typeof PROTOCOL_FAMILIES)[number];
export const PROTOCOL_LABELS: Record<ProtocolFamily, string> = {
  anthropic_messages: "Mensajes (familia Claude)",
  openai_responses: "Responses (OpenAI)",
  openai_chat: "Chat completions (OpenAI)",
};

/** Sugerencia de familia de protocolo nativa por proveedor (el admin la puede cambiar). */
export const SUGGESTED_PROTOCOL: Record<Provider, ProtocolFamily> = {
  anthropic: "anthropic_messages",
  bedrock: "anthropic_messages",
  vertex_ai: "anthropic_messages",
  openai: "openai_responses",
  azure: "openai_responses",
  azure_ai: "openai_chat",
  deepseek: "openai_chat",
  openrouter: "openai_chat",
  ollama: "openai_chat",
  openai_compatible: "openai_chat",
  gemini: "openai_chat",
  groq: "openai_chat",
  zai: "openai_chat",
  nvidia_nim: "openai_chat",
  mistral: "openai_chat",
  hosted_vllm: "openai_chat",
};

/** Forma de la credencial por proveedor: [requeridos, opcionales] (SHAPES del backend). */
export const CREDENTIAL_SHAPES: Record<Provider, [string[], string[]]> = {
  openai: [["api_key"], []],
  anthropic: [["api_key"], []],
  openai_compatible: [["api_key"], []],
  deepseek: [["api_key"], []],
  openrouter: [["api_key"], []],
  azure_ai: [["api_key"], []],
  gemini: [["api_key"], []],
  groq: [["api_key"], []],
  zai: [["api_key"], []],
  nvidia_nim: [["api_key"], []],
  mistral: [["api_key"], []],
  hosted_vllm: [[], ["api_key"]],
  azure: [["api_key", "api_version"], []],
  bedrock: [["aws_access_key_id", "aws_secret_access_key", "aws_region_name"], ["aws_session_token"]],
  vertex_ai: [["vertex_credentials", "vertex_project", "vertex_location"], []],
  ollama: [[], ["api_key"]],
};

export const REQUIRES_API_BASE: readonly Provider[] = ["azure", "azure_ai", "ollama", "openai_compatible", "hosted_vllm"];
export const DEFAULT_API_BASE: Partial<Record<Provider, string>> = {
  openrouter: "https://openrouter.ai/api/v1",
};

/** Campos que son secretos (se piden con input de contraseña). */
export const SECRET_FIELDS = new Set([
  "api_key", "aws_access_key_id", "aws_secret_access_key", "aws_session_token", "vertex_credentials",
]);

export const CREDENTIAL_FIELD_LABELS: Record<string, string> = {
  api_key: "Clave de API",
  api_version: "Versión de API",
  aws_access_key_id: "Access key ID",
  aws_secret_access_key: "Secret access key",
  aws_region_name: "Región AWS",
  aws_session_token: "Session token (opcional)",
  vertex_credentials: "Cuenta de servicio (JSON)",
  vertex_project: "Proyecto",
  vertex_location: "Ubicación",
};

export const ENV_PREFIX = "env:";
export const ENV_NAME_PREFIX = "REDIRECT_CRED_";
export const ENV_NAME_RE = /^REDIRECT_CRED_[A-Z0-9_]*[A-Z0-9]$/;

export const FACES = ["claude", "codex", "openai_generic"] as const;
export type Face = (typeof FACES)[number];
export const FACE_LABELS: Record<Face, string> = {
  claude: "Claude",
  codex: "Codex",
  openai_generic: "OpenAI genérica",
};

export const FAMILY_TIERS = ["opus", "sonnet", "haiku", "fable", "mythos"] as const;
export type FamilyTier = (typeof FAMILY_TIERS)[number];

export const LABEL_MODES = ["destination", "requested", "custom"] as const;
export type LabelMode = (typeof LABEL_MODES)[number];
export const LABEL_MODE_LABELS: Record<LabelMode, string> = {
  destination: "Muestra el destino que sirve (el cliente lo ve)",
  requested: "Muestra el id pedido (predeterminado)",
  custom: "Etiqueta propia",
};

export const REQUEST_CLASSES = ["main", "subagent", "workflow", "compaction", "auxiliary"] as const;
export type RequestClass = (typeof REQUEST_CLASSES)[number];
export const REQUEST_CLASS_LABELS: Record<RequestClass, string> = {
  main: "Principal",
  subagent: "Subagente",
  workflow: "Flujo de trabajo",
  compaction: "Compactación",
  auxiliary: "Auxiliar",
};

export const SCOPE_TYPES = ["tenant", "group", "user", "connection"] as const;
export type ScopeType = (typeof SCOPE_TYPES)[number];
export const SCOPE_TYPE_LABELS: Record<ScopeType, string> = {
  tenant: "Toda la organización",
  group: "Grupo",
  user: "Usuario",
  connection: "Conexión",
};

export const POLICY_STATES = ["off", "shadow", "on"] as const;
export type PolicyState = (typeof POLICY_STATES)[number];
/** Estados que la pantalla OFRECE en el MVP (FR-010): *sombra* queda reservado para la fase F6 y no se
 *  elige desde el panel; una fila que ya viniera en sombra se sigue mostrando con su etiqueta. */
export const OFFERED_POLICY_STATES = ["off", "on"] as const satisfies readonly PolicyState[];
export const POLICY_STATE_LABELS: Record<PolicyState, string> = {
  off: "Apagada",
  shadow: "Sombra (solo registra)",
  on: "Encendida",
};

export const POSTURE_MODES = ["off", "allowlist", "offregion_masked"] as const;
export type PostureMode = (typeof POSTURE_MODES)[number];
export const POSTURE_MODE_LABELS: Record<PostureMode, string> = {
  off: "Sin restricción",
  allowlist: "Solo jurisdicciones permitidas",
  offregion_masked: "Fuera de región con enmascarado forzado",
};

/** Códigos de jurisdicción que ofrece la pantalla (el backend acepta hasta 8 caracteres). */
export const JURISDICTIONS: { code: string; label: string }[] = [
  { code: "EU", label: "Unión Europea" },
  { code: "US", label: "Estados Unidos" },
  { code: "UK", label: "Reino Unido" },
  { code: "CH", label: "Suiza" },
  { code: "CA", label: "Canadá" },
  { code: "LATAM", label: "Latinoamérica" },
  { code: "AR", label: "Argentina" },
  { code: "BR", label: "Brasil" },
  { code: "CL", label: "Chile" },
  { code: "CO", label: "Colombia" },
  { code: "MX", label: "México" },
  { code: "UY", label: "Uruguay" },
  { code: "CN", label: "China" },
  { code: "JP", label: "Japón" },
  { code: "IN", label: "India" },
  { code: "SG", label: "Singapur" },
  { code: "AU", label: "Australia" },
];

// ── kits, prueba de fidelidad y costos (US5) ────────────────────────────────

/** Herramientas con kit y corpus de fidelidad: espejo de `kits.TOOLS` del backend. */
export const KIT_TOOLS = ["claude_desktop", "claude_code", "codex", "openai_generic"] as const;
export type KitTool = (typeof KIT_TOOLS)[number];
export const KIT_TOOL_LABELS: Record<KitTool, string> = {
  claude_desktop: "Claude Desktop (configuración gestionada)",
  claude_code: "Claude Code",
  codex: "Codex",
  openai_generic: "CLI genérica (API compatible)",
};

/** Capacidades que mide la prueba (`fidelity.CAPABILITIES`). */
export const CAPABILITY_LABELS: Record<string, string> = {
  conversation: "Conversación",
  tools: "Herramientas",
  long_stream: "Streaming largo",
  errors: "Errores",
  context: "Contexto largo",
};

export const VERDICT_LABELS: Record<string, string> = {
  apto: "Apto",
  no_apto: "No apto",
  incompleto: "Incompleto (se agotó el presupuesto de la prueba)",
};

/** `detail_code` de cada resultado (`fidelity.evaluate`) en castellano. */
export const DETAIL_LABELS: Record<string, string> = {
  ok: "Correcto",
  empty_response: "Respondió vacío sin avisar",
  no_tool_call: "No llamó a la herramienta pedida",
  stream_too_short: "El streaming llegó corto",
  needle_missing: "Perdió el dato del contexto",
  no_error: "Aceptó un pedido inválido en vez de rechazarlo",
  unclassified_error: "Falló sin un error que la herramienta entienda",
  no_finish: "La respuesta no terminó",
  send_failed: "No hubo respuesta del destino",
  budget_exhausted: "No corrió: se agotó el presupuesto",
};
