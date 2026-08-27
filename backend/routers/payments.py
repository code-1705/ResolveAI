"""
Payments Router
Endpoints for handling Razorpay checkout order creation and verification.
"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.core.config import settings
from backend.integrations.razorpay import razorpay_client
from backend.core.database import get_invoice
from backend.services.webhooks import reconcile_payment_event
from backend.routers.events import broadcast_sse_event

router = APIRouter(prefix="/api", tags=["payments"])

class CreateOrderRequest(BaseModel):
    amount_in_paise: int
    invoice_id: Optional[str] = None
    receipt: Optional[str] = None

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    invoice_id: Optional[str] = None

@router.post("/create-order")
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
            "key_id": settings.RAZORPAY_KEY_ID,
            "invoice_id": req.invoice_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create Razorpay Order: {str(e)}")

@router.post("/verify-payment")
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
        invoice = get_invoice(req.invoice_id)
        if invoice and invoice.remaining_amount_paise > 0:
            # Securely fetch actual payment amount from Razorpay to handle partial payments correctly
            payment_details = razorpay_client.get_payment(req.razorpay_payment_id)
            actual_paid_amount = payment_details.get("amount") or invoice.remaining_amount_paise

            mock_webhook_payload = {
                "event": "payment.captured",
                "payload": {
                    "payment": {
                        "entity": {
                            "id": req.razorpay_payment_id,
                            "order_id": req.razorpay_order_id,
                            "amount": actual_paid_amount,
                            "method": "CARD",
                            "notes": {"invoice_id": req.invoice_id}
                        }
                    }
                }
            }
            reconcile_res = await reconcile_payment_event(mock_webhook_payload)
            if reconcile_res.get("status") == "reconciled":
                await broadcast_sse_event("payment_reconciled", reconcile_res)

    return {
        "status": "success",
        "message": "Payment verified and invoice updated successfully",
        "razorpay_payment_id": req.razorpay_payment_id,
        "razorpay_order_id": req.razorpay_order_id
    }
