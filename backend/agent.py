import asyncio
import datetime
import time
import re
import json
import requests
from typing import Dict, Any, Tuple, Optional, List
from backend.config import settings
from backend.models import MasterInvoice, InvoiceStatus, PaymentLinkStatus, ChatMessage
from backend.database import (
    get_invoice,
    get_guardrails,
    upsert_invoice,
    get_connection
)
from backend.guardrails import GuardrailEngine, inr_to_paise, paise_to_inr
from backend.session_manager import SessionManager, session_manager, get_session_lock
from backend.razorpay_client import razorpay_client

TOOLS_DECLARATION = [
    {
        "functionDeclarations": [
            {
                "name": "propose_settlement_payment",
                "description": "Call this tool whenever the customer proposes a partial payment amount/percentage or requests a due date extension. Evaluates merchant guardrails and generates a Razorpay payment link if approved.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "proposed_amount_inr": {
                            "type": "NUMBER",
                            "description": "The proposed initial payment amount in INR (numeric float)."
                        },
                        "extension_days": {
                            "type": "INTEGER",
                            "description": "The requested due date extension in days (numeric int, e.g. 7, 14)."
                        }
                    },
                    "required": ["proposed_amount_inr", "extension_days"]
                }
            },
            {
                "name": "escalate_to_human",
                "description": "Call this tool when the customer is extremely hostile, threatens legal action, disputes the invoice validity entirely, or demands human management.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "reason": {
                            "type": "STRING",
                            "description": "Reason for human escalation."
                        }
                    },
                    "required": ["reason"]
                }
            }
        ]
    }
]

class AgenticNegotiator:
    def __init__(self):
        self.guardrail_engine = GuardrailEngine()
        self.session_manager = SessionManager()

    def _build_system_instruction(self, invoice: MasterInvoice, guardrails: Any) -> Dict[str, Any]:
        min_req_inr = round(invoice.remaining_amount_inr * (guardrails.min_partial_payment_pct / 100.0), 2)
        return {
            "parts": [{
                "text": f"""
You are Resolve.ai, an empathetic, highly professional automated debt collection assistant for Indian SMEs.
You are conversing via WhatsApp with customer '{invoice.customer_name}'.

INVOICE SUMMARY:
- Invoice ID: {invoice.invoice_id}
- Customer Name: {invoice.customer_name}
- Original Bill Amount: ₹{invoice.original_amount_inr:,.2f}
- Remaining Balance: ₹{invoice.remaining_amount_inr:,.2f}
- Due Date: {invoice.due_date}

MERCHANT POLICY GUARDRAILS:
- Minimum Initial Payment: {guardrails.min_partial_payment_pct}% of remaining balance (Minimum ₹{min_req_inr:,.2f})
- Maximum Allowed Extension: {guardrails.max_extension_days} days
- Persona Tone: {guardrails.tone}

CRITICAL INSTRUCTIONS:
1. Speak naturally, warmly, and concisely (2 to 4 sentences). Stay strictly in character as a helpful Indian SME financial advisor.
2. NEVER issue or promise a payment link or specific agreement directly in text without calling the 'propose_settlement_payment' tool.
3. If the customer makes ANY payment proposal (e.g. "I can pay 40%", "I will pay 20k next week", "give me 10 days", "can I pay half now?"), you MUST call the 'propose_settlement_payment' tool with the proposed amount in INR and requested extension days.
4. If the customer expresses inability to pay or asks what options exist, warmly present the merchant's available options (split payments starting at {guardrails.min_partial_payment_pct}% or extensions up to {guardrails.max_extension_days} days).
5. If the customer claims they ALREADY paid or sent money via UPI, remind them that payments are verified automatically via Razorpay webhooks and state their current verified balance.
6. If the customer is extremely hostile or disputes the bill entirely, call the 'escalate_to_human' tool.
"""
            }]
        }

    def _build_gemini_contents(self, messages: List[ChatMessage]) -> List[Dict[str, Any]]:
        contents = []
        for msg in messages:
            role = "user" if msg.sender == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg.text}]
            })
        return contents

    async def process_customer_message(
        self,
        session_id: str,
        invoice_id: str,
        customer_phone: str,
        customer_message: str
    ) -> Dict[str, Any]:
        """
        Main Agentic Negotiation Entrypoint using Native Gemini 2.5 Flash Multi-Turn Chat & Function Calling.
        """
        lock = get_session_lock(session_id)
        async with lock:
            # 1. Load chat session & invoice
            session = self.session_manager.get_or_create_session(session_id, invoice_id, customer_phone)
            self.session_manager.add_message(session_id, "user", customer_message)

            invoice = get_invoice(invoice_id)
            guardrails = get_guardrails()

            if not invoice:
                err_text = f"Invoice '{invoice_id}' not found."
                self.session_manager.add_message(session_id, "agent", err_text)
                return {
                    "response_text": err_text,
                    "trace": {"thought": "Invoice lookup failed", "guardrail_check": {"status": "ERROR"}}
                }

            # 2. Check for Text Payment Claims (Anti-Hallucination Directive)
            lower_msg = customer_message.lower()
            text_payment_keywords = ["paid", "transferred", "sent", "done via upi", "payment complete", "upi paid"]
            is_text_payment_claim = any(k in lower_msg for k in text_payment_keywords) and not re.search(r'\b(can i|will pay|how about|could i|if i)\b', lower_msg)

            if is_text_payment_claim:
                if invoice.status == InvoiceStatus.PAID:
                    resp_text = f"Thank you! Your invoice '{invoice_id}' is fully paid and settled."
                elif invoice.status == InvoiceStatus.PARTIALLY_PAID:
                    resp_text = (
                        f"Thank you! We have recorded partial payments totaling ₹{invoice.paid_amount_inr:,.2f}. "
                        f"Your remaining balance is ₹{invoice.remaining_amount_inr:,.2f}."
                    )
                else:
                    resp_text = (
                        f"Thank you for reaching out! Resolve.ai reconciles funds automatically via Razorpay webhooks. "
                        f"Your current invoice status is {invoice.status.value} with ₹{invoice.remaining_amount_inr:,.2f} remaining. "
                        "As soon as Razorpay confirms the transaction, your balance will update instantly."
                    )

                self.session_manager.add_message(session_id, "agent", resp_text)
                return {
                    "response_text": resp_text,
                    "trace": {
                        "thought": "Customer made text payment claim. Checked verified DB invoice status without hallucinating receipt.",
                        "guardrail_check": {"status": "PASS", "rule": "anti_hallucination_fund_check"},
                        "verified_invoice_status": invoice.status.value,
                        "remaining_balance_inr": invoice.remaining_amount_inr
                    }
                }

            # 3. Native Gemini 2.5 Flash Multi-Turn Chat Payload
            system_instruction = self._build_system_instruction(invoice, guardrails)
            contents = self._build_gemini_contents(session.messages)

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
            payload = {
                "systemInstruction": system_instruction,
                "contents": contents,
                "tools": TOOLS_DECLARATION
            }

            resp_text = None
            tool_executed = None
            payment_link_url = None
            guardrail_passed = True
            guardrail_check_status = "PASS"
            thought_summary = "Processed natural conversational turn with Gemini 2.5 Flash."

            try:
                resp = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=8.0)
                if resp.status_code == 200:
                    res_data = resp.json()
                    candidate = res_data["candidates"][0]["content"]
                    parts = candidate.get("parts", [])

                    # Check for Function Calls (Tools)
                    function_call = None
                    for part in parts:
                        if "functionCall" in part:
                            function_call = part["functionCall"]
                            break

                    if function_call:
                        fn_name = function_call["name"]
                        fn_args = function_call.get("args", {})

                        if fn_name == "escalate_to_human":
                            invoice.requires_human_attention = True
                            upsert_invoice(invoice)
                            resp_text = (
                                "I understand your frustration. I have escalated your case to a human agent "
                                "who will review this and get back to you shortly."
                            )
                            guardrail_check_status = "ESCALATED"
                            thought_summary = f"Customer escalated: {fn_args.get('reason', 'hostile dialogue')}"

                        elif fn_name == "propose_settlement_payment":
                            proposed_amount_inr = float(fn_args.get("proposed_amount_inr", 0))
                            extension_days = int(fn_args.get("extension_days", guardrails.max_extension_days))

                            # Run Python Guardrail Gateway
                            guardrail_passed, reason, guardrail_meta = self.guardrail_engine.validate_proposal(
                                invoice_id=invoice_id,
                                proposed_amount_inr=proposed_amount_inr,
                                extension_days=extension_days
                            )

                            if guardrail_passed:
                                approved_amount_inr = guardrail_meta["approved_amount_inr"]
                                approved_extension = guardrail_meta["approved_extension_days"]

                                # Generate Razorpay Payment Link
                                ref_id = f"ref_{session_id[:16]}_t{len(session.messages)}"
                                effective_days = min(approved_extension, 180)
                                expiry_timestamp = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=effective_days)).replace(hour=23, minute=59, second=59).timestamp())

                                link_res = razorpay_client.create_payment_link(
                                    invoice_id=invoice.invoice_id,
                                    customer_name=invoice.customer_name,
                                    customer_phone=invoice.customer_phone,
                                    amount_inr=approved_amount_inr,
                                    description=f"Settlement for Invoice {invoice.invoice_id}",
                                    expire_by_timestamp=expiry_timestamp,
                                    reference_id=ref_id
                                )

                                payment_link_url = link_res["short_url"]
                                tool_executed = f"create_razorpay_payment_link(₹{approved_amount_inr:,.2f})"
                                guardrail_check_status = "PASS"
                                thought_summary = f"Approved settlement ₹{approved_amount_inr:,.2f} with link {payment_link_url}."

                                # Second Pass to Gemini: Provide Function Result
                                fn_response_part = {
                                    "role": "function",
                                    "parts": [{
                                        "functionResponse": {
                                            "name": "propose_settlement_payment",
                                            "response": {
                                                "status": "APPROVED",
                                                "approved_amount_inr": approved_amount_inr,
                                                "payment_link_url": payment_link_url,
                                                "instructions": f"The proposal was APPROVED. Confirm ₹{approved_amount_inr:,.2f} and include the link: {payment_link_url}"
                                            }
                                        }
                                    }]
                                }

                                # Append model's function call & function response
                                second_contents = list(contents)
                                second_contents.append(candidate)
                                second_contents.append(fn_response_part)

                                second_payload = {
                                    "systemInstruction": system_instruction,
                                    "contents": second_contents
                                }

                                resp2 = requests.post(url, headers={"Content-Type": "application/json"}, json=second_payload, timeout=6.0)
                                if resp2.status_code == 200:
                                    resp_text = resp2.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

                                if not resp_text:
                                    resp_text = (
                                        f"Great news! Your payment proposal of ₹{approved_amount_inr:,.2f} has been approved. "
                                        f"You can make your payment directly here: {payment_link_url}"
                                    )

                            else:
                                # Guardrail REJECTED
                                suggested_inr = guardrail_meta.get("suggested_amount_inr", invoice.remaining_amount_inr * 0.3)
                                suggested_ext = guardrail_meta.get("max_allowed_extension_days", 14)
                                guardrail_check_status = "REJECTED"
                                thought_summary = f"Proposal rejected ({reason}). Counter-offered ₹{suggested_inr:,.2f}."

                                fn_response_part = {
                                    "role": "function",
                                    "parts": [{
                                        "functionResponse": {
                                            "name": "propose_settlement_payment",
                                            "response": {
                                                "status": "REJECTED",
                                                "reason": reason,
                                                "suggested_amount_inr": suggested_inr,
                                                "suggested_extension_days": suggested_ext,
                                                "instructions": f"Proposal REJECTED ({reason}). Politely counter-offer ₹{suggested_inr:,.2f} with up to {suggested_ext} days extension."
                                            }
                                        }
                                    }]
                                }

                                second_contents = list(contents)
                                second_contents.append(candidate)
                                second_contents.append(fn_response_part)

                                second_payload = {
                                    "systemInstruction": system_instruction,
                                    "contents": second_contents
                                }

                                resp2 = requests.post(url, headers={"Content-Type": "application/json"}, json=second_payload, timeout=6.0)
                                if resp2.status_code == 200:
                                    resp_text = resp2.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

                                if not resp_text:
                                    resp_text = (
                                        f"Thank you for your offer. However, {reason}. "
                                        f"Based on merchant policy, I can approve an initial payment of ₹{suggested_inr:,.2f} "
                                        f"with a date extension up to {suggested_ext} days. Would you like me to generate a payment link?"
                                    )

                    else:
                        # Direct text response from Gemini (greetings, general Q&A)
                        if parts and "text" in parts[0]:
                            resp_text = parts[0]["text"].strip()
            except Exception as e:
                print(f"[Gemini Agent Error]: {e}")

            # Fallback text if LLM call failed
            if not resp_text:
                resp_text = (
                    f"Hello! I am Resolve.ai assistant for invoice '{invoice.invoice_id}'. "
                    f"Your remaining balance is ₹{invoice.remaining_amount_inr:,.2f} (Due: {invoice.due_date}). "
                    f"How can I assist you with your payment today?"
                )

            # Record Agent Response
            self.session_manager.add_message(
                session_id=session_id,
                sender="agent",
                text=resp_text,
                metadata={
                    "tool_executed": tool_executed,
                    "payment_link_url": payment_link_url,
                    "guardrail_passed": guardrail_passed
                }
            )

            return {
                "response_text": resp_text,
                "trace": {
                    "thought": thought_summary,
                    "guardrail_check": {"status": guardrail_check_status},
                    "verified_invoice_status": invoice.status.value,
                    "remaining_balance_inr": invoice.remaining_amount_inr
                }
            }

agentic_negotiator = AgenticNegotiator()
