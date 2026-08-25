# ⚡ Resolve.ai — Autonomous AI Accounts Receivable & Collections Platform for Razorpay

<p align="center">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB" alt="React" />
  <img src="https://img.shields.io/badge/Vite-646CFF?style=for-the-badge&logo=vite&logoColor=white" alt="Vite" />
  <img src="https://img.shields.io/badge/Razorpay-02042B?style=for-the-badge&logo=razorpay&logoColor=3395FF" alt="Razorpay" />
  <img src="https://img.shields.io/badge/Google_Gemini-4285F4?style=for-the-badge&logo=google&logoColor=white" alt="Google Gemini" />
  <img src="https://img.shields.io/badge/PostgreSQL-316192?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Supabase-3ECF8E?style=for-the-badge&logo=supabase&logoColor=white" alt="Supabase" />
  <img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="License" />
</p>

---

## 📌 Executive Summary

**Resolve.ai** is an enterprise-grade, guardrail-constrained autonomous accounts receivable (AR) and debt collection engine built for Indian SMEs, enterprises, and freelancers using **Razorpay**. 

Resolve.ai bridges unstructured, human negotiation over **WhatsApp Cloud API / Email** with deterministic, verifiable financial transactions via the **Razorpay API**. It transforms delinquent accounts into recovered **Total Payment Volume (TPV)** without alienating clients or risking financial hallucination.

```
                  ┌────────────────────────────────────────────────────────┐
                  │                 RESOLVE.AI ECOSYSTEM                   │
                  └──────────────────────────┬─────────────────────────────┘
                                             │
      ┌──────────────────────────────────────┼──────────────────────────────────────┐
      ▼                                      ▼                                      ▼
💬 WhatsApp / Meta API             🧠 Agent & Guardrails Engine             💳 Razorpay API & Webhooks
• Unified phone-centric threads    • Google Gemini AI Negotiation          • Dynamic payment link generation
• Native PDF invoice delivery      • Integer paise math (zero float)       • HMAC-SHA256 signature verification
• Interactive payment buttons      • Multi-Bill FIFO auto-distribution     • Automated stale link invalidation
```

---

## 📑 Table of Contents

- [Key Value Propositions](#-key-value-propositions)
- [System Architecture](#-system-architecture)
- [Core Engineering Pillars](#-core-engineering-pillars)
  - [1. Deterministic Guardrail Firewall](#1-deterministic-guardrail-firewall)
  - [2. Multi-Bill FIFO Settlement Engine](#2-multi-bill-fifo-settlement-engine)
  - [3. Non-Reversible Financial FSM & Mutex Locking](#3-non-reversible-financial-fsm--mutex-locking)
  - [4. Anti-Hallucination Claim Verification](#4-anti-hallucination-claim-verification)
  - [5. Invoice Document CDN & PDF Generation](#5-invoice-document-cdn--pdf-generation)
- [Tech Stack](#-tech-stack)
- [Directory Structure](#-directory-structure)
- [Getting Started](#-getting-started)
  - [Prerequisites](#prerequisites)
  - [Environment Configuration](#environment-configuration)
  - [Backend Setup](#backend-setup)
  - [Frontend Setup](#frontend-setup)
- [API Reference](#-api-reference)
- [Verification & Automated Test Suite](#-verification--automated-test-suite)
- [Multi-Tenant SaaS Architecture](#-multi-tenant-saas-architecture)
- [License](#-license)

---

## 🌟 Key Value Propositions

| Feature | Problem It Solves | Resolve.ai Solution |
| :--- | :--- | :--- |
| **Autonomous Negotiation** | Manual AR follow-ups are labor-intensive, uncomfortable, and slow. | Empathetic AI acting as the merchant's Finance Relationship Team negotiates custom settlements 24/7. |
| **Strict Guardrail Firewall** | LLMs hallucinate unauthorized discounts, invalid due dates, or floating-point errors. | 100% deterministic Python rule gateway enforcing policy floors, ceilings, and 180-day caps before API execution. |
| **Multi-Bill FIFO Allocation** | Customers with multiple invoices get confused or make lump-sum payments that break single-invoice tracking. | Account-level ledger with automatic FIFO (First-In, First-Out) balance distribution across all outstanding bills. |
| **Cryptographic Webhooks** | Duplicate webhook processing leads to double-crediting or ledger corruption. | Timing-safe HMAC-SHA256 verification, `UNIQUE(razorpay_payment_id)` ledger idempotency, and row mutex locks. |
| **Live Multi-Tenant SaaS** | Single-tenant systems cannot isolate merchant data or handle organizational scaling. | Supabase Auth with JWT gatekeeper, tenant-isolated tables (`merchant_id`), and live Server-Sent Events (SSE). |

---

## 🏗️ System Architecture

```mermaid
flowchart TB
    subgraph Customer["Customer Channels"]
        WA["WhatsApp Cloud API"]
        SIM["Merchant WhatsApp Simulator (UI)"]
    end

    subgraph Gateway["FastAPI Server & Security Layer"]
        AUTH["Supabase JWT Auth Gatekeeper"]
        WH_ROUTER["Webhook Router\n(HMAC-SHA256 Verified)"]
        SSE["Server-Sent Events (SSE) Stream\n(/api/events)"]
        DOC_PROXY["Invoice PDF Streaming Proxy\n(/api/invoices/{id}/document)"]
    end

    subgraph AgenticCore["Agentic Reasoning & Guardrails"]
        SM["Session Context Manager\n(Phone-Centric Locks)"]
        GEMINI["Google Gemini AI\n(Negotiation Strategy)"]
        GUARD["Deterministic Guardrail Firewall\n(Paise Math, Bounds, Expiry)"]
    end

    subgraph FinancialCore["Financial Transaction Ledger"]
        FIFO["Multi-Bill FIFO Allocation Engine"]
        FSM["Invoice State Machine\n(UNPAID ➔ NEGOTIATING ➔ PARTIALLY_PAID ➔ PAID)"]
        RZP_CLIENT["Razorpay API Client\n(Idempotent Links & Link Cancellation)"]
    end

    subgraph Storage["Data & Storage Infrastructure"]
        PG[("PostgreSQL Database\n(Merchants, Invoices, Ledger)")]
        SUPA_STORAGE[("Supabase Storage CDN\n(Private Invoice PDF Buckets)")]
        SCHEDULER["APScheduler Cron\n(Missed Webhook & Link Expiry Reconciliation)"]
    end

    WA -->|Inbound Message| WH_ROUTER
    SIM -->|Simulated Chat| SM
    WH_ROUTER -->|Async Task| SM
    SM --> GEMINI
    GEMINI -->|Proposed Action| GUARD
    GUARD -->|Pass / Tool Execution| RZP_CLIENT
    RZP_CLIENT -->|Generated Payment Link| WA
    RZP_CLIENT -->|Generated Payment Link| SIM

    RZP_CLIENT -.->|Customer Pays| WH_ROUTER
    WH_ROUTER -->|payment.captured| FIFO
    FIFO --> FSM
    FSM --> PG
    FSM --> SSE
    SSE --> SIM

    DOC_PROXY --> SUPA_STORAGE
    SCHEDULER -->|Poll Active Links| RZP_CLIENT
    AUTH --> PG
```

---

## 🛡️ Core Engineering Pillars

### 1. Deterministic Guardrail Firewall
AI agents should **never** have direct, uncontrolled access to banking or payment APIs. In Resolve.ai:
- **Zero-Float Integer Paise Standard**: All monetary values are strictly converted to and computed as integer paise (`₹1 = 100 paise`), eliminating IEEE 754 floating-point drift.
- **Merchant Bounds Enforcement**: Every AI tool call is intercepted by `backend/guardrails.py`. Proposals are validated against merchant-configured policies:
  - Minimum down payment floor (`min_partial_payment_pct`).
  - Maximum due date extension (`max_extension_days`).
  - Maximum installment count (`max_split_installments`).
  - Maximum allowable waiver/discount (`max_discount_pct`).
- **Platform Cap Enforcement**: Payment link validity timestamps are strictly clamped to Razorpay's 180-day maximum limit.

### 2. Multi-Bill FIFO Settlement Engine
When an account has multiple overdue invoices (e.g., Bill A for ₹8,000 and Bill B for ₹9,000):
- If the customer offers a lump-sum payment (e.g., ₹12,000 towards their balance), the agent identifies an `account_settlement` scope.
- Upon payment capture, the **FIFO Webhook Reconciler** acquires an account-level mutex lock, queries all unpaid invoices ordered by `due_date ASC`, and cascades the payment:
  1. Fully satisfies Bill A (₹8,000) $\rightarrow$ Marks as `PAID`.
  2. Applies the remaining ₹4,000 to Bill B $\rightarrow$ Marks as `PARTIALLY_PAID`.
  3. Writes separate immutable audit records into `transaction_ledger`.

### 3. Non-Reversible Financial FSM & Mutex Locking
Invoices follow a strictly non-reversible Finite State Machine:

$$\text{UNPAID} \longrightarrow \text{NEGOTIATING} \longrightarrow \text{PARTIALLY\_PAID} \longrightarrow \text{PAID}$$

- **Row-Level Mutex Locks**: High-frequency webhooks or concurrent user double-clicks are queued via `asyncio.Lock` per invoice/account.
- **Idempotency Guarantee**: Every processed transaction is keyed with `UNIQUE(razorpay_payment_id)`. Duplicate webhook triggers are caught gracefully without double-crediting.
- **Link Invalidation**: When a partial or full payment is verified, any older, active Razorpay links are automatically cancelled via API to prevent duplicate charges.

### 4. Anti-Hallucination Claim Verification
If a customer sends a message stating *"I already paid yesterday via UPI"*:
- The agent **never** hallucinates payment confirmation or marks the invoice as settled based on text alone.
- The system checks the database for a verified `payment.captured` record. If none exists, it politely requests the UTR/transaction ID while explaining that the ledger currently reflects an open balance.

### 5. Invoice Document CDN & PDF Generation
- Dynamic B2B invoice generation using **ReportLab**.
- Uploaded and served securely via private **Supabase Storage Buckets**.
- Served via an authenticated proxy streaming endpoint (`GET /api/invoices/{id}/document`) with `Content-Disposition: inline`.
- Rendered natively in the WhatsApp simulator as interactive PDF preview cards with direct download capabilities.

---

## 💻 Tech Stack

| Layer | Technology | Description |
| :--- | :--- | :--- |
| **Backend Framework** | **FastAPI** (Python 3.10+) | High-performance asynchronous REST API, Webhook routers, and SSE streaming. |
| **AI / LLM Engine** | **Google Gemini 3.5 Flash** (`google-genai`) | Function calling, empathetic debt negotiation, and multi-turn context tracking. |
| **Payment Gateway** | **Razorpay SDK** | Dynamic payment links, webhook verification, and link lifecycle management. |
| **Database & ORM** | **PostgreSQL** (`psycopg2-binary`) / SQLite fallback | ACID-compliant transaction ledgers, row-level locking, and multi-tenant schema. |
| **Authentication & CDN** | **Supabase Auth & Storage** | Merchant JWT authentication and private document storage buckets. |
| **Background Tasks** | **APScheduler & BackgroundTasks** | Async webhook reconciliation and 15-minute cron for link status polling. |
| **Frontend UI** | **React (Vite) + Vanilla CSS** | Glassmorphic dark-mode dashboard, policy control center, and WhatsApp Simulator. |
| **Real-Time Sync** | **Server-Sent Events (SSE)** | Low-latency state synchronization between backend webhooks and frontend UI. |

---

## 📁 Directory Structure

```
ResolveAI/
├── backend/
│   ├── config.py             # Centralized Pydantic settings & environment variables
│   ├── auth.py               # Supabase JWT authentication & tenant resolution
│   ├── models.py             # Pydantic data schemas & integer paise models
│   ├── database.py           # PostgreSQL/SQLite connection, migrations & FSM validator
│   ├── guardrails.py         # Deterministic rule engine & integer currency math
│   ├── agent.py              # Gemini negotiation agent, tool calling & inspectable trace
│   ├── session_manager.py    # Unified phone-centric conversation context manager
│   ├── razorpay_client.py    # Razorpay SDK client, idempotency & link cancellations
│   ├── whatsapp_client.py    # Meta Graph API client & interactive button payloads
│   ├── webhooks.py           # HMAC-SHA256 webhook router & FIFO reconciler
│   ├── storage.py            # Supabase Storage client & PDF document streaming
│   ├── main.py               # FastAPI entrypoint, SSE stream & cron scheduler
│   └── test_all_scenarios.py # Comprehensive automated unit & integration test suite
├── frontend/
│   ├── src/
│   │   ├── App.jsx           # Main Merchant Dashboard & WhatsApp Simulator UI
│   │   ├── AuthView.jsx      # Multi-tenant Sign In & Merchant Registration
│   │   ├── LandingPage.jsx   # Public product presentation & feature walkthrough
│   │   ├── supabaseClient.js # Supabase JS authentication client
│   │   ├── index.css         # Glassmorphism dark-mode styling & design tokens
│   │   └── main.jsx          # React DOM entrypoint
│   ├── package.json          # Frontend dependencies
│   └── vite.config.js        # Vite bundler configuration
├── implementation_plans/     # Master architecture specs & roadmap documentation
├── project_storyline.md      # Detailed engineering narrative & architectural decisions
├── Dockerfile                # Production container deployment definition
├── requirements.txt          # Python backend dependencies
└── README.md                 # System documentation & developer guide
```

---

## 🚀 Getting Started

### Prerequisites
- **Python**: `3.10` or higher
- **Node.js**: `18.x` or higher (`npm` installed)
- **PostgreSQL Database** (or default to local SQLite mode for quick testing)
- **API Keys**:
  - Google Gemini API Key
  - Razorpay Key ID & Key Secret (Test mode supported)
  - Supabase URL & Service Key (Optional for cloud storage/auth)

---

### Environment Configuration

Create a `.env` file in the root directory:

```env
# Application Environment
ENVIRONMENT=development

# LLM Configuration
GEMINI_API_KEY=your_gemini_api_key_here

# Razorpay Credentials (Test or Live)
RAZORPAY_KEY_ID=rzp_test_your_key_id
RAZORPAY_KEY_SECRET=your_razorpay_secret
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret

# Meta WhatsApp Cloud API (Optional for direct Meta webhooks)
META_WHATSAPP_TOKEN=your_meta_token
META_WHATSAPP_PHONE_ID=your_phone_id
META_VERIFY_TOKEN=resolve_ai_webhook_token_2026

# Database & Cache (Leave empty to use built-in SQLite fallback)
DATABASE_URL=postgresql://postgres:password@localhost:5432/resolveai
REDIS_URL=redis://localhost:6379/0

# Supabase Auth & Storage
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your_supabase_service_role_key
```

---

### Backend Setup

1. **Create and activate a virtual environment**:
   ```bash
   # Windows PowerShell
   python -m venv venv
   .\venv\Scripts\Activate.ps1

   # macOS / Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Start the FastAPI backend server**:
   ```bash
   python -m uvicorn backend.main:app --reload --port 8000
   ```
   The API will be live at `http://localhost:8000`. Interactive Swagger documentation is available at `http://localhost:8000/docs`.

---

### Frontend Setup

1. **Navigate to the frontend directory and install packages**:
   ```bash
   cd frontend
   npm install
   ```

2. **Start the Vite development server**:
   ```bash
   npm run dev
   ```

3. **Access the application**:
   Open `http://localhost:5173` in your browser.
   - Use the **Merchant Portal** to register or click **Demo Workspace** to test instantly.
   - Interact with the **Merchant Dashboard** to inspect invoices, adjust guardrails, and track recovered TPV.
   - Use the **WhatsApp Simulator** to test real-time negotiations and payment link generation.

---

## 📡 API Reference

### Core Endpoints

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/invoices` | List all invoices for the authenticated merchant | ✅ Bearer JWT |
| `POST` | `/api/invoices` | Create a new master invoice (generates PDF) | ✅ Bearer JWT |
| `GET` | `/api/invoices/{id}/document` | Stream authenticated invoice PDF inline | ❌ (Signed) |
| `GET` | `/api/guardrails` | Fetch current merchant policy configuration | ✅ Bearer JWT |
| `POST` | `/api/guardrails` | Update down payment %, extension days, or tone | ✅ Bearer JWT |
| `GET` | `/api/analytics` | Fetch real-time TPV, recovered TPV, and recovery rate | ✅ Bearer JWT |
| `POST` | `/api/chat/message` | Send customer message to negotiation agent | ❌ Public / Demo |
| `POST` | `/api/chat/reset` | Reset customer conversation session | ❌ Public / Demo |
| `GET` | `/api/events` | Server-Sent Events (SSE) live update stream | ❌ Public |

### Webhook Endpoints

| Method | Endpoint | Description | Verification |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/webhooks/razorpay` | Ingests `payment.captured` & `payment_link.paid` events | HMAC-SHA256 Signature |
| `GET` | `/api/webhooks/whatsapp` | Meta WhatsApp Cloud API verification challenge | `hub.verify_token` |
| `POST` | `/api/webhooks/whatsapp` | Ingests live WhatsApp customer text & button replies | Payload Signature |

---

## 🧪 Verification & Automated Test Suite

Resolve.ai includes a comprehensive test suite covering cryptographic signatures, integer paise math, state machine integrity, and multi-bill allocation.

```bash
# Run the complete test suite
python backend/test_all_scenarios.py
```

### Verified Audit Criteria:
- ✅ **Cryptographic Timing-Safe HMAC-SHA256 Verification**
- ✅ **Zero-Float Integer Paise Conversions**
- ✅ **Guardrail Ceiling & Floor Rejections**
- ✅ **Non-Reversible State Transitions** (`UNPAID` $\rightarrow$ `PAID`)
- ✅ **Multi-Bill FIFO Allocation Cascades**
- ✅ **Unique Transaction Ledger Idempotency**

---

## 🏢 Multi-Tenant SaaS Architecture

Resolve.ai is built from the ground up to support multiple distinct businesses simultaneously:
1. **Isolated Data**: Every database query is strictly scoped by `merchant_id`.
2. **Custom Policy Profiles**: Each merchant configures their own negotiation guardrails, tone of voice, and discount thresholds.
3. **Organization Profile Management**: Real-time legal entity name updates via `PUT /api/merchant/profile`.
4. **Live SSE Channeling**: Real-time events broadcast dynamically to matching merchant sessions.

---

## 📄 License

This project is licensed under the **MIT License**. See the `LICENSE` file for details.
