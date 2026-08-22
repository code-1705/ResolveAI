# Implementation Plan - Submodule 4: FastAPI Server Core & REST Endpoints

## Overview
Submodule 4 constructs the HTTP server layer using Python FastAPI. It wires up database models, guardrail validation, agent negotiation, Razorpay API interactions, Meta WhatsApp webhooks, and UI REST endpoints into a unified backend service.

---

## Technical Specifications & Architecture

### 1. Seed Data Generator (`backend/seed_data.py`)
- Populates database with 3 realistic Indian SME overdue invoice records:
  - `inv_SME_001`: Apex Logistics Pvt Ltd - ₹50,000 (Overdue 5 days)
  - `inv_SME_002`: Vanguard Web Studios - ₹1,20,000 (Overdue 12 days)
  - `inv_SME_003`: GreenLeaf Organics - ₹35,000 (Overdue 2 days)

### 2. FastAPI Application Server (`backend/main.py`)
- **App Router Definitions**:
  - `GET /api/invoices`: Returns all master invoices with balance progress.
  - `GET /api/guardrails` / `POST /api/guardrails`: Fetch & update merchant negotiation rules.
  - `POST /api/chat/message`: Handles UI WhatsApp simulator message requests, returning agent message + visual trace payload.
  - `POST /api/chat/reset`: Resets simulator chat context.
  - `POST /api/webhooks/razorpay`: Idempotent Razorpay event handler (`payment.captured`, `invoice.partially_paid`).
  - `GET /api/webhooks/whatsapp` & `POST /api/webhooks/whatsapp`: Meta Cloud API verification & incoming message handler.
  - `GET /api/analytics`: Metrics endpoint (Total Overdue TPV, Recovered TPV, Conversion Rate).

---

## Verification Plan

### Automated Verification
- Run `python backend/test_submodule4.py`:
  1. Test FastAPI `TestClient` for `/api/invoices`, `/api/guardrails`, `/api/chat/message`, and `/api/analytics`.
  2. Verify JSON schema responses for frontend consumption.
