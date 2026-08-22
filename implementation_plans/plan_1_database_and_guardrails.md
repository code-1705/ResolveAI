# Implementation Plan - Submodule 1: Core Database, Models & Guardrail Engine

## Overview
This submodule forms the foundational data layer and safety engine for **Resolve.ai**. It establishes the database schema for invoices, transaction ledgers (with idempotent constraints), chat sessions, and merchant guardrails, alongside a deterministic Python rule-validation engine.

---

## Technical Specifications & Architecture

### 1. Database Schema (`backend/models.py` & `backend/database.py`)
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
  - `original_amount_inr`: float
  - `paid_amount_inr`: float
  - `remaining_amount_inr`: float
  - `due_date`: str (YYYY-MM-DD)
  - `status`: str (`UNPAID`, `NEGOTIATING`, `PARTIALLY_PAID`, `PAID`, `DEFAULTED`)

- **`TransactionLedger`**:
  - `id`: int (Primary Key Auto-Increment)
  - `invoice_id`: str (Foreign Key)
  - `razorpay_payment_id`: str (**UNIQUE INDEX** for Webhook Idempotency)
  - `razorpay_order_id`: str
  - `amount_paid_inr`: float
  - `amount_paid_paise`: int
  - `payment_method`: str (UPI, CARD, NETBANKING)
  - `created_at`: str (ISO Timestamp)

- **`ChatSession` & `ChatMessage`**:
  - `session_id`: str (WhatsApp Phone Number / UUID)
  - `invoice_id`: str
  - `messages`: JSON list of message turns (`sender`, `text`, `timestamp`, `tool_call_meta`)

---

### 2. Deterministic Guardrail Engine (`backend/guardrails.py`)
- **`GuardrailEngine`**:
  - `validate_proposal(invoice_id, proposed_amount_inr, extension_days)`:
    - Calculates `min_required_inr = remaining_amount_inr * (min_partial_payment_pct / 100.0)`.
    - Validates if `proposed_amount_inr >= min_required_inr`.
    - Validates if `extension_days <= max_extension_days`.
    - Returns `(is_valid: bool, reason: str, counter_offer: dict)`.

- **Currency Math Utility**:
  - `inr_to_paise(amount_in_inr: float) -> int`: Returns `int(round(amount_in_inr * 100.0))`.
  - `paise_to_inr(amount_in_paise: int) -> float`: Returns `round(amount_in_paise / 100.0, 2)`.

---

## Verification Plan

### Automated Verification
- Run `python backend/test_submodule1.py`:
  1. Test `inr_to_paise(20000.50)` equals `2000050` (exact integer paise).
  2. Test `GuardrailEngine` approves 40% initial payment offer and rejects 10% offer with structured counter-proposal.
  3. Test `TransactionLedger` enforcing `UNIQUE(razorpay_payment_id)` constraint on duplicate inserts.
