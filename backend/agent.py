import asyncio
import datetime
import re
from typing import Dict, Any, Tuple, Optional, List
from backend.config import settings
from backend.models import MasterInvoice, InvoiceStatus, PaymentLinkStatus
from backend.database import (
    get_invoice,
    get_guardrails,
    get_connection
)
from backend.guardrails import GuardrailEngine, inr_to_paise, paise_to_inr
from backend.session_manager import SessionManager, session_manager, get_session_lock
from backend.razorpay_client import razorpay_client

class AgenticNegotiator:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.DATABASE_PATH
        self.guardrail_engine = GuardrailEngine(db_path=self.db_path)
        self.session_manager = SessionManager(db_path=self.db_path)

    async def process_customer_message(
        self,
        session_id: str,
        invoice_id: str,
        customer_phone: str,
        customer_message: str
    ) -> Dict[str, Any]:
        """
        Main Agentic Negotiation Entrypoint.
        Enforces 5 Production Safeguards:
        1. Atomic Per-Session Concurrency Lock (async with lock:).
        2. Anti-Hallucination Fund Confirmation Directives.
        3. Untrusted LLM Gateway (GuardrailEngine hard floor & ceiling check).
        4. Reference ID Payload Idempotency (ref_{session_id[:20]}_t{turn}).
        5. Detailed Inspectable Agent Trace Payload.
        """
        # 1. Acquire Per-Session Lock
        lock = get_session_lock(session_id)
        async with lock:
            # Load or create chat session
            session = self.session_manager.get_or_create_session(session_id, invoice_id, customer_phone)
            
            # Record customer message turn
            self.session_manager.add_message(session_id, "user", customer_message)
            
            # Load recent 5-turn chat history
            history = self.session_manager.get_recent_history(session_id, limit=5)
            turn_count = len(session.messages)

            # Load active invoice & guardrails
            invoice = get_invoice(invoice_id, self.db_path)
            guardrails = get_guardrails(self.db_path)

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

            # 3. Parse Proposal Parameters (Amount & Extension Days)
            proposed_amount_inr, extension_days = self._parse_proposal_intent(customer_message, invoice, guardrails)

            # 4. Evaluate Proposal against GuardrailEngine Safety Gateway
            guardrail_passed, reason, guardrail_meta = self.guardrail_engine.validate_proposal(
                invoice_id=invoice_id,
                proposed_amount_inr=proposed_amount_inr,
                extension_days=extension_days
            )

            tool_executed = None
            payment_link_url = None
            payment_link_id = None
            currency_conversion_meta = {}

            if guardrail_passed:
                # 5. Guardrail Approved -> Generate Razorpay Payment Link!
                approved_amount_inr = guardrail_meta["approved_amount_inr"]
                approved_amount_paise = guardrail_meta["approved_amount_paise"]
                approved_extension = guardrail_meta["approved_extension_days"]

                currency_conversion_meta = {
                    "approved_amount_inr": approved_amount_inr,
                    "approved_amount_paise": approved_amount_paise
                }

                # Compute Unix Expiry Timestamp (Capped at 180 Days)
                effective_days = min(approved_extension, 180)
                expiry_timestamp = int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=effective_days)).replace(hour=23, minute=59, second=59).timestamp())

                # Generate reference_id payload idempotency key (max 40 chars)
                reference_id = f"ref_{session_id[:20]}_t{turn_count}"[:40]

                try:
                    # Call Razorpay Payment Links API
                    link_res = razorpay_client.create_payment_link(
                        amount_in_paise=approved_amount_paise,
                        description=f"Partial payment plan for Invoice {invoice_id}",
                        customer_info={"name": invoice.customer_name, "phone": customer_phone},
                        expiry_timestamp=expiry_timestamp,
                        reference_id=reference_id
                    )

                    tool_executed = "create_razorpay_payment_link"
                    payment_link_url = link_res.get("short_url")
                    payment_link_id = link_res.get("id")

                    # Persist Payment Link Record in DB
                    self._record_payment_link(invoice_id, payment_link_id, approved_amount_paise, reference_id)

                    resp_text = (
                        f"Great news! Your proposed payment of ₹{approved_amount_inr:,.2f} is approved. "
                        f"I have generated a custom Razorpay payment link for you:\n\n"
                        f"👉 {payment_link_url}\n\n"
                        f"This link is valid for {effective_days} days. Completing this payment will update your balance immediately."
                    )

                except Exception as e:
                    # Graceful Tool Exception Recovery
                    resp_text = (
                        f"I approved your proposal of ₹{approved_amount_inr:,.2f}, but encountered a temporary connection "
                        f"issue generating your Razorpay link. Please try sending your request again in a moment."
                    )
                    tool_executed = f"create_razorpay_payment_link_FAILED: {str(e)}"

            else:
                # Guardrail REJECTED -> Hard Block API call & Issue Polite Counter-Offer
                suggested_inr = guardrail_meta.get("suggested_amount_inr", invoice.remaining_amount_inr * 0.3)
                suggested_ext = guardrail_meta.get("max_allowed_extension_days", 14)
                
                resp_text = (
                    f"Thank you for your offer. However, {reason} "
                    f"Based on merchant policy, I can approve an initial payment of ₹{suggested_inr:,.2f} "
                    f"with a date extension of up to {suggested_ext} days. Would you like me to generate a payment link for ₹{suggested_inr:,.2f}?"
                )

            # Record Agent Response in ChatSession
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

            # Construct Detailed Inspectable Agent Trace Payload
            trace_payload = {
                "thought": f"Evaluated customer proposal ₹{proposed_amount_inr:,.2f} with {extension_days} days extension against guardrails.",
                "guardrail_check": {
                    "status": "PASS" if guardrail_passed else "REJECT",
                    "reason": reason,
                    "min_required_pct": guardrails.min_partial_payment_pct,
                    "min_required_inr": paise_to_inr(int(round(invoice.remaining_amount_paise * (guardrails.min_partial_payment_pct / 100.0)))),
                    "remaining_balance_inr": invoice.remaining_amount_inr
                },
                "currency_conversion": currency_conversion_meta,
                "tool_executed": tool_executed,
                "payment_link_id": payment_link_id,
                "payment_link_url": payment_link_url,
                "response_text": resp_text
            }

            return {
                "response_text": resp_text,
                "trace": trace_payload
            }

    def _parse_proposal_intent(
        self,
        message: str,
        invoice: MasterInvoice,
        guardrails: Any
    ) -> Tuple[float, int]:
        """
        Parses numerical payment proposals (amounts or percentages) and requested extension days from user text.
        """
        msg = message.lower()
        
        # 1. Parse Percentage (e.g., "40%", "30 percent")
        pct_match = re.search(r'(\d+)\s*(%|percent)', msg)
        proposed_amount_inr = 0.0

        if pct_match:
            pct_val = float(pct_match.group(1))
            proposed_amount_inr = round(invoice.remaining_amount_inr * (pct_val / 100.0), 2)
        else:
            # 2. Parse Absolute INR Amount (e.g. "20000", "₹20,000", "20k", "20000 rupees")
            k_match = re.search(r'(\d+(?:\.\d+)?)\s*k\b', msg)
            if k_match:
                proposed_amount_inr = float(k_match.group(1)) * 1000.0
            else:
                amt_match = re.search(r'(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{3})*|\d+)(?:\.\d+)?', msg)
                if amt_match:
                    raw_str = amt_match.group(1).replace(",", "")
                    val = float(raw_str)
                    if val > 100:  # Ignore small numbers like dates
                        proposed_amount_inr = val

        # Default fallback if no amount detected -> 40% of remaining balance
        if proposed_amount_inr <= 0:
            proposed_amount_inr = round(invoice.remaining_amount_inr * 0.40, 2)

        # 3. Parse Extension Days (e.g., "7 days", "next week", "14 days")
        days_match = re.search(r'(\d+)\s*(?:days?|date extension)', msg)
        extension_days = guardrails.max_extension_days

        if days_match:
            extension_days = int(days_match.group(1))
        elif "next week" in msg or "7 days" in msg:
            extension_days = 7
        elif "2 weeks" in msg or "14 days" in msg:
            extension_days = 14

        return (proposed_amount_inr, extension_days)

    def _record_payment_link(
        self,
        invoice_id: str,
        payment_link_id: str,
        amount_paise: int,
        reference_id: str
    ):
        """Records created payment link in the database."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor.execute("""
        INSERT INTO payment_links (invoice_id, razorpay_payment_link_id, amount_paise, status, reference_id, created_at)
        VALUES (?, ?, ?, 'ACTIVE', ?, ?);
        """, (invoice_id, payment_link_id, amount_paise, reference_id, created_at))
        conn.commit()
        conn.close()

agentic_negotiator = AgenticNegotiator()
