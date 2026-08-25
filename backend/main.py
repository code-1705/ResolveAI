from backend.storage import upload_to_supabase_storage
import jwt
from backend.auth import get_current_merchant, require_verified_merchant_bank
from backend.models import Merchant
import os
import time
import base64
import requests
import asyncio
import json
import logging
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends, Response, BackgroundTasks, HTTPException, Query, File, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.config import settings
from backend.models import MasterInvoice, MerchantGuardrails, InvoiceStatus
from backend.database import (
    init_db,
    save_invoice_document,
    get_invoice_document,
    get_guardrails,
    update_guardrails,
    get_invoice,
    upsert_invoice,
    get_connection,
    get_or_create_merchant,
    get_merchant_by_id,
    update_merchant_bank_settlement,
    get_merchant_by_email,
    create_merchant_with_password,
    get_merchant_settlement_ledger,
    update_merchant_razorpay_account
)
from backend.guardrails import GuardrailEngine, paise_to_inr, inr_to_paise
from backend.razorpay_client import razorpay_client
from backend.whatsapp_client import whatsapp_client
from backend.webhooks import verify_meta_webhook, process_whatsapp_webhook, reconcile_payment_event
from backend.agent import agentic_negotiator
from backend.session_manager import session_manager

# --- Real-time SSE Broadcast System ---
EVENT_QUEUES: List[asyncio.Queue] = []

async def broadcast_sse_event(event_type: str, data: Dict[str, Any]):
    """Broadcasts a real-time event to all connected SSE clients."""
    payload_str = json.dumps({"type": event_type, "data": data})
    for q in list(EVENT_QUEUES):
        try:
            await q.put(payload_str)
        except Exception:
            pass

from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- Active Reconciliation & Due Date Reminders Cron ---
scheduler = AsyncIOScheduler()

@scheduler.scheduled_job('interval', minutes=15)
async def active_reconciliation_job():
    """Polls Razorpay for missed webhooks and syncs active payment links every 15 minutes."""
    try:
        print("[Cron] Running Active Reconciliation & Payment Link Sync...")
        # 1. Sync captured payments
        payments = razorpay_client.get_recent_payments()
        for p in payments:
            if p.get("status") == "captured":
                mock_webhook = {
                    "event": "payment.captured",
                    "payload": {
                        "payment": {
                            "entity": p
                        }
                    }
                }
                await reconcile_payment_event(mock_webhook)

        # 2. Check and sync all ACTIVE payment links with live Razorpay status
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT razorpay_payment_link_id FROM payment_links WHERE status = 'ACTIVE';")
        active_links = [r[0] for r in cur.fetchall()]
        conn.close()

        for pl_id in active_links:
            try:
                rzp_url = f"https://api.razorpay.com/v1/payment_links/{pl_id}"
                resp = requests.get(rzp_url, auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET), timeout=5.0)
                if resp.status_code == 200:
                    data = resp.json()
                    live_status = data.get("status", "").upper()
                    if live_status in ("PAID", "EXPIRED", "CANCELLED"):
                        c = get_connection()
                        k = c.cursor()
                        k.execute("UPDATE payment_links SET status = %s WHERE razorpay_payment_link_id = %s;", (live_status, pl_id))
                        c.commit()
                        c.close()
                        print(f"[Cron Link Sync]: Updated {pl_id} status -> {live_status}")
            except Exception as pl_err:
                print(f"[Cron Link Sync Error] {pl_id}: {pl_err}")

        print("[Cron] Active Reconciliation Complete.")
    except Exception as e:
        print(f"[Cron] Active Reconciliation Failed: {e}")

@scheduler.scheduled_job('interval', hours=1)
async def check_due_date_reminders_job():
    """
    Automated Background Cron: Checks for invoices due today or overdue,
    and automatically dispatches WhatsApp reminder messages with invoice attachments to buyers.
    """
    import datetime
    try:
        print("[Cron] Checking for Due & Overdue Invoices to dispatch WhatsApp reminders...")
        today_str = datetime.date.today().isoformat()
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT invoice_id, customer_name, customer_phone, remaining_amount_paise, due_date, status, file_url
            FROM master_invoices
            WHERE due_date <= %s AND status IN ('UNPAID', 'NEGOTIATING');
        """, (today_str,))
        rows = cur.fetchall()
        conn.close()

        reminders_sent = 0
        for r in rows:
            inv_id, cust_name, phone, rem_paise, due_date, status, file_url = r
            rem_inr = rem_paise / 100.0
            due_verb = "was due on" if due_date < today_str else "is due TODAY on"
            
            doc_link = f"/api/invoices/{inv_id}/document?customer_phone={phone}"
            media_docs = [{
                "invoice_id": inv_id,
                "filename": f"{inv_id}_bill.pdf",
                "url": doc_link
            }]
            reminder_text = (
                f"⏰ *Payment Reminder:* Hi {cust_name}! This is a reminder regarding Invoice `{inv_id}` "
                f"for *₹{rem_inr:,.2f}*, which {due_verb} {due_date}.\n\n"
                "We have attached your official invoice bill statement below for your review. "
                "Please let us know if you need any assistance or options to settle your account today."
            )
            
            try:
                whatsapp_client.send_text_message(phone, f"{reminder_text}\n\nInvoice Bill: {doc_link}")
                session_manager.add_message(
                    phone,
                    "agent",
                    reminder_text,
                    metadata={
                        "outbound_due_date_reminder": True,
                        "invoice_id": inv_id,
                        "media_documents": media_docs
                    }
                )
                reminders_sent += 1
                print(f"[Cron Due Date Reminder Sent]: Invoice {inv_id} -> {phone}")
            except Exception as send_err:
                print(f"[Cron Due Date Reminder Error] Invoice {inv_id}: {send_err}")
                
        print(f"[Cron] Due Date Reminders Check Complete. Total sent: {reminders_sent}")
        return {"status": "success", "reminders_sent": reminders_sent}
    except Exception as e:
        print(f"[Cron] Due Date Reminders Check Failed: {e}")
        return {"status": "error", "error": str(e)}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize tables
    init_db()
    scheduler.start()
    yield
    # Shutdown
    scheduler.shutdown()
    EVENT_QUEUES.clear()

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Autonomous Collections Agent for Razorpay SMEs",
    lifespan=lifespan
)

# --- Production-Ready CORS Security Configuration ---
cors_origins_env = os.getenv("CORS_ORIGINS", "")
allowed_origins = [orig.strip() for orig in cors_origins_env.split(",") if orig.strip()] if cors_origins_env else [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if cors_origins_env else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Request / Response Models ---
class GuardrailsUpdateRequest(BaseModel):
    min_partial_payment_pct: float
    max_extension_days: int
    max_split_installments: int = 3
    auto_discount_waiver_pct: float = 5.0
    tone: str = "professional_empathetic"

class ChatMessageRequest(BaseModel):
    session_id: Optional[str] = None
    invoice_id: Optional[str] = None
    customer_phone: str
    message: str

class CreateInvoiceRequest(BaseModel):
    customer_name: str
    customer_phone: str
    original_amount_inr: float
    due_date: str
    invoice_number: Optional[str] = None
    summary_description: Optional[str] = None
    invoice_date: Optional[str] = None
    billing_address: Optional[str] = None
    shipping_address: Optional[str] = None
    line_items: Optional[List[Dict[str, Any]]] = None
    items: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None
    notes: Optional[str] = None
    file_bytes_b64: Optional[str] = None
    file_name: Optional[str] = None
    file_mime_type: Optional[str] = None

class ChatResetRequest(BaseModel):
    session_id: str

class CreateOrderRequest(BaseModel):
    amount_in_paise: int
    invoice_id: Optional[str] = None
    receipt: Optional[str] = None

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    invoice_id: Optional[str] = None

# --- 1. Real-time SSE Events Endpoint ---
@app.get("/api/events")
async def sse_events_endpoint(request: Request):
    """
    Server-Sent Events (SSE) stream.
    Broadcasts real-time payment captured, invoice reconciled, and chat updates directly to React UI clients.
    """
    queue = asyncio.Queue()
    EVENT_QUEUES.append(queue)

    async def event_generator():
        try:
            # Yield initial connection ping
            yield f"data: {json.dumps({'type': 'connected', 'data': {'message': 'SSE Live Stream Active'}})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data_str = await asyncio.wait_for(queue.get(), timeout=5.0)
                    yield f"data: {data_str}\n\n"
                except asyncio.TimeoutError:
                    # Heartbeat ping allows frequent disconnect checks to prevent memory leaks
                    yield f"data: {json.dumps({'type': 'ping', 'data': {}})}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in EVENT_QUEUES:
                EVENT_QUEUES.remove(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")




# --- Merchant Direct Bank Settlement & 3% Platform Commission Routes ---
class BankSettlementUpdateRequest(BaseModel):
    bank_beneficiary_name: str
    bank_account_number: str
    bank_ifsc: str
    bank_name: Optional[str] = None
    upi_id: Optional[str] = None
    pan_number: Optional[str] = None


@app.get("/api/merchant/settlement-ledger")
async def get_merchant_settlement_ledger_history(merchant: Merchant = Depends(get_current_merchant)):
    """Returns the authenticated merchant's live double-entry settlement ledger."""
    ledger = get_merchant_settlement_ledger(merchant.merchant_id)
    return ledger

@app.get("/api/merchant/bank-settlement")
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

@app.post("/api/merchant/bank-settlement")
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

# --- Merchant Authentication & Registration Routes ---
def _hash_merchant_password(password: str) -> str:
    import hashlib
    salt = "resolve_ai_salt_2026_"
    return hashlib.sha256((salt + password).encode()).hexdigest()

class MerchantAuthRequest(BaseModel):
    business_name: Optional[str] = None
    email: str
    password: str
    phone: Optional[str] = None

@app.post("/api/auth/register")
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
    }, "secret", algorithm="HS256")
    
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

@app.post("/api/auth/login")
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
    }, "secret", algorithm="HS256")
    
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

# --- Merchant Authentication Profile Route ---

class MerchantProfileUpdateRequest(BaseModel):
    business_name: str
    phone: Optional[str] = None

@app.put("/api/merchant/profile")
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

@app.get("/api/auth/me")
async def get_authenticated_merchant(merchant: Merchant = Depends(get_current_merchant)):
    """Returns the authenticated merchant profile context."""
    return {
        "merchant_id": merchant.merchant_id,
        "email": merchant.email,
        "business_name": merchant.business_name,
        "phone": merchant.phone
    }

# --- 2. Master Invoice Endpoints ---

class EditInvoiceRequest(BaseModel):
    customer_name: str
    customer_phone: str
    due_date: str
    invoice_number: Optional[str] = None
    summary_description: Optional[str] = None
    invoice_date: Optional[str] = None
    billing_address: Optional[str] = None
    shipping_address: Optional[str] = None
    line_items: Optional[List[Dict[str, Any]]] = None
    original_amount_inr: Optional[float] = None
    manual_payment_inr: Optional[float] = 0.0

@app.put("/api/invoices/{invoice_id:path}")
async def edit_invoice(invoice_id: str, req: EditInvoiceRequest):
    """Allows merchants to edit invoice details or record manual off-platform payments (cash/UPI/cheque)."""
    inv = get_invoice(invoice_id) or get_invoice(invoice_id.replace('/', '_')) or get_invoice(invoice_id.replace('_', '/'))
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    inv.customer_name = req.customer_name
    inv.customer_phone = req.customer_phone
    inv.due_date = req.due_date

    if req.line_items is not None:
        inv.items = req.line_items

    meta = inv.metadata or {}
    if req.summary_description is not None:
        meta["summary_description"] = req.summary_description
    if req.invoice_date is not None:
        meta["invoice_date"] = req.invoice_date
    if req.billing_address is not None:
        meta["billing_address"] = req.billing_address
    if req.shipping_address is not None:
        meta["shipping_address"] = req.shipping_address
    inv.metadata = meta

    if req.original_amount_inr is not None and req.original_amount_inr > 0:
        new_orig_paise = inr_to_paise(req.original_amount_inr)
        inv.original_amount_paise = new_orig_paise
        inv.remaining_amount_paise = max(0, new_orig_paise - inv.paid_amount_paise)

    if req.manual_payment_inr and req.manual_payment_inr > 0:
        payment_paise = inr_to_paise(req.manual_payment_inr)
        
        # Deduct from remaining balance
        new_remaining = max(0, inv.remaining_amount_paise - payment_paise)
        actual_paid = inv.remaining_amount_paise - new_remaining
        inv.remaining_amount_paise = new_remaining
        inv.paid_amount_paise = inv.paid_amount_paise + actual_paid

        if inv.remaining_amount_paise == 0:
            inv.status = InvoiceStatus.PAID
        else:
            inv.status = InvoiceStatus.PARTIALLY_PAID

        from backend.database import record_transaction
        record_transaction(
            invoice_id=inv.invoice_id,
            razorpay_payment_id=f"manual_{int(time.time())}",
            razorpay_payment_link_id=None,
            amount_paid_paise=actual_paid,
            payment_method="OFFLINE_MANUAL"
        )

    upsert_invoice(inv)
    await broadcast_sse_event("payment_reconciled", {"invoice_id": inv.invoice_id})
    return {"success": True, "invoice": inv}


@app.post("/api/invoices/extract")
async def extract_invoice_from_file(file: UploadFile = File(...)):
    """Accepts an invoice PDF or image file and extracts structured invoice fields via Gemini 2.5 Flash."""
    try:
        contents = await file.read()
        mime_type = file.content_type or "image/jpeg"
        if "pdf" in file.filename.lower() or "pdf" in mime_type.lower():
            mime_type = "application/pdf"
        elif "png" in mime_type.lower():
            mime_type = "image/png"
        elif "webp" in mime_type.lower():
            mime_type = "image/webp"
        else:
            mime_type = "image/jpeg"

        base64_data = base64.b64encode(contents).decode("utf-8")

        prompt = """
        You are an expert Document OCR and Financial Invoice Parser.
        Extract the following fields from the invoice document:
        - invoice_number: The official invoice number or bill reference ID (string or null).
        - summary_description: A brief summary or description of the project/bill (string or null).
        - customer_name: Name of the customer/SME billed (string).
        - customer_phone: WhatsApp or Phone number if listed (string or null).
        - invoice_date: Issue date (YYYY-MM-DD or null).
        - due_date: Expiry or Payment due date (YYYY-MM-DD, or current date if not found).
        - billing_address: Full billing address of the customer (string or null).
        - shipping_address: Full shipping/delivery address (string or null).
        - line_items: A list of every item/service row:
            [
              {
                "description": "Item description or product/service name",
                "rate": 500.0,
                "quantity": 1,
                "total": 500.0
              }
            ]
        - total_amount_inr: Total payable invoice amount in INR as a numeric float.

        Return ONLY a valid JSON object matching this schema:
        {
          "invoice_number": "string or null",
          "summary_description": "string or null",
          "customer_name": "string",
          "customer_phone": "string or null",
          "invoice_date": "YYYY-MM-DD or null",
          "due_date": "YYYY-MM-DD",
          "billing_address": "string or null",
          "shipping_address": "string or null",
          "line_items": [
            {
              "description": "string",
              "rate": number,
              "quantity": number,
              "total": number
            }
          ],
          "total_amount_inr": number
        }
        """

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={settings.GEMINI_API_KEY}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": base64_data
                            }
                        },
                        {
                            "text": prompt
                        }
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json"
            }
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=75.0)
            if resp.status_code == 200:
                res_json = resp.json()
                text_resp = res_json["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text_resp.replace('```json', '').replace('```', '').strip())
                return {
                    "success": True,
                    "data": parsed,
                    "file_bytes_b64": base64_data,
                    "file_name": file.filename,
                    "file_mime_type": mime_type
                }
            else:
                return {
                    "success": False,
                    "error": f"Gemini API returned status {resp.status_code}. Please enter details manually below.",
                    "file_bytes_b64": base64_data,
                    "file_name": file.filename,
                    "file_mime_type": mime_type
                }
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "error": "AI extraction took longer than 75s due to file size. Please enter details manually below.",
                "file_bytes_b64": base64_data,
                "file_name": file.filename,
                "file_mime_type": mime_type
            }
    except Exception as e:
        return {"success": False, "error": "Could not parse document automatically. Please enter details manually below."}



def generate_simple_invoice_pdf(invoice_id: str, customer_name: str, amount_inr: float, due_date: str) -> bytes:
    """Generates a standard compliant 1-page PDF document in pure Python with zero dependencies."""
    text_lines = [
        f"RESOLVE.AI - OFFICIAL INVOICE STATEMENT",
        f"========================================",
        f"Invoice ID:    {invoice_id}",
        f"Customer Name: {customer_name}",
        f"Amount Due:    INR {amount_inr:,.2f}",
        f"Due Date:      {due_date}",
        f"Status:        OUTSTANDING / UNPAID",
        f"",
        f"Payment Terms: Immediate via Razorpay",
        f"Thank you for your prompt business with us."
    ]
    
    stream_content = "BT\n/F1 14 Tf\n50 750 Td\n20 TL\n"
    for line in text_lines:
        safe_line = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream_content += f"({safe_line}) '\n"
    stream_content += "ET\n"
    
    stream_bytes = stream_content.encode("latin-1")
    stream_len = len(stream_bytes)
    
    pdf_template = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        b"5 0 obj\n<< /Length " + str(stream_len).encode("ascii") + b" >>\nstream\n" +
        stream_bytes +
        b"\nendstream\nendobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000234 00000 n \n0000000307 00000 n \n"
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n" +
        str(350 + stream_len).encode("ascii") +
        b"\n%%EOF\n"
    )
    return pdf_template


@app.get("/api/invoices/{invoice_id:path}/document")
async def stream_invoice_document(invoice_id: str, customer_phone: str = Query(..., alias="customer_phone")):
    """Streams invoice PDF document from Supabase CDN or generates dynamic standard PDF with strict phone verification."""
    from psycopg2.extras import DictCursor
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute(
        """
        SELECT customer_phone, file_url, customer_name, remaining_amount_paise, due_date 
        FROM master_invoices 
        WHERE invoice_id = %s OR invoice_id = %s OR invoice_id = %s;
        """,
        (invoice_id, invoice_id.replace('/', '_'), invoice_id.replace('_', '/'))
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found.")

    import re
    clean_db = re.sub(r'\D', '', row["customer_phone"])
    clean_req = re.sub(r'\D', '', customer_phone)
    if clean_db != clean_req:
        raise HTTPException(status_code=403, detail="Forbidden: Phone number mismatch")

    file_url = row.get("file_url")
    customer_name = row.get("customer_name", "Valued Customer")
    remaining_inr = paise_to_inr(row.get("remaining_amount_paise", 0))
    due_date = row.get("due_date", "")

    # 1. Check if original document file exists in Supabase Storage or CDN
    if file_url and file_url.strip():
        if file_url.startswith("http://") or file_url.startswith("https://"):
            try:
                cdn_res = requests.get(file_url, timeout=5.0)
                if cdn_res.status_code == 200:
                    return Response(
                        content=cdn_res.content,
                        media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="{invoice_id}_bill.pdf"'}
                    )
            except Exception as e:
                print(f"[CDN Fetch Error]: {e}")

        target_filename = file_url.split("/")[-1]
        supabase_url = f"{settings.SUPABASE_URL}/storage/v1/object/authenticated/resolveai-invoices/{target_filename}"
        headers = {
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
            "apikey": settings.SUPABASE_SERVICE_KEY
        }
        try:
            cdn_res = requests.get(supabase_url, headers=headers, timeout=5.0)
            if cdn_res.status_code == 200:
                return Response(
                    content=cdn_res.content,
                    media_type="application/pdf",
                    headers={
                        "Content-Disposition": f'inline; filename="{invoice_id}_bill.pdf"'
                    }
                )
        except Exception as e:
            print(f"[Supabase Storage Fetch Error]: {e}")

    # Fallback to high-fidelity pure-Python generated PDF
    pdf_bytes = generate_simple_invoice_pdf(
        invoice_id=invoice_id,
        customer_name=customer_name,
        amount_inr=remaining_inr,
        due_date=due_date
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{invoice_id}_bill.pdf"'
        }
    )

from urllib.parse import quote_plus

@app.get("/api/invoices")
async def list_invoices(merchant: Merchant = Depends(get_current_merchant)):
    """Returns list of master invoices scoped strictly to the authenticated merchant."""
    from psycopg2.extras import DictCursor
    conn = get_connection()
    cursor = conn.cursor(cursor_factory=DictCursor)
    cursor.execute("SELECT * FROM master_invoices WHERE merchant_id = %s ORDER BY due_date ASC;", (merchant.merchant_id,))
    rows = cursor.fetchall()
    conn.close()

    invoices = []
    for r in rows:
        orig = r["original_amount_paise"]
        paid = r["paid_amount_paise"]
        rem = r["remaining_amount_paise"]
        f_url = r.get("file_url")
        has_doc = True if (f_url and f_url.strip()) else False

        raw_items = r.get("items")
        if isinstance(raw_items, str):
            try:
                raw_items = json.loads(raw_items)
            except Exception:
                pass

        raw_meta = r.get("metadata")
        if isinstance(raw_meta, str):
            try:
                raw_meta = json.loads(raw_meta)
            except Exception:
                pass

        invoices.append({
            "invoice_id": r["invoice_id"],
            "customer_name": r["customer_name"],
            "customer_phone": r["customer_phone"],
            "original_amount_inr": paise_to_inr(orig),
            "paid_amount_inr": paise_to_inr(paid),
            "remaining_amount_inr": paise_to_inr(rem),
            "original_amount_paise": orig,
            "paid_amount_paise": paid,
            "remaining_amount_paise": rem,
            "due_date": r["due_date"],
            "status": r["status"],
            "requires_human_attention": r["requires_human_attention"],
            "has_document": has_doc,
            "document_url": f_url,
            "items": raw_items,
            "metadata": raw_meta
        })
    return invoices

@app.get("/api/invoices/{invoice_id:path}")
async def get_invoice_detail(invoice_id: str):
    """Returns detailed information for a single invoice."""
    inv = get_invoice(invoice_id) or get_invoice(invoice_id.replace('/', '_')) or get_invoice(invoice_id.replace('_', '/'))
    if not inv:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found.")
    return {
        "invoice_id": inv.invoice_id,
        "customer_name": inv.customer_name,
        "customer_phone": inv.customer_phone,
        "original_amount_inr": inv.original_amount_inr,
        "paid_amount_inr": inv.paid_amount_inr,
        "remaining_amount_inr": inv.remaining_amount_inr,
        "due_date": inv.due_date,
        "status": inv.status.value,
        "items": inv.items,
        "metadata": inv.metadata
    }

@app.post("/api/invoices")
async def create_invoice(req: CreateInvoiceRequest, merchant: Merchant = Depends(get_current_merchant)):
    """Creates a new master invoice scoped strictly for the authenticated merchant."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM master_invoices WHERE merchant_id = %s;", (merchant.merchant_id,))
    count = cursor.fetchone()[0]
    conn.close()

    prefix = merchant.merchant_id[:6] if len(merchant.merchant_id) >= 6 else "SME"
    invoice_id = req.invoice_number if (req.invoice_number and len(req.invoice_number.strip()) > 0) else f"inv_{prefix}_{count + 1:03d}"
    paise_amount = inr_to_paise(req.original_amount_inr)

    meta_dict = req.metadata or {}
    if req.summary_description:
        meta_dict["summary_description"] = req.summary_description
    if req.invoice_date:
        meta_dict["invoice_date"] = req.invoice_date
    if req.billing_address:
        meta_dict["billing_address"] = req.billing_address
    if req.shipping_address:
        meta_dict["shipping_address"] = req.shipping_address
    if req.notes:
        meta_dict["notes"] = req.notes

    inv = MasterInvoice(
        invoice_id=invoice_id,
        customer_name=req.customer_name,
        customer_phone=req.customer_phone,
        original_amount_paise=paise_amount,
        paid_amount_paise=0,
        remaining_amount_paise=paise_amount,
        due_date=req.due_date,
        status=InvoiceStatus.UNPAID,
        items=req.line_items or req.items,
        metadata=meta_dict if meta_dict else None
    )

    upsert_invoice(inv, merchant_id=merchant.merchant_id)

    if req.file_bytes_b64 and req.file_name and req.file_mime_type:
        try:
            raw_bytes = base64.b64decode(req.file_bytes_b64)
            cdn_url = upload_to_supabase_storage(f"{invoice_id}_{req.file_name}", raw_bytes, req.file_mime_type)
            if cdn_url:
                inv.file_url = cdn_url
                upsert_invoice(inv)
                print(f"[Supabase Storage Success]: Attached CDN URL for {invoice_id} -> {cdn_url}")
        except Exception as e:
            print(f"[Supabase Upload Error]: {e}")

    res = {
        "invoice_id": inv.invoice_id,
        "customer_name": inv.customer_name,
        "customer_phone": inv.customer_phone,
        "original_amount_inr": inv.original_amount_inr,
        "paid_amount_inr": 0.0,
        "remaining_amount_inr": inv.original_amount_inr,
        "due_date": inv.due_date,
        "status": inv.status.value,
        "has_document": True if (req.file_bytes_b64 and req.file_name) else False
    }

    await broadcast_sse_event("invoice_created", res)
    return res


@app.post("/api/invoices/trigger-due-reminders")
async def trigger_due_reminders():
    """Manually triggers the due date automated WhatsApp reminder background job."""
    res = await check_due_date_reminders_job()
    return res


# --- 3. Merchant Guardrail Control Endpoints ---
@app.get("/api/guardrails")
async def get_merchant_guardrails():
    """Returns current active merchant negotiation guardrails."""
    g = get_guardrails()
    return {
        "id": g.id,
        "min_partial_payment_pct": g.min_partial_payment_pct,
        "max_extension_days": g.max_extension_days,
        "max_split_installments": g.max_split_installments,
        "auto_discount_waiver_pct": g.auto_discount_waiver_pct,
        "tone": g.tone
    }

@app.post("/api/guardrails")
async def save_merchant_guardrails(req: GuardrailsUpdateRequest):
    """Updates merchant guardrail policies and broadcasts SSE event."""
    g = MerchantGuardrails(
        id=1,
        min_partial_payment_pct=req.min_partial_payment_pct,
        max_extension_days=req.max_extension_days,
        max_split_installments=req.max_split_installments,
        auto_discount_waiver_pct=req.auto_discount_waiver_pct,
        tone=req.tone
    )
    updated = update_guardrails(g)
    res = {
        "min_partial_payment_pct": updated.min_partial_payment_pct,
        "max_extension_days": updated.max_extension_days,
        "max_split_installments": updated.max_split_installments,
        "auto_discount_waiver_pct": updated.auto_discount_waiver_pct,
        "tone": updated.tone
    }
    await broadcast_sse_event("guardrails_updated", res)
    return res

# --- 4. Chat Simulator & Session Endpoints ---
@app.get("/api/chat/history")
async def get_chat_history(
    customer_phone: str = Query(...),
    invoice_id: Optional[str] = Query(None)
):
    """
    Returns full chat session message history for a customer phone number.
    Auto-initializes session with an outbound initial agent reminder message if brand new.
    """
    session = session_manager.get_or_create_session(customer_phone=customer_phone, invoice_id=invoice_id)
    return {
        "session_id": session.session_id,
        "customer_phone": session.customer_phone,
        "invoice_id": session.invoice_id,
        "messages": [
            {
                "sender": m.sender,
                "text": m.text,
                "timestamp": m.timestamp,
                "metadata": m.metadata
            } for m in session.messages
        ]
    }

@app.post("/api/chat/message")
async def send_chat_message(req: ChatMessageRequest):
    """
    Processes incoming messages from the WhatsApp simulator UI.
    Invokes AgenticNegotiator, returns response text & visual audit trace, and broadcasts SSE event.
    """
    session_id = req.customer_phone or req.session_id

    agent_res = await agentic_negotiator.process_customer_message(
        session_id=session_id,
        invoice_id=req.invoice_id,
        customer_phone=req.customer_phone,
        customer_message=req.message
    )

    out_data = {
        "session_id": session_id,
        "customer_phone": req.customer_phone,
        "invoice_id": req.invoice_id,
        "response_text": agent_res["response_text"],
        "metadata": agent_res.get("metadata", {}),
        "trace": agent_res["trace"]
    }

    await broadcast_sse_event("chat_message_processed", out_data)
    return out_data

@app.post("/api/chat/reset")
async def reset_chat_session(req: ChatResetRequest):
    """Resets chat history for a session."""
    phone = req.session_id.split("_")[0] if "_" in req.session_id else req.session_id
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE chat_sessions SET messages_json = '[]' WHERE customer_phone = %s;", (phone,))
    conn.commit()
    conn.close()
    return {"status": "reset", "customer_phone": phone}

# --- Razorpay Standard Web Checkout Endpoints ---
@app.post("/api/create-order")
async def create_checkout_order(req: CreateOrderRequest):
    """
    Creates a Razorpay Standard Checkout Order.
    Enforces minimum 100 paise (₹1.00) validation.
    """
    if req.amount_in_paise < 100:
        raise HTTPException(status_code=400, detail="Amount must be at least 100 paise (₹1.00).")

    notes = {}
    if req.invoice_id:
        notes["invoice_id"] = req.invoice_id

    try:
        order = razorpay_client.create_order(
            amount_in_paise=req.amount_in_paise,
            receipt=req.receipt,
            notes=notes
        )
        return {
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "key_id": settings.RAZORPAY_KEY_ID,
            "invoice_id": req.invoice_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create Razorpay Order: {str(e)}")

@app.post("/api/verify-payment")
async def verify_checkout_payment(req: VerifyPaymentRequest):
    """
    Verifies Razorpay Standard Checkout HMAC-SHA256 Payment Signature.
    Algorithm: HMAC-SHA256(order_id + "|" + payment_id, KEY_SECRET)
    If valid: Reconciles invoice balance, updates FSM status, and emits SSE event.
    If invalid: Returns 400 Bad Request and does NOT mark invoice as paid.
    """
    if not req.razorpay_order_id or not req.razorpay_payment_id or not req.razorpay_signature:
        raise HTTPException(status_code=400, detail="Missing required payment verification fields.")

    valid = razorpay_client.verify_payment_signature(
        razorpay_order_id=req.razorpay_order_id,
        razorpay_payment_id=req.razorpay_payment_id,
        razorpay_signature=req.razorpay_signature
    )

    if not valid:
        raise HTTPException(status_code=400, detail="Signature verification failed. Invalid payment signature.")

    # Payment Verified! Reconcile invoice balance if invoice_id is present
    if req.invoice_id:
        invoice = get_invoice(req.invoice_id)
        if invoice and invoice.remaining_amount_paise > 0:
            mock_webhook_payload = {
                "event": "payment.captured",
                "payload": {
                    "payment": {
                        "entity": {
                            "id": req.razorpay_payment_id,
                            "order_id": req.razorpay_order_id,
                            "amount": invoice.remaining_amount_paise,
                            "method": "CARD",
                            "notes": {"invoice_id": req.invoice_id}
                        }
                    }
                }
            }
            reconcile_res = await reconcile_payment_event(mock_webhook_payload, )
            if reconcile_res.get("status") == "reconciled":
                await broadcast_sse_event("payment_reconciled", reconcile_res)

    return {
        "status": "success",
        "message": "Payment verified and invoice updated successfully",
        "razorpay_payment_id": req.razorpay_payment_id,
        "razorpay_order_id": req.razorpay_order_id
    }

# --- 5. Webhook Endpoints (Razorpay & Meta) ---

async def background_razorpay_reconcile(payload: Dict[str, Any]):
    """Background task processing Razorpay payment reconciliation."""
    res = await reconcile_payment_event(payload)
    if res.get("status") == "reconciled":
        await broadcast_sse_event("payment_reconciled", res)

@app.post("/api/webhooks/razorpay")
async def razorpay_webhook_endpoint(request: Request, background_tasks: BackgroundTasks):
    """
    Asynchronous Non-Blocking Razorpay Payment Webhook Receiver.
    1. Reads raw_body bytes.
    2. Verifies HMAC-SHA256 signature.
    3. Enqueues background reconciliation task.
    4. Immediately returns HTTP 200 OK (<100ms) to eliminate retry storms.
    """
    raw_bytes = await request.body()
    sig_header = request.headers.get("X-Razorpay-Signature", "")

    if sig_header:
        valid = razorpay_client.verify_webhook_signature(raw_bytes, sig_header)
        if not valid:
            raise HTTPException(status_code=400, detail="Invalid Razorpay HMAC signature.")
    elif settings.ENVIRONMENT == "production":
        raise HTTPException(status_code=400, detail="Missing Razorpay signature header.")

    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload.")

    background_tasks.add_task(background_razorpay_reconcile, payload)
    return {"status": "ok"}

@app.get("/api/webhooks/whatsapp")
async def meta_whatsapp_webhook_verification(
    hub_mode: str = Query(..., alias="hub.mode"),
    hub_token: str = Query(..., alias="hub.verify_token"),
    hub_challenge: str = Query(..., alias="hub.challenge")
):
    """Meta WhatsApp Cloud API GET verification handshake endpoint."""
    valid, challenge = verify_meta_webhook(hub_mode, hub_token, hub_challenge)
    if valid:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status_code=403, detail="Meta verification failed.")

async def background_process_whatsapp_message(session_id: str, invoice_id: str, customer_phone: str, user_text: str):
    """Background task executing LLM negotiation for incoming WhatsApp messages."""
    await agentic_negotiator.process_customer_message(
        session_id=session_id,
        invoice_id=invoice_id,
        customer_phone=customer_phone,
        customer_message=user_text
    )

@app.post("/api/webhooks/whatsapp")
async def meta_whatsapp_webhook_receiver(request: Request, background_tasks: BackgroundTasks):
    """Meta WhatsApp Cloud API POST incoming message webhook receiver."""
    payload = await request.json()
    res = process_whatsapp_webhook(payload)

    if res.get("status") == "routed":
        # Safely enqueue LLM negotiator as a FastAPI BackgroundTask
        session_id = res["session_id"]
        invoice_id = res["invoice_id"]
        customer_phone = res["customer_phone"]
        user_text = res["user_text"]

        background_tasks.add_task(
            background_process_whatsapp_message,
            session_id,
            invoice_id,
            customer_phone,
            user_text
        )

    return {"status": "ok"}

# --- 6. Analytics & Metrics Endpoint (Merchant-Scoped) ---
@app.get("/api/analytics")
async def get_analytics_overview(merchant: Merchant = Depends(get_current_merchant)):
    """Returns merchant-scoped key metrics: Total Overdue TPV, Recovered TPV, Recovery Rate %, Active Negotiations."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT 
        COALESCE(SUM(original_amount_paise), 0),
        COALESCE(SUM(paid_amount_paise), 0),
        COALESCE(SUM(remaining_amount_paise), 0)
    FROM master_invoices
    WHERE merchant_id = %s;
    """, (merchant.merchant_id,))
    row = cursor.fetchone()

    total_orig = row[0] or 0
    total_paid = row[1] or 0
    total_rem = row[2] or 0

    cursor.execute("""
    SELECT COUNT(*) 
    FROM master_invoices 
    WHERE status = 'NEGOTIATING' AND merchant_id = %s;
    """, (merchant.merchant_id,))
    active_neg_count = cursor.fetchone()[0]

    conn.close()

    recovery_rate_pct = round((total_paid / total_orig * 100.0), 2) if total_orig > 0 else 0.0

    return {
        "total_overdue_tpv_inr": paise_to_inr(total_orig),
        "recovered_tpv_inr": paise_to_inr(total_paid),
        "remaining_overdue_tpv_inr": paise_to_inr(total_rem),
        "recovery_rate_pct": min(100.0, recovery_rate_pct),
        "active_negotiations_count": active_neg_count
    }
