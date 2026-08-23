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
    get_customer_all_invoices,
    get_customer_financial_profile,
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
        today_date = datetime.date.today()
        try:
            due_date_obj = datetime.datetime.strptime(invoice.due_date, "%Y-%m-%d").date()
            days_until_due = (due_date_obj - today_date).days
            if days_until_due < 0:
                due_status_str = f"OVERDUE by {abs(days_until_due)} days (Due Date was {invoice.due_date})"
            elif days_until_due == 0:
                due_status_str = f"DUE TODAY ({invoice.due_date})"
            else:
                due_status_str = f"Due in {days_until_due} days ({invoice.due_date})"
        except Exception:
            due_status_str = f"Due Date: {invoice.due_date}"

        min_req_inr = round(invoice.remaining_amount_inr * (guardrails.min_partial_payment_pct / 100.0), 2)

        # Retrieve FULL customer financial profile (All Invoices + Transaction History + CDN links)
        profile = get_customer_financial_profile(invoice.customer_phone)

        doc_url_for_this_inv = None
        inv_breakdown_lines = []
        for item in profile["invoices"]:
            doc_str = f" (Bill CDN Link: {item['document_url']})" if item.get("document_url") else ""
            if item["invoice_id"] == invoice.invoice_id and item.get("document_url"):
                doc_url_for_this_inv = item["document_url"]
            inv_breakdown_lines.append(
                f"  * Invoice {item['invoice_id']}: Original ₹{item['original_amount_inr']:,.2f} | Paid ₹{item['paid_amount_inr']:,.2f} | Remaining ₹{item['remaining_amount_inr']:,.2f} | Status: {item['status']} | Due: {item['due_date']}{doc_str}"
            )
        inv_breakdown_text = "\n".join(inv_breakdown_lines)

        tx_lines = []
        for t in profile["transactions"]:
            tx_lines.append(
                f"  * Date: {t['created_at']} | Invoice: {t['invoice_id']} | Amount Paid: ₹{t['amount_paid_inr']:,.2f} | Method: {t['payment_method']} | Ref: {t['razorpay_payment_id']}"
            )
        tx_history_text = "\n".join(tx_lines) if tx_lines else "  No past payments recorded yet."

        doc_instruction = f"Official Invoice Bill Document CDN Link: {doc_url_for_this_inv}" if doc_url_for_this_inv else "Invoice document available in session chat bubble above."

        return {
            "parts": [{
                "text": f"""
You are Resolve.ai, a warm, empathetic, interactive, and human-like AI financial specialist speaking on behalf of your merchant with customer '{invoice.customer_name}'.

CURRENT ACTIVE INVOICE IN SESSION:
- Customer Name: {invoice.customer_name}
- Customer Phone: {invoice.customer_phone}
- Active Invoice ID: {invoice.invoice_id}
- Original Total Bill: ₹{invoice.original_amount_inr:,.2f}
- Outstanding Balance Remaining: ₹{invoice.remaining_amount_inr:,.2f}
- Today's Date: {today_date.isoformat()}
- Due Date Status: {due_status_str}
- {doc_instruction}

CUSTOMER COMPLETE ACCOUNT & TRANSACTION HISTORY (ALL INVOICES BELONGING TO THIS CLIENT):
- Total Lifetime Billed: ₹{profile['total_billed_inr']:,.2f}
- Total Paid To Date Across All Bills: ₹{profile['total_paid_to_date_inr']:,.2f}
- Total Outstanding Balance Remaining Across All Bills: ₹{profile['total_remaining_balance_inr']:,.2f}
- Total Pending/Unpaid Invoices Count: {profile['pending_invoices_count']} bill(s)
- Total Overdue Invoices Count: {profile['overdue_invoices_count']} bill(s)

COMPLETE INVOICE LEDGER BREAKDOWN:
{inv_breakdown_text}

PAST TRANSACTION HISTORY LEDGER:
{tx_history_text}

MERCHANT POLICY GUARDRAILS:
- Minimum Required Down Payment: {guardrails.min_partial_payment_pct}% of balance (₹{min_req_inr:,.2f})
- Maximum Allowed Due Date Extension: {guardrails.max_extension_days} days
- Tone Style: {guardrails.tone}

HUMAN CONVERSATION GUIDELINES:
1. Speak like a friendly, helpful human specialist over WhatsApp. Be empathetic, conversational, and interactive.
2. Answer the customer's specific questions directly using their full account context and transaction history above.
3. If the customer asks "how many bills are pending?", "how much money do I owe totally?", "do I have other invoices?", provide their complete account summary showing total remaining balance across all bills.
4. If the customer asks about past payments ("how much did I pay?", "show payment history", "did my payment go through?"), reference their exact past transactions above with dates, amounts, and payment methods.
5. If the customer asks to view or receive their invoice bill (e.g. "send me the invoice", "give me the bill", "send bill", "show invoice"), check if an official document link exists above. If a document CDN link exists, state warmly "Here is your official invoice document below:". If NO document CDN link is present for that invoice, inform them politely: "We do not have a PDF document attached for this invoice at this time, but your remaining balance is ₹" followed by their exact balance.
6. If the customer makes ANY payment proposal (e.g. "I can pay 40%", "give me 10 days", "I can pay 15,000 next week"), you MUST invoke the 'propose_settlement_payment' tool.
7. Keep responses concise, warm, and end with a helpful question.
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
        lock = get_session_lock(session_id)
        async with lock:
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

            # Check for Text Payment Claims
            lower_msg = customer_message.lower()
            import re
            text_payment_keywords = [r"\bpaid\b", r"\btransferred\b", r"\bsent\b", "done via upi", "payment complete", "upi paid"]
            is_text_payment_claim = any(re.search(k, lower_msg) for k in text_payment_keywords) and not re.search(r'\b(can i|will pay|how about|could i|if i|unpaid|not paid|pending)\b', lower_msg)

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
                    candidates = res_data.get("candidates", [])
                    if candidates:
                        candidate = candidates[0].get("content", {})
                        parts = candidate.get("parts", [])

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
                                    "I understand your concern. I have escalated your case to a senior manager "
                                    "who will contact you directly to resolve this."
                                )
                                guardrail_check_status = "ESCALATED"
                                thought_summary = f"Customer escalated: {fn_args.get('reason', 'hostile dialogue')}"

                            elif fn_name == "propose_settlement_payment":
                                proposed_amount_inr = float(fn_args.get("proposed_amount_inr", 0))
                                extension_days = int(fn_args.get("extension_days", guardrails.max_extension_days))

                                guardrail_passed, reason, guardrail_meta = self.guardrail_engine.validate_proposal(
                                    invoice_id=invoice_id,
                                    proposed_amount_inr=proposed_amount_inr,
                                    extension_days=extension_days
                                )

                                if guardrail_passed:
                                    approved_amount_inr = guardrail_meta["approved_amount_inr"]
                                    approved_extension = guardrail_meta["approved_extension_days"]

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

                                    second_contents = list(contents)
                                    second_contents.append(candidate)
                                    second_contents.append(fn_response_part)

                                    second_payload = {
                                        "systemInstruction": system_instruction,
                                        "contents": second_contents
                                    }

                                    resp2 = requests.post(url, headers={"Content-Type": "application/json"}, json=second_payload, timeout=6.0)
                                    if resp2.status_code == 200:
                                        res2_data = resp2.json()
                                        c2_parts = res2_data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                                        for p in c2_parts:
                                            if "text" in p:
                                                resp_text = p["text"].strip()
                                                break

                                    if not resp_text:
                                        resp_text = (
                                            f"Great news! Your payment proposal of ₹{approved_amount_inr:,.2f} has been approved. "
                                            f"You can make your payment directly here: {payment_link_url}"
                                        )

                                else:
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
                                        res2_data = resp2.json()
                                        c2_parts = res2_data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                                        for p in c2_parts:
                                            if "text" in p:
                                                resp_text = p["text"].strip()
                                                break

                                    if not resp_text:
                                        resp_text = (
                                            f"Thank you for your offer. However, {reason}. "
                                            f"Based on merchant policy, I can approve an initial payment of ₹{suggested_inr:,.2f} "
                                            f"with a date extension up to {suggested_ext} days. Would you like me to generate a payment link?"
                                        )

                        else:
                            # Direct text response from Gemini (greetings, questions, conversational Q&A)
                            for part in parts:
                                if "text" in part:
                                    resp_text = part["text"].strip()
                                    break
            except Exception as e:
                print(f"[Gemini Agent Error]: {e}")

            # Fallback text if LLM call failed completely
            if not resp_text:
                resp_text = (
                    f"Hello {invoice.customer_name}! Your invoice '{invoice.invoice_id}' has a balance of "
                    f"₹{invoice.remaining_amount_inr:,.2f} (Due: {invoice.due_date}). "
                    f"How can I assist you with your payment today?"
                )

            # Check if customer asked for invoice document or if media documents should be attached
            media_documents = []
            doc_keywords = ["invoice", "bill", "pdf", "receipt", "document", "send me", "show me"]
            if any(k in customer_message.lower() for k in doc_keywords):
                profile = get_customer_financial_profile(customer_phone)
                for item in profile["invoices"]:
                    if item.get("document_url"):
                        media_documents.append({
                            "invoice_id": item["invoice_id"],
                            "filename": f"{item['invoice_id']}_bill.pdf",
                            "url": item["document_url"]
                        })

            # Record Agent Response
            self.session_manager.add_message(
                session_id=session_id,
                sender="agent",
                text=resp_text,
                metadata={
                    "tool_executed": tool_executed,
                    "payment_link_url": payment_link_url,
                    "guardrail_passed": guardrail_passed,
                    "media_documents": media_documents
                }
            )

            agent_metadata = {
                "tool_executed": tool_executed,
                "payment_link_url": payment_link_url,
                "guardrail_passed": guardrail_passed,
                "media_documents": media_documents
            }

            return {
                "response_text": resp_text,
                "metadata": agent_metadata,
                "trace": {
                    "thought": thought_summary,
                    "guardrail_check": {"status": guardrail_check_status},
                    "verified_invoice_status": invoice.status.value,
                    "remaining_balance_inr": invoice.remaining_amount_inr
                }
            }

agentic_negotiator = AgenticNegotiator()
