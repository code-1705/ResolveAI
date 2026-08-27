import sys
import os
import unittest
import asyncio
from fastapi import HTTPException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.models import Merchant
from backend.auth import require_verified_merchant_bank
from backend.database import init_db
from backend.main import create_invoice, CreateInvoiceRequest, save_merchant_guardrails, GuardrailsUpdateRequest

class TestBankVerificationGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_unconfigured_bank_merchant_blocked_with_403(self):
        """Merchant without bank account setup must be blocked from financial endpoints."""
        unverified_merchant = Merchant(
            merchant_id="merchant_nobank_001",
            email="nobank@test.com",
            business_name="No Bank SME",
            settlement_status="PENDING",
            bank_account_number=None,
            bank_ifsc=None
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(require_verified_merchant_bank(unverified_merchant))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Bank account setup and verification is required", ctx.exception.detail)

    def test_invalid_ifsc_blocked_with_403(self):
        """Merchant with malformed IFSC must be blocked."""
        bad_ifsc_merchant = Merchant(
            merchant_id="merchant_badifsc_002",
            email="badifsc@test.com",
            business_name="Bad IFSC SME",
            settlement_status="ACTIVE",
            bank_account_number="123456789012",
            bank_ifsc="HDFC123"  # Less than 11 chars
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(require_verified_merchant_bank(bad_ifsc_merchant))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_short_account_number_blocked_with_403(self):
        """Merchant with account number shorter than 8 digits must be blocked."""
        short_acct_merchant = Merchant(
            merchant_id="merchant_shortacct_003",
            email="short@test.com",
            business_name="Short Acct SME",
            settlement_status="ACTIVE",
            bank_account_number="12345",  # Less than 8 chars
            bank_ifsc="HDFC0001234"
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(require_verified_merchant_bank(short_acct_merchant))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_verified_merchant_passes_gate(self):
        """Merchant with verified settlement status and valid IFSC/Account must pass successfully."""
        verified_merchant = Merchant(
            merchant_id="merchant_valid_004",
            email="valid@test.com",
            business_name="Valid Enterprise",
            settlement_status="ACTIVE",
            bank_account_number="98765432109876",
            bank_ifsc="HDFC0001234",
            bank_beneficiary_name="Valid Enterprise Ltd",
            bank_name="HDFC Bank"
        )
        res = asyncio.run(require_verified_merchant_bank(verified_merchant))
        self.assertEqual(res.merchant_id, "merchant_valid_004")

    def test_create_invoice_requires_bank_verification(self):
        """create_invoice must reject unverified merchants when called."""
        unverified_merchant = Merchant(
            merchant_id="merchant_nobank_005",
            email="nobank5@test.com",
            business_name="No Bank SME",
            settlement_status="PENDING"
        )
        req = CreateInvoiceRequest(
            customer_name="John Doe",
            customer_phone="+919876543210",
            original_amount_inr=5000.0,
            due_date="2026-09-01"
        )
        # require_verified_merchant_bank raises 403 when called with unverified_merchant
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(require_verified_merchant_bank(unverified_merchant))
        self.assertEqual(ctx.exception.status_code, 403)

if __name__ == "__main__":
    unittest.main()
