"""
Analytics Router
Endpoints for fetching aggregated metrics and recovery rates for the merchant dashboard.
"""

from fastapi import APIRouter, Depends

from backend.models.core import Merchant
from backend.core.auth import require_verified_merchant_bank
from backend.core.database import get_connection
from backend.services.guardrails import paise_to_inr

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

@router.get("")
async def get_analytics_overview(merchant: Merchant = Depends(require_verified_merchant_bank)):
    """Returns merchant-scoped key metrics: Total Overdue TPV, Recovered TPV, Recovery Rate %, Active Negotiations."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT 
        COALESCE(SUM(original_amount_paise), 0),
        COALESCE(SUM(paid_amount_paise), 0),
        COALESCE(SUM(remaining_amount_paise), 0)
    FROM master_invoices
    WHERE merchant_id = %s;
    """, (merchant.merchant_id,))
    row = cursor.fetchone()

    total_orig = row[0] or 0
    total_paid = row[1] or 0
    total_rem = row[2] or 0

    cursor.execute("""
    SELECT COUNT(*) 
    FROM master_invoices 
    WHERE status = 'NEGOTIATING' AND merchant_id = %s;
    """, (merchant.merchant_id,))
    active_neg_count = cursor.fetchone()[0]

    conn.close()

    recovery_rate_pct = round((total_paid / total_orig * 100.0), 2) if total_orig > 0 else 0.0

    return {
        "total_overdue_tpv_inr": paise_to_inr(total_orig),
        "recovered_tpv_inr": paise_to_inr(total_paid),
        "remaining_overdue_tpv_inr": paise_to_inr(total_rem),
        "recovery_rate_pct": min(100.0, recovery_rate_pct),
        "active_negotiations_count": active_neg_count
    }
