# Configuración (variables de entorno)

!!! info "Página generada — no editar a mano"
    Esta referencia se genera del `.env.example` del producto (una sola fuente de
    verdad). Los valores marcados como secretos los genera cada instalación — jamás
    hay defaults sensibles.

| Variable | Default | Descripción |
|---|---|---|
| `POSTGRES_DB` | `basa_gateway` | Database Configuration |
| `POSTGRES_USER` | `basa_admin` | — |
| `POSTGRES_PASSWORD` | *(secreto — generado por instalación)* | — |
| `JWT_SECRET_KEY` | — | Backend secrets (OBLIGATORIOS - generar valores propios, no dejar vacíos) JWT_SECRET_KEY:    python3 -c "import secrets; print(secrets.token_urlsafe(48))" FERNET_SECRET_KEY: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" |
| `FERNET_SECRET_KEY` | — | — |
| `LITELLM_MASTER_KEY` | *(secreto — generado por instalación)* | Configuración del motor del gateway |
| `BASA_ENGINE_MAX_CONCURRENCY` | `8` | Pedidos en vuelo hacia el motor por proceso — la perilla del TOPE. Rango válido: 1..64 (fuera de ahí se ignora con warning). Cada pedido admitido retiene una conexión del pool (30 por proceso): con 8 quedan ~22 libres para login, admin y health. Un tope demasiado alto no es "más capacidad", es volver a no tener tope. ⚠ SI SUBÍS ESTA PERILLA, SUBÍ TAMBIÉN el `max_parallel_requests` del deployment local en el catálogo del motor. Invariante: max_parallel_requests > BASA_ENGINE_MAX_CONCURRENCY × WEB_CONCURRENCY (hoy 20 > 8 × 2 = 16). Si se invierte, el primero en rechazar pasa a ser el motor —error opaco, sin cabecera `X-Basa-Rejected` y sin fila auditada— en vez del backend, y saturar deja de verse. Nada lo verifica en runtime: es tuya al girar el tope. |
| `BASA_ENGINE_QUEUE_TIMEOUT_SECONDS` | `5` | Cuánto espera su turno un pedido antes de que se lo rechace, en segundos — la perilla de la PACIENCIA. Rango válido: 0 < v <= 60 (un queue-timeout de 600 s es la cola infinita con otro nombre). El `Retry-After` del 503 se deriva de este valor, no es un 5 fijo. |
| `BASA_ENGINE_TIMEOUT_SECONDS` | `60` | Timeout de la llamada al motor desde el CHAT de la consola, en segundos. Rango válido: 0 < v <= 600. Es una UI con una persona esperando, por eso el default es corto; el perfil de producción lo sube a 150 para no cortar antes que el router del motor (120 s con modelos locales lentos), que sería abortar una respuesta buena y ya pagada. |
| `BASA_GW_BYOK_TIMEOUT_SECONDS` | `150` | Timeout TOTAL de una llamada BYOK no-streaming de /gw (herramientas de código), en segundos. Rango válido: 0 < v <= 600. Perilla PROPIA y no la del chat a propósito: una coding tool tolera —y necesita— generaciones largas. Regla al girarla: el que ESPERA tiene que aguantar más que el que TRABAJA (el router del motor espera 120 s). |
| `BASA_GW_BYOK_READ_TIMEOUT_SECONDS` | `150` | Timeout ENTRE CHUNKS del streaming BYOK de /gw, en segundos. Rango válido: 0 < v <= 600. El modelo local no manda pings mientras piensa: con un valor bajo la conexión se corta sola en mitad de una respuesta buena. Misma regla que el anterior. |
| `NLP_ANALYZER_URL` | `http://nlp-analyzer:3000` | Motor de detección NLP real (spec 016) — servicio interno, sin necesidad de key. Default correcto para docker compose (nombre de servicio); no tocar salvo despliegue custom. |
| `BASA_ENTITY_REGION` | `eu` | Set de patrones estructurados a usar (DNI/pasaporte/etc.) — "eu" por default (despliegue actual). Cambiar a "latam_ar" en despliegues de esa región. |
| `OPENAI_API_KEY` | *(secreto — generado por instalación)* | LLM API Keys (agregar las de los providers que uses; sin key real NO hay respuesta LLM - el sistema es fail-closed, no existe modo simulado) |
| `ANTHROPIC_API_KEY` | *(secreto — generado por instalación)* | — |
| `GEMINI_API_KEY` | — | — |
| `AZURE_OPENAI_API_KEY` | — | Azure OpenAI (el compose las mapea a AZURE_API_KEY/AZURE_API_BASE del motor) |
| `AZURE_OPENAI_ENDPOINT` | — | — |
| `AZURE_API_VERSION` | — | — |
