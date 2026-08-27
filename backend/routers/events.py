"""
Events Router
Handles Server-Sent Events (SSE) for real-time frontend updates.
"""

import asyncio
import json
from typing import Dict, Any, List

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/events", tags=["events"])

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

@router.get("")
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
