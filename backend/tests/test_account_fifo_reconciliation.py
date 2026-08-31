import sys
import os
import unittest
import asyncio
import datetime
from typing import Dict, Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.core.database import (
    init_db,
    upsert_invoice,
    get_invoice,
    get_invoices_by_phone,
    get_connection
)
from backend.models.core import MasterInvoice, InvoiceStatus
from backend.services.guardrails import inr_to_paise
from backend.services.session import session_manager
from backend.services.webhooks import reconcile_payment_event


class TestAccountFIFOReconciliation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Initializes database schema before running tests."""
        init_db()

    def setUp(self):
        """Prepares standard test data for multi-bill FIFO payment testing."""
        self.phone = "+919999900088"
        self.inv_id_1 = "inv_fifo_test_001"
        self.inv_id_2 = "inv_fifo_test_002"
        self.inv_id_3 = "inv_fifo_test_003"
        
        self.amt_1 = inr_to_paise(10000.0) # ₹10,000 (1,000,000 paise)
        self.amt_2 = inr_to_paise(20000.0) # ₹20,000 (2,000,000 paise)
        self.amt_3 = inr_to_paise(15000.0) # ₹15,000 (1,500,000 paise)
        
        # Clean existing test data
        conn = get_connection()
        cur = conn.cursor()
        for inv_id in [self.inv_id_1, self.inv_id_2, self.inv_id_3]:
            cur.execute("DELETE FROM transaction_ledger WHERE invoice_id = %s;", (inv_id,))
            cur.execute("DELETE FROM payment_links WHERE invoice_id = %s;", (inv_id,))
            cur.execute("DELETE FROM master_invoices WHERE invoice_id = %s;", (inv_id,))
        cur.execute("DELETE FROM chat_sessions WHERE customer_phone = %s;", (self.phone,))
        conn.commit()
        conn.close()

    def test_account_fifo_settlement_ledger_and_notifications(self):
        """Tests that account-level FIFO payment correctly creates ledger splits, updates invoices, and sends notifications."""
        # 1. Seed 3 unpaid invoices with ascending due dates
        today = datetime.date.today()
        d1 = (today - datetime.timedelta(days=10)).isoformat()
        d2 = (today - datetime.timedelta(days=5)).isoformat()
        d3 = today.isoformat()

        inv1 = MasterInvoice(
            invoice_id=self.inv_id_1,
            customer_name="FIFO Debtor Corp",
            customer_phone=self.phone,
            original_amount_paise=self.amt_1,
            paid_amount_paise=0,
            remaining_amount_paise=self.amt_1,
            due_date=d1,
            status=InvoiceStatus.UNPAID
        )
        inv2 = MasterInvoice(
            invoice_id=self.inv_id_2,
            customer_name="FIFO Debtor Corp",
            customer_phone=self.phone,
            original_amount_paise=self.amt_2,
            paid_amount_paise=0,
            remaining_amount_paise=self.amt_2,
            due_date=d2,
            status=InvoiceStatus.UNPAID
        )
        inv3 = MasterInvoice(
            invoice_id=self.inv_id_3,
            customer_name="FIFO Debtor Corp",
            customer_phone=self.phone,
            original_amount_paise=self.amt_3,
            paid_amount_paise=0,
            remaining_amount_paise=self.amt_3,
            due_date=d3,
            status=InvoiceStatus.UNPAID
        )

        upsert_invoice(inv1, merchant_id="default_merchant")
        upsert_invoice(inv2, merchant_id="default_merchant")
        upsert_invoice(inv3, merchant_id="default_merchant")

        # 2. Simulate account-level payment of ₹25,000 (2,500,000 paise)
        # Should fully settle inv1 (₹10,000), partially settle inv2 (₹15,000 of ₹20,000), leave inv3 untouched (₹0 of ₹15,000)
        pay_amount_paise = inr_to_paise(25000.0)
        rzp_payment_id = "pay_test_fifo_25k"

        mock_payload = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": rzp_payment_id,
                        "amount": pay_amount_paise,
                        "method": "UPI",
                        "notes": {
                            "invoice_id": "ALL",
                            "customer_phone": self.phone
                        }
                    }
                }
            }
        }

        reconcile_res = asyncio.run(reconcile_payment_event(mock_payload))
        self.assertEqual(reconcile_res.get("status"), "success")
        self.assertEqual(reconcile_res.get("type"), "account_level")
        self.assertEqual(len(reconcile_res.get("distributed", [])), 2)

        # 3. Verify Invoice States
        up_inv1 = get_invoice(self.inv_id_1)
        self.assertEqual(up_inv1.status, InvoiceStatus.PAID)
        self.assertEqual(up_inv1.remaining_amount_paise, 0)
        self.assertEqual(up_inv1.paid_amount_paise, self.amt_1)

        up_inv2 = get_invoice(self.inv_id_2)
        self.assertEqual(up_inv2.status, InvoiceStatus.PARTIALLY_PAID)
        self.assertEqual(up_inv2.paid_amount_paise, inr_to_paise(15000.0))
        self.assertEqual(up_inv2.remaining_amount_paise, inr_to_paise(5000.0))

        up_inv3 = get_invoice(self.inv_id_3)
        self.assertEqual(up_inv3.status, InvoiceStatus.UNPAID)
        self.assertEqual(up_inv3.remaining_amount_paise, self.amt_3)

        # 4. Verify Double-Entry Financial Ledger Splits
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT transaction_type, invoice_id, gross_amount_paise, merchant_amount_paise, platform_fee_paise FROM transaction_ledger WHERE merchant_id = 'default_merchant' AND invoice_id IN (%s, %s) AND transaction_type IN ('INFLOW_CUSTOMER_PAYMENT', 'OUTFLOW_MERCHANT_SETTLEMENT') ORDER BY id ASC;", (self.inv_id_1, self.inv_id_2))
        ledger_rows = cur.fetchall()
        conn.close()

        # Should have 4 entries: INFLOW & OUTFLOW for inv1, INFLOW & OUTFLOW for inv2
        self.assertEqual(len(ledger_rows), 4)

        # Check inv1 splits (97% merchant = 970000 paise, 3% fee = 30000 paise)
        inv1_entries = [r for r in ledger_rows if r["invoice_id"] == self.inv_id_1]
        self.assertEqual(len(inv1_entries), 2)
        self.assertEqual(inv1_entries[0]["gross_amount_paise"], self.amt_1)
        self.assertEqual(inv1_entries[0]["merchant_amount_paise"], int(self.amt_1 * 0.97))
        self.assertEqual(inv1_entries[0]["platform_fee_paise"], int(self.amt_1 * 0.03))

        # Check inv2 splits (97% merchant = 1455000 paise, 3% fee = 45000 paise on 1500000 paise applied)
        inv2_entries = [r for r in ledger_rows if r["invoice_id"] == self.inv_id_2]
        self.assertEqual(len(inv2_entries), 2)
        self.assertEqual(inv2_entries[0]["gross_amount_paise"], inr_to_paise(15000.0))
        self.assertEqual(inv2_entries[0]["merchant_amount_paise"], int(inr_to_paise(15000.0) * 0.97))
        self.assertEqual(inv2_entries[0]["platform_fee_paise"], int(inr_to_paise(15000.0) * 0.03))

        # 5. Verify WhatsApp confirmation receipt was logged in chat session
        session = session_manager.get_or_create_session(customer_phone=self.phone)
        self.assertTrue(len(session.messages) > 0)
        latest_msg = session.messages[-1]
        self.assertIn("Payment Received & Allocated!", latest_msg.text)
        self.assertIn("FIFO Debtor Corp", latest_msg.text)
        self.assertIn(self.inv_id_1, latest_msg.text)
        self.assertIn(self.inv_id_2, latest_msg.text)


if __name__ == "__main__":
    unittest.main()
