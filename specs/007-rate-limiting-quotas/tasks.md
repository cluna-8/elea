# Tasks — 007 Rate Limiting & Quotas

## Phase 1 — Backend
- [x] T-001: Add `redis` to backend/requirements.txt
- [x] T-002: Create `backend/src/services/redis_client.py` — singleton Redis connection
- [x] T-003: Create `backend/src/services/rate_limiter.py` — check_rate_limit(key_id, rpm_limit, tpm_limit, tokens_used)
- [x] T-004: Wire rate limit check into `chat.py` before forwarding to engine
- [x] T-005: Return X-RateLimit-Remaining-* headers in chat response

## Phase 2 — Frontend
- [ ] T-006: Show rpm_limit / tpm_limit columns in keys table
- [ ] T-007: Add rpm/tpm inputs to key creation modal
