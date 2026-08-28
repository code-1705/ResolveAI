"""
Invoices Router
Endpoints for creating, extracting, listing, and streaming master invoices.
"""

import time
import base64
import requests
import httpx
import json
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile, Response
from pydantic import BaseModel

from backend.core.config import settings
from backend.models.core import MasterInvoice, InvoiceStatus, Merchant
from backend.core.auth import get_current_merchant, require_verified_merchant_bank
from backend.core.database import get_connection, get_invoice, upsert_invoice
from backend.services.guardrails import paise_to_inr, inr_to_paise
from backend.integrations.storage import upload_to_supabase_storage
from backend.routers.events import broadcast_sse_event

router = APIRouter(prefix="/api/invoices", tags=["invoices"])

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

@router.get("")
async def list_invoices(merchant: Merchant = Depends(require_verified_merchant_bank)):
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

@router.get("/{invoice_id:path}/document")
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

    if file_url and file_url.strip():
        if file_url.startswith("http://") or file_url.startswith("https://"):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    cdn_res = await client.get(file_url)
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
            async with httpx.AsyncClient(timeout=5.0) as client:
                cdn_res = await client.get(supabase_url, headers=headers)
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

    raise HTTPException(status_code=404, detail="Invoice document not found or could not be retrieved.")

@router.get("/{invoice_id:path}")
async def get_invoice_detail(invoice_id: str, merchant: Merchant = Depends(require_verified_merchant_bank)):
    """Returns detailed information for a single invoice scoped to the authenticated merchant."""
    inv = get_invoice(invoice_id) or get_invoice(invoice_id.replace('/', '_')) or get_invoice(invoice_id.replace('_', '/'))
    if not inv:
        raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found.")

    if inv.merchant_id and inv.merchant_id != merchant.merchant_id:
        raise HTTPException(status_code=403, detail="Forbidden: You do not have permission to view this invoice.")
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

@router.put("/{invoice_id:path}")
async def edit_invoice(invoice_id: str, req: EditInvoiceRequest, merchant: Merchant = Depends(require_verified_merchant_bank)):
    """Allows authenticated & bank-verified merchants to edit invoice details or record manual off-platform payments (cash/UPI/cheque)."""
    inv = get_invoice(invoice_id) or get_invoice(invoice_id.replace('/', '_')) or get_invoice(invoice_id.replace('_', '/'))
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if inv.merchant_id and inv.merchant_id != merchant.merchant_id:
        raise HTTPException(status_code=403, detail="Forbidden: You do not have permission to edit this invoice.")

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
        
        new_remaining = max(0, inv.remaining_amount_paise - payment_paise)
        actual_paid = inv.remaining_amount_paise - new_remaining
        inv.remaining_amount_paise = new_remaining
        inv.paid_amount_paise = inv.paid_amount_paise + actual_paid

        if inv.remaining_amount_paise == 0:
            inv.status = InvoiceStatus.PAID
        else:
            inv.status = InvoiceStatus.PARTIALLY_PAID

        from backend.core.database import record_transaction
        record_transaction(
            invoice_id=inv.invoice_id,
            razorpay_payment_id=f"manual_{int(time.time())}",
            razorpay_payment_link_id=None,
            amount_paid_paise=actual_paid,
            payment_method="OFFLINE_MANUAL"
        )

    upsert_invoice(inv, merchant_id=inv.merchant_id)
    await broadcast_sse_event("payment_reconciled", {"invoice_id": inv.invoice_id})
    return {"success": True, "invoice": inv}

@router.post("/extract")
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


@router.post("")
async def create_invoice(req: CreateInvoiceRequest, merchant: Merchant = Depends(require_verified_merchant_bank)):
    """Creates a new master invoice scoped strictly for the authenticated & bank-verified merchant."""
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
        metadata=meta_dict if meta_dict else None,
        merchant_id=merchant.merchant_id
    )

    upsert_invoice(inv, merchant_id=merchant.merchant_id)

    if req.file_bytes_b64 and req.file_name and req.file_mime_type:
        try:
            raw_bytes = base64.b64decode(req.file_bytes_b64)
            cdn_url = upload_to_supabase_storage(f"{invoice_id}_{req.file_name}", raw_bytes, req.file_mime_type)
            if cdn_url:
                inv.file_url = cdn_url
                upsert_invoice(inv, merchant_id=merchant.merchant_id)
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

@router.post("/trigger-due-reminders")
async def trigger_due_reminders():
    """Manually triggers the due date automated WhatsApp reminder background job."""
    from backend.main import check_due_date_reminders_job
    res = await check_due_date_reminders_job()
    return res
