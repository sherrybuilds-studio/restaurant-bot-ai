import os
import requests
from datetime import datetime, timedelta
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESTAURANT_ID = os.getenv("RESTAURANT_ID", "bosphorus-berlin")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
GOOGLE_REVIEW_LINK = "https://g.page/r/bosphorus-berlin/review"

_supabase = None


def _get_client():
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


def _send_whatsapp(phone, message):
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        print(f"[reviews] WhatsApp not configured — would send to {phone}")
        return False
    try:
        url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": message}
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[reviews] WhatsApp send error: {e}")
        return False


def send_review_request(phone, name, reservation_id=None):
    """
    Sends a post-visit Google review request via WhatsApp.
    Should be called ~2 hours after reservation time.
    """
    try:
        message = (
            f"Guten Abend, {name}! Wir hoffen, Ihr Abend bei Bosphorus Berlin war unvergesslich. 🌙\n"
            f"Eine kurze Google-Bewertung bedeutet uns alles — nur 30 Sekunden: {GOOGLE_REVIEW_LINK}\n"
            f"Herzlichen Dank und bis bald! Das Team vom Bosphorus Berlin 🫶"
        )

        success = _send_whatsapp(phone, message)

        if success and reservation_id:
            try:
                client = _get_client()
                client.table("reservations").update({
                    "review_request_sent": True,
                    "review_request_sent_at": datetime.utcnow().isoformat()
                }).eq("id", reservation_id).execute()
            except Exception as e:
                print(f"[reviews] Failed to update review_request_sent flag: {e}")

        if success:
            _log_review_sent(phone, name, reservation_id)

        return success

    except Exception as e:
        print(f"[reviews] send_review_request error: {e}")
        return False


def run_post_visit_reviews():
    """
    Called by n8n every 30 minutes.
    Finds reservations that ended ~2 hours ago and haven't received a review request yet.
    """
    try:
        client = _get_client()
        now = datetime.utcnow()
        today = now.strftime("%Y-%m-%d")

        reservations = (
            client.table("reservations")
            .select("*")
            .eq("restaurant_id", RESTAURANT_ID)
            .eq("date", today)
            .eq("status", "confirmed")
            .execute()
        )

        sent_count = 0
        for res in (reservations.data or []):
            if res.get("review_request_sent"):
                continue

            try:
                res_time = datetime.strptime(f"{today} {res['time']}", "%Y-%m-%d %H:%M")
                hours_since = (now - res_time).total_seconds() / 3600

                # Send review request 1.5–3 hours after reservation time
                if not (1.5 <= hours_since <= 3.0):
                    continue
            except Exception:
                continue

            success = send_review_request(res["phone"], res["customer_name"], res["id"])
            if success:
                sent_count += 1

        print(f"[reviews] Review requests sent: {sent_count}")
        return sent_count

    except Exception as e:
        print(f"[reviews] run_post_visit_reviews error: {e}")
        return 0


def _log_review_sent(phone, name, reservation_id):
    """Logs review request to analytics table."""
    try:
        client = _get_client()
        today = datetime.utcnow().strftime("%Y-%m-%d")

        existing = (
            client.table("analytics")
            .select("*")
            .eq("restaurant_id", RESTAURANT_ID)
            .eq("date", today)
            .execute()
        )

        if existing.data:
            record = existing.data[0]
            client.table("analytics").update({
                "reviews_sent": record.get("reviews_sent", 0) + 1
            }).eq("id", record["id"]).execute()
        else:
            client.table("analytics").insert({
                "restaurant_id": RESTAURANT_ID,
                "date": today,
                "reviews_sent": 1,
                "questions_asked": 0,
                "bookings_made": 0,
                "upsells_converted": 0
            }).execute()

    except Exception as e:
        print(f"[reviews] _log_review_sent error (non-fatal): {e}")
