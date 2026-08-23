from typing import Tuple, Dict, Any, Optional
from backend.config import settings
from backend.database import get_guardrails, get_invoice
from backend.models import MerchantGuardrails, MasterInvoice

def inr_to_paise(amount_in_inr: float) -> int:
    """
    Deterministically converts Rupee amounts to exact integer paise.
    Example: 20000.50 INR -> 2000050 paise.
    Eliminates binary floating-point representation drift.
    """
    return int(round(amount_in_inr * 100.0))

def paise_to_inr(amount_in_paise: int) -> float:
    """
    Converts integer paise back to human-readable Rupee float rounded to 2 decimals.
    """
    return round(amount_in_paise / 100.0, 2)

class GuardrailEngine:
    def __init__(self):
        pass

    def validate_proposal(
        self,
        invoice_id: str,
        proposed_amount_inr: float,
        extension_days: int
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Deterministically evaluates a client negotiation proposal against merchant guardrails and platform bounds.

        Enforces 4 Invariant Bounds:
        1. Integer Paise Conversion (Zero Float Drift)
        2. Lower Floor Bound: proposed_amount_paise >= min_required_paise
        3. Upper Ceiling Bound: proposed_amount_paise <= remaining_amount_paise
        4. Razorpay Platform 180-Day Extension Limit: extension_days <= min(max_extension_days, 180)

        Returns: (is_valid: bool, reason: str, counter_offer: dict)
        """
        guardrails = get_guardrails()
        invoice = get_invoice(invoice_id)

        if not invoice:
            return (False, f"Invoice '{invoice_id}' not found.", {})

        if invoice.remaining_amount_paise <= 0:
            return (False, f"Invoice '{invoice_id}' is already fully paid or settled.", {})

        # 1. Currency Conversion
        proposed_amount_paise = inr_to_paise(proposed_amount_inr)

        # 2. Lower Floor Bound Calculation
        min_required_paise = int(round(invoice.remaining_amount_paise * (guardrails.min_partial_payment_pct / 100.0)))

        # 3. Razorpay Platform Expiry Cap (Max 180 Days / 6 Months)
        effective_max_extension = min(guardrails.max_extension_days, 180)

        # Counter offer default template
        counter_offer = {
            "suggested_amount_inr": paise_to_inr(min_required_paise),
            "suggested_amount_paise": min_required_paise,
            "max_allowed_extension_days": effective_max_extension,
            "min_required_pct": guardrails.min_partial_payment_pct
        }

        # Check 1: Lower Floor Check
        if proposed_amount_paise < min_required_paise:
            reason = (
                f"Proposed initial payment ₹{proposed_amount_inr:,.2f} is below the merchant's "
                f"minimum threshold of {guardrails.min_partial_payment_pct}% (₹{paise_to_inr(min_required_paise):,.2f})."
            )
            return (False, reason, counter_offer)

        # Check 2: Upper Ceiling Check
        if proposed_amount_paise > invoice.remaining_amount_paise:
            reason = (
                f"Proposed payment ₹{proposed_amount_inr:,.2f} exceeds the outstanding remaining balance "
                f"of ₹{invoice.remaining_amount_inr:,.2f}."
            )
            return (False, reason, counter_offer)

        # Check 3: Extension Limit Check
        if extension_days > effective_max_extension:
            reason = (
                f"Requested extension of {extension_days} days exceeds the maximum allowed policy "
                f"of {effective_max_extension} days."
            )
            return (False, reason, counter_offer)

        # All Guardrail Checks Passed!
        return (True, "Proposal passed all merchant guardrail and platform safety checks.", {
            "approved_amount_inr": proposed_amount_inr,
            "approved_amount_paise": proposed_amount_paise,
            "approved_extension_days": extension_days
        })
