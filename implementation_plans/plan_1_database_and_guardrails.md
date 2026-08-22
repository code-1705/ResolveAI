# Implementation Plan - Submodule 1: Core Database, Models & Guardrail Engine

## Overview
This submodule forms the foundational data layer and safety engine for **Resolve.ai**. It establishes the database schema for invoices, transaction ledgers (with idempotent constraints), composite chat sessions, and merchant guardrails, alongside a deterministic Python rule-validation engine enforcing upper/lower boundary bounds, Razorpay's platform 180-day hard limit, and strict Finite State Machine (FSM) lifecycle rules.

---

## Technical Specifications & Architecture

### 1. Integer Currency Storage & Schema (`backend/models.py` & `backend/database.py`)
> [!IMPORTANT]
> **Fintech Core Rule - Integer Paise Only**:
> All monetary values are stored strictly as 64-bit integer paise (`int`) in the database to eliminate floating-point precision loss.

- **`MerchantGuardrails`**:
  - `min_partial_payment_pct`: float (default `30.0`)
  - `max_extension_days`: int (default `14`)
  - `max_split_installments`: int (default `3`)
  - `auto_discount_waiver_pct`: float (default `5.0`)
  - `tone`: str (`professional_empathetic`, `firm`, `concise`)

- **`MasterInvoice`**:
  - `invoice_id`: str (Primary Key, e.g., `inv_SME_001`)
  - `customer_name`: str
  - `customer_phone`: str
  - `original_amount_paise`: int (**Integer Paise**)
  - `paid_amount_paise`: int (**Integer Paise**)
  - `remaining_amount_paise`: int (**Integer Paise**)
  - `due_date`: str (YYYY-MM-DD)
  - `status`: str (`UNPAID`, `NEGOTIATING`, `PARTIALLY_PAID`, `PAID`, `CANCELLED`)

- **`TransactionLedger`**:
  - `id`: int (Primary Key Auto-Increment)
  - `invoice_id`: str (Foreign Key)
  - `razorpay_payment_id`: str (**UNIQUE INDEX** for Webhook Idempotency)
  - `razorpay_payment_link_id`: str
  - `amount_paid_paise`: int (**Integer Paise**)
  - `payment_method`: str (UPI, CARD, NETBANKING)
  - `created_at`: str (ISO Timestamp)

- **`ChatSession` & `ChatMessage` (Composite Session Key)**:
  - `session_id`: str (**Composite Key**: `f"{customer_phone}_{invoice_id}"` to prevent cross-talk between multiple active invoices for the same SME customer)
  - `invoice_id`: str
  - `customer_phone`: str
  - `messages`: JSON list of message turns (`sender`, `text`, `timestamp`, `tool_call_meta`)

---

### 2. Finite State Machine (FSM) Lifecycle Enforcement
Allowed state transitions:
$$\text{UNPAID} \longrightarrow \text{NEGOTIATING} \longrightarrow \text{PARTIALLY\_PAID} \longrightarrow \text{PAID}$$

- Terminal states (`PAID`, `CANCELLED`) cannot be modified or re-opened by incoming webhooks or chat actions.
- Backward state transitions (e.g., `PAID -> UNPAID` or `PARTIALLY_PAID -> NEGOTIATING`) are rejected with an explicit `FSMStateError`.

---

### 3. Database Concurrency & WAL Configuration (`backend/database.py`)
- Configured with `PRAGMA journal_mode=WAL;` and `PRAGMA busy_timeout=5000;`.
- Enables non-blocking concurrent reads while writing, preventing `sqlite3.OperationalError: database is locked` errors during simultaneous chat messages and webhook events.

---

### 4. Deterministic Guardrail Engine & Razorpay 180-Day Hard Limit (`backend/guardrails.py`)
- **`GuardrailEngine`**:
  - `validate_proposal(invoice_id, proposed_amount_inr, extension_days)`:
    - Converts `proposed_amount_inr` to `proposed_amount_paise = int(round(proposed_amount_inr * 100))`.
    - Calculates `min_required_paise = int(round(remaining_amount_paise * (min_partial_payment_pct / 100.0)))`.
    - **Enforces Ceiling & Floor Boundary**:
      $$\text{min\_required\_paise} \le \text{proposed\_amount\_paise} \le \text{remaining\_amount\_paise}$$
      Rejects any proposal where `proposed_amount_paise > remaining_amount_paise` (preventing over-billing or hallucinated inflated link amounts).
    - **Enforces Razorpay Platform 180-Day Limit**:
      ```python
      effective_max_extension = min(max_extension_days, 180)
      ```
      Rejects any extension request where `extension_days > effective_max_extension` to prevent Razorpay API `400 Bad Request` failures.
    - Returns `(is_valid: bool, reason: str, counter_offer_terms: dict)`.

---

## Verification Plan

### Automated Verification
- Run `python backend/test_submodule1.py`:
  1. Verify `inr_to_paise(20000.50)` equals `2000050` and DB stores integer `2000050`.
  2. Verify upper-bound check: Reject proposal of ₹60,000 on ₹50,000 remaining balance.
  3. Verify Razorpay 180-day cap: Merchant setting `max_extension_days: 200` is capped at 180 days.
  4. Verify composite session key `f"{phone}_{invoice_id}"` isolates multiple invoices for same phone.
  5. Verify FSM rejects invalid backward state transition (`PAID -> UNPAID`).
  6. Test `TransactionLedger` enforcing `UNIQUE(razorpay_payment_id)` constraint on duplicate inserts.
