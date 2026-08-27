"""
Guardrails Router
Endpoints for retrieving and updating automated negotiation boundaries.
"""

from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.models.core import Merchant, MerchantGuardrails
from backend.core.auth import require_verified_merchant_bank
from backend.core.database import get_guardrails, update_guardrails
from backend.routers.events import broadcast_sse_event

router = APIRouter(prefix="/api/guardrails", tags=["guardrails"])

class GuardrailsUpdateRequest(BaseModel):
    merchant_id: Optional[str] = None
    min_partial_payment_pct: float
    max_extension_days: int
    max_split_installments: int = 3
    auto_discount_waiver_pct: float = 5.0
    tone: str = "professional_empathetic"

@router.get("")
async def get_merchant_guardrails(merchant: Merchant = Depends(require_verified_merchant_bank)):
    """Returns current active merchant negotiation guardrails."""
    g = get_guardrails(merchant.merchant_id)
    return {
        "id": g.id,
        "merchant_id": g.merchant_id,
        "min_partial_payment_pct": g.min_partial_payment_pct,
        "max_extension_days": g.max_extension_days,
        "max_split_installments": g.max_split_installments,
        "auto_discount_waiver_pct": g.auto_discount_waiver_pct,
        "tone": g.tone
    }

@router.post("")
async def save_merchant_guardrails(req: GuardrailsUpdateRequest, merchant: Merchant = Depends(require_verified_merchant_bank)):
    """Updates merchant guardrail policies and broadcasts SSE event."""
    m_id = merchant.merchant_id
    g = MerchantGuardrails(
        merchant_id=m_id,
        min_partial_payment_pct=req.min_partial_payment_pct,
        max_extension_days=req.max_extension_days,
        max_split_installments=req.max_split_installments,
        auto_discount_waiver_pct=req.auto_discount_waiver_pct,
        tone=req.tone
    )
    updated = update_guardrails(g, merchant_id=m_id)
    res = {
        "merchant_id": updated.merchant_id,
        "min_partial_payment_pct": updated.min_partial_payment_pct,
        "max_extension_days": updated.max_extension_days,
        "max_split_installments": updated.max_split_installments,
        "auto_discount_waiver_pct": updated.auto_discount_waiver_pct,
        "tone": updated.tone
    }
    await broadcast_sse_event("guardrails_updated", res)
    return res
