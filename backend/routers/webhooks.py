"""
Webhooks Router
Exposes endpoints to receive asynchronous events from Razorpay and Meta.
"""

import json
from typing import Dict, Any

from fastapi import APIRouter, Request, BackgroundTasks, HTTPException, Query, Response

from backend.core.config import settings
from backend.integrations.razorpay import razorpay_client
from backend.services.webhooks import verify_meta_webhook, process_whatsapp_webhook, reconcile_payment_event
from backend.services.agent import agentic_negotiator
from backend.routers.events import broadcast_sse_event

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

async def background_razorpay_reconcile(payload: Dict[str, Any]):
    """Background task processing Razorpay payment reconciliation."""
    res = await reconcile_payment_event(payload)
    if res.get("status") == "reconciled":
        await broadcast_sse_event("payment_reconciled", res)

@router.post("/razorpay")
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

@router.get("/whatsapp")
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

@router.post("/whatsapp")
async def meta_whatsapp_webhook_receiver(request: Request, background_tasks: BackgroundTasks):
    """Meta WhatsApp Cloud API POST incoming message webhook receiver."""
    payload = await request.json()
    res = process_whatsapp_webhook(payload)

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
