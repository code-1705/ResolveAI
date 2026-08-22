# Implementation Plan - Submodule 3: LLM Negotiation Agent & Session Manager

## Overview
Submodule 3 implements the natural language negotiation brain of **Resolve.ai**. It manages conversation state via `ChatSession`, constructs prompts with multi-turn history, invokes LLM Tool Calling (with Rupee input schema), filters proposals through the `GuardrailEngine`, and outputs visual Agent Traces.

---

## Technical Specifications & Architecture

### 1. Chat Session Context Manager (`backend/session_manager.py`)
- **`SessionManager`**:
  - `get_or_create_session(session_id: str, invoice_id: str)`: Loads or initializes chat session mapped to WhatsApp sender ID.
  - `add_message(session_id: str, sender: str, text: str, metadata: dict)`: Records chat turns.
  - `get_recent_history(session_id: str, limit: int = 5)`: Loads rolling N-turn message context for LLM prompt generation.

### 2. LLM Negotiation Agent & Tool Engine (`backend/agent.py`)
- **`AgenticNegotiator`**:
  - **Tool Definitions**:
    - `create_razorpay_payment_link(invoice_id: str, amount_in_inr: float, description: str, extension_days: int)`
  - **Execution Pipeline**:
    1. Pulls last 5 messages from `SessionManager`.
    2. Constructs prompt with merchant guardrails (`min_partial_payment_pct`, `max_extension_days`) and current invoice remaining balance.
    3. Executes LLM tool call or fallback negotiator engine.
    4. Passes proposed payment terms to `GuardrailEngine.validate_proposal()`:
       - **PASS**: Converts `amount_in_inr` -> `amount_in_paise`, calls `RazorpayClient.create_payment_link()`, attaches link to response.
       - **REJECT**: Generates polite counter-offer explaining merchant minimum limits.
    5. Outputs structured **Agent Trace Payload** (`thought`, `guardrail_check`, `currency_conversion`, `tool_call`, `response_text`).

---

## Verification Plan

### Automated Verification
- Run `python backend/test_submodule3.py`:
  1. Verify multi-turn chat history retention across 3 turns.
  2. Verify 10% payment request triggers Guardrail `REJECT` and counter-offer without link creation.
  3. Verify 40% payment request triggers Guardrail `PASS`, `inr_to_paise` conversion, and payment link creation.
