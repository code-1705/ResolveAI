"""
FastAPI Application Entrypoint
Initializes the app, configures CORS, sets up scheduled cron jobs, and mounts all routers.
"""

import os
import requests
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from backend.core.config import settings
from backend.core.database import init_db, get_connection
from backend.integrations.razorpay import razorpay_client
from backend.integrations.whatsapp import whatsapp_client
from backend.services.webhooks import reconcile_payment_event
from backend.services.session import session_manager
from backend.routers.events import EVENT_QUEUES

# Import Routers
from backend.routers.events import router as events_router
from backend.routers.auth import auth_router, merchant_router
from backend.routers.invoices import router as invoices_router
from backend.routers.guardrails import router as guardrails_router
from backend.routers.chat import router as chat_router
from backend.routers.payments import router as payments_router
from backend.routers.webhooks import router as webhooks_router
from backend.routers.analytics import router as analytics_router

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

# Register all modular routers
app.include_router(events_router)
app.include_router(auth_router)
app.include_router(merchant_router)
app.include_router(invoices_router)
app.include_router(guardrails_router)
app.include_router(chat_router)
app.include_router(payments_router)
app.include_router(webhooks_router)
app.include_router(analytics_router)


