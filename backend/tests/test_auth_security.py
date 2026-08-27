import sys
import os
import unittest
import asyncio
import jwt
import time
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from backend.core.config import settings
from backend.core.auth import get_current_merchant
from backend.core.database import init_db

class TestAuthSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()

    def test_missing_credentials_raises_401(self):
        """Unauthenticated requests must raise 401 Unauthorized, not fallback to default_merchant."""
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_current_merchant(None))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("credentials required", ctx.exception.detail)

    def test_empty_credentials_raises_401(self):
        """Empty Bearer token must raise 401 Unauthorized."""
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_current_merchant(creds))
        self.assertEqual(ctx.exception.status_code, 401)

    def test_forged_jwt_signature_raises_401(self):
        """Tokens signed with an invalid/attacker secret must be rejected."""
        fake_token = jwt.encode(
            {"sub": "victim_merchant_123", "email": "victim@example.com"},
            "attacker_fake_secret_key_long_enough_for_sha256_32bytes",
            algorithm="HS256"
        )
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=fake_token)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_current_merchant(creds))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("signature", ctx.exception.detail.lower())

    def test_non_jwt_string_token_raises_401(self):
        """Arbitrary non-JWT strings must be rejected with 401."""
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="demo_fake_token_12345")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_current_merchant(creds))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("format", ctx.exception.detail.lower())

    def test_valid_jwt_authenticates_successfully(self):
        """Legitimate tokens signed with settings.JWT_SECRET must authenticate successfully."""
        test_merchant_id = "test_merchant_sec_01"
        test_email = "security_test@resolveai.com"
        valid_token = jwt.encode(
            {
                "sub": test_merchant_id,
                "email": test_email,
                "user_metadata": {"business_name": "Security Test Enterprise", "phone": "+919876500000"}
            },
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM
        )
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=valid_token)
        merchant = asyncio.run(get_current_merchant(creds))
        self.assertIsNotNone(merchant)
        self.assertEqual(merchant.merchant_id, test_merchant_id)
        self.assertEqual(merchant.email, test_email)
        self.assertEqual(merchant.business_name, "Security Test Enterprise")

if __name__ == "__main__":
    unittest.main()
