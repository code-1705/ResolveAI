# Master Implementation Roadmap - Resolve.ai (Autonomous Collections Agent for Razorpay)

**Resolve.ai** is a production-grade, guardrail-constrained autonomous collections agent designed for Indian SMEs and freelancers using Razorpay. It bridges unstructured human negotiation over WhatsApp/Email with deterministic financial transactions via the Razorpay API, transforming overdue invoices into recovered Total Payment Volume (TPV).

---

## 25 Production-Grade Fintech Safeguards Integrated

### Submodule 1: Core Database, Models & Guardrail Engine
1. **Integer Paise Storage in DB**: Storing all monetary balances as integer paise (`amount_paise: int`) in SQLite/PostgreSQL to prevent binary floating-point drift.
2. **Finite State Machine (FSM) Lifecycle**: Enforcing strict, non-reversible invoice lifecycle transitions ($\text{UNPAID} \rightarrow \text{NEGOTIATING} \rightarrow \text{PARTIALLY\_PAID} \rightarrow \text{PAID}$) with terminal state locking.
3. **Database Concurrency & WAL Mode**: SQLite configured with `PRAGMA journal_mode=WAL;` and busy timeouts to prevent database locking errors.
4. **Upper & Lower Bound Guardrail Engine**: Enforces $\text{min\_required\_paise} \le \text{proposed\_amount\_paise} \le \text{remaining\_amount\_paise}$ to prevent over-billing or hallucinated inflated payment link amounts.
5. **Razorpay 180-Day Platform Expiry Cap**: Enforces `effective_max_extension = min(max_extension_days, 180)` to prevent `400 Bad Request` API errors.
6. **Composite Session Key Isolation**: `session_id = f"{customer_phone}_{invoice_id}"` ensuring distinct invoice context isolation for SME customers with multiple active debts.

### Submodule 2: Razorpay API Client & Webhook Engines
7. **Raw Byte Webhook HMAC Verification**: Verifying Razorpay HMAC-SHA256 signatures against `await request.body()` (raw bytes) before JSON parsing to preserve exact payload formatting.
8. **Razorpay `reference_id` Payload Idempotency**: Passing deterministic `reference_id` fields (`ref_{session_id[:20]}_t{turn}`) strictly $\le 40$ chars in `POST /v1/payment_links` JSON body to prevent duplicate link creation during retries (Razorpay Payment Links API enforces account-level uniqueness on `reference_id`, not HTTP headers).
9. **Payment Link Lifecycle & Link Deactivation**: Storing `razorpay_payment_link_id` in `PaymentLinkRecord`, listening for `payment_link.paid`, and explicitly cancelling superseded links via `POST /v1/payment_links/{id}/cancel`.
10. **Asynchronous Non-Blocking Webhook Processing**: Validating HMAC immediately, dispatching ledger processing to FastAPI `BackgroundTasks`, and instantly returning `200 OK` (<100ms) to eliminate Razorpay retry storms.
11. **Strict Balance Math Execution Inside Row Lock**: Executing `MasterInvoice` balance deductions, FSM state determination, and DB commits strictly inside an acquired row lock (`invoice_locks[invoice_id]`).
12. **Meta WhatsApp Cloud API & Interactive Payload Receiver**: `GET` verification handshake (`hub.challenge`) & `POST` message receiver with text/interactive button payload parsing (`button_reply.id` / `list_reply.id`) for phone-to-invoice routing.

### Submodule 3: LLM Negotiation Agent & Session Manager
13. **Session Mutex Locking**: Per-session concurrency locks (`session_locks[session_id]`) to prevent double-texting race conditions from executing parallel LLM tool calls.
14. **Deterministic Safety Gateway (Untrusted LLM)**: Treating LLM outputs as strictly untrusted. `GuardrailEngine` acts as a hard gateway; if validation fails, API execution is blocked.
15. **Anti-Hallucination Fund Receipt Directives**: System prompt forbids acknowledging settled funds based on user text claims alone; receipt confirmation requires `PARTIALLY_PAID` or `PAID` invoice status in injected system context.
16. **Unix Timestamp Expiration Calculation**: Explicit UTC epoch timestamp calculation (`int((datetime.now() + timedelta(days)).timestamp())`) for payment links, capped at 180 days.
17. **Graceful Tool Exception Recovery**: Wrapping Razorpay API tool calls in try/except blocks, passing error diagnostics back to the LLM context for user-friendly retry messaging.

### Submodule 4: FastAPI Server Core & REST Endpoints
18. **Strict Explicit CORS Security**: Restricting origins explicitly to frontend dev servers (`http://localhost:5173`, `http://127.0.0.1:5173`) with `allow_credentials=True` and clean syntax.
19. **Non-Blocking Asynchronous I/O**: Using `httpx.AsyncClient` and async database drivers to prevent blocking the asyncio event loop.

### Submodule 5: Frontend Dashboard & WhatsApp Simulator UI
20. **Real-time Server-Sent Events (SSE)**: `GET /api/events` broadcasting instantaneous webhook reconciliation updates directly to the React dashboard without requiring manual page refreshes.
21. **WhatsApp Simulator Typing Polish**: Animated three-dot *"Resolve.ai is typing..."* bubble rendered during backend processing.
22. **Agent Trace & Authentic Razorpay Modal**: Real-time AI thought inspection drawer & clickable Razorpay Checkout Modal triggering live webhooks.

---

## Submodule Plan Index

1. 📄 [Submodule 1: Database, Models & Guardrail Engine](file:///c:/Users/Vansh/Desktop/TrustBridge/implementation_plans/plan_1_database_and_guardrails.md)
2. 📄 [Submodule 2: Razorpay API Client & Meta Webhook Engines](file:///c:/Users/Vansh/Desktop/TrustBridge/implementation_plans/plan_2_razorpay_and_webhooks.md)
3. 📄 [Submodule 3: Agentic LLM Negotiation Engine & Session Context](file:///c:/Users/Vansh/Desktop/TrustBridge/implementation_plans/plan_3_agent_and_session_manager.md)
4. 📄 [Submodule 4: FastAPI Server Core & REST Endpoints](file:///c:/Users/Vansh/Desktop/TrustBridge/implementation_plans/plan_4_fastapi_server.md)
5. 📄 [Submodule 5: Merchant Dashboard & WhatsApp Simulator UI](file:///c:/Users/Vansh/Desktop/TrustBridge/implementation_plans/plan_5_frontend_dashboard_and_simulator.md)
