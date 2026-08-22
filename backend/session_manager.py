import asyncio
import threading
import json
import datetime
from typing import Dict, Any, List, Optional
from backend.config import settings
from backend.models import ChatSession, ChatMessage
from backend.database import get_connection, get_invoice
from backend.guardrails import paise_to_inr

# Session locks with multi-loop asyncio safety
SESSION_LOCKS: Dict[str, asyncio.Lock] = {}
SESSION_LOCK_MUTEX = threading.Lock()

def get_session_lock(session_id: str) -> asyncio.Lock:
    """
    Returns an asyncio.Lock bound to the current running event loop for the session_id.
    Prevents double-texting race conditions from executing parallel LLM tool calls.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    loop_id = id(loop)
    with SESSION_LOCK_MUTEX:
        key = f"{loop_id}_{session_id}"
        if key not in SESSION_LOCKS:
            SESSION_LOCKS[key] = asyncio.Lock()
        return SESSION_LOCKS[key]

class SessionManager:
    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path

    @property
    def db_path(self) -> str:
        return self._db_path or settings.DATABASE_PATH

    def get_or_create_session(self, session_id: str, invoice_id: str, customer_phone: str) -> ChatSession:
        """
        Loads an existing ChatSession from SQLite or creates a new one.
        Composite session key: f"{customer_phone}_{invoice_id}"
        """
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM chat_sessions WHERE session_id = ?;", (session_id,))
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

        # Create new session with initial outbound agent reminder message
        inv = get_invoice(invoice_id, self.db_path)
        greeting_text = ""
        if inv:
            greeting_text = (
                f"Hi {inv.customer_name}! This is Resolve.ai reaching out on behalf of your merchant regarding Invoice {invoice_id} "
                f"for ₹{paise_to_inr(inv.remaining_amount_paise):,.2f}. Your due date is {inv.due_date}. "
                "How would you like to resolve this bill today? Tap a quick proposal button below to start flexible terms."
            )
        else:
            greeting_text = (
                f"Hi! This is Resolve.ai reaching out regarding Invoice {invoice_id}. "
                "How would you like to resolve this bill today?"
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
        VALUES (?, ?, ?, ?);
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
        Appends a user or agent message turn to the SQLite chat session.
        """
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM chat_sessions WHERE session_id = ?;", (session_id,))
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
        SET messages_json = ?
        WHERE session_id = ?;
        """, (json.dumps(raw_messages), session_id))
        conn.commit()
        conn.close()

        return new_msg

    def get_recent_history(self, session_id: str, limit: int = 5) -> List[ChatMessage]:
        """
        Returns the last `limit` message turns for LLM prompt context construction.
        """
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT messages_json FROM chat_sessions WHERE session_id = ?;", (session_id,))
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
