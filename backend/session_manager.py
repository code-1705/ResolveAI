import asyncio
import threading
import json
import datetime
from typing import Dict, Any, List, Optional
import redis.asyncio as redis_async
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

def get_session_lock(session_id: str) -> SessionLock:
    """
    Returns a Distributed Redis Lock (or falls back to asyncio.Lock).
    Prevents double-texting race conditions across multiple server instances.
    """
    return SessionLock(session_id)

class SessionManager:
    def __init__(self):
        pass

    def get_or_create_session(self, session_id: str, invoice_id: str, customer_phone: str) -> ChatSession:
        """
        Loads an existing ChatSession from PostgreSQL or creates a new one.
        Composite session key: f"{customer_phone}_{invoice_id}"
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM chat_sessions WHERE session_id = %s;", (session_id,))
        row = cursor.fetchone()

        if row:
            raw_messages = json.loads(row["messages_json"])
            messages = [
                ChatMessage(
                    sender=m["sender"],
                    text=m["text"],
                    timestamp=m["timestamp"],
                    metadata=m.get("metadata", {})
                ) for m in raw_messages
            ]
            conn.close()
            return ChatSession(
                session_id=row["session_id"],
                invoice_id=row["invoice_id"],
                customer_phone=row["customer_phone"],
                messages=messages
            )

        # Create new customer session with initial outbound agent reminder message
        profile = get_customer_financial_profile(customer_phone)
        cust_name = profile["invoices"][0]["customer_name"] if profile["invoices"] else "valued customer"
        pending_bills = [item for item in profile["invoices"] if item["status"] != "PAID"]
        
        if len(pending_bills) > 1:
            bill_ids_str = ", ".join([b["invoice_id"] for b in pending_bills])
            greeting_text = (
                f"Hi {cust_name}! This is Resolve.ai reaching out on behalf of your merchant regarding your {len(pending_bills)} pending invoices "
                f"({bill_ids_str}) with a total outstanding balance of ₹{profile['total_remaining_balance_inr']:,.2f}. "
                "How would you like to resolve these today? Tap a quick proposal button below to start flexible terms."
            )
        elif pending_bills:
            inv_item = pending_bills[0]
            today_str = datetime.date.today().isoformat()
            due_verb = "was" if inv_item["due_date"] < today_str else "is"
            greeting_text = (
                f"Hi {cust_name}! This is Resolve.ai reaching out on behalf of your merchant regarding Invoice {inv_item['invoice_id']} "
                f"for ₹{inv_item['remaining_amount_inr']:,.2f}. Your due date {due_verb} {inv_item['due_date']}. "
                "How would you like to resolve this bill today? Tap a quick proposal button below to start flexible terms."
            )
        else:
            greeting_text = (
                f"Hi {cust_name}! This is Resolve.ai reaching out on behalf of your merchant. "
                "How can I assist you with your account today?"
            )

        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        initial_messages = [{
            "sender": "agent",
            "text": greeting_text,
            "timestamp": timestamp,
            "metadata": {"outbound_initial_reminder": True}
        }]

        cursor.execute("""
        INSERT INTO chat_sessions (session_id, invoice_id, customer_phone, messages_json)
        VALUES (%s, %s, %s, %s);
        """, (session_id, invoice_id, customer_phone, json.dumps(initial_messages)))
        conn.commit()
        conn.close()

        return ChatSession(
            session_id=session_id,
            invoice_id=invoice_id,
            customer_phone=customer_phone,
            messages=[
                ChatMessage(
                    sender="agent",
                    text=greeting_text,
                    timestamp=timestamp,
                    metadata={"outbound_initial_reminder": True}
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
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM chat_sessions WHERE session_id = %s;", (session_id,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            raise ValueError(f"ChatSession '{session_id}' not found.")

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
        WHERE session_id = %s;
        """, (json.dumps(raw_messages), session_id))
        conn.commit()
        conn.close()

        return new_msg

    def get_recent_history(self, session_id: str, limit: int = 5) -> List[ChatMessage]:
        """
        Returns the last `limit` message turns for LLM prompt context construction.
        """
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT messages_json FROM chat_sessions WHERE session_id = %s;", (session_id,))
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
