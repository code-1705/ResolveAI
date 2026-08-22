import os
import sys
import unittest
import asyncio
import time

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.config import settings
from backend.models import MasterInvoice, InvoiceStatus
from backend.database import init_db, upsert_invoice, get_invoice
from backend.session_manager import SessionManager
from backend.agent import AgenticNegotiator

class TestSubmodule3(unittest.TestCase):
    def setUp(self):
        self.test_db_path = os.path.join(os.path.dirname(__file__), "test_sub3_resolve_ai.db")
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        init_db(self.test_db_path)
        self.session_mgr = SessionManager(db_path=self.test_db_path)
        self.negotiator = AgenticNegotiator(db_path=self.test_db_path)

    def tearDown(self):
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_1_session_manager_history_retention(self):
        """Test SessionManager chat session initialization and rolling history retrieval."""
        session_id = "+919876543210_inv_SME_001"
        self.session_mgr.get_or_create_session(session_id, "inv_SME_001", "+919876543210")

        self.session_mgr.add_message(session_id, "user", "Hi, I received the invoice.")
        self.session_mgr.add_message(session_id, "agent", "Hello! Let us know if you need flexible payment terms.")
        self.session_mgr.add_message(session_id, "user", "Can I pay 40% today?")

        history = self.session_mgr.get_recent_history(session_id, limit=5)
        self.assertEqual(len(history), 3)
        self.assertEqual(history[0].text, "Hi, I received the invoice.")
        self.assertEqual(history[2].text, "Can I pay 40% today?")

    def test_2_anti_hallucination_text_payment_claim(self):
        """Test anti-hallucination directive: Text payment claims do NOT trigger fund confirmation without verified DB status."""
        inv = MasterInvoice(
            invoice_id="inv_SME_001",
            customer_name="Apex Logistics",
            customer_phone="+919876543210",
            original_amount_paise=5000000,  # ₹50,000
            remaining_amount_paise=5000000,
            due_date="2026-08-10",
            status=InvoiceStatus.UNPAID
        )
        upsert_invoice(inv, db_path=self.test_db_path)

        session_id = "+919876543210_inv_SME_001"

        # Run Negotiator for Text Claim: "I just paid 50000 via UPI"
        res = asyncio.run(self.negotiator.process_customer_message(
            session_id=session_id,
            invoice_id="inv_SME_001",
            customer_phone="+919876543210",
            customer_message="I just paid 50000 via UPI"
        ))

        # Verify LLM responds politely without hallucinating receipt confirmation
        self.assertIn("Resolve.ai reconciles funds automatically via Razorpay webhooks", res["response_text"])
        self.assertEqual(res["trace"]["guardrail_check"]["status"], "PASS")
        self.assertEqual(res["trace"]["guardrail_check"]["rule"], "anti_hallucination_fund_check")

    def test_3_guardrail_rejection_lowball_offer(self):
        """Test GuardrailEngine hard rejection & counter-offer flow for lowball 10% offer (below 30% min)."""
        inv = MasterInvoice(
            invoice_id="inv_SME_002",
            customer_name="Vanguard Web Studios",
            customer_phone="+919876543211",
            original_amount_paise=10000000,  # ₹1,00,000
            remaining_amount_paise=10000000,
            due_date="2026-08-12",
            status=InvoiceStatus.UNPAID
        )
        upsert_invoice(inv, db_path=self.test_db_path)

        session_id = "+919876543211_inv_SME_002"

        # User offers 10% payment (₹10,000)
        res = asyncio.run(self.negotiator.process_customer_message(
            session_id=session_id,
            invoice_id="inv_SME_002",
            customer_phone="+919876543211",
            customer_message="I can only pay 10% today"
        ))

        # Verify Guardrail REJECTED API call and issued polite counter-offer
        self.assertIn("minimum threshold of 30.0%", res["response_text"])
        self.assertIn("₹30,000.00", res["response_text"])  # 30% counter-offer
        self.assertIsNone(res["trace"]["payment_link_url"])
        self.assertEqual(res["trace"]["guardrail_check"]["status"], "REJECT")

    def test_4_guardrail_approval_and_payment_link_generation(self):
        """Test GuardrailEngine approval flow for valid 40% initial payment request."""
        inv = MasterInvoice(
            invoice_id="inv_SME_003",
            customer_name="GreenLeaf Organics",
            customer_phone="+919876543212",
            original_amount_paise=5000000,  # ₹50,000
            remaining_amount_paise=5000000,
            due_date="2026-08-15",
            status=InvoiceStatus.UNPAID
        )
        upsert_invoice(inv, db_path=self.test_db_path)

        session_id = "+919876543212_inv_SME_003"

        # User requests 40% payment (₹20,000) for 7 days extension
        res = asyncio.run(self.negotiator.process_customer_message(
            session_id=session_id,
            invoice_id="inv_SME_003",
            customer_phone="+919876543212",
            customer_message="Can I do ₹20,000 today and the rest in 7 days?"
        ))

        # Verify Guardrail PASSED and Payment Link was created!
        self.assertIn("approved", res["response_text"].lower())
        self.assertIsNotNone(res["trace"]["payment_link_url"])
        self.assertTrue(res["trace"]["payment_link_url"].startswith("https://rzp.io/i/"))
        self.assertEqual(res["trace"]["currency_conversion"]["approved_amount_paise"], 2000000)  # ₹20,000 in paise
        self.assertEqual(res["trace"]["tool_executed"], "create_razorpay_payment_link")

if __name__ == "__main__":
    unittest.main()
