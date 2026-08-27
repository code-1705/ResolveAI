import json
import datetime
from typing import Optional, List, Tuple, Dict, Any
from backend.config import settings
from backend.models import (
    Merchant,
    MerchantGuardrails,
    MasterInvoice,
    TransactionLedger,
    PaymentLinkRecord,
    ChatSession,
    ChatMessage,
    InvoiceStatus,
    PaymentLinkStatus
)


def paise_to_inr(paise: int) -> float:
    return round(paise / 100.0, 2)

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
    return psycopg2.connect(settings.DATABASE_URL, cursor_factory=DictCursor)

def init_db():
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)

    # 0. Merchants Table (Multi-Tenant Accounts)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS merchants (
        merchant_id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        business_name TEXT NOT NULL,
        phone TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
        bank_beneficiary_name TEXT,
        bank_account_number TEXT,
        bank_ifsc TEXT,
        bank_name TEXT,
        upi_id TEXT,
        pan_number TEXT,
        commission_pct REAL DEFAULT 3.0,
        settlement_status TEXT DEFAULT 'ACTIVE',
        password_hash TEXT,
        razorpay_account_id TEXT
    );
    """)
    cursor.execute("""
    INSERT INTO merchants (merchant_id, email, business_name, phone, settlement_status, bank_beneficiary_name, bank_account_number, bank_ifsc, bank_name)
    VALUES ('default_merchant', 'merchant@resolveai.com', 'Resolve.ai Merchant', '+919876543210', 'ACTIVE', 'Resolve.ai Merchant', '123456789012', 'HDFC0001234', 'HDFC Bank')
    ON CONFLICT (merchant_id) DO NOTHING;
    """)
    cursor.execute("""
    UPDATE merchants 
    SET bank_beneficiary_name = COALESCE(bank_beneficiary_name, 'Resolve.ai Merchant'),
        bank_account_number = COALESCE(bank_account_number, '123456789012'),
        bank_ifsc = COALESCE(bank_ifsc, 'HDFC0001234'),
        bank_name = COALESCE(bank_name, 'HDFC Bank'),
        settlement_status = COALESCE(settlement_status, 'ACTIVE')
    WHERE merchant_id = 'default_merchant';
    """)

    # 1. Merchant Guardrails Table (Multi-Tenant)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS merchant_guardrails (
        id SERIAL PRIMARY KEY,
        merchant_id TEXT UNIQUE NOT NULL DEFAULT 'default_merchant',
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
        requires_human_attention BOOLEAN NOT NULL DEFAULT FALSE,
        merchant_id TEXT DEFAULT 'default_merchant',
        file_url TEXT,
        items JSONB,
        metadata JSONB
    );
    """)
    conn.commit()

    # Migration safe-guards for existing databases
    for col_def in [
        "ALTER TABLE master_invoices ADD COLUMN IF NOT EXISTS requires_human_attention BOOLEAN NOT NULL DEFAULT FALSE;",
        "ALTER TABLE master_invoices ADD COLUMN IF NOT EXISTS merchant_id TEXT DEFAULT 'default_merchant';",
        "ALTER TABLE master_invoices ADD COLUMN IF NOT EXISTS file_url TEXT;",
        "ALTER TABLE master_invoices ADD COLUMN IF NOT EXISTS items JSONB;",
        "ALTER TABLE master_invoices ADD COLUMN IF NOT EXISTS metadata JSONB;",
        "ALTER TABLE merchants ADD COLUMN IF NOT EXISTS bank_beneficiary_name TEXT;",
        "ALTER TABLE merchants ADD COLUMN IF NOT EXISTS bank_account_number TEXT;",
        "ALTER TABLE merchants ADD COLUMN IF NOT EXISTS bank_ifsc TEXT;",
        "ALTER TABLE merchants ADD COLUMN IF NOT EXISTS bank_name TEXT;",
        "ALTER TABLE merchants ADD COLUMN IF NOT EXISTS upi_id TEXT;",
        "ALTER TABLE merchants ADD COLUMN IF NOT EXISTS pan_number TEXT;",
        "ALTER TABLE merchants ADD COLUMN IF NOT EXISTS commission_pct REAL DEFAULT 3.0;",
        "ALTER TABLE merchants ADD COLUMN IF NOT EXISTS settlement_status TEXT DEFAULT 'ACTIVE';",
        "ALTER TABLE merchants ADD COLUMN IF NOT EXISTS password_hash TEXT;",
        "ALTER TABLE merchants ADD COLUMN IF NOT EXISTS razorpay_account_id TEXT;"
    ]:
        try:
            cursor.execute(col_def)
            conn.commit()
        except Exception:
            conn.rollback()

    # Invoice Documents Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS invoice_documents (
        invoice_id TEXT PRIMARY KEY,
        file_name TEXT NOT NULL,
        file_mime_type TEXT NOT NULL,
        file_bytes BYTEA NOT NULL,
        customer_phone TEXT NOT NULL,
        uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()

    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_invoices_phone ON master_invoices(customer_phone);")

    # 3. Double-Entry Transaction Ledger Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transaction_ledger (
        id SERIAL PRIMARY KEY,
        merchant_id TEXT NOT NULL DEFAULT 'default_merchant',
        invoice_id TEXT NOT NULL,
        transaction_type TEXT NOT NULL DEFAULT 'INFLOW_CUSTOMER_PAYMENT',
        razorpay_payment_id TEXT,
        razorpay_transfer_id TEXT,
        razorpay_account_id TEXT,
        gross_amount_paise INTEGER NOT NULL DEFAULT 0,
        merchant_amount_paise INTEGER NOT NULL DEFAULT 0,
        platform_fee_paise INTEGER NOT NULL DEFAULT 0,
        amount_paid_paise INTEGER,
        payment_method TEXT,
        bank_beneficiary_name TEXT,
        bank_account_masked TEXT,
        bank_ifsc TEXT,
        status TEXT NOT NULL DEFAULT 'CAPTURED',
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ledger_payment_id ON transaction_ledger(razorpay_payment_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ledger_merchant_id ON transaction_ledger(merchant_id);")

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

    # 5. Chat Sessions Table (Unified 1 row per customer_phone)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_sessions (
        customer_phone TEXT PRIMARY KEY,
        messages_json TEXT NOT NULL DEFAULT '[]'
    );
    """)

    # Seed/Backfill Default Guardrails for all merchants in merchants table
    cursor.execute("""
    INSERT INTO merchant_guardrails (merchant_id, min_partial_payment_pct, max_extension_days, max_split_installments, auto_discount_waiver_pct, tone)
    SELECT merchant_id, %s, %s, %s, %s, %s
    FROM merchants
    ON CONFLICT (merchant_id) DO NOTHING;
    """, (
        settings.DEFAULT_MIN_PARTIAL_PAYMENT_PCT,
        settings.DEFAULT_MAX_EXTENSION_DAYS,
        settings.DEFAULT_MAX_SPLIT_INSTALLMENTS,
        settings.DEFAULT_AUTO_DISCOUNT_WAIVER_PCT,
        settings.DEFAULT_TONE
    ))

    # Also ensure default_merchant fallback exists
    cursor.execute("""
    INSERT INTO merchant_guardrails (merchant_id, min_partial_payment_pct, max_extension_days, max_split_installments, auto_discount_waiver_pct, tone)
    VALUES ('default_merchant', %s, %s, %s, %s, %s)
    ON CONFLICT (merchant_id) DO NOTHING;
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

def get_guardrails(merchant_id: Optional[str] = "default_merchant") -> MerchantGuardrails:
    target_m_id = merchant_id or "default_merchant"
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("SELECT * FROM merchant_guardrails WHERE merchant_id = %s;", (target_m_id,))
    row = cursor.fetchone()
    if not row and target_m_id != "default_merchant":
        # Fallback to default merchant guardrails or first row
        cursor.execute("SELECT * FROM merchant_guardrails WHERE merchant_id = 'default_merchant' OR id = 1 LIMIT 1;")
        row = cursor.fetchone()
    conn.close()
    if row:
        return MerchantGuardrails(
            id=row["id"],
            merchant_id=row.get("merchant_id", target_m_id),
            min_partial_payment_pct=row["min_partial_payment_pct"],
            max_extension_days=row["max_extension_days"],
            max_split_installments=row["max_split_installments"],
            auto_discount_waiver_pct=row["auto_discount_waiver_pct"],
            tone=row["tone"]
        )
    return MerchantGuardrails(merchant_id=target_m_id)

def update_guardrails(guardrails: MerchantGuardrails, merchant_id: Optional[str] = None) -> MerchantGuardrails:
    target_m_id = merchant_id or getattr(guardrails, 'merchant_id', None) or "default_merchant"
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("""
    INSERT INTO merchant_guardrails (merchant_id, min_partial_payment_pct, max_extension_days, max_split_installments, auto_discount_waiver_pct, tone)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (merchant_id) DO UPDATE SET
        min_partial_payment_pct = EXCLUDED.min_partial_payment_pct,
        max_extension_days = EXCLUDED.max_extension_days,
        max_split_installments = EXCLUDED.max_split_installments,
        auto_discount_waiver_pct = EXCLUDED.auto_discount_waiver_pct,
        tone = EXCLUDED.tone
    RETURNING *;
    """, (
        target_m_id,
        guardrails.min_partial_payment_pct,
        guardrails.max_extension_days,
        guardrails.max_split_installments,
        guardrails.auto_discount_waiver_pct,
        guardrails.tone
    ))
    row = cursor.fetchone()
    conn.commit()
    conn.close()
    if row:
        return MerchantGuardrails(
            id=row["id"],
            merchant_id=row.get("merchant_id", target_m_id),
            min_partial_payment_pct=row["min_partial_payment_pct"],
            max_extension_days=row["max_extension_days"],
            max_split_installments=row["max_split_installments"],
            auto_discount_waiver_pct=row["auto_discount_waiver_pct"],
            tone=row["tone"]
        )
    return guardrails

def upsert_invoice(invoice: MasterInvoice, merchant_id: Optional[str] = None) -> MasterInvoice:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    m_id = merchant_id or getattr(invoice, 'merchant_id', None)
    f_url = getattr(invoice, 'file_url', None)
    items_json = json.dumps(invoice.items) if getattr(invoice, 'items', None) else None
    meta_json = json.dumps(invoice.metadata) if getattr(invoice, 'metadata', None) else None
    cursor.execute("""
    INSERT INTO master_invoices (invoice_id, customer_name, customer_phone, original_amount_paise, paid_amount_paise, remaining_amount_paise, due_date, status, requires_human_attention, merchant_id, file_url, items, metadata)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT(invoice_id) DO UPDATE SET
        customer_name=excluded.customer_name,
        customer_phone=excluded.customer_phone,
        original_amount_paise=excluded.original_amount_paise,
        paid_amount_paise=excluded.paid_amount_paise,
        remaining_amount_paise=excluded.remaining_amount_paise,
        due_date=excluded.due_date,
        status=excluded.status,
        requires_human_attention=excluded.requires_human_attention,
        merchant_id=COALESCE(excluded.merchant_id, master_invoices.merchant_id),
        file_url=COALESCE(excluded.file_url, master_invoices.file_url),
        items=COALESCE(excluded.items, master_invoices.items),
        metadata=COALESCE(excluded.metadata, master_invoices.metadata);
    """, (
        invoice.invoice_id,
        invoice.customer_name,
        invoice.customer_phone,
        invoice.original_amount_paise,
        invoice.paid_amount_paise,
        invoice.remaining_amount_paise,
        invoice.due_date,
        invoice.status.value if isinstance(invoice.status, InvoiceStatus) else invoice.status,
        invoice.requires_human_attention,
        m_id or 'default_merchant',
        f_url,
        items_json,
        meta_json
    ))
    conn.commit()
    conn.close()
    return invoice

def _parse_json_field(val):
    if not val:
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return None

def get_invoice(invoice_id: str, ) -> Optional[MasterInvoice]:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("SELECT * FROM master_invoices WHERE invoice_id = %s;", (invoice_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        r_dict = dict(row)
        return MasterInvoice(
            invoice_id=r_dict["invoice_id"],
            customer_name=r_dict["customer_name"],
            customer_phone=r_dict["customer_phone"],
            original_amount_paise=r_dict["original_amount_paise"],
            paid_amount_paise=r_dict["paid_amount_paise"],
            remaining_amount_paise=r_dict["remaining_amount_paise"],
            due_date=r_dict["due_date"],
            status=InvoiceStatus(r_dict["status"]),
            requires_human_attention=bool(r_dict.get("requires_human_attention", False)),
            file_url=r_dict.get("file_url"),
            items=_parse_json_field(r_dict.get("items")),
            metadata=_parse_json_field(r_dict.get("metadata")),
            merchant_id=r_dict.get("merchant_id")
        )
    return None

def get_invoices_by_phone(phone: str) -> List[MasterInvoice]:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    clean_phone = phone.replace(" ", "").replace("-", "").replace("+", "")
    cursor.execute("""
        SELECT * FROM master_invoices 
        WHERE REPLACE(REPLACE(REPLACE(customer_phone, ' ', ''), '-', ''), '+', '') = %s 
           OR (LENGTH(%s) >= 10 AND RIGHT(REPLACE(REPLACE(REPLACE(customer_phone, ' ', ''), '-', ''), '+', ''), 10) = RIGHT(%s, 10))
        ORDER BY due_date ASC;
    """, (clean_phone, clean_phone, clean_phone))
    rows = cursor.fetchall()
    conn.close()
    res = []
    for r in rows:
        r_dict = dict(r)
        res.append(
            MasterInvoice(
                invoice_id=r_dict["invoice_id"],
                customer_name=r_dict["customer_name"],
                customer_phone=r_dict["customer_phone"],
                original_amount_paise=r_dict["original_amount_paise"],
                paid_amount_paise=r_dict["paid_amount_paise"],
                remaining_amount_paise=r_dict["remaining_amount_paise"],
                due_date=r_dict["due_date"],
                status=InvoiceStatus(r_dict["status"]),
                requires_human_attention=bool(r_dict.get("requires_human_attention", False)),
                file_url=r_dict.get("file_url"),
                items=_parse_json_field(r_dict.get("items")),
                metadata=_parse_json_field(r_dict.get("metadata")),
                merchant_id=r_dict.get("merchant_id")
            )
        )
    return res

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

from backend.storage import upload_to_supabase_storage

def save_invoice_document(
    invoice_id: str,
    customer_phone: str,
    file_name: str,
    file_mime_type: str,
    file_bytes: bytes
) -> bool:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    uploaded_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # Attempt Supabase Cloud Storage bucket upload first
    cdn_url = upload_to_supabase_storage(f"{invoice_id}_{file_name}", file_bytes, file_mime_type)

    try:
        cursor.execute("""
        INSERT INTO invoice_documents (invoice_id, file_name, file_mime_type, file_bytes, customer_phone, uploaded_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT(invoice_id) DO UPDATE SET
            file_name=excluded.file_name,
            file_mime_type=excluded.file_mime_type,
            file_bytes=excluded.file_bytes,
            customer_phone=excluded.customer_phone,
            uploaded_at=excluded.uploaded_at;
        """, (invoice_id, cdn_url or file_name, file_mime_type, psycopg2.Binary(file_bytes), customer_phone, uploaded_at))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        conn.rollback()
        conn.close()
        print(f"[DB Document Save Error]: {e}")
        return False

def get_invoice_document(invoice_id: str, customer_phone: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("""
    SELECT file_name, file_mime_type, file_bytes, customer_phone 
    FROM invoice_documents 
    WHERE invoice_id = %s;
    """, (invoice_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    
    clean_db_phone = row["customer_phone"].replace(" ", "").replace("-", "").replace("+", "")
    clean_req_phone = customer_phone.replace(" ", "").replace("-", "").replace("+", "")
    match = (clean_db_phone == clean_req_phone) or (
        len(clean_db_phone) >= 10 and len(clean_req_phone) >= 10 and clean_db_phone[-10:] == clean_req_phone[-10:]
    )
    if not match:
        return {"error": "FORBIDDEN"}
    
    return {
        "file_name": row["file_name"],
        "file_mime_type": row["file_mime_type"],
        "file_bytes": bytes(row["file_bytes"])
    }


def get_customer_all_invoices(customer_phone: str) -> List[Dict[str, Any]]:
    """Returns all pending/unpaid invoices and document URLs belonging to a customer phone number."""
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    clean_phone = customer_phone.replace(" ", "").replace("-", "").replace("+", "")
    cursor.execute("""
        SELECT * FROM master_invoices 
        WHERE REPLACE(REPLACE(REPLACE(customer_phone, ' ', ''), '-', ''), '+', '') = %s 
           OR (LENGTH(%s) >= 10 AND RIGHT(REPLACE(REPLACE(REPLACE(customer_phone, ' ', ''), '-', ''), '+', ''), 10) = RIGHT(%s, 10))
        ORDER BY due_date ASC;
    """, (clean_phone, clean_phone, clean_phone))
    rows = cursor.fetchall()
    conn.close()

    results = []
    for r in rows:
        orig = r["original_amount_paise"]
        paid = r["paid_amount_paise"]
        rem = r["remaining_amount_paise"]
        doc = get_invoice_document(r["invoice_id"], r["customer_phone"])
        doc_url = None
        has_doc = False
        if doc and "error" not in doc:
            has_doc = True
            fn = doc.get("file_name", "")
            if fn.startswith("http://") or fn.startswith("https://"):
                doc_url = fn
            else:
                doc_url = f"/api/invoices/{r['invoice_id']}/document?customer_phone={r['customer_phone']}"

        results.append({
            "invoice_id": r["invoice_id"],
            "customer_name": r["customer_name"],
            "customer_phone": r["customer_phone"],
            "original_amount_inr": paise_to_inr(orig),
            "paid_amount_inr": paise_to_inr(paid),
            "remaining_amount_inr": paise_to_inr(rem),
            "due_date": r["due_date"],
            "status": r["status"],
            "has_document": has_doc,
            "document_url": doc_url
        })
    return results


def get_customer_financial_profile(customer_phone: str) -> Dict[str, Any]:
    """Retrieves full account financial ledger, UNPAID invoice list, and past transaction history for a customer phone number."""
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    clean_phone = customer_phone.replace(" ", "").replace("-", "").replace("+", "")

    # ONLY select UNPAID / PARTIALLY_PAID / OVERDUE invoices (Exclude fully PAID bills)
    cursor.execute("""
        SELECT * FROM master_invoices 
        WHERE (REPLACE(REPLACE(REPLACE(customer_phone, ' ', ''), '-', ''), '+', '') = %s 
           OR (LENGTH(%s) >= 10 AND RIGHT(REPLACE(REPLACE(REPLACE(customer_phone, ' ', ''), '-', ''), '+', ''), 10) = RIGHT(%s, 10)))
          AND status != 'PAID' 
        ORDER BY due_date ASC;
    """, (clean_phone, clean_phone, clean_phone))
    inv_rows = cursor.fetchall()

    today_str = datetime.date.today().isoformat()
    invoices_list = []
    invoice_ids = []

    total_billed_paise = 0
    total_paid_paise = 0
    total_remaining_paise = 0
    pending_count = 0
    overdue_count = 0

    cust_name = None

    for r in inv_rows:
        inv_id = r["invoice_id"]
        invoice_ids.append(inv_id)
        orig = r["original_amount_paise"]
        paid = r["paid_amount_paise"]
        rem = r["remaining_amount_paise"]

        total_billed_paise += orig
        total_paid_paise += paid
        total_remaining_paise += rem

        if not cust_name and r["customer_name"]:
            cust_name = r["customer_name"]

        pending_count += 1
        if r["due_date"] < today_str:
            overdue_count += 1

        f_url = r.get("file_url")
        has_doc = True if (f_url and f_url.strip()) else False

        invoices_list.append({
            "invoice_id": inv_id,
            "customer_name": r["customer_name"],
            "customer_phone": r["customer_phone"],
            "original_amount_inr": paise_to_inr(orig),
            "paid_amount_inr": paise_to_inr(paid),
            "remaining_amount_inr": paise_to_inr(rem),
            "due_date": r["due_date"],
            "status": r["status"],
            "has_document": has_doc,
            "document_url": f"/api/invoices/{inv_id}/document?customer_phone={r['customer_phone']}" if has_doc else None
        })

    # If no pending invoices, query any invoice (e.g. PAID) to find the customer_name
    if not cust_name:
        cursor.execute("""
            SELECT customer_name FROM master_invoices 
            WHERE REPLACE(REPLACE(REPLACE(customer_phone, ' ', ''), '-', ''), '+', '') = %s 
               OR (LENGTH(%s) >= 10 AND RIGHT(REPLACE(REPLACE(REPLACE(customer_phone, ' ', ''), '-', ''), '+', ''), 10) = RIGHT(%s, 10))
            LIMIT 1;
        """, (clean_phone, clean_phone, clean_phone))
        name_row = cursor.fetchone()
        if name_row:
            cust_name = name_row["customer_name"]

    transactions_list = []
    if invoice_ids:
        cursor.execute(
            "SELECT * FROM transaction_ledger WHERE invoice_id = ANY(%s) ORDER BY id DESC;",
            (invoice_ids,)
        )
        tx_rows = cursor.fetchall()
        for t in tx_rows:
            transactions_list.append({
                "id": t["id"],
                "invoice_id": t["invoice_id"],
                "razorpay_payment_id": t["razorpay_payment_id"],
                "amount_paid_inr": paise_to_inr(t["amount_paid_paise"]),
                "payment_method": t["payment_method"],
                "created_at": t["created_at"]
            })

    conn.close()

    return {
        "customer_phone": customer_phone,
        "customer_name": cust_name or "valued customer",
        "total_invoices_count": len(inv_rows),
        "pending_invoices_count": pending_count,
        "overdue_invoices_count": overdue_count,
        "total_billed_inr": paise_to_inr(total_billed_paise),
        "total_paid_to_date_inr": paise_to_inr(total_paid_paise),
        "total_remaining_balance_inr": paise_to_inr(total_remaining_paise),
        "invoices": invoices_list,
        "transactions": transactions_list
    }


def get_merchant_by_id(merchant_id: str) -> Optional[Merchant]:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("SELECT * FROM merchants WHERE merchant_id = %s;", (merchant_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return Merchant(
            merchant_id=row["merchant_id"],
            email=row["email"],
            business_name=row["business_name"],
            phone=row.get("phone"),
            created_at=str(row.get("created_at", "")),
            bank_beneficiary_name=row.get("bank_beneficiary_name"),
            bank_account_number=row.get("bank_account_number"),
            bank_ifsc=row.get("bank_ifsc"),
            bank_name=row.get("bank_name"),
            upi_id=row.get("upi_id"),
            pan_number=row.get("pan_number"),
            commission_pct=float(row.get("commission_pct") or 3.0),
            settlement_status=row.get("settlement_status") or "ACTIVE"
        )
    return None

def update_merchant_bank_settlement(
    merchant_id: str,
    bank_beneficiary_name: str,
    bank_account_number: str,
    bank_ifsc: str,
    bank_name: Optional[str] = None,
    upi_id: Optional[str] = None,
    pan_number: Optional[str] = None
) -> Optional[Merchant]:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("""
    UPDATE merchants
    SET bank_beneficiary_name = %s,
        bank_account_number = %s,
        bank_ifsc = %s,
        bank_name = %s,
        upi_id = %s,
        pan_number = %s,
        settlement_status = 'ACTIVE'
    WHERE merchant_id = %s
    RETURNING *;
    """, (
        bank_beneficiary_name.strip(),
        bank_account_number.strip(),
        bank_ifsc.strip().upper(),
        (bank_name or "").strip(),
        (upi_id or "").strip(),
        (pan_number or "").strip().upper(),
        merchant_id
    ))
    row = cursor.fetchone()
    conn.commit()
    conn.close()
    if row:
        return Merchant(
            merchant_id=row["merchant_id"],
            email=row["email"],
            business_name=row["business_name"],
            phone=row.get("phone"),
            created_at=str(row.get("created_at", "")),
            bank_beneficiary_name=row.get("bank_beneficiary_name"),
            bank_account_number=row.get("bank_account_number"),
            bank_ifsc=row.get("bank_ifsc"),
            bank_name=row.get("bank_name"),
            upi_id=row.get("upi_id"),
            pan_number=row.get("pan_number"),
            commission_pct=float(row.get("commission_pct") or 3.0),
            settlement_status=row.get("settlement_status") or "ACTIVE"
        )
    return None

def get_or_create_merchant(merchant_id: str, email: str, business_name: str, phone: Optional[str] = None) -> Merchant:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("SELECT * FROM merchants WHERE merchant_id = %s OR email = %s;", (merchant_id, email))
    row = cursor.fetchone()
    if row:
        conn.close()
        return Merchant(
            merchant_id=row["merchant_id"],
            email=row["email"],
            business_name=row["business_name"],
            phone=row.get("phone"),
            created_at=str(row.get("created_at", "")),
            bank_beneficiary_name=row.get("bank_beneficiary_name"),
            bank_account_number=row.get("bank_account_number"),
            bank_ifsc=row.get("bank_ifsc"),
            bank_name=row.get("bank_name"),
            upi_id=row.get("upi_id"),
            pan_number=row.get("pan_number"),
            commission_pct=float(row.get("commission_pct") or 3.0),
            settlement_status=row.get("settlement_status") or "ACTIVE",
            password_hash=row.get("password_hash"),
            razorpay_account_id=row.get("razorpay_account_id")
        )
    
    cursor.execute("""
    INSERT INTO merchants (merchant_id, email, business_name, phone, settlement_status)
    VALUES (%s, %s, %s, %s, 'ACTIVE')
    ON CONFLICT (merchant_id) DO UPDATE SET business_name = EXCLUDED.business_name
    RETURNING *;
    """, (merchant_id, email, business_name, phone))
    new_row = cursor.fetchone()

    # Auto-seed default guardrails for newly created merchant
    cursor.execute("""
    INSERT INTO merchant_guardrails (merchant_id, min_partial_payment_pct, max_extension_days, max_split_installments, auto_discount_waiver_pct, tone)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (merchant_id) DO NOTHING;
    """, (
        merchant_id,
        settings.DEFAULT_MIN_PARTIAL_PAYMENT_PCT,
        settings.DEFAULT_MAX_EXTENSION_DAYS,
        settings.DEFAULT_MAX_SPLIT_INSTALLMENTS,
        settings.DEFAULT_AUTO_DISCOUNT_WAIVER_PCT,
        settings.DEFAULT_TONE
    ))
    conn.commit()
    conn.close()
    return Merchant(
        merchant_id=new_row["merchant_id"],
        email=new_row["email"],
        business_name=new_row["business_name"],
        phone=new_row.get("phone"),
        created_at=str(new_row.get("created_at", "")),
        bank_beneficiary_name=new_row.get("bank_beneficiary_name"),
        bank_account_number=new_row.get("bank_account_number"),
        bank_ifsc=new_row.get("bank_ifsc"),
        bank_name=new_row.get("bank_name"),
        upi_id=new_row.get("upi_id"),
        pan_number=new_row.get("pan_number"),
        commission_pct=float(new_row.get("commission_pct") or 3.0),
        settlement_status=new_row.get("settlement_status") or "ACTIVE",
        password_hash=new_row.get("password_hash")
    )


def get_merchant_by_email(email: str) -> Optional[Merchant]:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("SELECT * FROM merchants WHERE LOWER(email) = LOWER(%s);", (email.strip(),))
    row = cursor.fetchone()
    conn.close()
    if row:
        return Merchant(
            merchant_id=row["merchant_id"],
            email=row["email"],
            business_name=row["business_name"],
            phone=row.get("phone"),
            created_at=str(row.get("created_at", "")),
            bank_beneficiary_name=row.get("bank_beneficiary_name"),
            bank_account_number=row.get("bank_account_number"),
            bank_ifsc=row.get("bank_ifsc"),
            bank_name=row.get("bank_name"),
            upi_id=row.get("upi_id"),
            pan_number=row.get("pan_number"),
            commission_pct=float(row.get("commission_pct") or 3.0),
            settlement_status=row.get("settlement_status") or "ACTIVE",
            password_hash=row.get("password_hash"),
            razorpay_account_id=row.get("razorpay_account_id")
        )
    return None

def create_merchant_with_password(
    merchant_id: str,
    email: str,
    business_name: str,
    password_hash: str,
    phone: Optional[str] = None
) -> Merchant:
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("""
    INSERT INTO merchants (merchant_id, email, business_name, password_hash, phone, settlement_status)
    VALUES (%s, %s, %s, %s, %s, 'ACTIVE')
    ON CONFLICT (merchant_id) DO UPDATE SET
        business_name = EXCLUDED.business_name,
        password_hash = COALESCE(EXCLUDED.password_hash, merchants.password_hash)
    RETURNING *;
    """, (merchant_id, email.strip().lower(), business_name.strip(), password_hash, phone))
    row = cursor.fetchone()

    # Auto-seed default guardrails for newly created merchant with password
    cursor.execute("""
    INSERT INTO merchant_guardrails (merchant_id, min_partial_payment_pct, max_extension_days, max_split_installments, auto_discount_waiver_pct, tone)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (merchant_id) DO NOTHING;
    """, (
        merchant_id,
        settings.DEFAULT_MIN_PARTIAL_PAYMENT_PCT,
        settings.DEFAULT_MAX_EXTENSION_DAYS,
        settings.DEFAULT_MAX_SPLIT_INSTALLMENTS,
        settings.DEFAULT_AUTO_DISCOUNT_WAIVER_PCT,
        settings.DEFAULT_TONE
    ))
    conn.commit()
    conn.close()
    return Merchant(
        merchant_id=row["merchant_id"],
        email=row["email"],
        business_name=row["business_name"],
        phone=row.get("phone"),
        created_at=str(row.get("created_at", "")),
        bank_beneficiary_name=row.get("bank_beneficiary_name"),
        bank_account_number=row.get("bank_account_number"),
        bank_ifsc=row.get("bank_ifsc"),
        bank_name=row.get("bank_name"),
        upi_id=row.get("upi_id"),
        pan_number=row.get("pan_number"),
        commission_pct=float(row.get("commission_pct") or 3.0),
        settlement_status=row.get("settlement_status") or "ACTIVE",
        password_hash=row.get("password_hash")
    )


def log_financial_transaction(
    merchant_id: str,
    invoice_id: str,
    transaction_type: str,
    gross_amount_paise: int,
    merchant_amount_paise: int,
    platform_fee_paise: int,
    razorpay_payment_id: Optional[str] = None,
    razorpay_transfer_id: Optional[str] = None,
    razorpay_account_id: Optional[str] = None,
    bank_beneficiary_name: Optional[str] = None,
    bank_account_masked: Optional[str] = None,
    bank_ifsc: Optional[str] = None,
    status: str = 'CAPTURED'
) -> int:
    """Records an immutable financial event (Customer Payment Inflow or 97% Merchant Transfer Outflow) in the Double-Entry Ledger."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO transaction_ledger (
        merchant_id, invoice_id, transaction_type,
        razorpay_payment_id, razorpay_transfer_id, razorpay_account_id,
        gross_amount_paise, merchant_amount_paise, platform_fee_paise,
        amount_paid_paise, payment_method,
        bank_beneficiary_name, bank_account_masked, bank_ifsc,
        status, created_at
    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
    RETURNING id;
    """, (
        merchant_id, invoice_id, transaction_type,
        razorpay_payment_id, razorpay_transfer_id, razorpay_account_id,
        gross_amount_paise, merchant_amount_paise, platform_fee_paise,
        gross_amount_paise, "RAZORPAY_ROUTE_SPLIT",
        bank_beneficiary_name, bank_account_masked, bank_ifsc,
        status
    ))
    trans_id = cursor.fetchone()[0]
    conn.commit()
    conn.close()
    return trans_id

def get_merchant_settlement_ledger(merchant_id: str) -> List[Dict[str, Any]]:
    """Fetches complete financial double-entry transaction history for a specific merchant."""
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("""
    SELECT tl.*, mi.customer_name
    FROM transaction_ledger tl
    LEFT JOIN master_invoices mi ON tl.invoice_id = mi.invoice_id
    WHERE tl.merchant_id = %s
    ORDER BY tl.created_at DESC;
    """, (merchant_id,))
    rows = cursor.fetchall()
    conn.close()

    ledger = []
    for r in rows:
        gross_paise = r["gross_amount_paise"] or 0
        merchant_paise = r["merchant_amount_paise"] or 0
        fee_paise = r["platform_fee_paise"] or 0
        
        ledger.append({
            "id": r["id"],
            "invoice_id": r["invoice_id"],
            "customer_name": r.get("customer_name") or "Customer",
            "transaction_type": r["transaction_type"],
            "razorpay_payment_id": r.get("razorpay_payment_id"),
            "razorpay_transfer_id": r.get("razorpay_transfer_id"),
            "razorpay_account_id": r.get("razorpay_account_id"),
            "gross_amount_inr": round(gross_paise / 100.0, 2),
            "merchant_amount_inr": round(merchant_paise / 100.0, 2),
            "platform_fee_inr": round(fee_paise / 100.0, 2),
            "bank_beneficiary_name": r.get("bank_beneficiary_name"),
            "bank_account_masked": r.get("bank_account_masked"),
            "bank_ifsc": r.get("bank_ifsc"),
            "status": r["status"],
            "created_at": str(r["created_at"])
        })
    return ledger

def update_merchant_razorpay_account(merchant_id: str, razorpay_account_id: str):
    """Saves the linked Razorpay Route Account ID for automated payouts."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE merchants
    SET razorpay_account_id = %s
    WHERE merchant_id = %s;
    """, (razorpay_account_id, merchant_id))
    conn.commit()
    conn.close()
