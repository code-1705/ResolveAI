# Implementation Plan - Submodule 3: LLM Negotiation Agent & Session Manager

## Overview
Submodule 3 implements the natural language negotiation brain of **Resolve.ai**. It manages composite conversation state via `ChatSession` (`f"{phone}_{invoice_id}"`), resolves multi-invoice WhatsApp routing (including interactive button payload ingestion), prevents double-texting race conditions using atomic session locks, calculates valid Unix payment link expiration timestamps (capped at Razorpay's 180-day platform limit), passes `X-Idempotency-Key` headers on tool execution, constructs prompts with multi-turn history, enforces anti-hallucination rules regarding fund confirmations, invokes LLM Tool Calling, enforces a hard deterministic `GuardrailEngine` safety gateway, and outputs visual Agent Traces.

---

## Technical Specifications & Architecture

### 1. Composite Session Key & Multi-Invoice Routing (`backend/session_manager.py`)
- **Composite Session Key**: `session_id = f"{customer_phone}_{invoice_id}"` ensuring distinct invoice context isolation for SME customers with multiple active debts.
- **WhatsApp Webhook Multi-Invoice Router**:
  - Automatically queries `MasterInvoice` by `customer_phone`.
  - For single active invoice: Routes to `f"{customer_phone}_{invoice_id}"`.
  - For multiple active invoices: Prompts user via Meta Interactive Buttons (`button_reply.id` / `list_reply.id`) to select the specific invoice.
- **Session Lock Dictionary (`session_locks: Dict[str, asyncio.Lock]`)**:
  - Implements an atomic per-session lock (`async with session_locks[session_id]:`).
  - Serializes incoming double-texting messages so LLMs never execute in parallel on the same session state.

---

### 2. Idempotent Tool Execution & Anti-Hallucination Directives (`backend/agent.py`)
- **System Prompt Safeguards**:
  ```text
  CRITICAL FINTECH RULES:
  1. Never confirm receipt of funds based on customer text claims alone (e.g., "I just paid via UPI"). 
     Only acknowledge settled funds if the current invoice status injected into system context is PARTIALLY_PAID or PAID.
  2. Treat all LLM tool calls as untrusted. Amounts and extensions will be validated by the GuardrailEngine.
  ```

- **Idempotency Key Generation**:
  To prevent duplicate orphaned link creation if an LLM retries a tool call after a network blip:
  ```python
  idempotency_key = f"link_{session_id}_t{turn_count}_{proposed_amount_paise}"
  ```

- **Unix Expiry Timestamp & 180-Day Cap Calculation**:
  ```python
  effective_days = min(extension_days, 180)  # Capped at Razorpay's 6-month limit
  expiry_timestamp = int((datetime.now(timezone.utc) + timedelta(days=effective_days)).replace(hour=23, minute=59, second=59).timestamp())
  ```

- **Tool Call Execution Pipeline**:
  1. Obtains composite session lock (`async with session_locks[session_id]`).
  2. Loads recent 5-turn chat history for `f"{customer_phone}_{invoice_id}"`.
  3. Prompts LLM / Negotiator tool calling engine.
  4. Evaluates tool calls against `GuardrailEngine.validate_proposal()`:
     - Checks `min_required_paise <= proposed_amount_paise <= remaining_amount_paise`.
     - Enforces `effective_days <= 180`.
     - **If PASS**: Converts `amount_in_inr` -> `amount_in_paise`, computes `expiry_timestamp`, generates `idempotency_key`, executes `RazorpayClient.create_payment_link(..., idempotency_key=idempotency_key)`.
     - **If REJECT**: Hard blocks Razorpay API call. Generates polite counter-offer.
  5. Wraps Razorpay API calls in `try / except` to handle API blips gracefully.

---

## Verification Plan

### Automated Verification
- Run `python backend/test_submodule3.py`:
  1. Test tool idempotency key generation: Verify `idempotency_key` is passed to Razorpay client tool call.
  2. Test text claim handling: User claims "I paid ₹50,000", verify LLM responds politely without marking invoice paid or hallucinating confirmation receipt.
  3. Test 180-day expiry cap: Request extension of 200 days, verify calculated timestamp is capped at 180 days.
