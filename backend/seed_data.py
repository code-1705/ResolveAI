import os
import datetime
from backend.config import settings
from backend.models import MasterInvoice, InvoiceStatus
from backend.database import init_db, upsert_invoice, get_connection

DEMO_INVOICES = [
    MasterInvoice(
        invoice_id="inv_SME_001",
        customer_name="Apex Logistics Pvt Ltd",
        customer_phone="+919876543210",
        original_amount_paise=5000000,  # ₹50,000.00
        paid_amount_paise=0,
        remaining_amount_paise=5000000,
        due_date=(datetime.datetime.now() - datetime.timedelta(days=5)).strftime("%Y-%m-%d"),
        status=InvoiceStatus.UNPAID
    ),
    MasterInvoice(
        invoice_id="inv_SME_002",
        customer_name="Vanguard Web Studios",
        customer_phone="+919876543211",
        original_amount_paise=12000000,  # ₹1,20,000.00
        paid_amount_paise=0,
        remaining_amount_paise=12000000,
        due_date=(datetime.datetime.now() - datetime.timedelta(days=12)).strftime("%Y-%m-%d"),
        status=InvoiceStatus.UNPAID
    ),
    MasterInvoice(
        invoice_id="inv_SME_003",
        customer_name="GreenLeaf Organics",
        customer_phone="+919876543212",
        original_amount_paise=3500000,  # ₹35,000.00
        paid_amount_paise=0,
        remaining_amount_paise=3500000,
        due_date=(datetime.datetime.now() - datetime.timedelta(days=2)).strftime("%Y-%m-%d"),
        status=InvoiceStatus.UNPAID
    )
]

def seed_database(db_path: str = settings.DATABASE_PATH):
    """
    Initializes the database schema and seeds realistic Indian SME overdue invoices for testing and demo.
    """
    init_db(db_path)
    for inv in DEMO_INVOICES:
        upsert_invoice(inv, db_path=db_path)
    print(f"Database seeded successfully with {len(DEMO_INVOICES)} demo invoices at '{db_path}'.")

if __name__ == "__main__":
    seed_database()
