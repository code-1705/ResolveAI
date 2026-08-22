import os
import sys
import unittest
import asyncio
import json
import time
import hmac
import hashlib

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.config import settings
from backend.models import MasterInvoice, InvoiceStatus
from backend.database import init_db, upsert_invoice, get_invoice, get_connection
from backend.razorpay_client import RazorpayClient
from backend.whatsapp_client import WhatsAppCloudClient
from backend.webhooks import (
    verify_meta_webhook,
    process_whatsapp_webhook,
    reconcile_payment_event
)

class TestSubmodule2(unittest.TestCase):
    def setUp(self):
        self.test_db_path = os.path.join(os.path.dirname(__file__), "test_sub2_resolve_ai.db")
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        init_db(self.test_db_path)
        self.rzp = RazorpayClient(webhook_secret="test_secret_123")
        self.wa = WhatsAppCloudClient()

    def tearDown(self):
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_1_razorpay_payment_link_reference_id_idempotency(self):
        """Test Razorpay payment link creation formats integer paise and enforces reference_id payload idempotency."""
        link_res = self.rzp.create_payment_link(
            amount_in_paise=2000050,  # ₹20,000.50 in paise
            description="Partial payment for Invoice inv_TEST_001",
            customer_info={"name": "Apex Logistics", "phone": "+919876543210"},
            expiry_timestamp=int(time.time()) + 86400,
            reference_id=f"ref_test_{int(time.time())}"
        )
        self.assertEqual(link_res["amount"], 2000050)
        self.assertTrue(link_res["reference_id"].startswith("ref_test_"))
        self.assertTrue(link_res["short_url"].startswith("https://"))

    def test_2_raw_byte_hmac_signature_verification(self):
        """Test HMAC-SHA256 signature verification directly over raw request bytes."""
        raw_bytes = b'{"event":"payment_link.paid","payload":{"payment":{"entity":{"id":"pay_123"}}}}'
        import hmac, hashlib
        valid_signature = hmac.new(b"test_secret_123", raw_bytes, hashlib.sha256).hexdigest()

        # Valid Signature -> Pass
        self.assertTrue(self.rzp.verify_webhook_signature(raw_bytes, valid_signature, "test_secret_123"))

        # Invalid Signature -> Fail
        self.assertFalse(self.rzp.verify_webhook_signature(raw_bytes, "invalid_sig_999", "test_secret_123"))

    def test_3_meta_whatsapp_webhook_handshake_and_routing(self):
        """Test Meta WhatsApp GET verification handshake & POST interactive button payload parsing."""
        # 1. GET Handshake
        valid_hs, challenge = verify_meta_webhook("subscribe", settings.META_VERIFY_TOKEN, "challenge_12345")
        self.assertTrue(valid_hs)
        self.assertEqual(challenge, "challenge_12345")

        invalid_hs, _ = verify_meta_webhook("subscribe", "wrong_token", "challenge_12345")
        self.assertFalse(invalid_hs)

        # Seed Invoice for Phone Matching
        inv = MasterInvoice(
            invoice_id="inv_WA_001",
            customer_name="WhatsApp SME Corp",
            customer_phone="+919999988888",
            original_amount_paise=5000000,
            remaining_amount_paise=5000000,
            due_date="2026-08-15"
        )
        upsert_invoice(inv, db_path=self.test_db_path)

        # 2. POST Text Message -> Single Invoice Auto-Route
        text_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "+919999988888",
                            "type": "text",
                            "text": {"body": "I can pay 40% today"}
                        }]
                    }
                }]
            }]
        }
        res_text = process_whatsapp_webhook(text_payload, db_path=self.test_db_path)
        self.assertEqual(res_text["status"], "routed")
        self.assertEqual(res_text["session_id"], "+919999988888_inv_WA_001")

        # 3. POST Interactive Button Reply -> Composite Session Routing
        interactive_payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "+919999988888",
                            "type": "interactive",
                            "interactive": {
                                "button_reply": {
                                    "id": "select_invoice_inv_WA_001",
                                    "title": "Invoice inv_WA_001"
                                }
                            }
                        }]
                    }
                }]
            }]
        }
        res_btn = process_whatsapp_webhook(interactive_payload, db_path=self.test_db_path)
        self.assertEqual(res_btn["status"], "routed")
        self.assertEqual(res_btn["session_id"], "+919999988888_inv_WA_001")
        self.assertTrue(res_btn["is_interactive"])

    def test_4_asynchronous_row_locked_webhook_reconciliation(self):
        """Test asynchronous Razorpay webhook reconciliation inside invoice row lock with exact integer paise math."""
        inv = MasterInvoice(
            invoice_id="inv_RECON_001",
            customer_name="Reconcile Logistics",
            customer_phone="+918888877777",
            original_amount_paise=5000000,  # ₹50,000.00
            paid_amount_paise=0,
            remaining_amount_paise=5000000,
            due_date="2026-08-10",
            status=InvoiceStatus.UNPAID
        )
        upsert_invoice(inv, db_path=self.test_db_path)

        # Seed Payment Link Record
        conn = get_connection(self.test_db_path)
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO payment_links (invoice_id, razorpay_payment_link_id, amount_paise, status, reference_id, created_at)
        VALUES ('inv_RECON_001', 'plink_RECON_123', 2000000, 'ACTIVE', 'ref_8888877777_inv_RECON_001_t1', '2026-08-20T00:00:00Z');
        """)
        conn.commit()
        conn.close()

        # Webhook Payload 1: Partial Payment ₹20,000 (2,000,000 paise)
        webhook_payload_1 = {
            "event": "payment_link.paid",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_RECON_PARTIAL_001",
                        "payment_link_id": "plink_RECON_123",
                        "amount": 2000000,
                        "method": "upi",
                        "notes": {"invoice_id": "inv_RECON_001"}
                    }
                }
            }
        }

        # Run Async Reconciler inside asyncio loop
        res_1 = asyncio.run(reconcile_payment_event(webhook_payload_1, db_path=self.test_db_path))

        self.assertEqual(res_1["status"], "reconciled")
        self.assertEqual(res_1["new_status"], "PARTIALLY_PAID")
        self.assertEqual(res_1["new_remaining_paise"], 3000000)  # ₹30,000 remaining

        # Verify DB Updated
        inv_updated = get_invoice("inv_RECON_001", db_path=self.test_db_path)
        self.assertEqual(inv_updated.paid_amount_paise, 2000000)
        self.assertEqual(inv_updated.remaining_amount_paise, 3000000)
        self.assertEqual(inv_updated.status, InvoiceStatus.PARTIALLY_PAID)

        # Webhook Payload 2: Duplicate Delivery of same payment_id -> Idempotency Ignore!
        res_dup = asyncio.run(reconcile_payment_event(webhook_payload_1, db_path=self.test_db_path))
        self.assertEqual(res_dup["status"], "ignored")
        self.assertEqual(res_dup["reason"], "duplicate_payment_id")

        # Webhook Payload 3: Final Remaining Balance Payment ₹30,000 (3,000,000 paise) -> Status PAID
        webhook_payload_2 = {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_RECON_FINAL_002",
                        "payment_link_id": "plink_RECON_123",
                        "amount": 3000000,
                        "method": "card",
                        "notes": {"invoice_id": "inv_RECON_001"}
                    }
                }
            }
        }
        res_final = asyncio.run(reconcile_payment_event(webhook_payload_2, db_path=self.test_db_path))
        self.assertEqual(res_final["status"], "reconciled")
        self.assertEqual(res_final["new_status"], "PAID")
        self.assertEqual(res_final["new_remaining_paise"], 0)

        # Verify DB Final State
        inv_final = get_invoice("inv_RECON_001", db_path=self.test_db_path)
        self.assertEqual(inv_final.paid_amount_paise, 5000000)
        self.assertEqual(inv_final.remaining_amount_paise, 0)
        self.assertEqual(inv_final.status, InvoiceStatus.PAID)

    def test_5_razorpay_standard_checkout_order_and_signature_verification(self):
        """Test Razorpay standard checkout order creation and HMAC-SHA256 signature verification."""
        # 1. Test Order Creation (amount >= 100 paise)
        order = self.rzp.create_order(amount_in_paise=500000, receipt="rcpt_test_123")
        self.assertIsNotNone(order["id"])
        self.assertEqual(order["amount"], 500000)

        # 2. Test Invalid Amount (< 100 paise)
        with self.assertRaises(ValueError):
            self.rzp.create_order(amount_in_paise=50)

        # 3. Test Signature Verification
        order_id = "order_12345"
        payment_id = "pay_67890"
        secret = self.rzp.key_secret
        msg = f"{order_id}|{payment_id}"
        valid_signature = hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()

        self.assertTrue(self.rzp.verify_payment_signature(order_id, payment_id, valid_signature))
        self.assertFalse(self.rzp.verify_payment_signature(order_id, payment_id, "invalid_signature_xxx"))

if __name__ == "__main__":
    unittest.main()
