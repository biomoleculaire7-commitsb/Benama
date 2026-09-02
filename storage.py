"""
تخزين الملفات الدائم — يستعمل Supabase Storage (نفس حساب قاعدة البيانات)
بدل القرص المحلي المؤقت الذي يُمسح عند إعادة تشغيل Render.

يعمل تلقائياً بمجرد وجود SUPABASE_URL و SUPABASE_SERVICE_KEY كمتغيّرات بيئة.
إن لم تتوفرا، يعود النظام للتخزين المحلي القديم (غير دائم) دون أي عطل.
"""
import os
import time
import requests

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
STORAGE_ENABLED = bool(SUPABASE_URL and SUPABASE_KEY)
BUCKET = "school-files"


def upload_file(file_bytes, filename, content_type=None):
    """Uploads to Supabase Storage and returns a permanent public URL, or None on failure."""
    if not STORAGE_ENABLED:
        return None
    safe_name = f"{int(time.time()*1000)}_{filename}".replace(" ", "_")
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{safe_name}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "apikey": SUPABASE_KEY,
        "Content-Type": content_type or "application/octet-stream",
        "x-upsert": "true",
    }
    try:
        resp = requests.post(url, headers=headers, data=file_bytes, timeout=30)
        if resp.status_code in (200, 201):
            return f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{safe_name}"
        print(f"[WARNING] Supabase Storage upload failed ({resp.status_code}): {resp.text[:200]}")
        return None
    except Exception as e:
        print(f"[WARNING] Supabase Storage upload error: {e}")
        return None
