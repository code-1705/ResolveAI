import asyncio
import json
import logging
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, BackgroundTasks, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.config import settings
from backend.models import MasterInvoice, MerchantGuardrails, InvoiceStatus
from backend.database import (
    init_db,
    get_guardrails,
    update_guardrails,
    get_invoice,
    upsert_invoice,
    get_connection
)
from backend.seed_data import seed_database
from backend.guardrails import GuardrailEngine, paise_to_inr, inr_to_paise
from backend.razorpay_client import razorpay_client
from backend.webhooks import verify_meta_webhook, process_whatsapp_webhook, reconcile_payment_event
from backend.agent import agentic_negotiator
from backend.session_manager import session_manager

# --- Real-time SSE Broadcast System ---
EVENT_QUEUES: List[asyncio.Queue] = []

async def broadcast_sse_event(event_type: str, data: Dict[str, Any]):
    """Broadcasts a real-time event to all connected SSE clients."""
    payload_str = json.dumps({"type": event_type, "data": data})
    for q in list(EVENT_QUEUES):
        try:
            await q.put(payload_str)
        except Exception:
            pass

from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- Active Reconciliation Cron ---
scheduler = AsyncIOScheduler()

@scheduler.scheduled_job('interval', minutes=30)
async def active_reconciliation_job():
    """Polls Razorpay for missed webhooks every 30 minutes."""
    try:
        print("[Cron] Running Active Reconciliation...")
        payments = razorpay_client.get_recent_payments()
        for p in payments:
            if p.get("status") == "captured":
                # Synthesize a webhook payload and reconcile it
                mock_webhook = {
                    "event": "payment.captured",
                    "payload": {
                        "payment": {
                            "entity": p
                        }
                    }
                }
                await reconcile_payment_event(mock_webhook, settings.DATABASE_PATH)
        print("[Cron] Active Reconciliation Complete.")
    except Exception as e:
        print(f"[Cron] Active Reconciliation Failed: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Seed database and initialize tables
    seed_database(settings.DATABASE_PATH)
    scheduler.start()
    yield
    # Shutdown
    scheduler.shutdown()
    EVENT_QUEUES.clear()

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Autonomous Collections Agent for Razorpay SMEs",
    lifespan=lifespan
)

# --- Explicit CORS Security Configuration ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Request / Response Models ---
class GuardrailsUpdateRequest(BaseModel):
    min_partial_payment_pct: float
    max_extension_days: int
    max_split_installments: int = 3
    auto_discount_waiver_pct: float = 5.0
    tone: str = "professional_empathetic"

class ChatMessageRequest(BaseModel):
    session_id: Optional[str] = None
    invoice_id: str
    customer_phone: str
    message: str

class CreateInvoiceRequest(BaseModel):
    customer_name: str
    customer_phone: str
    original_amount_inr: float
    due_date: str

class ChatResetRequest(BaseModel):
    session_id: str

class CreateOrderRequest(BaseModel):
    amount_in_paise: int
    invoice_id: Optional[str] = None
    receipt: Optional[str] = None

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    invoice_id: Optional[str] = None

# --- 1. Real-time SSE Events Endpoint ---
@app.get("/api/events")
async def sse_events_endpoint(request: Request):
    """
    Server-Sent Events (SSE) stream.
    Broadcasts real-time payment captured, invoice reconciled, and chat updates directly to React UI clients.
    """
    queue = asyncio.Queue()
    EVENT_QUEUES.append(queue)

    async def event_generator():
        try:
            # Yield initial connection ping
            yield f"data: {json.dumps({'type': 'connected', 'data': {'message': 'SSE Live Stream Active'}})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data_str = await asyncio.wait_for(queue.get(), timeout=5.0)
                    yield f"data: {data_str}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat ping allows frequent disconnect checks to prevent memory leaks
                    yield f"data: {json.dumps({'type': 'ping', 'data': {}})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in EVENT_QUEUES:
                EVENT_QUEUES.remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

# --- 2. Master Invoice Endpoints ---
@app.get("/api/invoices")
async def list_invoices():
    """Returns list of all master invoices with balance progress and status."""
    conn = get_connection(settings.DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM master_invoices ORDER BY due_date ASC;")
    rows = cursor.fetchall()
    conn.close()

    invoices = []
    for r in rows:
        orig = r["original_amount_paise"]
        paid = r["paid_amount_paise"]
        rem = r["remaining_amount_paise"]
        invoices.append({
            "invoice_id": r["invoice_id"],
            "customer_name": r["customer_name"],
            "customer_phone": r["customer_phone"],
            "original_amount_inr": paise_to_inr(orig),
            "paid_amount_inr": paise_to_inr(paid),
            "remaining_amount_inr": paise_to_inr(rem),
            "original_amount_paise": orig,
            "paid_amount_paise": paid,
            "remaining_amount_paise": rem,
            "due_date": r["due_date"],
            "status": r["status"]
        })
    return invoices

@app.get("/api/invoices/{invoice_id}")
async def get_invoice_detail(invoice_id: str):
    """Returns detailed information for a single invoice."""
    inv = get_invoice(invoice_id, settings.DATABASE_PATH)
    if not inv:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found.")
    return {
        "invoice_id": inv.invoice_id,
        "customer_name": inv.customer_name,
        "customer_phone": inv.customer_phone,
        "original_amount_inr": inv.original_amount_inr,
        "paid_amount_inr": inv.paid_amount_inr,
        "remaining_amount_inr": inv.remaining_amount_inr,
        "due_date": inv.due_date,
        "status": inv.status.value
    }

@app.post("/api/invoices")
async def create_invoice(req: CreateInvoiceRequest):
    """Creates a new master invoice with integer paise currency conversion."""
    conn = get_connection(settings.DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM master_invoices;")
    count = cursor.fetchone()[0]
    conn.close()

    invoice_id = f"inv_SME_{count + 1:03d}"
    paise_amount = inr_to_paise(req.original_amount_inr)

    inv = MasterInvoice(
        invoice_id=invoice_id,
        customer_name=req.customer_name,
        customer_phone=req.customer_phone,
        original_amount_paise=paise_amount,
        paid_amount_paise=0,
        remaining_amount_paise=paise_amount,
        due_date=req.due_date,
        status=InvoiceStatus.UNPAID
    )

    upsert_invoice(inv, settings.DATABASE_PATH)

    res = {
        "invoice_id": inv.invoice_id,
        "customer_name": inv.customer_name,
        "customer_phone": inv.customer_phone,
        "original_amount_inr": inv.original_amount_inr,
        "paid_amount_inr": 0.0,
        "remaining_amount_inr": inv.original_amount_inr,
        "due_date": inv.due_date,
        "status": inv.status.value
    }

    await broadcast_sse_event("invoice_created", res)
    return res

# --- 3. Merchant Guardrail Control Endpoints ---
@app.get("/api/guardrails")
async def get_merchant_guardrails():
    """Returns current active merchant negotiation guardrails."""
    g = get_guardrails(settings.DATABASE_PATH)
    return {
        "id": g.id,
        "min_partial_payment_pct": g.min_partial_payment_pct,
        "max_extension_days": g.max_extension_days,
        "max_split_installments": g.max_split_installments,
        "auto_discount_waiver_pct": g.auto_discount_waiver_pct,
        "tone": g.tone
    }

@app.post("/api/guardrails")
async def save_merchant_guardrails(req: GuardrailsUpdateRequest):
    """Updates merchant guardrail policies and broadcasts SSE event."""
    g = MerchantGuardrails(
        id=1,
        min_partial_payment_pct=req.min_partial_payment_pct,
        max_extension_days=req.max_extension_days,
        max_split_installments=req.max_split_installments,
        auto_discount_waiver_pct=req.auto_discount_waiver_pct,
        tone=req.tone
    )
    updated = update_guardrails(g, settings.DATABASE_PATH)
    res = {
        "min_partial_payment_pct": updated.min_partial_payment_pct,
        "max_extension_days": updated.max_extension_days,
        "max_split_installments": updated.max_split_installments,
        "auto_discount_waiver_pct": updated.auto_discount_waiver_pct,
        "tone": updated.tone
    }
    await broadcast_sse_event("guardrails_updated", res)
    return res

# --- 4. Chat Simulator & Session Endpoints ---
@app.get("/api/chat/history")
async def get_chat_history(
    invoice_id: str = Query(...),
    customer_phone: str = Query(...)
):
    """
    Returns full chat session message history.
    Auto-initializes session with an outbound initial agent reminder message if brand new.
    """
    session_id = f"{customer_phone}_{invoice_id}"
    session = session_manager.get_or_create_session(session_id, invoice_id, customer_phone)
    return {
        "session_id": session.session_id,
        "invoice_id": session.invoice_id,
        "customer_phone": session.customer_phone,
        "messages": [
            {
                "sender": m.sender,
                "text": m.text,
                "timestamp": m.timestamp,
                "metadata": m.metadata
            } for m in session.messages
        ]
    }

@app.post("/api/chat/message")
async def send_chat_message(req: ChatMessageRequest):
    """
    Processes incoming messages from the WhatsApp simulator UI.
    Invokes AgenticNegotiator, returns response text & visual audit trace, and broadcasts SSE event.
    """
    session_id = req.session_id or f"{req.customer_phone}_{req.invoice_id}"
    
    agent_res = await agentic_negotiator.process_customer_message(
        session_id=session_id,
        invoice_id=req.invoice_id,
        customer_phone=req.customer_phone,
        customer_message=req.message
    )

    out_data = {
        "session_id": session_id,
        "invoice_id": req.invoice_id,
        "response_text": agent_res["response_text"],
        "trace": agent_res["trace"]
    }
    
    await broadcast_sse_event("chat_message_processed", out_data)
    return out_data

@app.post("/api/chat/reset")
async def reset_chat_session(req: ChatResetRequest):
    """Resets chat history for a session."""
    conn = get_connection(settings.DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE chat_sessions SET messages_json = '[]' WHERE session_id = ?;", (req.session_id,))
    conn.commit()
    conn.close()
    return {"status": "reset", "session_id": req.session_id}

# --- Razorpay Standard Web Checkout Endpoints ---
@app.post("/api/create-order")
async def create_checkout_order(req: CreateOrderRequest):
    """
    Creates a Razorpay Standard Checkout Order.
    Enforces minimum 100 paise (₹1.00) validation.
    """
    if req.amount_in_paise < 100:
        raise HTTPException(status_code=400, detail="Amount must be at least 100 paise (₹1.00).")

    notes = {}
    if req.invoice_id:
        notes["invoice_id"] = req.invoice_id

    try:
        order = razorpay_client.create_order(
            amount_in_paise=req.amount_in_paise,
            receipt=req.receipt,
            notes=notes
        )
        return {
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "invoice_id": req.invoice_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create Razorpay Order: {str(e)}")

@app.post("/api/verify-payment")
async def verify_checkout_payment(req: VerifyPaymentRequest):
    """
    Verifies Razorpay Standard Checkout HMAC-SHA256 Payment Signature.
    Algorithm: HMAC-SHA256(order_id + "|" + payment_id, KEY_SECRET)
    If valid: Reconciles invoice balance, updates FSM status, and emits SSE event.
    If invalid: Returns 400 Bad Request and does NOT mark invoice as paid.
    """
    if not req.razorpay_order_id or not req.razorpay_payment_id or not req.razorpay_signature:
        raise HTTPException(status_code=400, detail="Missing required payment verification fields.")

    valid = razorpay_client.verify_payment_signature(
        razorpay_order_id=req.razorpay_order_id,
        razorpay_payment_id=req.razorpay_payment_id,
        razorpay_signature=req.razorpay_signature
    )

    if not valid:
        raise HTTPException(status_code=400, detail="Signature verification failed. Invalid payment signature.")

    # Payment Verified! Reconcile invoice balance if invoice_id is present
    if req.invoice_id:
        invoice = get_invoice(req.invoice_id, settings.DATABASE_PATH)
        if invoice and invoice.remaining_amount_paise > 0:
            mock_webhook_payload = {
                "event": "payment.captured",
                "payload": {
                    "payment": {
                        "entity": {
                            "id": req.razorpay_payment_id,
                            "order_id": req.razorpay_order_id,
                            "amount": invoice.remaining_amount_paise,
                            "method": "CARD",
                            "notes": {"invoice_id": req.invoice_id}
                        }
                    }
                }
            }
            reconcile_res = await reconcile_payment_event(mock_webhook_payload, db_path=settings.DATABASE_PATH)
            if reconcile_res.get("status") == "reconciled":
                await broadcast_sse_event("payment_reconciled", reconcile_res)

    return {
        "status": "success",
        "message": "Payment verified and invoice updated successfully",
        "razorpay_payment_id": req.razorpay_payment_id,
        "razorpay_order_id": req.razorpay_order_id
    }

# --- 5. Webhook Endpoints (Razorpay & Meta) ---

async def background_razorpay_reconcile(payload: Dict[str, Any]):
    """Background task processing Razorpay payment reconciliation."""
    res = await reconcile_payment_event(payload, db_path=settings.DATABASE_PATH)
    if res.get("status") == "reconciled":
        await broadcast_sse_event("payment_reconciled", res)

@app.post("/api/webhooks/razorpay")
async def razorpay_webhook_endpoint(request: Request, background_tasks: BackgroundTasks):
    """
    Asynchronous Non-Blocking Razorpay Payment Webhook Receiver.
    1. Reads raw_body bytes.
    2. Verifies HMAC-SHA256 signature.
    3. Enqueues background reconciliation task.
    4. Immediately returns HTTP 200 OK (<100ms) to eliminate retry storms.
    """
    raw_bytes = await request.body()
    sig_header = request.headers.get("X-Razorpay-Signature", "")

    if sig_header:
        valid = razorpay_client.verify_webhook_signature(raw_bytes, sig_header)
        if not valid:
            raise HTTPException(status_code=400, detail="Invalid Razorpay HMAC signature.")
    elif settings.ENVIRONMENT == "production":
        raise HTTPException(status_code=400, detail="Missing Razorpay signature header.")

    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    background_tasks.add_task(background_razorpay_reconcile, payload)
    return {"status": "ok"}

@app.get("/api/webhooks/whatsapp")
async def meta_whatsapp_webhook_verification(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge")
):
    """Meta WhatsApp Cloud API GET verification handshake endpoint."""
    valid, challenge = verify_meta_webhook(hub_mode, hub_token, hub_challenge)
    if valid:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Meta verification failed.")

async def background_process_whatsapp_message(session_id: str, invoice_id: str, customer_phone: str, user_text: str):
    """Background task executing LLM negotiation for incoming WhatsApp messages."""
    await agentic_negotiator.process_customer_message(
        session_id=session_id,
        invoice_id=invoice_id,
        customer_phone=customer_phone,
        customer_message=user_text
    )

@app.post("/api/webhooks/whatsapp")
async def meta_whatsapp_webhook_receiver(request: Request, background_tasks: BackgroundTasks):
    """Meta WhatsApp Cloud API POST incoming message webhook receiver."""
    payload = await request.json()
    res = process_whatsapp_webhook(payload, db_path=settings.DATABASE_PATH)
    
    if res.get("status") == "routed":
        # Safely enqueue LLM negotiator as a FastAPI BackgroundTask
        session_id = res["session_id"]
        invoice_id = res["invoice_id"]
        customer_phone = res["customer_phone"]
        user_text = res["user_text"]

        background_tasks.add_task(
            background_process_whatsapp_message,
            session_id,
            invoice_id,
            customer_phone,
            user_text
        )

    return {"status": "ok"}

# --- 6. Analytics & Metrics Endpoint ---
@app.get("/api/analytics")
async def get_analytics_overview():
    """Returns key metrics: Total Overdue TPV, Recovered TPV, Recovery Rate %, Active Negotiations."""
    conn = get_connection(settings.DATABASE_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT SUM(original_amount_paise), SUM(paid_amount_paise), SUM(remaining_amount_paise) FROM master_invoices;")
    row = cursor.fetchone()

    total_orig = row[0] or 0
    total_paid = row[1] or 0
    total_rem = row[2] or 0

    cursor.execute("SELECT COUNT(*) FROM master_invoices WHERE status = 'NEGOTIATING';")
    active_neg_count = cursor.fetchone()[0]

    conn.close()

    recovery_rate_pct = round((total_paid / total_orig * 100.0), 2) if total_orig > 0 else 0.0

    return {
        "total_overdue_tpv_inr": paise_to_inr(total_orig),
        "recovered_tpv_inr": paise_to_inr(total_paid),
        "remaining_overdue_tpv_inr": paise_to_inr(total_rem),
        "recovery_rate_pct": recovery_rate_pct,
        "active_negotiations_count": active_neg_count
    }
