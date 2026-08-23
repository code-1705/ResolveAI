from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum

class InvoiceStatus(str, Enum):
    UNPAID = "UNPAID"
    NEGOTIATING = "NEGOTIATING"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CANCELLED = "CANCELLED"

class PaymentLinkStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"

@dataclass
class MerchantGuardrails:
    id: int = 1
    min_partial_payment_pct: float = 30.0
    max_extension_days: int = 14
    max_split_installments: int = 3
    auto_discount_waiver_pct: float = 5.0
    tone: str = "professional_empathetic"

@dataclass
class MasterInvoice:
    invoice_id: str
    customer_name: str
    customer_phone: str
    original_amount_paise: int  # Stored strictly as integer paise (₹1 = 100 paise)
    paid_amount_paise: int = 0  # Stored strictly as integer paise
    remaining_amount_paise: int = 0  # Stored strictly as integer paise
    due_date: str = ""  # YYYY-MM-DD
    status: InvoiceStatus = InvoiceStatus.UNPAID
    requires_human_attention: bool = False
    file_url: Optional[str] = None

    @property
    def original_amount_inr(self) -> float:
        return round(self.original_amount_paise / 100.0, 2)

    @property
    def paid_amount_inr(self) -> float:
        return round(self.paid_amount_paise / 100.0, 2)

    @property
    def remaining_amount_inr(self) -> float:
        return round(self.remaining_amount_paise / 100.0, 2)

@dataclass
class TransactionLedger:
    invoice_id: str
    razorpay_payment_id: str  # UNIQUE constraint enforced in DB
    amount_paid_paise: int
    payment_method: str
    created_at: str
    razorpay_payment_link_id: Optional[str] = None
    id: Optional[int] = None

@dataclass
class PaymentLinkRecord:
    invoice_id: str
    razorpay_payment_link_id: str  # Primary index
    amount_paise: int
    status: PaymentLinkStatus
    reference_id: str
    created_at: str
    id: Optional[int] = None

@dataclass
class ChatMessage:
    sender: str  # "user" or "agent"
    text: str
    timestamp: str
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ChatSession:
    session_id: str  # Composite key: f"{customer_phone}_{invoice_id}"
    invoice_id: str
    customer_phone: str
    messages: List[ChatMessage] = field(default_factory=list)
