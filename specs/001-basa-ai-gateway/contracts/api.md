# API Contracts: Basa Secure AI Gateway (by basa dev)

This document defines the REST API endpoints exposed by the FastAPI backend wrapper.

## 1. Authentication

All administrative endpoints require a JWT bearer token in the `Authorization` header:
`Authorization: Bearer <JWT_TOKEN>`

---

## 2. Administrative Endpoints

### User & Group Management

#### `GET /api/v1/users`
Retrieve a list of users.
* **Response (200 OK)**:
  ```json
  [
    {
      "id": "c3e8a71c-323b-419b-a010-85f8c85775f5",
      "username": "dr.gonzalez",
      "email": "gonzalez@basadev.com",
      "role": "clinician",
      "group_name": "Cardiology",
      "is_active": true
    }
  ]
  ```

#### `POST /api/v1/users`
Create a new user.
* **Request Body**:
  ```json
  {
    "username": "dr.gonzalez",
    "email": "gonzalez@basadev.com",
    "password": "securepassword123",
    "role": "clinician",
    "group_id": "8fb5fb08-331a-474b-88df-09b1a5afefec"
  }
  ```

---

### Budget Management

#### `GET /api/v1/budgets`
Retrieve all active budgets.
* **Response (200 OK)**:
  ```json
  [
    {
      "id": "d4a5b6c7-8d9e-0f1a-2b3c-4d5e6f7a8b9c",
      "user_id": "c3e8a71c-323b-419b-a010-85f8c85775f5",
      "max_spend_usd": 50.0000,
      "current_spend_usd": 12.4500,
      "max_tokens": 1000000,
      "current_tokens": 245000,
      "reset_period": "monthly",
      "last_reset_at": "2026-06-01T00:00:00Z"
    }
  ]
  ```

#### `PUT /api/v1/budgets/{id}`
Update an existing budget.
* **Request Body**:
  ```json
  {
    "max_spend_usd": 100.0000,
    "max_tokens": 2000000,
    "reset_period": "monthly"
  }
  ```

---

### Security & Compliance Settings

#### `GET /api/v1/security/policy`
Retrieve the active security policy.
* **Response (200 OK)**:
  ```json
  {
    "id": "e5f6a7b8-c9d0-e1f2-a3b4-c5d6e7f8a9b0",
    "name": "Default Healthcare Policy",
    "is_active": true,
    "entity_configs": {
      "PERSON": "MASK",
      "PHONE_NUMBER": "MASK",
      "EMAIL_ADDRESS": "MASK",
      "US_SSN": "BLOCK",
      "MEDICAL_LICENSE": "BLOCK"
    },
    "gdpr_mode": true,
    "ai_act_mode": true
  }
  ```

#### `PUT /api/v1/security/policy`
Update the active security policy.
* **Request Body**:
  ```json
  {
    "entity_configs": {
      "PERSON": "MASK",
      "PHONE_NUMBER": "MASK",
      "MEDICAL_LICENSE": "BLOCK"
    },
    "gdpr_mode": true,
    "ai_act_mode": false
  }
  ```

---

### Audit Logs

#### `GET /api/v1/audit-logs`
Retrieve audit logs with pagination and filters.
* **Query Parameters**:
  - `page` (default: 1)
  - `limit` (default: 50)
  - `user_id` (optional)
  - `model` (optional)
  - `pii_detected` (optional, boolean)
* **Response (200 OK)**:
  ```json
  {
    "total": 1420,
    "page": 1,
    "limit": 50,
    "logs": [
      {
        "id": "f7a8b9c0-d1e2-f3a4-b5c6-d7e8f9a0b1c2",
        "timestamp": "2026-06-29T10:15:30Z",
        "username": "dr.gonzalez",
        "model": "claude-3-5-sonnet",
        "tokens": 450,
        "cost_usd": 0.0067,
        "pii_detected": true,
        "masked_entities": [
          { "type": "PERSON", "count": 2 },
          { "type": "PHONE_NUMBER", "count": 1 }
        ],
        "compliance_status": "passed",
        "latency_ms": 125
      }
    ]
  }
  ```

---

## 3. Playground & Chat Endpoint

This endpoint is used by the custom UI Playground. It executes the entire gateway pipeline and returns both the chat completion and the step-by-step layer metadata.

#### `POST /api/v1/chat/completions`
* **Request Body**:
  ```json
  {
    "model": "claude-3-5-sonnet",
    "messages": [
      { "role": "user", "content": "El paciente Juan Pérez con teléfono 555-0199 tiene fiebre." }
    ],
    "stream": false
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "choices": [
      {
        "message": {
          "role": "assistant",
          "content": "Recomiendo monitorear la temperatura de Juan Pérez y administrar paracetamol si supera los 38°C."
        }
      }
    ],
    "pipeline_metadata": {
      "original_prompt": "El paciente Juan Pérez con teléfono 555-0199 tiene fiebre.",
      "layers": {
        "security_masking": {
          "status": "success",
          "masked_prompt": "El paciente <PERSON> con teléfono <PHONE_NUMBER> tiene fiebre.",
          "detected_entities": [
            { "entity": "Juan Pérez", "type": "PERSON", "score": 0.98 },
            { "entity": "555-0199", "type": "PHONE_NUMBER", "score": 0.95 }
          ]
        },
        "compliance_check": {
          "status": "success",
          "gdpr_rule": "Enrouted to EU-West-1 endpoint",
          "ai_act_risk": "Low Risk"
        },
        "budget_check": {
          "status": "success",
          "user_remaining_budget_usd": 37.55
        },
        "llm_execution": {
          "status": "success",
          "provider": "Anthropic (via Basa AI Router)",
          "latency_ms": 750,
          "tokens_used": 54
        },
        "security_unmasking": {
          "status": "success",
          "raw_response": "Recomiendo monitorear la temperatura de <PERSON> y administrar paracetamol si supera los 38°C."
        }
      }
    }
  }
  ```
