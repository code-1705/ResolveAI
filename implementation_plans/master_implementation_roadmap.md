# Master Implementation Roadmap - Resolve.ai (Autonomous Collections Agent for Razorpay)

**Resolve.ai** is an intelligent, guardrail-constrained autonomous collections agent designed for Indian SMEs and freelancers using Razorpay. It bridges unstructured human negotiation over WhatsApp/Email with deterministic financial transactions via the Razorpay API, transforming overdue invoices into recovered Total Payment Volume (TPV).

---

## 3 Critical Fintech Principles Built In

1. **The "Paise" Currency Math Rule**:
   - Razorpay APIs require amounts in integer paise (₹1 = 100 paise).
   - LLM tool schema receives Rupee amounts (`amount_in_inr`). The Python backend deterministically executes `int(round(amount_in_inr * 100))` to prevent hallucinated pricing errors (e.g., creating ₹200 links for ₹20,000 requests).

2. **Idempotent Webhook Engine**:
   - Payment webhooks guarantee at-least-once delivery.
   - `TransactionLedger` table enforces `UNIQUE(razorpay_payment_id)`. Duplicate webhook deliveries return `200 OK` instantly without double-counting TPV.

3. **Session Context & Dual Entry Points**:
   - `ChatSessions` maintains a rolling 5-turn context per WhatsApp sender ID mapped to the active `invoice_id`.
   - Supports both the interactive **WhatsApp Simulator UI** and a production **Meta WhatsApp Cloud API Webhook** (`GET` verification handshake & `POST` message ingestion).

---

## Submodule Plan Index

1. 📄 [Submodule 1: Database, Models & Guardrail Engine](file:///c:/Users/Vansh/Desktop/TrustBridge/implementation_plans/plan_1_database_and_guardrails.md)
2. 📄 [Submodule 2: Razorpay API Client & Meta Webhook Engines](file:///c:/Users/Vansh/Desktop/TrustBridge/implementation_plans/plan_2_razorpay_and_webhooks.md)
3. 📄 [Submodule 3: Agentic LLM Negotiation Engine & Session Context](file:///c:/Users/Vansh/Desktop/TrustBridge/implementation_plans/plan_3_agent_and_session_manager.md)
4. 📄 [Submodule 4: FastAPI Server Core & REST Endpoints](file:///c:/Users/Vansh/Desktop/TrustBridge/implementation_plans/plan_4_fastapi_server.md)
5. 📄 [Submodule 5: Merchant Dashboard & WhatsApp Simulator UI](file:///c:/Users/Vansh/Desktop/TrustBridge/implementation_plans/plan_5_frontend_dashboard_and_simulator.md)
