# Research: Sentinel Secure AI Gateway (by sentinel dev)

## 1. LiteLLM Engine Performance & Scalability

### Decision
Use the official LiteLLM Docker image (`ghcr.io/berriai/litellm:main-latest`) configured with a PostgreSQL database and Redis cache.

### Rationale
LiteLLM is built on top of FastAPI and Uvicorn, utilizing Python's `asyncio` for non-blocking I/O. It achieves high scalability through:
1. **Connection Pooling**: Native integration with SQLAlchemy and tortoise-orm, using connection pooling to PostgreSQL to handle high concurrent database writes for spend logging.
2. **Caching**: Integration with Redis for caching LLM responses and API keys, reducing database lookups and external API costs.
3. **Load Balancing**: Built-in routing that distributes requests across multiple API keys or model deployments based on cooldowns, latency, and TPM/RPM limits.
4. **Asynchronous Streaming**: Efficiently handles HTTP streaming (Server-Sent Events) with minimal memory overhead.

### Alternatives Considered
- **Custom Python Proxy**: Writing a custom proxy from scratch using FastAPI and `httpx`. Rejected because implementing streaming budget tracking, automatic retries, fallbacks, and load balancing is highly complex and would take months of development.

---

## 2. Microsoft Presidio Integration

### Decision
Deploy `mcr.microsoft.com/presidio-analyzer:latest` and `mcr.microsoft.com/presidio-anonymizer:latest` as independent Docker containers. Configure LiteLLM to call these services via the native `presidio-pii` guardrail.

### Rationale
- **Presidio Analyzer**: Uses spaCy models to detect PII/PHI entities (such as names, phone numbers, credit card numbers) in multiple languages (including English and Spanish).
- **Presidio Anonymizer**: Replaces detected entities with placeholders (e.g., `<PERSON>`).
- **LiteLLM Integration**: LiteLLM has a built-in pre-call hook that sends the prompt to the Presidio Analyzer, receives the entity list, calls the Anonymizer, and sends the masked text to the LLM. It also supports `output_parse_pii: true` to automatically restore the original values in the LLM response.

### Performance & Latency Optimization
To keep the overhead under 150ms:
1. **Local Network**: Keep Presidio and LiteLLM in the same Docker bridge network to minimize network round-trip time.
2. **Lightweight Models**: Use the default spaCy small model (`en_core_web_sm` / `es_core_news_sm`) for fast analysis. If higher accuracy is needed, we can scale to medium models later.

---

## 3. Custom UI & FastAPI Wrapper (White-Labeling)

### Decision
Build a custom **FastAPI** backend wrapper that acts as the administrative control plane, and a **Vite + React** frontend for the UI.

### Rationale
- **FastAPI Wrapper**: Instead of exposing the LiteLLM admin endpoints directly to the frontend, the FastAPI wrapper will expose clean, custom-branded endpoints. It will communicate with LiteLLM's database or management APIs to create keys, set budgets, and retrieve logs. It will also serve as the backend for the custom compliance templates and playground.
- **Vite + React**: Extremely fast build times, lightweight bundle, and excellent support for modern CSS animations (Framer Motion or CSS transitions) for the Playground layer animation.
- **White-Labeling**: By routing all frontend requests through the FastAPI wrapper, we ensure that the user never sees LiteLLM headers, URLs, or error messages. Any LiteLLM-specific errors will be caught by the wrapper and translated into custom "Sentinel Secure AI Gateway" errors.
