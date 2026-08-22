# Resolve.ai - Autonomous Collections Agent for Razorpay

**Resolve.ai** is a production-grade, guardrail-constrained autonomous collections agent designed for Indian SMEs and freelancers using Razorpay. It bridges unstructured human negotiation over WhatsApp/Email with deterministic financial transactions via the Razorpay API, transforming overdue invoices into recovered Total Payment Volume (TPV).

---

## 🏆 Completed 5-Submodule End-to-End Implementation

### Submodule 1: Core Database, Models & Guardrail Engine (`backend/`)
1. **Configuration & Secrets (`backend/config.py`)**: Centralized Pydantic settings loading environment variables, merchant defaults, and DB paths.
2. **Data Schemas & Models (`backend/models.py`)**:
   - Integer paise currency storage (`original_amount_paise`, `paid_amount_paise`, `remaining_amount_paise`).
   - `MerchantGuardrails`, `MasterInvoice`, `TransactionLedger` (`UNIQUE(razorpay_payment_id)`), `PaymentLinkRecord`, `ChatSession` (`f"{phone}_{invoice_id}"`), `ChatMessage`.
3. **Database Engine & FSM Validation (`backend/database.py`)**:
   - SQLite WAL mode (`PRAGMA journal_mode=WAL;`) with 5000ms busy timeout.
   - Non-reversible FSM state machine ($\text{UNPAID} \rightarrow \text{NEGOTIATING} \rightarrow \text{PARTIALLY\_PAID} \rightarrow \text{PAID}$).
4. **Deterministic Guardrail Engine (`backend/guardrails.py`)**:
   - Floor check (`proposed >= min_required`), Ceiling check (`proposed <= remaining`), and Razorpay 180-day cap check.

### Submodule 2: Razorpay API Client & Meta Webhook Engines (`backend/`)
1. **Razorpay Client & Payload Idempotency (`backend/razorpay_client.py`)**:
   - `create_payment_link()` with `"reference_id": f"ref_{session_id[:20]}_t{turn}"` (max 40 chars) payload idempotency & `"notes": {"invoice_id": invoice_id}`.
   - `cancel_payment_link()` deactivating superseded active links.
   - `verify_webhook_signature()` validating HMAC-SHA256 directly over raw request bytes.
2. **Meta WhatsApp Cloud API Client (`backend/whatsapp_client.py`)**:
   - `send_text_message()` and `send_interactive_buttons()` (multi-invoice button prompt).
3. **Meta & Razorpay Webhook Engine (`backend/webhooks.py`)**:
   - `verify_meta_webhook()` GET challenge handshake (`hub.challenge`).
   - `process_whatsapp_webhook()` parsing both `type == "text"` and `type == "interactive"` button replies for composite session key binding (`f"{customer_phone}_{invoice_id}"`).
   - `reconcile_payment_event()` async reconciler executing integer paise math, FSM updates, and link deactivation strictly inside invoice row locks (`async with invoice_locks[invoice_id]:`).

### Submodule 3: LLM Negotiation Agent & Session Manager (`backend/`)
1. **Session Context Manager (`backend/session_manager.py`)**:
   - `SessionManager`: Manages multi-turn conversation state mapped to composite session keys `f"{customer_phone}_{invoice_id}"`.
   - `get_session_lock()`: Multi-loop thread-safe per-session async locks preventing double-texting race conditions.
2. **Agentic Negotiation Engine (`backend/agent.py`)**:
   - **Anti-Hallucination Directives**: Forbids confirming receipt of funds based on customer text claims alone without verified DB status (`PARTIALLY_PAID` or `PAID`).
   - **Untrusted LLM Safety Gateway**: Filters tool proposals through `GuardrailEngine`. If `PASS`, converts INR to integer paise, calculates 180-day capped UTC expiry timestamp, generates `reference_id`, and executes Razorpay API call. If `REJECT`, hard blocks API call and issues polite counter-offer.
   - **Inspectable Agent Trace**: Constructs visual audit payload (`thought`, `guardrail_check`, `currency_conversion`, `tool_executed`, `payment_link_url`).

### Submodule 4: FastAPI Server Core & REST Endpoints (`backend/`)
1. **Demo Seed Data (`backend/seed_data.py`)**:
   - Seeds realistic Indian SME overdue invoices: Apex Logistics (₹50,000), Vanguard Web Studios (₹1,20,000), GreenLeaf Organics (₹35,000).
2. **FastAPI Application Server (`backend/main.py`)**:
   - **Explicit CORS Security**: `allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"]`.
   - **Real-Time Server-Sent Events (SSE)** (`GET /api/events`): Broadcasts live updates (`payment_reconciled`, `guardrails_updated`, `chat_message_processed`) with non-blocking timeout polling.
   - **REST & Webhook Endpoints**:
     - `GET /api/invoices`, `GET /api/invoices/{id}`
     - `GET /api/guardrails`, `POST /api/guardrails`
     - `POST /api/chat/message`, `POST /api/chat/reset`
     - `POST /api/webhooks/razorpay` (HMAC verified, enqueued as `BackgroundTasks`)
     - `GET /api/webhooks/whatsapp`, `POST /api/webhooks/whatsapp` (enqueued as `BackgroundTasks`)
     - `GET /api/analytics` (Total Overdue TPV, Recovered TPV, Recovery Rate %)

### Submodule 5: Frontend Dashboard & WhatsApp Simulator (`frontend/`)
1. **Glassmorphism Dark-Mode Web Application (`frontend/src/`)**:
   - **Real-Time SSE Syncing (`EventSource`)**: Live updates without page refreshes.
   - **📊 Invoices & Analytics Dashboard**: TPV metric cards, recovery progress bar, master invoice table with status badges (`UNPAID`, `NEGOTIATING`, `PARTIALLY_PAID`, `PAID`).
   - **🛡️ Merchant Guardrails Control**: Interactive policy sliders for minimum partial payment % (10-100%), maximum extension days (1-180), and negotiation persona/tone.
   - **💬 WhatsApp Customer Simulator**: Dual-pane layout featuring WhatsApp chat bubbles with proposal presets (*Propose 40% Today*, *14-Day Extension*, *Lowball 10%*, *Claim Paid via UPI*).
   - **🔍 Inspectable Real-Time Agent Trace Panel**: Step-by-step audit visualization showing strategy reasoning, guardrail pass/reject status, zero-float-drift integer paise conversion, payload idempotency keys, and generated Razorpay payment link URLs.

---

## 🧪 Verification Results

### 1. Complete Backend Unit Test Suite (`backend/test_submodule*.py`)
```bash
python -m unittest backend/test_submodule1.py backend/test_submodule2.py backend/test_submodule3.py backend/test_submodule4.py
```
Output:
```text
...................
----------------------------------------------------------------------
Ran 19 tests in 2.050s

OK
```

### 2. Frontend Production Bundle Build (`frontend/`)
```bash
cd frontend
npm run build
```
Output:
```text
vite v8.2.2 building client environment for production...
✓ 16 modules transformed.
dist/index.html                   0.45 kB │ gzip:  0.29 kB
dist/assets/index-4Ppi2ilN.css    1.67 kB │ gzip:  0.84 kB
dist/assets/index-DpfKmeO8.js   213.65 kB │ gzip: 65.43 kB

✓ built in 2.80s
```

---

## 🚀 Running the Project Locally

### 1. Start the FastAPI Backend Server
```bash
python -m uvicorn backend.main:app --reload --port 8000
```

### 2. Start the React Frontend UI
```bash
cd frontend
npm run dev
```

Open `http://localhost:5173` in your browser to interact with the Resolve.ai Merchant Dashboard and WhatsApp Simulator!

---

## 📁 Complete Project Architecture

```
c:\Users\Vansh\Desktop\TrustBridge\
├── backend/
│   ├── config.py           # Application settings & secrets
│   ├── models.py           # Dataclass & Pydantic schemas
│   ├── database.py         # SQLite WAL connection & FSM validator
│   ├── guardrails.py       # Deterministic rule engine & currency math
│   ├── razorpay_client.py  # Razorpay SDK client & reference_id idempotency
│   ├── whatsapp_client.py  # Meta Graph API WhatsApp client
│   ├── webhooks.py         # Meta & Razorpay webhook engine + row locking
│   ├── session_manager.py  # Composite session manager & per-session locks
│   ├── agent.py            # Agentic negotiator, Guardrail gateway & trace log
│   ├── seed_data.py        # Demo invoice seeding script
│   ├── main.py             # FastAPI server, SSE stream & REST endpoints
│   ├── test_submodule1.py  # Submodule 1 unit test suite
│   ├── test_submodule2.py  # Submodule 2 unit test suite
│   ├── test_submodule3.py  # Submodule 3 unit test suite
│   └── test_submodule4.py  # Submodule 4 unit test suite
├── frontend/
│   ├── src/
│   │   ├── App.jsx         # Dashboard, Guardrails & WhatsApp Simulator UI
│   │   ├── index.css       # Glassmorphism dark-mode styling
│   │   └── main.jsx        # React entrypoint
│   ├── package.json        # Frontend dependencies
│   └── vite.config.js      # Vite build configuration
├── implementation_plans/   # Master roadmap & 5 submodule plans
└── README.md               # End-to-end documentation & verification results
```
