# Implementation Plan - Submodule 2: Razorpay API & Webhook Engines

## Overview
Submodule 2 manages direct integration with financial and messaging API infrastructures:
1. **Razorpay Payments**: Payment link generation (with explicit Unix timestamp expiry calculation), raw byte HMAC signature validation, idempotency enforcement via `TransactionLedger`, superseded link cancellation, and invoice balance auto-reconciliation with row locking.
2. **Asynchronous Non-Blocking Processing**: Returns HTTP 200 OK under 100ms to eliminate Razorpay retry storms.
3. **Meta WhatsApp Cloud API**: Real production-grade Webhook receiver (`GET` verification handshake & `POST` message ingestion with composite invoice routing) and outbound Meta Graph API client.

---

## Technical Specifications & Architecture

### 1. Razorpay API Client (`backend/razorpay_client.py`)
- **`RazorpayClient`**:
  - `create_payment_link(amount_in_paise: int, description: str, customer_info: dict, expiry_timestamp: int) -> dict`:
    - Sends POST to `/v1/payment_links` formatted in exact integer paise and valid Unix timestamp `expiry_timestamp` (capped at 180 days).
  - `cancel_payment_link(payment_link_id: str)`:
    - Sends POST to `/v1/payment_links/{payment_link_id}/cancel` to deactivate superseded payment links when a new agreement is reached.
  - `verify_webhook_signature(raw_body_bytes: bytes, signature: str, secret: str) -> bool`:
    - Computes HMAC-SHA256 digest directly over **raw bytes** (`bytes`) before JSON parsing to preserve exact formatting/key order.

---

### 2. Asynchronous Idempotent Webhook Handler & Invoice Row Locking (`backend/webhooks.py`)
- **Endpoint Workflow**:
  1. `raw_body = await request.body()`
  2. `RazorpayClient.verify_webhook_signature(raw_body, signature, secret)`: Returns 400 Bad Request if invalid.
  3. Spawns `background_tasks.add_task(reconcile_payment_event, raw_body_json)`.
  4. Returns `{"status": "ok"}` **immediately (HTTP 200 OK < 100ms)**.

- **Background Reconciler with Invoice Row Locking (`reconcile_payment_event`)**:
  - Checks event type: `payment_link.paid`, `payment_link.partially_paid`, or `payment.captured`.
  - Extracts `payment_id`, `payment_link_id`, and `invoice_id`.
  - **Invoice Mutex Lock (`async with invoice_locks[invoice_id]:` / `SELECT ... FOR UPDATE`)**:
    - Prevents race conditions where two simultaneous webhooks (`payment.captured` and `payment_link.paid`) attempt to update the same invoice status concurrently.
  - Checks `TransactionLedger` for duplicate `payment_id` (Idempotency check).
  - Updates `MasterInvoice` balance, applies FSM state transition, and cancels any other `ACTIVE` payment links associated with this invoice.

---

### 3. Meta WhatsApp Cloud API Receiver & Multi-Invoice Router (`backend/webhooks.py`)
- `GET /api/webhooks/whatsapp`: Validates `hub.verify_token` and returns `hub.challenge`.
- `POST /api/webhooks/whatsapp`:
  1. Parses Meta Cloud API `messages` payload, extracting `customer_phone` and `text.body`.
  2. **Multi-Invoice Routing Resolution**:
     - Queries `MasterInvoice` for active invoices (`UNPAID`, `NEGOTIATING`, `PARTIALLY_PAID`) matching `customer_phone`.
     - **If count == 1**: Auto-generates composite session key `session_id = f"{customer_phone}_{invoice_id}"` and forwards message to `AgenticNegotiator`.
     - **If count > 1**: Pauses LLM execution and sends a Meta Interactive Message (List/Buttons) to WhatsApp asking:
       *"Hi! You have 2 active invoices (Inv-001 for ₹50,000 and Inv-002 for ₹1,20,000). Which invoice would you like to discuss?"*
     - **If count == 0**: Sends friendly message: *"No active overdue invoices found for this number."*

---

## Verification Plan

### Automated Verification
- Run `python backend/test_submodule2.py`:
  1. Test HMAC-SHA256 signature verification over raw bytes.
  2. Test background task invoice row lock: Simulate simultaneous webhooks for same `invoice_id` and verify sequential processing.
  3. Test WhatsApp Routing: Phone with 1 active invoice routes to LLM; phone with 2 active invoices returns Meta Interactive Button response.
  4. Test duplicate webhook payload delivery: Assert background task executes idempotently and returns HTTP 200 OK.
