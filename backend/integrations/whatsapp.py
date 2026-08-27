"""
WhatsApp Cloud API Client
Handles sending outbound WhatsApp template and text messages to customers.
"""

import requests
import time
from typing import Dict, Any, List, Optional
from backend.core.config import settings

class WhatsAppCloudClient:
    def __init__(
        self,
        token: Optional[str] = None,
        phone_id: Optional[str] = None
    ):
        self.token = token or settings.META_WHATSAPP_TOKEN
        self.phone_id = phone_id or settings.META_WHATSAPP_PHONE_ID
        self.base_url = f"https://graph.facebook.com/v18.0/{self.phone_id}/messages"
        self.is_mock = self.token == "mock_meta_token" or not self.token

    def send_text_message(self, to_phone: str, message_text: str) -> Dict[str, Any]:
        """
        Sends a standard text WhatsApp message to a customer.
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "text",
            "text": {
                "preview_url": True,
                "body": message_text
            }
        }

        if self.is_mock:
            return {
                "messaging_product": "whatsapp",
                "contacts": [{"input": to_phone, "wa_id": to_phone}],
                "messages": [{"id": f"wamid.mock_{int(time.time())}"}],
                "status": "sent_mock"
            }

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        response = requests.post(self.base_url, json=payload, headers=headers, timeout=10.0)
        response.raise_for_status()
        return response.json()

    def send_interactive_buttons(
        self,
        to_phone: str,
        body_text: str,
        buttons: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Sends a Meta Interactive Button message (e.g. for multi-invoice selection).
        Each button in buttons list: {"id": "select_invoice_inv_001", "title": "Invoice Inv-001"}
        """
        formatted_buttons = []
        for b in buttons[:3]:  # Meta limits quick reply buttons to max 3
            formatted_buttons.append({
                "type": "reply",
                "reply": {
                    "id": b["id"],
                    "title": b["title"][:20]  # Meta button title 20 char max limit
                }
            })

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_phone,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "action": {"buttons": formatted_buttons}
            }
        }

        if self.is_mock:
            return {
                "messaging_product": "whatsapp",
                "contacts": [{"input": to_phone, "wa_id": to_phone}],
                "messages": [{"id": f"wamid.mock_btn_{int(time.time())}"}],
                "status": "sent_mock_interactive"
            }

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        response = requests.post(self.base_url, json=payload, headers=headers, timeout=10.0)
        response.raise_for_status()
        return response.json()

whatsapp_client = WhatsAppCloudClient()
