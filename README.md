# Resolve.ai - Autonomous Collections Agent for Razorpay

**Resolve.ai** is a production-grade, guardrail-constrained autonomous collections agent designed for Indian SMEs and freelancers using Razorpay. It bridges unstructured human negotiation over WhatsApp/Email with deterministic financial transactions via the Razorpay API, transforming overdue invoices into recovered Total Payment Volume (TPV).

---

## Completed Implementation Submodules

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
   - `create_payment_link()` with `"reference_id": f"ref_{session_id[:20]}_t{turn}"` (max 40 chars) payload idempotency.
   - `cancel_payment_link()` deactivating superseded active links.
   - `verify_webhook_signature()` validating HMAC-SHA256 directly over raw request bytes.
2. **Meta WhatsApp Cloud API Client (`backend/whatsapp_client.py`)**:
   - `send_text_message()` and `send_interactive_buttons()` (multi-invoice button prompt).
3. **Meta & Razorpay Webhook Engine (`backend/webhooks.py`)**:
   - `verify_meta_webhook()` GET challenge handshake (`hub.challenge`).
   - `process_whatsapp_webhook()` parsing both `type == "text"` and `type == "interactive"` button replies for composite session key binding (`f"{customer_phone}_{invoice_id}"`).
   - `reconcile_payment_event()` async reconciler executing integer paise math, FSM updates, and link deactivation strictly inside invoice row locks (`async with invoice_locks[invoice_id]:`).

---

## Verification Results

### Submodule 1 Unit Tests (`backend/test_submodule1.py`)
```bash
python -m unittest backend/test_submodule1.py
```
- `test_1_currency_math`: PASSED
- `test_2_fsm_lifecycle_transitions`: PASSED
- `test_3_database_operations`: PASSED
- `test_4_unique_payment_id_idempotency`: PASSED
- `test_5_guardrail_engine_validation`: PASSED

### Submodule 2 Unit Tests (`backend/test_submodule2.py`)
```bash
python -m unittest backend/test_submodule2.py
```
- `test_1_razorpay_payment_link_reference_id_idempotency`: PASSED
- `test_2_raw_byte_hmac_signature_verification`: PASSED
- `test_3_meta_whatsapp_webhook_handshake_and_routing`: PASSED
- `test_4_asynchronous_row_locked_webhook_reconciliation`: PASSED

```text
----------------------------------------------------------------------
Ran 4 tests in 0.277s

OK
```

---

## Project Structure

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
│   ├── test_submodule1.py  # Submodule 1 unit test suite
│   └── test_submodule2.py  # Submodule 2 unit test suite
├── implementation_plans/   # Detailed implementation plans
└── README.md
```

---

## Next Steps
- **Submodule 3**: Implement Agentic LLM Negotiation Engine & Session Manager (`session_manager.py`, `agent.py`).
