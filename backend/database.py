import json
import datetime
from typing import Optional, List, Tuple
from backend.config import settings
from backend.models import (
    MerchantGuardrails,
    MasterInvoice,
    TransactionLedger,
    PaymentLinkRecord,
    ChatSession,
    ChatMessage,
    InvoiceStatus,
    PaymentLinkStatus
)

class FSMStateError(ValueError):
    """Raised when an illegal FSM invoice state transition is attempted."""
    pass

# FSM Transition Rules: Current Status -> Allowed Next Statuses
ALLOWED_FSM_TRANSITIONS = {
    InvoiceStatus.UNPAID: {InvoiceStatus.NEGOTIATING, InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID, InvoiceStatus.CANCELLED},
    InvoiceStatus.NEGOTIATING: {InvoiceStatus.PARTIALLY_PAID, InvoiceStatus.PAID, InvoiceStatus.CANCELLED},
    InvoiceStatus.PARTIALLY_PAID: {InvoiceStatus.PAID, InvoiceStatus.CANCELLED},
    InvoiceStatus.PAID: set(),  # Terminal state: Cannot transition anywhere
    InvoiceStatus.CANCELLED: set()  # Terminal state: Cannot transition anywhere
}

def validate_fsm_transition(current_status: str, new_status: str) -> bool:
    """Validates directional invoice lifecycle transitions."""
    if current_status == new_status:
        return True  # Idempotent state re-affirmation
    
    current_enum = InvoiceStatus(current_status)
    new_enum = InvoiceStatus(new_status)
    
    allowed = ALLOWED_FSM_TRANSITIONS.get(current_enum, set())
    if new_enum not in allowed:
        raise FSMStateError(
            f"Illegal FSM Transition: Cannot transition invoice from terminal or backward state '{current_status}' to '{new_status}'."
        )
    return True

import psycopg2
from psycopg2.extras import DictCursor

def get_connection():
    return psycopg2.connect(settings.DATABASE_URL)

def init_db():
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)

    # 1. Merchant Guardrails Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS merchant_guardrails (
        id INTEGER PRIMARY KEY DEFAULT 1,
        min_partial_payment_pct REAL NOT NULL DEFAULT 30.0,
        max_extension_days INTEGER NOT NULL DEFAULT 14,
        max_split_installments INTEGER NOT NULL DEFAULT 3,
        auto_discount_waiver_pct REAL NOT NULL DEFAULT 5.0,
        tone TEXT NOT NULL DEFAULT 'professional_empathetic'
    );
    """)

    # 2. Master Invoices Table (Integer Paise Storage)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS master_invoices (
        invoice_id TEXT PRIMARY KEY,
        customer_name TEXT NOT NULL,
        customer_phone TEXT NOT NULL,
        original_amount_paise INTEGER NOT NULL,
        paid_amount_paise INTEGER NOT NULL DEFAULT 0,
        remaining_amount_paise INTEGER NOT NULL,
        due_date TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'UNPAID',
        requires_human_attention BOOLEAN NOT NULL DEFAULT FALSE
    );
    """)
    conn.commit()
    try:
        cursor.execute("ALTER TABLE master_invoices ADD COLUMN requires_human_attention BOOLEAN NOT NULL DEFAULT FALSE;")
        conn.commit()
    except Exception:
        conn.rollback()

    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_phone ON master_invoices(customer_phone);")

    # 3. Transaction Ledger Table (UNIQUE razorpay_payment_id)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transaction_ledger (
        id SERIAL PRIMARY KEY,
        invoice_id TEXT NOT NULL,
        razorpay_payment_id TEXT NOT NULL UNIQUE,
        razorpay_payment_link_id TEXT,
        amount_paid_paise INTEGER NOT NULL,
        payment_method TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (invoice_id) REFERENCES master_invoices (invoice_id)
    );
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_payment_id ON transaction_ledger(razorpay_payment_id);")

    # 4. Payment Link Records Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payment_links (
        id SERIAL PRIMARY KEY,
        invoice_id TEXT NOT NULL,
        razorpay_payment_link_id TEXT NOT NULL UNIQUE,
        amount_paise INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'ACTIVE',
        reference_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (invoice_id) REFERENCES master_invoices (invoice_id)
    );
    """)

    # 5. Chat Sessions Table (Composite Session Key: customer_phone + '_' + invoice_id)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_sessions (
        session_id TEXT PRIMARY KEY,
        invoice_id TEXT NOT NULL,
        customer_phone TEXT NOT NULL,
        messages_json TEXT NOT NULL DEFAULT '[]'
    );
    """)

    # Seed Default Guardrails if not exists
    cursor.execute("SELECT COUNT(*) FROM merchant_guardrails;")
    if cursor.fetchone()[0] == 0:
        cursor.execute("""
        INSERT INTO merchant_guardrails (id, min_partial_payment_pct, max_extension_days, max_split_installments, auto_discount_waiver_pct, tone)
        VALUES (1, %s, %s, %s, %s, %s);
        """, (
            settings.DEFAULT_MIN_PARTIAL_PAYMENT_PCT,
            settings.DEFAULT_MAX_EXTENSION_DAYS,
            settings.DEFAULT_MAX_SPLIT_INSTALLMENTS,
            settings.DEFAULT_AUTO_DISCOUNT_WAIVER_PCT,
            settings.DEFAULT_TONE
        ))

    conn.commit()
    conn.close()

# --- CRUD Operations ---

def get_guardrails() -> MerchantGuardrails:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("SELECT * FROM merchant_guardrails WHERE id = 1;")
    row = cursor.fetchone()
    conn.close()
    if row:
        return MerchantGuardrails(
            id=row["id"],
            min_partial_payment_pct=row["min_partial_payment_pct"],
            max_extension_days=row["max_extension_days"],
            max_split_installments=row["max_split_installments"],
            auto_discount_waiver_pct=row["auto_discount_waiver_pct"],
            tone=row["tone"]
        )
    return MerchantGuardrails()

def update_guardrails(guardrails: MerchantGuardrails, ) -> MerchantGuardrails:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("""
    UPDATE merchant_guardrails
    SET min_partial_payment_pct = %s,
        max_extension_days = %s,
        max_split_installments = %s,
        auto_discount_waiver_pct = %s,
        tone = %s
    WHERE id = 1;
    """, (
        guardrails.min_partial_payment_pct,
        guardrails.max_extension_days,
        guardrails.max_split_installments,
        guardrails.auto_discount_waiver_pct,
        guardrails.tone
    ))
    conn.commit()
    conn.close()
    return guardrails

def upsert_invoice(invoice: MasterInvoice, ) -> MasterInvoice:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("""
    INSERT INTO master_invoices (invoice_id, customer_name, customer_phone, original_amount_paise, paid_amount_paise, remaining_amount_paise, due_date, status, requires_human_attention)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT(invoice_id) DO UPDATE SET
        customer_name=excluded.customer_name,
        customer_phone=excluded.customer_phone,
        original_amount_paise=excluded.original_amount_paise,
        paid_amount_paise=excluded.paid_amount_paise,
        remaining_amount_paise=excluded.remaining_amount_paise,
        due_date=excluded.due_date,
        status=excluded.status,
        requires_human_attention=excluded.requires_human_attention;
    """, (
        invoice.invoice_id,
        invoice.customer_name,
        invoice.customer_phone,
        invoice.original_amount_paise,
        invoice.paid_amount_paise,
        invoice.remaining_amount_paise,
        invoice.due_date,
        invoice.status.value if isinstance(invoice.status, InvoiceStatus) else invoice.status,
        invoice.requires_human_attention
    ))
    conn.commit()
    conn.close()
    return invoice

def get_invoice(invoice_id: str, ) -> Optional[MasterInvoice]:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("SELECT * FROM master_invoices WHERE invoice_id = %s;", (invoice_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return MasterInvoice(
            invoice_id=row["invoice_id"],
            customer_name=row["customer_name"],
            customer_phone=row["customer_phone"],
            original_amount_paise=row["original_amount_paise"],
            paid_amount_paise=row["paid_amount_paise"],
            remaining_amount_paise=row["remaining_amount_paise"],
            due_date=row["due_date"],
            status=InvoiceStatus(row["status"]),
            requires_human_attention=bool(dict(row).get("requires_human_attention", False))
        )
    return None

def get_invoices_by_phone(phone: str, ) -> List[MasterInvoice]:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("SELECT * FROM master_invoices WHERE customer_phone = %s;", (phone,))
    rows = cursor.fetchall()
    conn.close()
    return [
        MasterInvoice(
            invoice_id=r["invoice_id"],
            customer_name=r["customer_name"],
            customer_phone=r["customer_phone"],
            original_amount_paise=r["original_amount_paise"],
            paid_amount_paise=r["paid_amount_paise"],
            remaining_amount_paise=r["remaining_amount_paise"],
            due_date=r["due_date"],
            status=InvoiceStatus(r["status"]),
            requires_human_attention=bool(dict(r).get("requires_human_attention", False))
        ) for r in rows
    ]

def update_invoice_status(invoice_id: str, new_status: str, ) -> MasterInvoice:
    invoice = get_invoice(invoice_id, )
    if not invoice:
        raise ValueError(f"Invoice '{invoice_id}' not found.")
    
    # Enforce FSM state transitions
    validate_fsm_transition(invoice.status.value, new_status)
    
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("UPDATE master_invoices SET status = %s WHERE invoice_id = %s;", (new_status, invoice_id))
    conn.commit()
    conn.close()
    
    invoice.status = InvoiceStatus(new_status)
    return invoice

def record_transaction(
    invoice_id: str,
    razorpay_payment_id: str,
    razorpay_payment_link_id: Optional[str],
    amount_paid_paise: int,
    payment_method: str = "UPI",
    
) -> Tuple[bool, bool]:
    """
    Records a payment transaction into the TransactionLedger table.
    Enforces UNIQUE(razorpay_payment_id) at DB level.
    Returns: (success: bool, is_duplicate: bool)
    """
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    created_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    try:
        cursor.execute("""
        INSERT INTO transaction_ledger (invoice_id, razorpay_payment_id, razorpay_payment_link_id, amount_paid_paise, payment_method, created_at)
        VALUES (%s, %s, %s, %s, %s, %s);
        """, (invoice_id, razorpay_payment_id, razorpay_payment_link_id, amount_paid_paise, payment_method, created_at))
        conn.commit()
        conn.close()
        return (True, False)  # Successfully inserted
    except (psycopg2.IntegrityError):
        conn.rollback()
        conn.close()
        return (False, True)  # Duplicate payment_id caught cleanly!
