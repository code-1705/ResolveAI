"""
Auth & Merchant Profile Router
Endpoints for merchant registration, login, and profile management.
"""

import jwt
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, status

from backend.core.config import settings
from backend.models.core import Merchant
from backend.core.auth import get_current_merchant
from backend.core.database import (
    get_connection,
    get_merchant_by_id,
    get_merchant_by_email,
    create_merchant_with_password,
    update_merchant_bank_settlement,
    get_merchant_settlement_ledger,
    update_merchant_razorpay_account
)
from backend.integrations.razorpay import razorpay_client

# Define auth and merchant routers
# Since we have /api/auth and /api/merchant, we can create one router and mount it to /api, 
# or two separate routers. Let's create two routers here and expose both.

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
merchant_router = APIRouter(prefix="/api/merchant", tags=["merchant"])

class BankSettlementUpdateRequest(BaseModel):
    bank_beneficiary_name: str
    bank_account_number: str
    bank_ifsc: str
    bank_name: Optional[str] = None
    upi_id: Optional[str] = None
    pan_number: Optional[str] = None

@merchant_router.get("/settlement-ledger")
async def get_merchant_settlement_ledger_history(merchant: Merchant = Depends(get_current_merchant)):
    """Returns the authenticated merchant's live double-entry settlement ledger."""
    ledger = get_merchant_settlement_ledger(merchant.merchant_id)
    return ledger

@merchant_router.get("/bank-settlement")
async def get_merchant_bank_settlement_config(merchant: Merchant = Depends(get_current_merchant)):
    """Returns the authenticated merchant's configured bank settlement details & 3% platform fee structure."""
    m = get_merchant_by_id(merchant.merchant_id) or merchant
    acc = m.bank_account_number or ""
    masked_acc = f"••••••••{acc[-4:]}" if len(acc) >= 4 else (acc or "Not Configured")
    
    return {
        "merchant_id": m.merchant_id,
        "business_name": m.business_name,
        "bank_beneficiary_name": m.bank_beneficiary_name or m.business_name,
        "bank_account_number": m.bank_account_number or "",
        "bank_account_masked": masked_acc,
        "bank_ifsc": m.bank_ifsc or "",
        "bank_name": m.bank_name or "",
        "upi_id": m.upi_id or "",
        "pan_number": m.pan_number or "",
        "commission_pct": getattr(m, 'commission_pct', 3.0) or 3.0,
        "settlement_payout_pct": 100.0 - (getattr(m, 'commission_pct', 3.0) or 3.0),
        "settlement_cycle": "Instant Direct Settlement (Real-Time)",
        "settlement_status": getattr(m, 'settlement_status', 'ACTIVE') or 'ACTIVE',
        "gateway_mode": "Resolve.ai Master Platform Gateway (Auto 3% Split)"
    }

@merchant_router.post("/bank-settlement")
async def save_merchant_bank_settlement_config(req: BankSettlementUpdateRequest, merchant: Merchant = Depends(get_current_merchant)):
    """Saves or updates merchant bank settlement details for direct 97% automated payout."""
    if not req.bank_account_number.strip() or len(req.bank_account_number.strip()) < 8:
        raise HTTPException(status_code=400, detail="Invalid bank account number (minimum 8 digits required)")
    
    if not req.bank_ifsc.strip() or len(req.bank_ifsc.strip()) != 11:
        raise HTTPException(status_code=400, detail="Invalid IFSC Code (must be exactly 11 characters e.g. HDFC0001234)")

    updated = update_merchant_bank_settlement(
        merchant_id=merchant.merchant_id,
        bank_beneficiary_name=req.bank_beneficiary_name,
        bank_account_number=req.bank_account_number,
        bank_ifsc=req.bank_ifsc,
        bank_name=req.bank_name,
        upi_id=req.upi_id,
        pan_number=req.pan_number
    )
    
    # Automatically provision / link Razorpay Route Linked Account for 97% payouts
    try:
        rzp_acc = razorpay_client.create_linked_account(
            business_name=req.bank_beneficiary_name,
            email=merchant.email,
            bank_account=req.bank_account_number,
            ifsc=req.bank_ifsc,
            pan=req.pan_number
        )
        if rzp_acc.get("id"):
            update_merchant_razorpay_account(merchant.merchant_id, rzp_acc["id"])
            print(f"[Razorpay Route Linked Account Ready]: {rzp_acc['id']} for merchant {merchant.merchant_id}")
    except Exception as e:
        print(f"[Razorpay Route Account Warning]: {e}")
    
    acc = updated.bank_account_number or ""
    masked_acc = f"••••••••{acc[-4:]}" if len(acc) >= 4 else acc

    return {
        "success": True,
        "message": "Bank Settlement Account updated successfully!",
        "merchant": {
            "merchant_id": updated.merchant_id,
            "business_name": updated.business_name,
            "bank_beneficiary_name": updated.bank_beneficiary_name,
            "bank_account_masked": masked_acc,
            "bank_ifsc": updated.bank_ifsc,
            "bank_name": updated.bank_name,
            "upi_id": updated.upi_id,
            "commission_pct": updated.commission_pct,
            "settlement_status": updated.settlement_status
        }
    }

def _hash_merchant_password(password: str) -> str:
    import hashlib
    salt = "resolve_ai_salt_2026_"
    return hashlib.sha256((salt + password).encode()).hexdigest()

class MerchantAuthRequest(BaseModel):
    business_name: Optional[str] = None
    email: str
    password: str
    phone: Optional[str] = None

@auth_router.post("/register")
async def register_merchant_account(req: MerchantAuthRequest):
    """Registers a new merchant and permanently saves them to the PostgreSQL merchants table with hashed password."""
    import hashlib
    email_clean = req.email.strip().lower()
    if not req.password or len(req.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    
    existing = get_merchant_by_email(email_clean)
    if existing:
        raise HTTPException(status_code=400, detail="An account with this email already exists. Please Sign In.")
    
    b_name = (req.business_name or email_clean.split('@')[0]).strip()
    merchant_id = f"m_{hashlib.md5(email_clean.encode()).hexdigest()[:10]}"
    pwd_hash = _hash_merchant_password(req.password)
    
    merchant = create_merchant_with_password(
        merchant_id=merchant_id,
        email=email_clean,
        business_name=b_name,
        password_hash=pwd_hash,
        phone=req.phone
    )
    
    token = jwt.encode({
        "sub": merchant.merchant_id,
        "email": merchant.email,
        "user_metadata": {
            "business_name": merchant.business_name,
            "phone": merchant.phone
        }
    }, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    
    return {
        "session": {
            "access_token": token,
            "user": {
                "id": merchant.merchant_id,
                "email": merchant.email,
                "user_metadata": {
                    "business_name": merchant.business_name,
                    "phone": merchant.phone
                }
            }
        },
        "merchant": merchant
    }

@auth_router.post("/login")
async def login_merchant_account(req: MerchantAuthRequest):
    """Logs in a merchant with strict password hash comparison."""
    import hashlib
    email_clean = req.email.strip().lower()
    if not req.password:
        raise HTTPException(status_code=400, detail="Password is required")
        
    merchant = get_merchant_by_email(email_clean)
    if not merchant:
        raise HTTPException(status_code=401, detail="Invalid email or password. Please check your credentials.")
    
    pwd_hash = _hash_merchant_password(req.password)
    if merchant.password_hash and merchant.password_hash != pwd_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password. Please check your credentials.")
    
    # If legacy record without password hash, upgrade it
    if not merchant.password_hash:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE merchants SET password_hash = %s WHERE merchant_id = %s;", (pwd_hash, merchant.merchant_id))
        conn.commit()
        conn.close()

    token = jwt.encode({
        "sub": merchant.merchant_id,
        "email": merchant.email,
        "user_metadata": {
            "business_name": merchant.business_name,
            "phone": merchant.phone
        }
    }, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    
    return {
        "session": {
            "access_token": token,
            "user": {
                "id": merchant.merchant_id,
                "email": merchant.email,
                "user_metadata": {
                    "business_name": merchant.business_name,
                    "phone": merchant.phone
                }
            }
        },
        "merchant": merchant
    }

class MerchantProfileUpdateRequest(BaseModel):
    business_name: str
    phone: Optional[str] = None

@merchant_router.put("/profile")
async def update_merchant_profile(req: MerchantProfileUpdateRequest, merchant: Merchant = Depends(get_current_merchant)):
    """Updates the authenticated merchant's official organization / business name."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE merchants
    SET business_name = %s,
        phone = COALESCE(%s, phone)
    WHERE merchant_id = %s
    RETURNING merchant_id, email, business_name, phone;
    """, (req.business_name.strip(), req.phone, merchant.merchant_id))
    row = cursor.fetchone()
    conn.commit()
    conn.close()
    
    return {
        "merchant_id": row[0],
        "email": row[1],
        "business_name": row[2],
        "phone": row[3]
    }

@auth_router.get("/me")
async def get_authenticated_merchant(merchant: Merchant = Depends(get_current_merchant)):
    """Returns the authenticated merchant profile context."""
    return {
        "merchant_id": merchant.merchant_id,
        "email": merchant.email,
        "business_name": merchant.business_name,
        "phone": merchant.phone
    }
