# Implementation Plan - Submodule 2: Razorpay API & Webhook Engines

## Overview
Submodule 2 manages direct integration with financial and messaging API infrastructures:
1. **Razorpay Payments**: Payment link generation (with explicit Unix timestamp expiry calculation), raw byte HMAC signature validation, idempotency enforcement via `TransactionLedger`, superseded link cancellation, and invoice balance auto-reconciliation.
2. **Asynchronous Non-Blocking Processing**: Returns HTTP 200 OK under 100ms to eliminate Razorpay retry storms.
3. **Meta WhatsApp Cloud API**: Real production-grade Webhook receiver (`GET` verification handshake & `POST` message ingestion) and outbound Meta Graph API client.

---

## Technical Specifications & Architecture

### 1. Razorpay API Client (`backend/razorpay_client.py`)
- **`RazorpayClient`**:
  - `create_payment_link(amount_in_paise: int, description: str, customer_info: dict, expiry_timestamp: int) -> dict`:
    - Sends POST to `/v1/payment_links` formatted in exact integer paise and valid Unix timestamp `expiry_timestamp`.
  - `cancel_payment_link(payment_link_id: str)`:
    - Sends POST to `/v1/payment_links/{payment_link_id}/cancel` to deactivate superseded payment links when a new agreement is reached.
  - `verify_webhook_signature(raw_body_bytes: bytes, signature: str, secret: str) -> bool`:
    - Computes HMAC-SHA256 digest directly over **raw bytes** (`bytes`) before JSON parsing to preserve exact formatting/key order.

---

### 2. Multi-Link Tracking (`backend/models.py`)
- **`PaymentLinkRecord`**:
  - `id`: int
  - `invoice_id`: str (Foreign Key)
  - `razorpay_payment_link_id`: str (Primary Index)
  - `amount_paise`: int
  - `status`: str (`ACTIVE`, `PAID`, `CANCELLED`, `EXPIRED`)
  - `created_at`: str

---

### 3. Asynchronous Idempotent Webhook Handler (`backend/webhooks.py`)
- **Endpoint Workflow**:
  1. `raw_body = await request.body()`
  2. `RazorpayClient.verify_webhook_signature(raw_body, signature, secret)`: Returns 400 Bad Request if invalid.
  3. Spawns `background_tasks.add_task(reconcile_payment_event, raw_body_json)`.
  4. Returns `{"status": "ok"}` **immediately (HTTP 200 OK < 100ms)**.

- **Background Reconciler (`reconcile_payment_event`)**:
  - Checks event type: `payment_link.paid`, `payment_link.partially_paid`, or `payment.captured`.
  - Extracts `payment_id` and `payment_link_id`.
  - Checks `TransactionLedger` for duplicate `payment_id` (Idempotency check).
  - Updates `MasterInvoice` balance, applies FSM state transition, and cancels any other `ACTIVE` payment links associated with this invoice.

---

### 4. Meta WhatsApp Cloud API Receiver (`backend/webhooks.py`)
- `GET /api/webhooks/whatsapp`: Validates `hub.verify_token` and returns `hub.challenge`.
- `POST /api/webhooks/whatsapp`: Parses Meta Cloud API `messages` payload, extracts sender phone + text, and forwards to core `AgenticNegotiator`.

---

## Verification Plan

### Automated Verification
- Run `python backend/test_submodule2.py`:
  1. Test HMAC-SHA256 signature verification over raw bytes.
  2. Test Razorpay payment link request payload formats `amount` in integer paise and valid Unix `expiry_timestamp`.
  3. Test duplicate webhook payload delivery: Assert background task executes idempotently and webhook endpoint returns HTTP 200 OK instantly.
  4. Test cancellation of superseded payment links when a new payment link record is created.
