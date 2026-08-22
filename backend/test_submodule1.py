import os
import sys
import unittest

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.config import settings
from backend.models import MasterInvoice, MerchantGuardrails, InvoiceStatus
from backend.database import (
    init_db,
    get_guardrails,
    update_guardrails,
    upsert_invoice,
    get_invoice,
    update_invoice_status,
    record_transaction,
    validate_fsm_transition,
    FSMStateError
)
from backend.guardrails import inr_to_paise, paise_to_inr, GuardrailEngine

class TestSubmodule1(unittest.TestCase):
    def setUp(self):
        self.test_db_path = os.path.join(os.path.dirname(__file__), "test_resolve_ai.db")
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        init_db(self.test_db_path)
        self.engine = GuardrailEngine(db_path=self.test_db_path)

    def tearDown(self):
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_1_currency_math(self):
        """Test integer paise currency conversion eliminates binary float drift."""
        self.assertEqual(inr_to_paise(20000.50), 2000050)
        self.assertEqual(inr_to_paise(50000.00), 5000000)
        self.assertEqual(inr_to_paise(100.10), 10010)
        self.assertEqual(paise_to_inr(2000050), 20000.50)

    def test_2_fsm_lifecycle_transitions(self):
        """Test strict Finite State Machine directional transitions and terminal state protection."""
        # Valid Transitions
        self.assertTrue(validate_fsm_transition("UNPAID", "NEGOTIATING"))
        self.assertTrue(validate_fsm_transition("NEGOTIATING", "PARTIALLY_PAID"))
        self.assertTrue(validate_fsm_transition("PARTIALLY_PAID", "PAID"))

        # Invalid Backward Transitions
        with self.assertRaises(FSMStateError):
            validate_fsm_transition("PAID", "UNPAID")

        with self.assertRaises(FSMStateError):
            validate_fsm_transition("PAID", "PARTIALLY_PAID")

        with self.assertRaises(FSMStateError):
            validate_fsm_transition("PARTIALLY_PAID", "NEGOTIATING")

    def test_3_database_operations(self):
        """Test SQLite table creation, WAL mode configuration, and MasterInvoice persistence."""
        invoice = MasterInvoice(
            invoice_id="inv_TEST_001",
            customer_name="Test Enterprise Pvt Ltd",
            customer_phone="+919876543210",
            original_amount_paise=5000000,  # ₹50,000.00 in paise
            paid_amount_paise=0,
            remaining_amount_paise=5000000,
            due_date="2026-08-15",
            status=InvoiceStatus.UNPAID
        )
        upsert_invoice(invoice, db_path=self.test_db_path)

        retrieved = get_invoice("inv_TEST_001", db_path=self.test_db_path)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.customer_name, "Test Enterprise Pvt Ltd")
        self.assertEqual(retrieved.remaining_amount_inr, 50000.00)

    def test_4_unique_payment_id_idempotency(self):
        """Test TransactionLedger UNIQUE(razorpay_payment_id) constraint catches duplicate payments."""
        invoice = MasterInvoice(
            invoice_id="inv_TEST_002",
            customer_name="Duplicate Test Corp",
            customer_phone="+919876543211",
            original_amount_paise=1000000,
            paid_amount_paise=0,
            remaining_amount_paise=1000000,
            due_date="2026-08-20"
        )
        upsert_invoice(invoice, db_path=self.test_db_path)

        # First Payment Insert -> Success
        success, is_dup = record_transaction(
            invoice_id="inv_TEST_002",
            razorpay_payment_id="pay_H9xK2pL001",
            razorpay_payment_link_id="plink_H9xK2pL001",
            amount_paid_paise=500000,
            payment_method="UPI",
            db_path=self.test_db_path
        )
        self.assertTrue(success)
        self.assertFalse(is_dup)

        # Duplicate Payment Insert -> Caught cleanly by DB Unique Index!
        success_dup, is_dup_caught = record_transaction(
            invoice_id="inv_TEST_002",
            razorpay_payment_id="pay_H9xK2pL001",  # Same payment_id
            razorpay_payment_link_id="plink_H9xK2pL001",
            amount_paid_paise=500000,
            payment_method="UPI",
            db_path=self.test_db_path
        )
        self.assertFalse(success_dup)
        self.assertTrue(is_dup_caught)

    def test_5_guardrail_engine_validation(self):
        """Test GuardrailEngine rule validation (Floor check, Ceiling check, and 180-day Expiry cap)."""
        invoice = MasterInvoice(
            invoice_id="inv_GUARD_001",
            customer_name="Guardrail Client Ltd",
            customer_phone="+919876543212",
            original_amount_paise=5000000,  # ₹50,000.00
            paid_amount_paise=0,
            remaining_amount_paise=5000000,
            due_date="2026-08-01",
            status=InvoiceStatus.UNPAID
        )
        upsert_invoice(invoice, db_path=self.test_db_path)

        # Case A: Valid 40% initial payment request (₹20,000 on ₹50,000 invoice, 7 days extension)
        passed, reason, res = self.engine.validate_proposal("inv_GUARD_001", 20000.00, 7)
        self.assertTrue(passed)
        self.assertEqual(res["approved_amount_paise"], 2000000)

        # Case B: Lowball 10% request (₹5,000 on ₹50,000 invoice, below min 30% threshold)
        passed, reason, counter = self.engine.validate_proposal("inv_GUARD_001", 5000.00, 7)
        self.assertFalse(passed)
        self.assertIn("minimum threshold of 30.0%", reason)
        self.assertEqual(counter["suggested_amount_inr"], 15000.00)  # 30% of ₹50,000

        # Case C: Exceeding Remaining Balance (₹60,000 on ₹50,000 invoice) -> Ceiling Check Failure
        passed, reason, counter = self.engine.validate_proposal("inv_GUARD_001", 60000.00, 7)
        self.assertFalse(passed)
        self.assertIn("exceeds the outstanding remaining balance", reason)

        # Case D1: Exceeding Merchant Policy (Requested 20 days > merchant 14 days)
        passed, reason, counter = self.engine.validate_proposal("inv_GUARD_001", 20000.00, 20)
        self.assertFalse(passed)
        self.assertIn("exceeds the maximum allowed policy of 14 days", reason)

        # Case D2: Exceeding 180-Day Razorpay Platform Cap (Merchant max_extension_days = 200)
        guardrails = get_guardrails(self.test_db_path)
        guardrails.max_extension_days = 200
        update_guardrails(guardrails, self.test_db_path)

        passed, reason, counter = self.engine.validate_proposal("inv_GUARD_001", 20000.00, 190)
        self.assertFalse(passed)
        self.assertIn("exceeds the maximum allowed policy of 180 days", reason)

if __name__ == "__main__":
    unittest.main()
