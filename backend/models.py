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
class Merchant:
    merchant_id: str
    email: str
    business_name: str
    phone: Optional[str] = None
    created_at: Optional[str] = None
    bank_beneficiary_name: Optional[str] = None
    bank_account_number: Optional[str] = None
    bank_ifsc: Optional[str] = None
    bank_name: Optional[str] = None
    upi_id: Optional[str] = None
    pan_number: Optional[str] = None
    commission_pct: float = 3.0
    settlement_status: str = "ACTIVE"
    password_hash: Optional[str] = None
    razorpay_account_id: Optional[str] = None

@dataclass
class MerchantGuardrails:
    id: int = 1
    merchant_id: str = 'default_merchant'
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
    items: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None
    merchant_id: Optional[str] = None

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
    customer_phone: str  # Primary key: 1 session per customer phone
    messages: List[ChatMessage] = field(default_factory=list)
    session_id: Optional[str] = None
    invoice_id: Optional[str] = None

    def __post_init__(self):
        if not self.session_id:
            self.session_id = self.customer_phone
