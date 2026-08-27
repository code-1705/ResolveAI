"""
Authentication Module
Provides JWT verification and role-based access control dependencies for FastAPI.
"""

import os
import json
import base64
import jwt
from typing import Optional
from fastapi import Request, HTTPException, Security, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from backend.core.config import settings
from backend.models.core import Merchant
from backend.core.database import get_or_create_merchant, get_merchant_by_id

security = HTTPBearer(auto_error=False)

async def get_current_merchant(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security)
) -> Merchant:
    """
    Cryptographically validates JWT authentication token and ensures merchant is in DB.
    Rejects unauthenticated or invalid tokens with HTTP 401 Unauthorized.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=401,
            detail="Authentication credentials required. Please provide a valid Bearer token."
        )

    token = credentials.credentials.strip()
    payload = None

    if "." in token:
        # 1. Primary: Verify signature with platform JWT_SECRET
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET,
                algorithms=[settings.JWT_ALGORITHM],
                options={"verify_signature": True}
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Authentication token has expired. Please log in again.")
        except jwt.InvalidTokenError:
            # 2. Secondary fallback: Attempt verification with Supabase secret if configured
            if settings.SUPABASE_SERVICE_KEY:
                try:
                    payload = jwt.decode(
                        token,
                        settings.SUPABASE_SERVICE_KEY,
                        algorithms=["HS256"],
                        options={"verify_signature": True}
                    )
                except Exception:
                    pass

            if not payload:
                raise HTTPException(status_code=401, detail="Invalid authentication token signature.")
    else:
        raise HTTPException(status_code=401, detail="Invalid authentication token format.")

    user_id = payload.get("sub") or payload.get("merchant_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload: missing merchant identifier.")

    email = payload.get("email", f"{user_id}@resolveai.com")
    metadata = payload.get("user_metadata", {})
    business_name = metadata.get("business_name") or metadata.get("name") or email.split("@")[0].capitalize()
    phone = metadata.get("phone")

    merchant = get_or_create_merchant(
        merchant_id=user_id,
        email=email,
        business_name=business_name,
        phone=phone
    )
    return merchant


async def require_verified_merchant_bank(
    merchant: Merchant = Depends(get_current_merchant)
) -> Merchant:
    """
    Strict financial authorization gate: Blocks access to invoices, analytics, guardrails,
    and collection tools until the merchant has verified their official Bank Account & IFSC.
    """
    has_valid_bank = bool(
        merchant.bank_account_number and
        len(str(merchant.bank_account_number).strip()) >= 8 and
        merchant.bank_ifsc and
        len(str(merchant.bank_ifsc).strip()) == 11
    )
    is_verified = (merchant.settlement_status in ["VERIFIED", "ACTIVE"]) and has_valid_bank

    if not is_verified:
        raise HTTPException(
            status_code=403,
            detail="Bank account setup and verification is required before accessing merchant features."
        )
    return merchant
