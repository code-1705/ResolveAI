# Implementation Plan - Submodule 2: Razorpay API & Webhook Engines

## Overview
Submodule 2 manages direct integration with financial and messaging API infrastructures:
1. **Razorpay Payments**: Payment link generation with `X-Idempotency-Key` headers (preventing duplicate link creation on network retries), raw byte HMAC signature validation, idempotency enforcement via `TransactionLedger`, superseded link cancellation, and row-locked transaction reconciliation math.
2. **Asynchronous Non-Blocking Processing**: Returns HTTP 200 OK under 100ms to eliminate Razorpay retry storms.
3. **Meta WhatsApp Cloud API**: Real production-grade Webhook receiver (`GET` verification handshake & `POST` message ingestion with text & interactive button/list payload extraction) and outbound Meta Graph API client.

---

## Technical Specifications & Architecture

### 1. Razorpay API Client & Idempotency Header (`backend/razorpay_client.py`)
- **`RazorpayClient`**:
  - `create_payment_link(amount_in_paise: int, description: str, customer_info: dict, expiry_timestamp: int, idempotency_key: str = None) -> dict`:
    - Sends POST to `/v1/payment_links` formatted in exact integer paise and valid Unix timestamp `expiry_timestamp`.
    - **Header Safeguard**: Includes `X-Idempotency-Key: idempotency_key` (derived from `f"link_{session_id}_{turn_count}_{amount_paise}"`). If a network timeout causes an LLM or client retry, Razorpay returns the existing payment link instead of creating a duplicate orphaned link.
  - `cancel_payment_link(payment_link_id: str)`:
    - Sends POST to `/v1/payment_links/{payment_link_id}/cancel` to deactivate superseded payment links when a new agreement is reached.
  - `verify_webhook_signature(raw_body_bytes: bytes, signature: str, secret: str) -> bool`:
    - Computes HMAC-SHA256 digest directly over **raw bytes** (`bytes`) before JSON parsing.

---

### 2. Transaction Reconciler with Row Lock & Balance Math (`backend/webhooks.py`)
- **Endpoint Workflow**:
  1. `raw_body = await request.body()`
  2. `RazorpayClient.verify_webhook_signature(raw_body, signature, secret)`: Returns 400 Bad Request if invalid.
  3. Spawns `background_tasks.add_task(reconcile_payment_event, raw_body_json)`.
  4. Returns `{"status": "ok"}` **immediately (HTTP 200 OK < 100ms)**.

- **Strict Reconciler Execution Steps inside Row Lock (`reconcile_payment_event`)**:
  1. Extract `payment_id`, `payment_link_id`, `invoice_id`, and `amount_paise` from webhook JSON.
  2. **Acquire Invoice Mutex Lock (`async with invoice_locks[invoice_id]:`)**:
  3. **Re-Read Latest State**: Query DB for current `MasterInvoice` (`paid_amount_paise`, `remaining_amount_paise`, `status`).
  4. **Idempotency Check**: Query `TransactionLedger` for existing `razorpay_payment_id`. If exists, release lock & return.
  5. **Execute Balance Math Strictly Inside Lock**:
     - `new_paid_paise = current_paid_paise + amount_paise`
     - `new_remaining_paise = max(0, original_amount_paise - new_paid_paise)`
     - Determine FSM status: `PAID` if `new_remaining_paise == 0` else `PARTIALLY_PAID`.
  6. **Persist Transaction & Update Invoice**: Record into `TransactionLedger`, update `MasterInvoice`, cancel older active payment links, commit DB transaction, and release row lock.

---

### 3. Meta WhatsApp Cloud API Receiver & Interactive Payload Parser (`backend/webhooks.py`)
- `GET /api/webhooks/whatsapp`: Validates `hub.verify_token` and returns `hub.challenge`.
- `POST /api/webhooks/whatsapp`:
  1. Parses Meta Cloud API payload `entry[0].changes[0].value.messages[0]`.
  2. **Extract Message Payload Type**:
     - **Text Message (`type == "text"`)**: Extracts `text.body`.
     - **Interactive Button / List Selection (`type == "interactive"`)**: Extracts `button_reply.id` or `list_reply.id` (e.g. `id = "select_invoice_inv_SME_002"`).
  3. **Routing & Session Key Binding**:
     - If interactive payload received: Binds selected `invoice_id`, initializes composite session key `session_id = f"{customer_phone}_{selected_invoice_id}"`, and acknowledges selection.
     - If text message received and count == 1: Auto-routes to `f"{customer_phone}_{invoice_id}"`.
     - If text message received and count > 1: Sends Meta Interactive Buttons asking user to select active invoice.

---

## Verification Plan

### Automated Verification
- Run `python backend/test_submodule2.py`:
  1. Test Razorpay `X-Idempotency-Key` header prevents duplicate link creation on simulated API retry.
  2. Test background task balance math inside row lock: Verify accurate `remaining_amount_paise` deduction.
  3. Test Meta WhatsApp Interactive payload parser: Parse `type == "interactive"` button reply and confirm extraction of `invoice_id`.
  4. Test HMAC-SHA256 signature verification over raw bytes.
