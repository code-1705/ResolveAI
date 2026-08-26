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
                        },
                        "invoice_scope": {
                            "type": "STRING",
                            "description": "The specific invoice_id (e.g., 'inv_SME_005') they are paying, OR the word 'ALL' if they are making an account-level payment towards their total balance."
                        }
                    },
                    "required": ["proposed_amount_inr", "extension_days", "invoice_scope"]
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

        # Itemized line item details for current invoice
        items_breakdown = []
        if getattr(invoice, 'items', None):
            for it in invoice.items:
                desc = it.get('item_description') or it.get('name') or 'Item/Service'
                qty = it.get('quantity', 1)
                unit_p = it.get('unit_price') or it.get('price') or 0.0
                tot_p = it.get('total_price') or (qty * unit_p)
                items_breakdown.append(f"  * {desc} (Qty: {qty}, Unit Price: ₹{unit_p:,.2f}, Total: ₹{tot_p:,.2f})")
        itemized_text = "\n".join(items_breakdown) if items_breakdown else "  * Full itemized details matching official invoice document."

        notes_str = f"  * Notes / Terms: {invoice.metadata.get('notes')}" if (getattr(invoice, 'metadata', None) and invoice.metadata.get('notes')) else ""

        return {
            "parts": [{
                "text": f"""
You are the Senior Accounts Receivable & Financial Collections Officer speaking directly with customer '{invoice.customer_name}'.
Your primary and sole objective is to RECOVER OVERDUE OUTSTANDING PAYMENTS and secure payment commitments.

YOU ARE NOT A GENERIC CUSTOMER SUPPORT BOT. You are a firm, professional, and authoritative collections relationship manager.

CURRENT ACTIVE INVOICE IN SESSION:
- Customer Name: {invoice.customer_name}
- Customer Phone: {invoice.customer_phone}
- Active Invoice ID: {invoice.invoice_id}
- Original Total Bill: ₹{invoice.original_amount_inr:,.2f}
- Outstanding Balance Remaining: ₹{invoice.remaining_amount_inr:,.2f}
- Today's Date: {today_date.isoformat()}
- Due Date Status: {due_status_str}
- {doc_instruction}

ITEMIZED PRODUCT & SERVICE LINE ITEMS ON THIS BILL:
{itemized_text}
{notes_str}

CUSTOMER COMPLETE ACCOUNT & TRANSACTION HISTORY:
- Total Lifetime Billed: ₹{profile['total_billed_inr']:,.2f}
- Total Paid To Date Across All Bills: ₹{profile['total_paid_to_date_inr']:,.2f}
- Total Outstanding Balance Remaining: ₹{profile['total_remaining_balance_inr']:,.2f}
- Total Overdue Invoices Count: {profile['overdue_invoices_count']} bill(s)

COMPLETE INVOICE LEDGER BREAKDOWN:
{inv_breakdown_text}

PAST TRANSACTION HISTORY LEDGER:
{tx_history_text}

MERCHANT POLICY GUARDRAILS (STRICT BOUNDARIES):
- Minimum Required Down Payment: {guardrails.min_partial_payment_pct}% of balance (₹{min_req_inr:,.2f})
- Maximum Allowed Due Date Extension: {guardrails.max_extension_days} days

CORE COLLECTIONS DIRECTIVES & RULES OF ENGAGEMENT:
1. FIRM POSTURE ON REFUSAL / NON-PAYMENT:
   - If the customer says "I won't pay", "I refuse", "I don't have money", "no", or resists payment:
     * NEVER apologize. NEVER say "We understand and want to make this easy" or "Is there anything else we can assist you with?".
     * Firmly remind them that this invoice ({invoice.invoice_id}) is legally binding for verified services/goods delivered.
     * Clearly state the consequences of continued non-payment: account freeze, suspension of future orders/services, negative impact on commercial credit rating, and formal escalation to legal recovery.
     * Demand an immediate resolution: either full payment today or an immediate minimum down payment of at least {guardrails.min_partial_payment_pct}% (₹{min_req_inr:,.2f}) to avoid escalation.

2. NEGOTIATIONS & PROPOSALS:
   - When the customer makes a partial payment proposal or extension request (e.g. "I can pay ₹3000", "I can pay 40%", "extend by 5 days"):
     * Call the 'propose_settlement_payment' tool to validate against merchant guardrails and generate the official Razorpay payment link.
     * If approved, provide the payment link and firmly instruct them to complete the payment immediately to lock in the terms.

3. DIRECT & AUTHORITATIVE COMMUNICATION:
   - Speak in the first-person plural ('We', 'Our Finance Department').
   - Never refer to yourself as an AI, bot, robot, or language model.
   - Keep messages direct, concise (2-4 sentences max), firm, and action-oriented towards payment.
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
        lock = get_session_lock(customer_phone)
        async with lock:
            self.session_manager.add_message(customer_phone, "user", customer_message)
            session = self.session_manager.get_or_create_session(customer_phone=customer_phone, invoice_id=invoice_id)

            if not invoice_id:
                profile = get_customer_financial_profile(customer_phone)
                pending = [inv for inv in profile["invoices"] if inv["status"] != "PAID"]
                if pending:
                    invoice_id = pending[0]["invoice_id"]
                elif profile["invoices"]:
                    invoice_id = profile["invoices"][0]["invoice_id"]

            invoice = get_invoice(invoice_id) if invoice_id else None
            guardrails = get_guardrails()

            if not invoice:
                err_text = f"No active invoices found for your account."
                self.session_manager.add_message(customer_phone, "agent", err_text)
                return {
                    "response_text": err_text,
                    "trace": {"thought": "No invoice found for customer", "guardrail_check": {"status": "ERROR"}}
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

            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={settings.GEMINI_API_KEY}"
            payload = {
                "systemInstruction": system_instruction,
                "contents": contents,
                "tools": TOOLS_DECLARATION
            }

            resp_text = None
            tool_executed = None
            payment_link_url = None
            payment_amount_paise = None
            guardrail_passed = True
            guardrail_check_status = "PASS"
            thought_summary = "Processed natural conversational turn with Gemini 3.6 Flash."

            try:
                resp = requests.post(url, headers={"Content-Type": "application/json"}, json=payload, timeout=8.0)
                if resp.status_code != 200:
                    print(f"[Gemini API Error 1]: {resp.status_code} - {resp.text}")
                resp.raise_for_status()
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
                                invoice_scope = fn_args.get("invoice_scope", invoice_id)

                                guardrail_passed, reason, guardrail_meta = self.guardrail_engine.validate_proposal(
                                    invoice_id=invoice_scope,
                                    proposed_amount_inr=proposed_amount_inr,
                                    extension_days=extension_days,
                                    customer_phone=invoice.customer_phone
                                )

                                if guardrail_passed:
                                    approved_amount_inr = guardrail_meta["approved_amount_inr"]
                                    approved_extension = guardrail_meta["approved_extension_days"]

                                    if invoice_scope == "ALL":
                                        ref_id = f"account_settlement_{invoice.customer_phone}_{len(session.messages)}"
                                        desc = f"Account Settlement for {invoice.customer_phone}"
                                    else:
                                        ref_id = f"ref_{session_id[:16]}_t{len(session.messages)}"
                                        desc = f"Settlement for Invoice {invoice_scope}"

                                    effective_days = min(approved_extension, 180)
                                    expiry_timestamp = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=effective_days)).replace(hour=23, minute=59, second=59).timestamp())

                                    # Convert INR to paise for Razorpay
                                    amount_in_paise = int(round(approved_amount_inr * 100))
                                    payment_amount_paise = amount_in_paise
                                    link_res = razorpay_client.create_payment_link(
                                        amount_in_paise=amount_in_paise,
                                        description=desc,
                                        customer_info={
                                            "name": invoice.customer_name,
                                            "phone": invoice.customer_phone,
                                            "invoice_id": invoice_scope
                                        },
                                        expiry_timestamp=expiry_timestamp,
                                        reference_id=ref_id
                                    )

                                    payment_link_url = link_res["short_url"]
                                    tool_executed = f"create_razorpay_payment_link(₹{approved_amount_inr:,.2f})"
                                    guardrail_check_status = "PASS"
                                    thought_summary = f"Approved settlement ₹{approved_amount_inr:,.2f} with link {payment_link_url}."

                                    fn_response_part = {
                                        "role": "user",
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
                                            f"Here is your secure payment link for ₹{approved_amount_inr:,.2f}: {payment_link_url}\n"
                                            "Once paid, your account balance will update instantly in real-time."
                                        )

                                else:
                                    suggested_inr = guardrail_meta.get("suggested_amount_inr", invoice.remaining_amount_inr * 0.3)
                                    suggested_ext = guardrail_meta.get("max_allowed_extension_days", 14)
                                    guardrail_check_status = "REJECTED"
                                    thought_summary = f"Proposal rejected ({reason}). Counter-offered ₹{suggested_inr:,.2f}."

                                    fn_response_part = {
                                        "role": "user",
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
                                    if resp2.status_code != 200:
                                        print(f"[Gemini API Error 2]: {resp2.status_code} - {resp2.text}")
                                    resp2.raise_for_status()
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

            # If Gemini returned empty text or fallback is needed:
            if not resp_text:
                if media_documents:
                    resp_text = f"Here are your official invoice documents for your review below. Please let me know if you would like to proceed with payment or discuss a settlement:"
                else:
                    if len(session.messages) > 1:
                        resp_text = "I apologize, but I am experiencing a temporary connection issue. Could you please wait a moment and try sending your message again?"
                    else:
                        resp_text = (
                            f"Hello {invoice.customer_name}! We are checking on your invoice '{invoice.invoice_id}' with a remaining balance of "
                            f"₹{invoice.remaining_amount_inr:,.2f} (Due: {invoice.due_date}). "
                            f"How can we best assist you with your account today?"
                        )


            # Record Agent Response
            self.session_manager.add_message(
                session_id=session_id,
                sender="agent",
                text=resp_text,
                metadata={
                    "tool_executed": tool_executed,
                    "payment_link_url": payment_link_url,
                    "payment_amount_paise": payment_amount_paise,
                    "guardrail_passed": guardrail_passed,
                    "media_documents": media_documents
                }
            )

            agent_metadata = {
                "tool_executed": tool_executed,
                "payment_link_url": payment_link_url,
                "payment_amount_paise": payment_amount_paise,
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
