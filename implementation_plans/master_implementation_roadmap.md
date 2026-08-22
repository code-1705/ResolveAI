# Master Implementation Roadmap - Resolve.ai (Autonomous Collections Agent for Razorpay)

**Resolve.ai** is an production-grade, guardrail-constrained autonomous collections agent designed for Indian SMEs and freelancers using Razorpay. It bridges unstructured human negotiation over WhatsApp/Email with deterministic financial transactions via the Razorpay API, transforming overdue invoices into recovered Total Payment Volume (TPV).

---

## 12 Production-Grade Fintech Safeguards Integrated

### Submodule 1: Core Database, Models & Guardrail Engine
1. **Integer Paise Storage in DB**: Storing all monetary balances as integer paise (`amount_paise: int`) in SQLite/PostgreSQL to prevent binary floating-point drift.
2. **Finite State Machine (FSM) Lifecycle**: Enforcing strict, non-reversible invoice lifecycle transitions (`UNPAID -> NEGOTIATING -> PARTIALLY_PAID -> PAID`) with terminal state locking.
3. **Database Concurrency & WAL Mode**: SQLite configured with `PRAGMA journal_mode=WAL` and busy timeouts (or PostgreSQL) to prevent `database is locked` operational errors under concurrent chat + webhook loads.

### Submodule 2: Razorpay API Client & Webhook Engines
4. **Raw Byte Webhook HMAC Verification**: Verifying Razorpay HMAC-SHA256 signatures against `await request.body()` (raw bytes) before JSON parsing to preserve exact payload formatting.
5. **Payment Link Lifecycle & Supersonic Link Cancellation**: Storing `razorpay_payment_link_id` in a dedicated `PaymentLinkRecord` table, listening for `payment_link.paid`, and explicitly cancelling older superseded links via `POST /v1/payment_links/{id}/cancel` when new agreements are struck.
6. **Asynchronous Webhook Processing**: Validating HMAC immediately, dispatching ledger processing to FastAPI `BackgroundTasks`, and instantly returning `200 OK` (under 100ms) to eliminate Razorpay retry storms.

### Submodule 3: LLM Negotiation Agent & Session Manager
7. **Session Mutex Locking**: Per-session concurrency locks (`session_locks[session_id]`) to prevent double-texting race conditions from executing parallel LLM tool calls.
8. **Deterministic Safety Gateway (Untrusted LLM)**: Treating LLM outputs as strictly untrusted. `GuardrailEngine` acts as a hard gateway; if `validate_proposal()` fails, API execution is blocked regardless of LLM output or prompt injection attempts.
9. **Graceful Tool Exception Recovery**: Wrapping Razorpay API tool calls in try/except blocks, passing error diagnostics back to the LLM context for user-friendly retry messaging.

### Submodule 4: FastAPI Server Core & REST Endpoints
10. **Strict Explicit CORS Security**: Restricting origins explicitly to frontend dev servers (`http://localhost:5173`, `http://127.0.0.1:5173`) with `allow_credentials=True`.
11. **Non-Blocking Asynchronous I/O**: Using `httpx.AsyncClient` and async database drivers to prevent blocking the asyncio event loop.

### Submodule 5: Frontend Dashboard & WhatsApp Simulator UI
12. **Real-time Server-Sent Events (SSE)**: `GET /api/events` broadcasting instantaneous webhook reconciliation updates directly to the React dashboard without requiring manual page refreshes.

---

## Submodule Plan Index

1. 📄 [Submodule 1: Database, Models & Guardrail Engine](file:///c:/Users/Vansh/Desktop/TrustBridge/implementation_plans/plan_1_database_and_guardrails.md)
2. 📄 [Submodule 2: Razorpay API Client & Meta Webhook Engines](file:///c:/Users/Vansh/Desktop/TrustBridge/implementation_plans/plan_2_razorpay_and_webhooks.md)
3. 📄 [Submodule 3: Agentic LLM Negotiation Engine & Session Context](file:///c:/Users/Vansh/Desktop/TrustBridge/implementation_plans/plan_3_agent_and_session_manager.md)
4. 📄 [Submodule 4: FastAPI Server Core & REST Endpoints](file:///c:/Users/Vansh/Desktop/TrustBridge/implementation_plans/plan_4_fastapi_server.md)
5. 📄 [Submodule 5: Merchant Dashboard & WhatsApp Simulator UI](file:///c:/Users/Vansh/Desktop/TrustBridge/implementation_plans/plan_5_frontend_dashboard_and_simulator.md)
