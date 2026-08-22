# Resolve.ai - Autonomous Collections Agent for Razorpay

**Resolve.ai** is a production-grade, guardrail-constrained autonomous collections agent designed for Indian SMEs and freelancers using Razorpay. It bridges unstructured human negotiation over WhatsApp/Email with deterministic financial transactions via the Razorpay API, transforming overdue invoices into recovered Total Payment Volume (TPV).

---

## Submodule 1 Execution Summary

### Features Implemented (`backend/`)
1. **Configuration & Secrets Management (`backend/config.py`)**:
   - Centralized Pydantic settings loading environment variables, default merchant guardrails, API credentials, and SQLite database paths.

2. **Data Models & Schema (`backend/models.py`)**:
   - **Integer Paise Storage**: All monetary fields (`original_amount_paise`, `paid_amount_paise`, `remaining_amount_paise`) stored strictly as 64-bit integer paise to eliminate floating-point precision drift (`₹50,000.10 -> 5000010 paise`).
   - `MerchantGuardrails`: Editable negotiation thresholds (`min_partial_payment_pct`, `max_extension_days`, `max_split_installments`, `auto_discount_waiver_pct`, `tone`).
   - `MasterInvoice`: Overdue invoice ledger with calculated INR helper properties.
   - `TransactionLedger`: Ledger records with **`UNIQUE(razorpay_payment_id)`** index enforcing DB-level idempotency.
   - `PaymentLinkRecord`: Tracks generated Razorpay links and statuses (`ACTIVE`, `PAID`, `CANCELLED`, `EXPIRED`).
   - `ChatSession` & `ChatMessage`: Composite key routing (`session_id = f"{customer_phone}_{invoice_id}"`).

3. **Database Engine & Finite State Machine (`backend/database.py`)**:
   - SQLite WAL Mode (`PRAGMA journal_mode=WAL;`) with 5000ms busy timeout for high async concurrency.
   - **Directional FSM State Validation (`validate_fsm_transition`)**:
     $$\text{UNPAID} \longrightarrow \text{NEGOTIATING} \longrightarrow \text{PARTIALLY\_PAID} \longrightarrow \text{PAID}$$
     Locks terminal states (`PAID`, `CANCELLED`) and rejects backward state transitions (`FSMStateError`).
   - DB-level catch for duplicate `razorpay_payment_id` insertions.

4. **Deterministic Guardrail Engine (`backend/guardrails.py`)**:
   - Currency math helpers (`inr_to_paise`, `paise_to_inr`).
   - `GuardrailEngine.validate_proposal()` enforcing 4 invariant bounds:
     - **Floor Check**: `proposed_amount_paise >= min_required_paise`
     - **Ceiling Check**: `proposed_amount_paise <= remaining_amount_paise`
     - **Razorpay 180-Day Cap**: `extension_days <= min(max_extension_days, 180)`
     - **Counter-Offer Generation**: Returns structured counter-offer terms when proposals breach guardrails.

---

## Verification Results

Submodule 1 unit tests (`backend/test_submodule1.py`) executed and passed cleanly:

```bash
python -m unittest backend/test_submodule1.py
```

### Test Suite Output:
- `test_1_currency_math`: PASSED (Exact integer paise conversion)
- `test_2_fsm_lifecycle_transitions`: PASSED (FSM state enforcement & terminal locking)
- `test_3_database_operations`: PASSED (WAL mode DB table creation & queries)
- `test_4_unique_payment_id_idempotency`: PASSED (UNIQUE constraint duplicate catch)
- `test_5_guardrail_engine_validation`: PASSED (Floor, ceiling, and 180-day cap checks)

```text
----------------------------------------------------------------------
Ran 5 tests in 0.230s

OK
```

---

## Project Structure

```
c:\Users\Vansh\Desktop\TrustBridge\
├── backend/
│   ├── config.py           # Application settings & secrets
│   ├── models.py           # Pydantic & dataclass schemas
│   ├── database.py         # SQLite WAL connection & FSM validator
│   ├── guardrails.py       # Deterministic rule engine & currency math
│   └── test_submodule1.py  # Submodule 1 unit test suite
├── implementation_plans/   # Submodule plan documentation
│   ├── master_implementation_roadmap.md
│   ├── plan_1_database_and_guardrails.md
│   ├── plan_2_razorpay_and_webhooks.md
│   ├── plan_3_agent_and_session_manager.md
│   ├── plan_4_fastapi_server.md
│   └── plan_5_frontend_dashboard_and_simulator.md
└── README.md
```

---

## Next Steps
- **Submodule 2**: Implement Razorpay API Client (with `"reference_id"` payload idempotency & superseded link cancellation) and Meta WhatsApp Webhooks.
