import asyncio
import threading
from typing import Dict, Any, Tuple, Optional, List
from backend.config import settings
from backend.models import InvoiceStatus, PaymentLinkStatus
from backend.database import (
    get_invoice,
    get_invoices_by_phone,
    upsert_invoice,
    record_transaction,
    validate_fsm_transition,
    get_connection
)
from backend.razorpay_client import razorpay_client
from backend.whatsapp_client import whatsapp_client

# Invoice Row Locks (Per invoice_id asyncio / thread Lock dictionary to prevent concurrent webhook race conditions)
INVOICE_ROW_LOCKS: Dict[str, asyncio.Lock] = {}
INVOICE_LOCK_INIT_MUTEX = threading.Lock()

def get_invoice_lock(invoice_id: str) -> asyncio.Lock:
    """Returns an asyncio.Lock bound to the current running event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    loop_id = id(loop)
    with INVOICE_LOCK_INIT_MUTEX:
        key = f"{loop_id}_{invoice_id}"
        if key not in INVOICE_ROW_LOCKS:
            INVOICE_ROW_LOCKS[key] = asyncio.Lock()
        return INVOICE_ROW_LOCKS[key]

# --- Meta WhatsApp Webhook Handlers ---

def verify_meta_webhook(mode: str, token: str, challenge: str) -> Tuple[bool, str]:
    """
    Handles GET /api/webhooks/whatsapp Meta verification handshake.
    Compares token against settings.META_VERIFY_TOKEN and returns (True, challenge).
    """
    if mode == "subscribe" and token == settings.META_VERIFY_TOKEN:
        return (True, challenge)
    return (False, "Invalid verification token or mode")

def process_whatsapp_webhook(payload: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
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
        all_invoices = get_invoices_by_phone(customer_phone, db_path)
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
                "Thank you for contacting Resolve.ai. No active overdue invoices were found for your number."
            )
            return {
                "status": "no_active_invoices",
                "customer_phone": customer_phone
            }

    except Exception as e:
        return {"status": "error", "error": str(e)}

# --- Razorpay Asynchronous Reconciler ---

async def reconcile_payment_event(payload: Dict[str, Any], db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Asynchronous Payment Reconciler for Razorpay Webhooks.
    Executes strictly inside an invoice row lock to prevent race conditions.
    Enforces 5 Invariants:
    1. Raw HMAC verification (performed prior to calling reconciler).
    2. Invoice Row Mutex Lock (async with lock:).
    3. UNIQUE(razorpay_payment_id) Idempotency check.
    4. Exact Integer Paise Balance Math: new_remaining = max(0, original - new_paid).
    5. FSM State Transition & Superseded Payment Link Cancellation.
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

    # Extract invoice_id from notes, description, or payment_links table
    notes = payment_entity.get("notes", {}) or payment_link_entity.get("notes", {})
    invoice_id = notes.get("invoice_id")

    if not invoice_id and razorpay_payment_link_id:
        # Query DB for linked invoice_id
        conn = get_connection(db_path or settings.DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT invoice_id FROM payment_links WHERE razorpay_payment_link_id = ?;", (razorpay_payment_link_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            invoice_id = row["invoice_id"]

    if not invoice_id:
        # Default fallback match from reference_id if present
        ref_id = payment_link_entity.get("reference_id", "")
        if "_" in ref_id:
            # ref_{session_id}_{turn} -> reference parsing
            parts = ref_id.split("_")
            if len(parts) >= 3:
                invoice_id = parts[2]

    if not invoice_id or not razorpay_payment_id:
        return {"status": "ignored", "reason": "missing_invoice_id_or_payment_id"}

    # Acquire Async Invoice Row Lock
    lock = get_invoice_lock(invoice_id)
    async with lock:
        invoice = get_invoice(invoice_id, db_path)
        if not invoice:
            return {"status": "error", "reason": f"Invoice '{invoice_id}' not found"}

        # 1. Idempotency Check via TransactionLedger
        success, is_duplicate = record_transaction(
            invoice_id=invoice_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_payment_link_id=razorpay_payment_link_id,
            amount_paid_paise=amount_paise,
            payment_method=payment_method,
            db_path=db_path
        )

        if is_duplicate:
            return {"status": "ignored", "reason": "duplicate_payment_id", "razorpay_payment_id": razorpay_payment_id}

        # 2. Execute Balance Math Strictly Inside Row Lock
        new_paid_paise = invoice.paid_amount_paise + amount_paise
        new_remaining_paise = max(0, invoice.original_amount_paise - new_paid_paise)

        # 3. Determine FSM Status
        target_status = InvoiceStatus.PAID if new_remaining_paise == 0 else InvoiceStatus.PARTIALLY_PAID

        # 4. Enforce FSM Transition Invariant
        validate_fsm_transition(invoice.status.value, target_status.value)

        # 5. Persist Invoice Updates
        invoice.paid_amount_paise = new_paid_paise
        invoice.remaining_amount_paise = new_remaining_paise
        invoice.status = target_status
        upsert_invoice(invoice, db_path)

        # 6. Deactivate Superseded Payment Links
        if razorpay_payment_link_id:
            try:
                razorpay_client.cancel_payment_link(razorpay_payment_link_id)
            except Exception:
                pass  # Ignore mock / API cancel errors gracefully

        return {
            "status": "reconciled",
            "invoice_id": invoice_id,
            "razorpay_payment_id": razorpay_payment_id,
            "amount_paid_paise": amount_paise,
            "new_remaining_paise": new_remaining_paise,
            "new_status": target_status.value
        }
