"""
Chat Router
Endpoints for fetching session history and simulating WhatsApp chat interactions.
"""

from typing import Optional
from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.services.session import session_manager
from backend.services.agent import agentic_negotiator
from backend.core.database import get_connection
from backend.routers.events import broadcast_sse_event

router = APIRouter(prefix="/api/chat", tags=["chat"])

class ChatMessageRequest(BaseModel):
    session_id: Optional[str] = None
    invoice_id: Optional[str] = None
    customer_phone: str
    message: str

class ChatResetRequest(BaseModel):
    session_id: str

@router.get("/history")
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

@router.post("/message")
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

@router.post("/reset")
async def reset_chat_session(req: ChatResetRequest):
    """Resets chat history for a session."""
    phone = req.session_id.split("_")[0] if "_" in req.session_id else req.session_id
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE chat_sessions SET messages_json = '[]' WHERE customer_phone = %s;", (phone,))
    conn.commit()
    conn.close()
    return {"status": "reset", "customer_phone": phone}
