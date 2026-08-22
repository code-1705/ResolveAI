import os
import sys
import unittest
import json
from fastapi.testclient import TestClient

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.config import settings
from backend.seed_data import seed_database
from backend.main import app

class TestSubmodule4(unittest.TestCase):
    def setUp(self):
        self.test_db_path = os.path.join(os.path.dirname(__file__), "test_sub4_resolve_ai.db")
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)
        settings.DATABASE_PATH = self.test_db_path
        seed_database(self.test_db_path)
        self.client = TestClient(app)

    def tearDown(self):
        if os.path.exists(self.test_db_path):
            os.remove(self.test_db_path)

    def test_1_list_invoices_endpoint(self):
        """Test GET /api/invoices returns 3 seeded overdue Indian SME invoices."""
        res = self.client.get("/api/invoices")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 3)
        invoice_ids = {inv["invoice_id"] for inv in data}
        self.assertIn("inv_SME_001", invoice_ids)
        self.assertIn("inv_SME_002", invoice_ids)
        self.assertIn("inv_SME_003", invoice_ids)

    def test_2_guardrails_endpoints(self):
        """Test GET & POST /api/guardrails fetches and updates merchant policies."""
        # 1. GET
        res_get = self.client.get("/api/guardrails")
        self.assertEqual(res_get.status_code, 200)
        self.assertEqual(res_get.json()["min_partial_payment_pct"], 30.0)

        # 2. POST Update
        update_payload = {
            "min_partial_payment_pct": 40.0,
            "max_extension_days": 21,
            "max_split_installments": 4,
            "auto_discount_waiver_pct": 5.0,
            "tone": "firm"
        }
        res_post = self.client.post("/api/guardrails", json=update_payload)
        self.assertEqual(res_post.status_code, 200)
        self.assertEqual(res_post.json()["min_partial_payment_pct"], 40.0)
        self.assertEqual(res_post.json()["max_extension_days"], 21)

    def test_3_chat_message_simulator_endpoint(self):
        """Test POST /api/chat/message chat simulator endpoint returning agent message & visual trace."""
        chat_payload = {
            "session_id": "+919876543210_inv_SME_001",
            "invoice_id": "inv_SME_001",
            "customer_phone": "+919876543210",
            "message": "Can I pay ₹20,000 today and the rest next week?"
        }
        res = self.client.post("/api/chat/message", json=chat_payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("approved", data["response_text"].lower())
        self.assertIsNotNone(data["trace"]["payment_link_url"])
        self.assertEqual(data["trace"]["guardrail_check"]["status"], "PASS")

    def test_4_analytics_endpoint(self):
        """Test GET /api/analytics returns total TPV metrics."""
        res = self.client.get("/api/analytics")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total_overdue_tpv_inr"], 205000.00)  # 50k + 120k + 35k
        self.assertEqual(data["recovered_tpv_inr"], 0.00)
        self.assertEqual(data["recovery_rate_pct"], 0.00)

    def test_5_razorpay_webhook_endpoint(self):
        """Test POST /api/webhooks/razorpay accepts raw body and returns HTTP 200 immediately."""
        webhook_body = {
            "event": "payment_link.paid",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_TEST_WEBHOOK_001",
                        "payment_link_id": "plink_SME_001",
                        "amount": 2000000,
                        "method": "upi",
                        "notes": {"invoice_id": "inv_SME_001"}
                    }
                }
            }
        }
        res = self.client.post(
            "/api/webhooks/razorpay",
            content=json.dumps(webhook_body),
            headers={"Content-Type": "application/json"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "ok")

    def test_6_meta_whatsapp_webhook_verification(self):
        """Test GET /api/webhooks/whatsapp Meta challenge handshake."""
        res = self.client.get(
            f"/api/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token={settings.META_VERIFY_TOKEN}&hub.challenge=test_challenge_123"
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.text, "test_challenge_123")

if __name__ == "__main__":
    unittest.main()
