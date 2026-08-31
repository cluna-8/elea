# Quickstart & Validation Guide: Sentinel Secure AI Gateway (by sentinel dev)

This document provides step-by-step instructions to launch the Sentinel Secure AI Gateway in a local development environment and validate its core functionalities.

## 1. Prerequisites

- **Docker** and **Docker Compose** installed on the host system.
- An **OpenAI API Key** or **Anthropic API Key** (configured in the `.env` file).

---

## 2. Environment Setup

Create a `.env` file in the root directory of the project:

```env
# Database Configuration
POSTGRES_DB=sentinel_gateway
POSTGRES_USER=sentinel_admin
POSTGRES_PASSWORD=sentinelsecurepass123
POSTGRES_HOST=db
POSTGRES_PORT=5432

# LiteLLM Configuration
LITELLM_MASTER_KEY=sentinel_master_key_9999
DATABASE_URL=postgresql://sentinel_admin:sentinelsecurepass123@db:5432/sentinel_gateway

# Presidio Configuration
PRESIDIO_ANALYZER_API_BASE=http://presidio-analyzer:5002
PRESIDIO_ANONYMIZER_API_BASE=http://presidio-anonymizer:5001

# LLM Provider Keys (at least one is required)
OPENAI_API_KEY=your_openai_api_key_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

---

## 3. Launching the Services

Run the following command in the root directory to build and start all 6 containers:

```bash
docker compose up --build -d
```

Verify that all containers are running successfully:

```bash
docker compose ps
```

You should see:
- `sentinel-frontend` (running on port `80` or `3000`)
- `sentinel-backend` (running on port `8000`)
- `sentinel-litellm` (running on port `4000`, internal only)
- `sentinel-db` (running on port `5432`)
- `presidio-analyzer` (running on port `5002`)
- `presidio-anonymizer` (running on port `5001`)

---

## 4. End-to-End Validation Scenarios

### Scenario 1: PII Masking and Unmasking (Playground Simulation)

We will simulate a request from a doctor containing patient information and verify that the gateway masks the data before sending it to the LLM, but returns the unmasked response.

Send a request to the custom chat endpoint:

```bash
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer test_admin_token" \
  -d '{
    "model": "claude-3-5-sonnet",
    "messages": [
      { "role": "user", "content": "El paciente Juan Pérez, DNI 12345678X, tiene síntomas de neumonía." }
    ]
  }'
```

#### Expected Outcome:
1. **Response Text**: The message returned in `choices[0].message.content` should contain "Juan Pérez" (properly unmasked).
2. **Pipeline Metadata**: The `pipeline_metadata.layers.security_masking` object in the JSON response should show:
   - `masked_prompt`: `"El paciente <PERSON>, DNI <IDENTIFIER>, tiene síntomas de neumonía."`
   - `detected_entities`: A list identifying `"Juan Pérez"` as `PERSON` and `"12345678X"` as `IDENTIFIER`.
3. **Audit Log Verification**: The raw prompt in the database logs must be masked or omitted, and only the metadata (entity types) recorded.

---

### Scenario 2: Budget Enforcement

To verify budget enforcement, we will assign a user a budget of $0.05 and make multiple requests until they are blocked.

1. **Verify budget status**:
   ```bash
   curl -X GET http://localhost:8000/api/v1/budgets \
     -H "Authorization: Bearer test_admin_token"
   ```
2. **Make a request exceeding the budget**:
   If the user makes a request that costs more than the remaining budget, the gateway should return a `402 Payment Required` or `400 Bad Request` with the message:
   `"Budget exceeded. Request blocked."`
