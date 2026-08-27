import sys
import os
import unittest
import asyncio
import jwt
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from backend.config import settings
from backend.models import MasterInvoice, InvoiceStatus, Merchant
from backend.database import init_db, upsert_invoice, get_invoice
from backend.main import edit_invoice, get_invoice_detail, EditInvoiceRequest
from backend.auth import get_current_merchant

class TestInvoiceAuthSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def setUp(self):
        self.owner_merchant = Merchant(
            merchant_id="merchant_owner_001",
            email="owner@test.com",
            business_name="Owner Merchant Corp"
        )
        self.attacker_merchant = Merchant(
            merchant_id="merchant_attacker_002",
            email="attacker@test.com",
            business_name="Attacker Corp"
        )

        self.invoice_id = "inv_sec_test_001"
        self.test_invoice = MasterInvoice(
            invoice_id=self.invoice_id,
            customer_name="Customer Protected",
            customer_phone="+919876543210",
            original_amount_paise=100000,
            paid_amount_paise=0,
            remaining_amount_paise=100000,
            due_date="2026-09-01",
            status=InvoiceStatus.UNPAID,
            merchant_id="merchant_owner_001"
        )
        upsert_invoice(self.test_invoice, merchant_id="merchant_owner_001")

    def test_owner_can_get_invoice_detail(self):
        """Owner merchant should successfully retrieve their own invoice."""
        res = asyncio.run(get_invoice_detail(self.invoice_id, merchant=self.owner_merchant))
        self.assertEqual(res["invoice_id"], self.invoice_id)
        self.assertEqual(res["customer_name"], "Customer Protected")

    def test_non_owner_cannot_get_invoice_detail(self):
        """Another merchant attempting to read someone else's invoice must receive 403 Forbidden."""
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_invoice_detail(self.invoice_id, merchant=self.attacker_merchant))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("permission", ctx.exception.detail.lower())

    def test_owner_can_edit_invoice(self):
        """Owner merchant should successfully update their own invoice."""
        req = EditInvoiceRequest(
            customer_name="Customer Updated By Owner",
            customer_phone="+919876543210",
            due_date="2026-09-15"
        )
        res = asyncio.run(edit_invoice(self.invoice_id, req=req, merchant=self.owner_merchant))
        self.assertTrue(res["success"])
        
        # Verify in DB
        updated = get_invoice(self.invoice_id)
        self.assertEqual(updated.customer_name, "Customer Updated By Owner")
        self.assertEqual(updated.due_date, "2026-09-15")

    def test_non_owner_cannot_edit_invoice(self):
        """Another merchant attempting to edit someone else's invoice must receive 403 Forbidden."""
        req = EditInvoiceRequest(
            customer_name="Hacked Name",
            customer_phone="+919876543210",
            due_date="2026-09-01",
            manual_payment_inr=1000.0  # Attempting fraudulent manual settlement
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(edit_invoice(self.invoice_id, req=req, merchant=self.attacker_merchant))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("permission", ctx.exception.detail.lower())

        # Verify DB was NOT mutated
        inv = get_invoice(self.invoice_id)
        self.assertNotEqual(inv.customer_name, "Hacked Name")

if __name__ == "__main__":
    unittest.main()
