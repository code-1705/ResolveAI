# Implementation Plan - Submodule 4: FastAPI Server Core & REST Endpoints

## Overview
Submodule 4 constructs the HTTP server layer using Python FastAPI. It wires up database models, guardrail validation, agent negotiation, Razorpay API interactions, Meta WhatsApp webhooks, Server-Sent Events (SSE), and explicit CORS security.

---

## Technical Specifications & Architecture

### 1. Explicit CORS Security Configuration (`backend/main.py`)
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

### 2. Async Non-Blocking Architecture
- External HTTP requests use `httpx.AsyncClient` instead of synchronous `requests`.
- Database sessions use async SQLAlchemy drivers (`asyncpg` / `aiosqlite`) to avoid blocking the Python asyncio event loop.

---

### 3. Server-Sent Events (SSE) Real-Time Stream (`backend/main.py`)
- **`GET /api/events`**:
  - SSE EventSource stream emitting real-time events (`payment_captured`, `invoice_updated`, `guardrail_changed`) to connected React dashboard clients whenever webhooks or chat actions update balances.

---

### 4. REST Route Definitions (`backend/main.py`)
- `GET /api/invoices`: List all master invoices with balance progress.
- `GET /api/guardrails` / `POST /api/guardrails`: Fetch & update merchant negotiation rules.
- `POST /api/chat/message`: Process simulator chat messages.
- `POST /api/chat/reset`: Reset session history.
- `POST /api/webhooks/razorpay`: Raw-byte HMAC verified asynchronous Razorpay payment webhook.
- `GET /api/webhooks/whatsapp` & `POST /api/webhooks/whatsapp`: Meta Cloud API verification & message receiver with text/interactive button payload parsing.
- `GET /api/events`: Real-time SSE event stream.
- `GET /api/analytics`: Overview metrics.

---

## Verification Plan

### Automated Verification
- Run `python backend/test_submodule4.py`:
  1. Test CORS preflight options headers with explicit origins.
  2. Test SSE endpoint `GET /api/events` connecting and receiving broadcast payloads upon invoice updates.
