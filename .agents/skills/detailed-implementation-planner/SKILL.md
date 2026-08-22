---
name: detailed-implementation-planner
description: Universal methodology for AI agents to design modular, battle-tested, production-grade implementation plans with technical edge-case auditing, FSM state machines, concurrency locks, and verification criteria.
---

# Universal Production Implementation Planning Guide

When asked to create an implementation plan for any complex software system, follow this systematic multi-phase methodology. Never generate generic high-level summaries; build detailed, battle-tested, modular technical blueprints.

---

## Phase 1: Modular Partitioning Strategy
1. **Never build everything in one monolithic plan.** Divide the system into 4-6 modular, independently executable, and verifiable submodules:
   - **Submodule 1: Data Models, Persistence & Safety Engines** (Schemas, integer math, FSMs, DB WAL mode).
   - **Submodule 2: External API Integrations & Webhook Processing** (Raw-byte HMACs, payload idempotency, row locking, non-blocking background tasks).
   - **Submodule 3: Core Business & Agentic Logic** (Session context, concurrency locks, untrusted LLM gateway, anti-hallucination directives).
   - **Submodule 4: Server Orchestration & REST Endpoints** (FastAPI/Express setup, explicit CORS, SSE real-time event streams, async I/O).
   - **Submodule 5: User Interface, Simulators & Dashboards** (Design system, real-time SSE syncing, latency polish/typing indicators, interactive modals).
2. **Create a `master_implementation_roadmap.md`** linking to every individual submodule plan file.

---

## Phase 2: Mandatory Technical & Edge-Case Auditing
Before finalizing any plan, audit the architecture against 5 critical technical pillars:

### 1. Data Precision & Storage Invariants
- **Monetary Values**: Store currency strictly as integer subunits (e.g. integer paise, cents) to prevent floating-point binary math errors (`50000.10 + 20.20 -> 50020.299999999996`).
- **Finite State Machine (FSM)**: Define explicit non-reversible state transitions ($\text{STATE\_A} \rightarrow \text{STATE\_B} \rightarrow \text{STATE\_C}$). Lock terminal states from backward mutation.
- **DB Concurrency**: Use WAL mode (`PRAGMA journal_mode=WAL;`), row locks (`SELECT ... FOR UPDATE`), or busy timeouts for SQLite/PostgreSQL under concurrent async traffic.

### 2. External API & Webhook Specifications
- **Raw Byte Webhook Verification**: Compute HMAC-SHA256 signatures over `raw_body` bytes **before** JSON deserialization to preserve exact payload formatting.
- **Payload vs Header Idempotency**: Verify API-specific idempotency requirements (e.g. `reference_id` JSON payload fields vs `X-Idempotency-Key` headers) and enforce uniqueness.
- **Platform Limit Caps**: Audit third-party API restrictions (e.g. 180-day max expiration timestamps) and cap inputs deterministically.
- **Non-Blocking Webhook Execution**: Validate signature, dispatch reconciliation to async background queues, and return `HTTP 200 OK` in <100ms to eliminate API gateway retry storms.

### 3. Agentic & System Concurrency Safety
- **Composite Session Keys**: Format routing keys with context attributes (e.g. `f"{customer_id}_{entity_id}"`) to prevent multi-entity context pollution.
- **Atomic Session Locks**: Wrap request handlers in per-session async locks (`session_locks[session_id]`) to prevent double-texting race conditions from executing parallel LLM tool calls.
- **Untrusted Model Principle**: Treat LLM outputs as untrusted. Place a hard, deterministic Python/code gateway (`GuardrailEngine`) between LLM tool calls and API execution.
- **Anti-Hallucination Directives**: System prompts must explicitly forbid acknowledging state changes (e.g. fund receipt) based solely on user text claims without verified backend state injection.

### 4. Server & Interface Experience
- **Explicit CORS**: Restrict origins to exact domains (`["http://localhost:5173"]`) with `allow_credentials=True`.
- **Real-Time State Syncing**: Use Server-Sent Events (SSE) or WebSockets (`GET /api/events`) so dashboards update automatically when background webhooks execute.
- **Latency Polish**: Include UI typing indicators or optimistic updates during backend processing delays.

---

## Phase 3: Verification & Invariants
- **Clean Markdown & Syntax**: Ensure all code blocks are complete with matching closing parentheses/brackets (`)`).
- **Automated & Manual Verification Plans**: Every submodule plan must include executable unit test cases and step-by-step manual test walkthroughs.
