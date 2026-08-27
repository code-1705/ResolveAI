"""
Cloud Storage Integration
Manages secure invoice document uploads and CDN URL generation via Supabase.
"""

import requests
from typing import Optional
from backend.core.config import settings

def upload_to_supabase_storage(file_name: str, file_bytes: bytes, mime_type: str) -> Optional[str]:
    """Uploads file bytes to Supabase Storage Bucket 'resolveai-invoices' and generates a 10-year signed CDN URL."""
    supabase_url = getattr(settings, 'SUPABASE_URL', 'https://lcpyyilepfnlmbrwdzcv.supabase.co').rstrip('/')
    supabase_key = getattr(settings, 'SUPABASE_SERVICE_KEY', '')

    if not supabase_key:
        print("[Supabase Storage]: SUPABASE_SERVICE_KEY not set in .env. Falling back to DB blob.")
        return None

    safe_name = file_name.replace(' ', '_').replace('/', '_')
    upload_url = f"{supabase_url}/storage/v1/object/resolveai-invoices/{safe_name}"

    headers = {
        "Authorization": f"Bearer {supabase_key}",
        "apiKey": supabase_key,
        "Content-Type": mime_type,
        "x-upsert": "true"
    }

    try:
        # 1. Upload Binary File to Supabase Storage Bucket
        resp = requests.post(upload_url, headers=headers, data=file_bytes, timeout=15.0)
        if resp.status_code in (200, 201):
            # 2. Generate Secure Signed CDN URL
            sign_url = f"{supabase_url}/storage/v1/object/sign/resolveai-invoices/{safe_name}"
            sign_headers = {
                "Authorization": f"Bearer {supabase_key}",
                "apiKey": supabase_key,
                "Content-Type": "application/json"
            }
            sign_res = requests.post(sign_url, headers=sign_headers, json={"expiresIn": 315360000}, timeout=10.0)
            if sign_res.status_code == 200:
                signed_path = sign_res.json().get("signedURL")
                full_cdn_url = f"{supabase_url}/storage/v1{signed_path}"
                print(f"[Supabase Storage Success]: Uploaded {safe_name} -> {full_cdn_url}")
                return full_cdn_url

            # Fallback to public URL format if signing fails
            public_cdn_url = f"{supabase_url}/storage/v1/object/public/resolveai-invoices/{safe_name}"
            print(f"[Supabase Storage Uploaded]: {safe_name} -> {public_cdn_url}")
            return public_cdn_url
        else:
            print(f"[Supabase Storage Error]: {resp.status_code} - {resp.text}")
            return None
    except Exception as e:
        print(f"[Supabase Storage Exception]: {e}")
        return None
