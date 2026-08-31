import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.core.database import (
    init_db,
    get_connection,
    upsert_invoice,
    log_financial_transaction,
    get_customer_financial_profile
)
from backend.models.core import MasterInvoice, InvoiceStatus

class TestCustomerFinancialProfile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.invoice_id = "INV-TEST-FIN-PROF-001"
        self.customer_phone = "+919988776655"
        self.merchant_id = "test_merchant_profile"
        self._cleanup()

        # Insert test invoice
        test_inv = MasterInvoice(
            invoice_id=self.invoice_id,
            customer_name="Test Customer Ledger",
            customer_phone=self.customer_phone,
            original_amount_paise=100000,
            paid_amount_paise=0,
            remaining_amount_paise=100000,
            due_date="2026-12-31",
            status=InvoiceStatus.UNPAID
        )
        upsert_invoice(test_inv, merchant_id=self.merchant_id)

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM transaction_ledger WHERE invoice_id = %s;", (self.invoice_id,))
        cur.execute("DELETE FROM master_invoices WHERE invoice_id = %s;", (self.invoice_id,))
        conn.commit()
        conn.close()

    def test_financial_profile_excludes_outflow_settlement_duplicates(self):
        """Ensure get_customer_financial_profile returns only INFLOW_CUSTOMER_PAYMENT transactions."""
        # 1. Log Inflow payment
        log_financial_transaction(
            merchant_id=self.merchant_id,
            invoice_id=self.invoice_id,
            transaction_type="INFLOW_CUSTOMER_PAYMENT",
            gross_amount_paise=50000,
            merchant_amount_paise=48500,
            platform_fee_paise=1500,
            razorpay_payment_id="pay_inflow_test_123",
            status="CAPTURED"
        )

        # 2. Log Outflow settlement (merchant wire)
        log_financial_transaction(
            merchant_id=self.merchant_id,
            invoice_id=self.invoice_id,
            transaction_type="OUTFLOW_MERCHANT_SETTLEMENT",
            gross_amount_paise=50000,
            merchant_amount_paise=48500,
            platform_fee_paise=1500,
            razorpay_payment_id="pay_inflow_test_123",
            razorpay_transfer_id="trf_outflow_test_123",
            status="CAPTURED"
        )

        # 3. Retrieve financial profile
        profile = get_customer_financial_profile(self.customer_phone)

        # 4. Verify transactions list contains exactly 1 transaction (the inflow), avoiding duplicate
        transactions = profile.get("transactions", [])
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0]["invoice_id"], self.invoice_id)
        self.assertEqual(transactions[0]["razorpay_payment_id"], "pay_inflow_test_123")
        self.assertEqual(transactions[0]["amount_paid_inr"], 500.0)

if __name__ == '__main__':
    unittest.main()
