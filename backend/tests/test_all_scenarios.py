import sys
import os
import unittest
import asyncio
import datetime
import json
from typing import Dict, Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.core.database import (
    init_db,
    upsert_invoice,
    get_invoice,
    get_guardrails,
    update_guardrails,
    get_connection
)
from backend.models.core import MasterInvoice, InvoiceStatus, MerchantGuardrails
from backend.services.guardrails import GuardrailEngine, inr_to_paise, paise_to_inr
from backend.services.session import session_manager
from backend.integrations.razorpay import razorpay_client
from backend.integrations.whatsapp import whatsapp_client
from backend.services.webhooks import reconcile_payment_event
from backend.main import check_due_date_reminders_job


class TestResolveAIScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Initializes database schema before running tests."""
        init_db()

    def setUp(self):
        """Prepares standard test data for each test run."""
        self.phone = "+919999900001"
        self.invoice_id = "inv_test_999"
        self.amount_inr = 50000.0
        self.paise_amount = inr_to_paise(self.amount_inr)
        self.today_str = datetime.date.today().isoformat()

        # Clean existing test data (delete child records first to satisfy foreign key constraints)
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM transaction_ledger WHERE invoice_id = %s;", (self.invoice_id,))
        cur.execute("DELETE FROM payment_links WHERE invoice_id = %s;", (self.invoice_id,))
        cur.execute("DELETE FROM chat_sessions WHERE customer_phone = %s;", (self.phone,))
        cur.execute("DELETE FROM master_invoices WHERE invoice_id = %s;", (self.invoice_id,))
        conn.commit()
        conn.close()

    def test_scenario_1_entering_invoice_stores_in_db(self):
        """Scenario 1: When entering invoice it stores in DB."""
        inv = MasterInvoice(
            invoice_id=self.invoice_id,
            customer_name="Apex Logistics Test",
            customer_phone=self.phone,
            original_amount_paise=self.paise_amount,
            paid_amount_paise=0,
            remaining_amount_paise=self.paise_amount,
            due_date=self.today_str,
            status=InvoiceStatus.UNPAID
        )

        saved_inv = upsert_invoice(inv, merchant_id="default_merchant")
        self.assertIsNotNone(saved_inv)

        # Retrieve directly from DB
        retrieved = get_invoice(self.invoice_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.invoice_id, self.invoice_id)
        self.assertEqual(retrieved.customer_name, "Apex Logistics Test")
        self.assertEqual(retrieved.customer_phone, self.phone)
        self.assertEqual(retrieved.original_amount_paise, self.paise_amount)
        self.assertEqual(retrieved.remaining_amount_paise, self.paise_amount)
        self.assertEqual(retrieved.status, InvoiceStatus.UNPAID)
        print("[PASS] Scenario 1: Invoice saved and verified in DB.")

    def test_scenario_2_due_date_automatic_whatsapp_message(self):
        """Scenario 2: When due date comes automatically WhatsApp message goes to buyer."""
        # 1. Ensure an overdue/due-today invoice exists in DB
        inv = MasterInvoice(
            invoice_id=self.invoice_id,
            customer_name="Vanguard Web Test",
            customer_phone=self.phone,
            original_amount_paise=self.paise_amount,
            paid_amount_paise=0,
            remaining_amount_paise=self.paise_amount,
            due_date=self.today_str,
            status=InvoiceStatus.UNPAID
        )
        upsert_invoice(inv)

        # 2. Run the automated due date reminder job
        res = asyncio.run(check_due_date_reminders_job())
        self.assertEqual(res.get("status"), "success")
        self.assertGreaterEqual(res.get("reminders_sent", 0), 1)

        # 3. Assert message is logged in chat_sessions
        session = session_manager.get_or_create_session(customer_phone=self.phone, invoice_id=self.invoice_id)
        self.assertTrue(len(session.messages) > 0)
        latest_msg = session.messages[-1]
        self.assertIn("Payment Reminder", latest_msg.text)
        self.assertIn(self.invoice_id, latest_msg.text)
        print("[PASS] Scenario 2: Automatic due-date WhatsApp reminder dispatched successfully.")

    def test_scenario_3_opening_message_contains_invoice(self):
        """Scenario 3: The opening message contains the invoice itself."""
        inv = MasterInvoice(
            invoice_id=self.invoice_id,
            customer_name="GreenLeaf Organics Test",
            customer_phone=self.phone,
            original_amount_paise=self.paise_amount,
            paid_amount_paise=0,
            remaining_amount_paise=self.paise_amount,
            due_date=self.today_str,
            status=InvoiceStatus.UNPAID
        )
        upsert_invoice(inv)

        # Retrieve/initialize brand new session
        session = session_manager.get_or_create_session(customer_phone=self.phone, invoice_id=self.invoice_id)
        self.assertTrue(len(session.messages) >= 1)

        opening_msg = session.messages[0]
        self.assertEqual(opening_msg.sender, "agent")
        self.assertIn("reaching out regarding Invoice", opening_msg.text)
        self.assertIn(self.invoice_id, opening_msg.text)

        # Check metadata document URL
        media_docs = opening_msg.metadata.get("media_documents", [])
        self.assertTrue(len(media_docs) > 0)
        self.assertEqual(media_docs[0]["invoice_id"], self.invoice_id)
        self.assertIn("/document", media_docs[0]["url"])
        print("[PASS] Scenario 3: Opening message contains invoice bill details & attachment link.")

    def test_scenario_4_ai_able_to_negotiate_correctly(self):
        """Scenario 4: AI able to negotiate correctly within guardrail boundaries."""
        inv = MasterInvoice(
            invoice_id=self.invoice_id,
            customer_name="Apex Logistics Test",
            customer_phone=self.phone,
            original_amount_paise=self.paise_amount,
            paid_amount_paise=0,
            remaining_amount_paise=self.paise_amount,
            due_date=self.today_str,
            status=InvoiceStatus.UNPAID
        )
        upsert_invoice(inv)

        engine = GuardrailEngine()

        # Case A: Lowball offer below min partial payment threshold (e.g. 5% = ₹2,500)
        passed_lowball, reason_lowball, meta_lowball = engine.validate_proposal(
            invoice_id=self.invoice_id,
            proposed_amount_inr=2500.0,
            extension_days=7,
            customer_phone=self.phone
        )
        self.assertFalse(passed_lowball)
        self.assertIn("below the merchant's minimum threshold", reason_lowball)
        self.assertGreaterEqual(meta_lowball["suggested_amount_inr"], 15000.0)

        # Case B: Acceptable proposal (50% payment = ₹25,000, 7 days extension)
        passed_valid, reason_valid, meta_valid = engine.validate_proposal(
            invoice_id=self.invoice_id,
            proposed_amount_inr=25000.0,
            extension_days=7,
            customer_phone=self.phone
        )
        self.assertTrue(passed_valid)
        self.assertEqual(reason_valid, "Proposal passed all merchant guardrail and platform safety checks.")
        self.assertEqual(meta_valid["approved_amount_inr"], 25000.0)

        print("[PASS] Scenario 4: Guardrail engine correctly evaluates proposals & generates counter-offers.")

    def test_scenario_5_payment_link_generated_correctly(self):
        """Scenario 5: Payment link is generated correctly."""
        amount_inr = 25000.0
        amount_paise = inr_to_paise(amount_inr)

        link_data = razorpay_client.create_payment_link(
            amount_in_paise=amount_paise,
            description=f"Settlement for Invoice {self.invoice_id}",
            customer_info={
                "name": "Test Customer",
                "phone": self.phone,
                "invoice_id": self.invoice_id
            },
            expiry_timestamp=int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)).timestamp()),
            reference_id=f"ref_test_{int(datetime.datetime.now().timestamp())}"
        )

        self.assertIsNotNone(link_data)
        self.assertIn("short_url", link_data)
        self.assertTrue(link_data["short_url"].startswith("http"))
        self.assertEqual(link_data["amount"], amount_paise)
        print(f"[PASS] Scenario 5: Payment link generated correctly ({link_data['short_url']}).")

    def test_scenario_6_automatic_payment_confirmation(self):
        """Scenario 6: User automatically gets payment confirmation message after payment is done."""
        inv = MasterInvoice(
            invoice_id=self.invoice_id,
            customer_name="Confirmation Test Client",
            customer_phone=self.phone,
            original_amount_paise=self.paise_amount,
            paid_amount_paise=0,
            remaining_amount_paise=self.paise_amount,
            due_date=self.today_str,
            status=InvoiceStatus.UNPAID
        )
        upsert_invoice(inv)

        # Simulate Razorpay payment.captured webhook payload
        mock_webhook_payload = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_test_scenario_6_full",
                        "amount": self.paise_amount,
                        "method": "UPI",
                        "notes": {
                            "invoice_id": self.invoice_id,
                            "customer_phone": self.phone
                        }
                    }
                }
            }
        }

        reconcile_res = asyncio.run(reconcile_payment_event(mock_webhook_payload))
        self.assertEqual(reconcile_res.get("status"), "success")

        # 1. Verify DB status updated to PAID
        updated_inv = get_invoice(self.invoice_id)
        self.assertEqual(updated_inv.status, InvoiceStatus.PAID)
        self.assertEqual(updated_inv.remaining_amount_paise, 0)
        self.assertEqual(updated_inv.paid_amount_paise, self.paise_amount)

        # 2. Verify confirmation receipt message in chat history
        session = session_manager.get_or_create_session(customer_phone=self.phone, invoice_id=self.invoice_id)
        latest_msg = session.messages[-1]
        self.assertIn("Payment Confirmed!", latest_msg.text)
        self.assertIn("fully settled", latest_msg.text)

        print("[PASS] Scenario 6: Invoice status updated to PAID and payment confirmation receipt sent.")


if __name__ == "__main__":
    unittest.main()
