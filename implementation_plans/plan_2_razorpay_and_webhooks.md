# Implementation Plan - Submodule 2: Razorpay API Client & Meta Webhook Engines

## Overview
Submodule 2 manages direct integration with both financial and messaging API infrastructures:
1. **Razorpay Payments**: Payment link generation, HMAC signature validation, idempotency enforcement via `TransactionLedger`, and invoice balance auto-reconciliation.
2. **Meta WhatsApp Cloud API**: Real production-grade Webhook receiver (`GET` verification handshake & `POST` message ingestion) and outbound Meta Graph API message client.

---

## Technical Specifications & Architecture

### 1. Razorpay API Client (`backend/razorpay_client.py`)
- **`RazorpayClient`**:
  - `create_payment_link(amount_in_paise: int, description: str, customer_info: dict, expiry_timestamp: int) -> dict`:
    - Sends POST to `/v1/payment_links` formatted in exact integer paise.
    - Sandbox fallback mode: Generates authentic Razorpay payment link responses if live API keys are omitted.
  - `verify_webhook_signature(payload_body: str, signature: str, secret: str) -> bool`:
    - Computes HMAC-SHA256 digest matching Razorpay security specification.

### 2. Meta WhatsApp Cloud API Client (`backend/whatsapp_client.py`)
- **`WhatsAppCloudClient`**:
  - Outbound messaging wrapper for Meta Graph API (`https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages`).
  - `send_message(to_phone: str, message_text: str, payment_link_url: str = None)`: Sends interactive text or CTA button messages directly to WhatsApp accounts.

### 3. Webhook Receiver Engine (`backend/webhooks.py`)
- **Idempotent Razorpay Webhook Handler**:
  - Extracts `payment_id` from `payment.captured` or `invoice.partially_paid` payload.
  - Checks `TransactionLedger` for existing `payment_id`:
    - If found: Logs warning & silently returns `200 OK` (Idempotent bypass).
    - If new: Inserts into `TransactionLedger`, updates `MasterInvoice` remaining balance & status (`PARTIALLY_PAID` or `PAID`).
- **Meta WhatsApp Webhook Handler**:
  - `verify_meta_webhook(mode: str, token: str, challenge: str)`: Validates `hub.verify_token` and returns `hub.challenge`.
  - `process_whatsapp_webhook(payload: dict)`: Parses Meta Cloud API `messages` payload, extracts sender phone + text, and forwards to core `AgenticNegotiator`.

---

## Verification Plan

### Automated Verification
- Run `python backend/test_submodule2.py`:
  1. Test HMAC-SHA256 signature verification pass/fail.
  2. Test Razorpay payment link request payload formats `amount` in integer paise.
  3. Test duplicate webhook payload delivery: Assert single ledger record created and both return HTTP 200 OK.
  4. Test Meta `GET` webhook verification handshake returning `hub.challenge`.
