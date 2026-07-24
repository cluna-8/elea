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
| `NLP_ANALYZER_URL` | `http://nlp-analyzer:3000` | Motor de detección NLP real (spec 016) — servicio interno, sin necesidad de key. Default correcto para docker compose (nombre de servicio); no tocar salvo despliegue custom. |
| `BASA_ENTITY_REGION` | `eu` | Set de patrones estructurados a usar (DNI/pasaporte/etc.) — "eu" por default (despliegue actual). Cambiar a "latam_ar" en despliegues de esa región. |
| `OPENAI_API_KEY` | *(secreto — generado por instalación)* | LLM API Keys (agregar las de los providers que uses; sin key real NO hay respuesta LLM - el sistema es fail-closed, no existe modo simulado) |
| `ANTHROPIC_API_KEY` | *(secreto — generado por instalación)* | — |
| `GEMINI_API_KEY` | — | — |
| `AZURE_OPENAI_API_KEY` | — | Azure OpenAI (el compose las mapea a AZURE_API_KEY/AZURE_API_BASE del motor) |
| `AZURE_OPENAI_ENDPOINT` | — | — |
| `AZURE_API_VERSION` | — | — |
