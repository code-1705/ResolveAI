import re
import asyncio
import threading
import json
import datetime
from typing import Dict, Any, List, Optional
import redis.asyncio as redis_async
from psycopg2.extras import DictCursor
from backend.config import settings
from backend.models import ChatSession, ChatMessage
from backend.database import get_connection, get_invoice, get_customer_financial_profile
from backend.guardrails import paise_to_inr

# Redis Client Initialization
redis_client = None
if settings.REDIS_URL:
    try:
        redis_client = redis_async.from_url(settings.REDIS_URL)
    except Exception as e:
        print(f"Warning: Failed to connect to Redis: {e}")

# In-Memory Fallback Session locks
SESSION_LOCKS: Dict[str, asyncio.Lock] = {}
SESSION_LOCK_MUTEX = threading.Lock()

class SessionLock:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.redis_lock = None
        self.memory_lock = None

        if redis_client:
            self.redis_lock = redis_client.lock(f"lock:session:{session_id}", timeout=30)
        else:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.get_event_loop()
            loop_id = id(loop)
            with SESSION_LOCK_MUTEX:
                key = f"{loop_id}_{session_id}"
                if key not in SESSION_LOCKS:
                    SESSION_LOCKS[key] = asyncio.Lock()
                self.memory_lock = SESSION_LOCKS[key]

    async def __aenter__(self):
        if self.redis_lock:
            await self.redis_lock.acquire(blocking=True)
        else:
            await self.memory_lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.redis_lock:
            await self.redis_lock.release()
        else:
            self.memory_lock.release()

def normalize_phone(phone_str: str) -> str:
    """Normalizes any phone string (handling URL encoded spaces) to standard +E.164 format."""
    if not phone_str:
        return "+910000000000"
    digits = re.sub(r'\D', '', phone_str)
    return f"+{digits}" if digits else "+910000000000"

def get_session_lock(session_id: str) -> SessionLock:
    """
    Returns a Distributed Redis Lock (or falls back to asyncio.Lock).
    Prevents double-texting race conditions across multiple server instances.
    """
    clean_key = normalize_phone(session_id)
    return SessionLock(clean_key)

def generate_greeting_and_docs(profile: Dict[str, Any], phone: str) -> tuple[str, list]:
    cust_name = profile.get("customer_name")
    if not cust_name or cust_name == "valued customer":
        if profile.get("invoices") and profile["invoices"][0].get("customer_name"):
            cust_name = profile["invoices"][0]["customer_name"]
        else:
            cust_name = "valued customer"

    pending_bills = [item for item in profile.get("invoices", []) if item.get("status") != "PAID"]

    if len(pending_bills) > 1:
        bill_ids_str = ", ".join([b["invoice_id"] for b in pending_bills])
        greeting_text = (
            f"Hi {cust_name}! We are reaching out regarding your {len(pending_bills)} pending invoices "
            f"({bill_ids_str}) with a total outstanding balance of ₹{profile['total_remaining_balance_inr']:,.2f}. "
            "We have attached your official bill documents below for your review. How can we best assist you with resolving these today?"
        )
    elif pending_bills:
        inv_item = pending_bills[0]
        today_str = datetime.date.today().isoformat()
        due_verb = "was" if inv_item["due_date"] < today_str else "is"
        greeting_text = (
            f"Hi {cust_name}! We are reaching out regarding Invoice {inv_item['invoice_id']} "
            f"for ₹{inv_item['remaining_amount_inr']:,.2f}. Your due date {due_verb} {inv_item['due_date']}. "
            "We have attached your official invoice bill below for your review. How can we best assist you with this today?"
        )
    else:
        greeting_text = (
            f"Hi {cust_name}! We are reaching out regarding your account. "
            "How can we best assist you today?"
        )

    import urllib.parse
    media_docs = []
    for b in pending_bills:
        media_docs.append({
            "invoice_id": b["invoice_id"],
            "filename": f"{b['invoice_id']}_bill.pdf",
            "url": f"/api/invoices/{b['invoice_id']}/document?customer_phone={urllib.parse.quote_plus(phone)}"
        })
    return greeting_text, media_docs


class SessionManager:
    def __init__(self):
        pass

    def get_or_create_session(
        self,
        session_id: Optional[str] = None,
        invoice_id: Optional[str] = None,
        customer_phone: Optional[str] = None
    ) -> ChatSession:
        """
        Loads an existing ChatSession from PostgreSQL or creates a new one.
        Keyed strictly by customer_phone (1 session per phone number).
        """
        raw = customer_phone or (session_id.split("_")[0] if session_id and "_" in session_id else session_id)
        phone = normalize_phone(raw)

        conn = get_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute("SELECT * FROM chat_sessions WHERE customer_phone = %s OR customer_phone = %s;", (phone, raw or phone))
        row = cursor.fetchone()

        profile = get_customer_financial_profile(phone)
        greeting_text, media_docs = generate_greeting_and_docs(profile, phone)

        if row:
            raw_messages = json.loads(row["messages_json"])
            messages = []
            updated = False

            for i, m in enumerate(raw_messages):
                meta = m.get("metadata") or {}
                # If this is the initial outbound agent message
                if i == 0 and m.get("sender") == "agent":
                    # Refresh if it was using the generic fallback text or missing attachments
                    if ("Hi valued customer" in m.get("text", "") or meta.get("outbound_initial_reminder")) and (len(raw_messages) <= 1 or "Hi valued customer" in m.get("text", "")):
                        m["text"] = greeting_text
                        meta["media_documents"] = media_docs
                        updated = True
                    elif not meta.get("media_documents") and media_docs:
                        meta["media_documents"] = media_docs
                        updated = True

                messages.append(
                    ChatMessage(
                        sender=m["sender"],
                        text=m["text"],
                        timestamp=m["timestamp"],
                        metadata=meta
                    )
                )

            if updated:
                cursor.execute("""
                UPDATE chat_sessions
                SET messages_json = %s
                WHERE customer_phone = %s;
                """, (json.dumps([msg.dict() for msg in messages]), row["customer_phone"]))
                conn.commit()

            conn.close()
            return ChatSession(
                customer_phone=phone,
                session_id=phone,
                invoice_id=invoice_id,
                messages=messages
            )

        # Create new customer session with initial outbound agent reminder message
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        initial_messages = [{
            "sender": "agent",
            "text": greeting_text,
            "timestamp": timestamp,
            "metadata": {
                "outbound_initial_reminder": True,
                "media_documents": media_docs
            }
        }]

        cursor.execute("""
        INSERT INTO chat_sessions (customer_phone, messages_json)
        VALUES (%s, %s)
        ON CONFLICT (customer_phone) DO UPDATE SET messages_json = EXCLUDED.messages_json;
        """, (phone, json.dumps(initial_messages)))
        conn.commit()
        conn.close()

        return ChatSession(
            customer_phone=phone,
            session_id=phone,
            invoice_id=invoice_id,
            messages=[
                ChatMessage(
                    sender="agent",
                    text=greeting_text,
                    timestamp=timestamp,
                    metadata={
                        "outbound_initial_reminder": True,
                        "media_documents": media_docs
                    }
                )
            ]
        )

    def add_message(
        self,
        session_id: str,
        sender: str,
        text: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ChatMessage:
        """
        Appends a user or agent message turn to the PostgreSQL chat session.
        Keyed strictly by customer_phone.
        """
        phone = normalize_phone(session_id)
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute("SELECT * FROM chat_sessions WHERE customer_phone = %s;", (phone,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            self.get_or_create_session(customer_phone=phone)
            conn = get_connection()
            cursor = conn.cursor(cursor_factory=DictCursor)
            cursor.execute("SELECT * FROM chat_sessions WHERE customer_phone = %s;", (phone,))
            row = cursor.fetchone()

        raw_messages = json.loads(row["messages_json"])
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

        new_msg = ChatMessage(
            sender=sender,
            text=text,
            timestamp=timestamp,
            metadata=metadata or {}
        )

        raw_messages.append({
            "sender": new_msg.sender,
            "text": new_msg.text,
            "timestamp": new_msg.timestamp,
            "metadata": new_msg.metadata
        })

        cursor.execute("""
        UPDATE chat_sessions
        SET messages_json = %s
        WHERE customer_phone = %s;
        """, (json.dumps(raw_messages), phone))
        conn.commit()
        conn.close()

        return new_msg

    def get_recent_history(self, session_id: str, limit: int = 5) -> List[ChatMessage]:
        """
        Returns the last `limit` message turns for LLM prompt context construction.
        """
        phone = normalize_phone(session_id)
        conn = get_connection()
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute("SELECT messages_json FROM chat_sessions WHERE customer_phone = %s;", (phone,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return []

        raw_messages = json.loads(row["messages_json"])
        recent = raw_messages[-limit:] if len(raw_messages) > limit else raw_messages

        return [
            ChatMessage(
                sender=m["sender"],
                text=m["text"],
                timestamp=m["timestamp"],
                metadata=m.get("metadata", {})
            ) for m in recent
        ]

session_manager = SessionManager()
