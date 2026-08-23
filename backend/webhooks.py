import asyncio
import threading
import datetime
import re
from typing import Dict, Any, Tuple, Optional, List
from backend.config import settings
from backend.models import InvoiceStatus, PaymentLinkStatus
from backend.database import (
    get_invoice,
    get_invoices_by_phone,
    upsert_invoice,
    record_transaction,
    validate_fsm_transition,
    get_connection,
    get_merchant_by_id,
    log_financial_transaction
)
from backend.razorpay_client import razorpay_client
from backend.whatsapp_client import whatsapp_client
from backend.session_manager import session_manager
from backend.guardrails import paise_to_inr

import redis.asyncio as redis_async

# Redis Client Initialization
redis_client = None
if settings.REDIS_URL:
    try:
        redis_client = redis_async.from_url(settings.REDIS_URL)
    except Exception as e:
        pass

# Invoice Row Locks (Per invoice_id asyncio / thread Lock dictionary to prevent concurrent webhook race conditions)
INVOICE_ROW_LOCKS: Dict[str, asyncio.Lock] = {}
INVOICE_LOCK_INIT_MUTEX = threading.Lock()

class InvoiceLock:
    def __init__(self, invoice_id: str):
        self.invoice_id = invoice_id
        self.redis_lock = None
        self.memory_lock = None

        if redis_client:
            self.redis_lock = redis_client.lock(f"lock:invoice:{invoice_id}", timeout=30)
        else:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.get_event_loop()
            loop_id = id(loop)
            with INVOICE_LOCK_INIT_MUTEX:
                key = f"{loop_id}_{invoice_id}"
                if key not in INVOICE_ROW_LOCKS:
                    INVOICE_ROW_LOCKS[key] = asyncio.Lock()
                self.memory_lock = INVOICE_ROW_LOCKS[key]

    async def __aenter__(self):
        if self.redis_lock:
            await self.redis_lock.acquire(blocking=True)
        else:
            await self.memory_lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.redis_lock:
            await self.redis_lock.release()
        else:
            self.memory_lock.release()

def get_invoice_lock(invoice_id: str) -> InvoiceLock:
    """Returns a Distributed Redis Lock (or falls back to asyncio.Lock)."""
    return InvoiceLock(invoice_id)

# --- Meta WhatsApp Webhook Handlers ---

def verify_meta_webhook(mode: str, token: str, challenge: str) -> Tuple[bool, str]:
    """
    Handles GET /api/webhooks/whatsapp Meta verification handshake.
    Compares token against settings.META_VERIFY_TOKEN and returns (True, challenge).
    """
    if mode == "subscribe" and token == settings.META_VERIFY_TOKEN:
        return (True, challenge)
    return (False, "Invalid verification token or mode")

def process_whatsapp_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parses POST /api/webhooks/whatsapp incoming message payloads from Meta Graph API.
    Handles both 'text' messages and 'interactive' button/list selection replies.
    Executes phone-to-invoice multi-invoice routing.
    """
    try:
        entries = payload.get("entry", [])
        if not entries:
            return {"status": "no_entries"}

        changes = entries[0].get("changes", [])
        if not changes:
            return {"status": "no_changes"}

        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return {"status": "no_messages"}

        msg = messages[0]
        customer_phone = msg.get("from", "")
        msg_type = msg.get("type", "text")

        user_text = ""
        interactive_id = None

        if msg_type == "text":
            user_text = msg.get("text", {}).get("body", "").strip()
        elif msg_type == "interactive":
            interactive = msg.get("interactive", {})
            button_reply = interactive.get("button_reply", {})
            list_reply = interactive.get("list_reply", {})
            interactive_id = button_reply.get("id") or list_reply.get("id")
            user_text = button_reply.get("title") or list_reply.get("title") or "Interactive Selection"

        # Case A: User selected an invoice via Interactive Button reply (e.g. 'select_invoice_inv_SME_002')
        if interactive_id and interactive_id.startswith("select_invoice_"):
            invoice_id = interactive_id.replace("select_invoice_", "")
            composite_session_id = f"{customer_phone}_{invoice_id}"
            return {
                "status": "routed",
                "session_id": composite_session_id,
                "invoice_id": invoice_id,
                "customer_phone": customer_phone,
                "user_text": user_text,
                "is_interactive": True
            }

        # Case B: Standard text message -> Perform Multi-Invoice Phone Query
        all_invoices = get_invoices_by_phone(customer_phone)
        active_invoices = [
            inv for inv in all_invoices 
            if inv.status in (InvoiceStatus.UNPAID, InvoiceStatus.NEGOTIATING, InvoiceStatus.PARTIALLY_PAID)
        ]

        if len(active_invoices) == 1:
            target_inv = active_invoices[0]
            composite_session_id = f"{customer_phone}_{target_inv.invoice_id}"
            return {
                "status": "routed",
                "session_id": composite_session_id,
                "invoice_id": target_inv.invoice_id,
                "customer_phone": customer_phone,
                "user_text": user_text,
                "is_interactive": False
            }

        elif len(active_invoices) > 1:
            # Send Meta Interactive Button Message to user asking to pick invoice
            button_options = []
            for inv in active_invoices[:3]:  # Meta max 3 buttons
                button_options.append({
                    "id": f"select_invoice_{inv.invoice_id}",
                    "title": f"Invoice {inv.invoice_id}"
                })

            prompt_msg = (
                f"Hi! You have {len(active_invoices)} active overdue invoices. "
                "Which invoice would you like to resolve today?"
            )
            whatsapp_client.send_interactive_buttons(customer_phone, prompt_msg, button_options)

            return {
                "status": "multi_invoice_prompt_sent",
                "customer_phone": customer_phone,
                "active_invoice_count": len(active_invoices)
            }

        else:
            # 0 active invoices found
            whatsapp_client.send_text_message(
                customer_phone,
                "Thank you for reaching out to us! We did not find any active overdue invoices for your number. Please let us know if you need any assistance."
            )
            return {
                "status": "no_active_invoices",
                "customer_phone": customer_phone
            }

    except Exception as e:
        return {"status": "error", "error": str(e)}

# --- Razorpay Asynchronous Reconciler ---

async def reconcile_payment_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Asynchronous Payment Reconciler for Razorpay Webhooks.
    Supports BOTH Invoice-Level and Account-Level (FIFO) Multi-Bill Payments.
    """
    event = payload.get("event", "")
    payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
    payment_link_entity = payload.get("payload", {}).get("payment_link", {}).get("entity", {})

    razorpay_payment_id = payment_entity.get("id", "")
    razorpay_payment_link_id = payment_entity.get("payment_link_id") or payment_link_entity.get("id", "")
    amount_paise = (
        payment_entity.get("amount")
        or payment_link_entity.get("amount_paid")
        or payment_link_entity.get("amount")
        or 0
    )
    payment_method = payment_entity.get("method", "UPI").upper()

    notes = payment_entity.get("notes", {}) or payment_link_entity.get("notes", {})
    invoice_id = notes.get("invoice_id")
    customer_phone = notes.get("customer_phone")

    if not invoice_id and razorpay_payment_link_id:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT invoice_id FROM payment_links WHERE razorpay_payment_link_id = %s;", (razorpay_payment_link_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            invoice_id = row["invoice_id"]

    if not invoice_id:
        ref_id = payment_link_entity.get("reference_id", "")
        if "account_settlement" in ref_id:
            invoice_id = "ALL"
            parts_ref = ref_id.split("_")
            if len(parts_ref) >= 3:
                customer_phone = parts_ref[2]
        elif "_" in ref_id:
            parts_ref = ref_id.split("_")
            if len(parts_ref) >= 3:
                invoice_id = parts_ref[1] if parts_ref[1].startswith("inv_") else (parts_ref[2] if len(parts_ref) > 2 and parts_ref[2].startswith("inv_") else None)

    if not invoice_id or not razorpay_payment_id:
        return {"status": "ignored", "reason": "missing_invoice_id_or_payment_id"}

    # ==========================================
    # ACCOUNT LEVEL FIFO DISTRIBUTION (MULTI-BILL)
    # ==========================================
    if invoice_id == "ALL":
        if not customer_phone:
            return {"status": "error", "reason": "missing_customer_phone_for_account_payment"}
        
        lock = get_invoice_lock(f"account_{customer_phone}")
        async with lock:
            from psycopg2.extras import DictCursor
            conn = get_connection()
            cursor = conn.cursor(cursor_factory=DictCursor)
            clean_phone = customer_phone.replace(" ", "").replace("-", "")
            cursor.execute(
                "SELECT invoice_id FROM master_invoices WHERE REPLACE(REPLACE(customer_phone, ' ', ''), '-', '') = %s AND status != 'PAID' ORDER BY due_date ASC;",
                (clean_phone,)
            )
            rows = cursor.fetchall()
            conn.close()

            remaining_payment_paise = amount_paise
            distributed_invoices = []

            for r in rows:
                if remaining_payment_paise <= 0:
                    break
                
                inv_id = r["invoice_id"]
                invoice = get_invoice(inv_id)
                if not invoice or invoice.remaining_amount_paise <= 0:
                    continue
                
                unique_rzp_id = f"{razorpay_payment_id}_{inv_id}"
                amount_to_apply = min(remaining_payment_paise, invoice.remaining_amount_paise)
                
                success, is_dup = record_transaction(
                    invoice_id=inv_id,
                    razorpay_payment_id=unique_rzp_id,
                    razorpay_payment_link_id=razorpay_payment_link_id,
                    amount_paid_paise=amount_to_apply,
                    payment_method=payment_method
                )
                if is_dup:
                    continue
                
                new_paid = invoice.paid_amount_paise + amount_to_apply
                new_rem = invoice.original_amount_paise - new_paid
                target_status = InvoiceStatus.PAID if new_rem == 0 else InvoiceStatus.PARTIALLY_PAID
                
                invoice.paid_amount_paise = new_paid
                invoice.remaining_amount_paise = new_rem
                invoice.status = target_status
                upsert_invoice(invoice)
                
                distributed_invoices.append({"invoice_id": inv_id, "amount_applied": amount_to_apply, "status": target_status.value})
                remaining_payment_paise -= amount_to_apply

            if razorpay_payment_link_id:
                try:
                    conn_pl = get_connection()
                    cur_pl = conn_pl.cursor()
                    cur_pl.execute("UPDATE payment_links SET status = 'PAID' WHERE razorpay_payment_link_id = %s;", (razorpay_payment_link_id,))
                    conn_pl.commit()
                    conn_pl.close()
                except Exception as pl_err:
                    print(f"[Payment Link Status Update Error]: {pl_err}")
                try:
                    razorpay_client.cancel_payment_link(razorpay_payment_link_id)
                except Exception:
                    pass

            return {"status": "success", "type": "account_level", "distributed": distributed_invoices, "unallocated_paise": remaining_payment_paise}


    # ==========================================
    # SINGLE INVOICE LEVEL LOGIC (LEGACY)
    # ==========================================
    lock = get_invoice_lock(invoice_id)
    async with lock:
                
        invoice = get_invoice(invoice_id)
        if not invoice:
            return {"status": "error", "reason": f"Invoice '{invoice_id}' not found"}

        # 1. Idempotency Check
        conn_check = get_connection()
        cur_check = conn_check.cursor()
        cur_check.execute("SELECT id FROM transaction_ledger WHERE razorpay_payment_id = %s;", (razorpay_payment_id,))
        if cur_check.fetchone():
            conn_check.close()
            print(f"[Webhook Idempotency]: Payment {razorpay_payment_id} already recorded.")
            return {"status": "ignored", "reason": "duplicate_payment_id", "razorpay_payment_id": razorpay_payment_id}
        conn_check.close()

        # 2. Update Invoice State (Capped strictly at invoice original amount)
        new_paid_paise = min(invoice.original_amount_paise, invoice.paid_amount_paise + amount_paise)
        new_remaining_paise = max(0, invoice.original_amount_paise - new_paid_paise)
        target_status = InvoiceStatus.PAID if new_remaining_paise == 0 else InvoiceStatus.PARTIALLY_PAID
        
        invoice.paid_amount_paise = new_paid_paise
        invoice.remaining_amount_paise = new_remaining_paise
        invoice.status = target_status
        upsert_invoice(invoice)

        # 3. Retrieve Merchant Profile & Financial Split (99% Merchant, 1% Platform Take-Rate)
        conn_m = get_connection()
        cur_m = conn_m.cursor()
        cur_m.execute("SELECT merchant_id FROM master_invoices WHERE invoice_id = %s;", (invoice_id,))
        m_row = cur_m.fetchone()
        conn_m.close()
        m_id = m_row[0] if (m_row and m_row[0]) else "default_merchant"
        merchant = get_merchant_by_id(m_id)

        comm_pct = getattr(merchant, 'commission_pct', 1.0) or 1.0
        m_payout_pct = 100.0 - comm_pct
        merchant_share_paise = int(amount_paise * (m_payout_pct / 100.0))
        platform_fee_paise = amount_paise - merchant_share_paise

        # 4. Execute Automated Razorpay Route Split Transfer
        rzp_acc_id = getattr(merchant, 'razorpay_account_id', None) or f"acc_{m_id}"
        trf_res = razorpay_client.create_payment_transfer(
            payment_id=razorpay_payment_id,
            account_id=rzp_acc_id,
            amount_paise=merchant_share_paise,
            notes={"invoice_id": invoice_id, "merchant_id": m_id}
        )
        transfer_id = trf_res.get("id")
        is_transfer_successful = trf_res.get("success", True) if not razorpay_client.is_mock else True
        outflow_status = "TRANSFERRED" if is_transfer_successful and transfer_id else "FAILED"

        # 5. Record Double-Entry Ledger (Inflow Customer Payment & Outflow 99% Merchant Wire)
        log_financial_transaction(
            merchant_id=m_id,
            invoice_id=invoice_id,
            transaction_type="INFLOW_CUSTOMER_PAYMENT",
            gross_amount_paise=amount_paise,
            merchant_amount_paise=merchant_share_paise,
            platform_fee_paise=platform_fee_paise,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_transfer_id=transfer_id,
            razorpay_account_id=rzp_acc_id,
            bank_beneficiary_name=getattr(merchant, 'bank_beneficiary_name', None),
            bank_account_masked=f"••••••••{(getattr(merchant, 'bank_account_number', '') or '')[-4:]}",
            bank_ifsc=getattr(merchant, 'bank_ifsc', None),
            status="CAPTURED"
        )
        log_financial_transaction(
            merchant_id=m_id,
            invoice_id=invoice_id,
            transaction_type="OUTFLOW_MERCHANT_SETTLEMENT",
            gross_amount_paise=amount_paise,
            merchant_amount_paise=merchant_share_paise,
            platform_fee_paise=platform_fee_paise,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_transfer_id=transfer_id,
            razorpay_account_id=rzp_acc_id,
            bank_beneficiary_name=getattr(merchant, 'bank_beneficiary_name', None),
            bank_account_masked=f"••••••••{(getattr(merchant, 'bank_account_number', '') or '')[-4:]}",
            bank_ifsc=getattr(merchant, 'bank_ifsc', None),
            status=outflow_status
        )

        if razorpay_payment_link_id:
            try:
                conn_pl = get_connection()
                cur_pl = conn_pl.cursor()
                cur_pl.execute("UPDATE payment_links SET status = 'PAID' WHERE razorpay_payment_link_id = %s;", (razorpay_payment_link_id,))
                conn_pl.commit()
                conn_pl.close()
            except Exception:
                pass
            try:
                razorpay_client.cancel_payment_link(razorpay_payment_link_id)
            except Exception:
                pass

        # 6. Auto-Inject Confirmation Receipt into WhatsApp Chat Session
        if invoice.customer_phone:
            if new_remaining_paise == 0:
                receipt_msg = (
                    f"✅ *Payment Confirmed!* Thank you, {invoice.customer_name}.\n\n"
                    f"We have received your payment of *₹{amount_paise/100:,.2f}* for invoice `{invoice_id}` via Razorpay (Ref: `{razorpay_payment_id}`).\n\n"
                    "🎉 *Your invoice is now fully settled!*"
                )
            else:
                receipt_msg = (
                    f"✅ *Partial Payment Received!* Thank you, {invoice.customer_name}.\n\n"
                    f"We have credited *₹{amount_paise/100:,.2f}* towards invoice `{invoice_id}` via Razorpay.\n"
                    f"Remaining balance due: *₹{new_remaining_paise/100:,.2f}*."
                )
            
            session_manager.add_message(invoice.customer_phone, "agent", receipt_msg)
            
            # Broadcast real-time SSE event with chat update
            try:
                from backend.main import broadcast_sse_event
                await broadcast_sse_event("payment_reconciled", {
                    "invoice_id": invoice_id,
                    "customer_phone": invoice.customer_phone,
                    "amount_paid_inr": amount_paise / 100.0,
                    "remaining_inr": new_remaining_paise / 100.0,
                    "receipt_message": receipt_msg
                })
            except Exception as sse_err:
                print(f"[SSE Broadcast Notice]: {sse_err}")

        return {"status": "success", "invoice_id": invoice_id, "new_status": invoice.status.value}
