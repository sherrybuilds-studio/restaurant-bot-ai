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
    """Sends a WhatsApp text message. Returns True on success."""
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        print(f"[reminders] WhatsApp not configured — would send to {phone}:\n{message}")
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
        print(f"[reminders] WhatsApp sent to {phone}")
        return True
    except Exception as e:
        print(f"[reminders] WhatsApp send error to {phone}: {e}")
        return False


def send_reminder_24h():
    """
    Called by n8n daily. Sends 24h reminder to all reservations for tomorrow.
    Marks reminder_24h_sent = true on each record.
    """
    try:
        client = _get_client()
        tomorrow = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")

        reservations = (
            client.table("reservations")
            .select("*")
            .eq("restaurant_id", RESTAURANT_ID)
            .eq("date", tomorrow)
            .eq("status", "confirmed")
            .execute()
        )

        sent_count = 0
        for res in (reservations.data or []):
            if res.get("reminder_24h_sent"):
                continue

            message = (
                f"Hallo {res['customer_name']}! 🍽️\n"
                f"Erinnerung: Ihr Tisch für {res['party_size']} Personen morgen um {res['time']} Uhr im Bosphorus Berlin.\n"
                f"Antworten Sie mit JA zur Bestätigung oder NEIN zum Stornieren. Bestätigungsnr.: {res['confirmation_number']}"
            )

            if _send_whatsapp(res["phone"], message):
                client.table("reservations").update(
                    {"reminder_24h_sent": True}
                ).eq("id", res["id"]).execute()
                sent_count += 1

        print(f"[reminders] 24h reminders sent: {sent_count}")
        return sent_count

    except Exception as e:
        print(f"[reminders] send_reminder_24h error: {e}")
        return 0


def send_reminder_2h():
    """
    Called by n8n every hour. Sends 2h reminder to reservations without 24h reply.
    Targets reservations starting in the next 2–3 hour window.
    """
    try:
        client = _get_client()
        now = datetime.utcnow()
        today = now.strftime("%Y-%m-%d")

        # Get all of today's confirmed reservations that haven't had the 2h reminder yet
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
            if res.get("reminder_2h_sent"):
                continue

            try:
                res_time = datetime.strptime(f"{today} {res['time']}", "%Y-%m-%d %H:%M")
                minutes_until = (res_time - now).total_seconds() / 60

                # Send if 90–150 mins away (buffer so we don't double-send)
                if not (90 <= minutes_until <= 150):
                    continue
            except Exception:
                continue

            message = (
                f"Bosphorus Berlin erinnert Sie: Ihr Tisch für {res['party_size']} Personen ist heute um {res['time']} Uhr reserviert. 🌟\n"
                f"Wir freuen uns auf Sie, {res['customer_name']}!\n"
                f"Falls Sie stornieren möchten, antworten Sie bitte mit NEIN. Bestätigungsnr.: {res['confirmation_number']}"
            )

            if _send_whatsapp(res["phone"], message):
                client.table("reservations").update(
                    {"reminder_2h_sent": True}
                ).eq("id", res["id"]).execute()
                sent_count += 1

        print(f"[reminders] 2h reminders sent: {sent_count}")
        return sent_count

    except Exception as e:
        print(f"[reminders] send_reminder_2h error: {e}")
        return 0


def send_review_request(phone, name, reservation_id=None):
    """
    Sends a Google review request 2 hours after the reservation time.
    Called by n8n or automations/reviews.py.
    """
    try:
        message = (
            f"Guten Abend, {name}! Wir hoffen, Ihr Abend im Bosphorus Berlin war wunderbar. 🌙\n"
            f"Eine kurze Google-Bewertung (30 Sekunden) bedeutet uns sehr viel: {GOOGLE_REVIEW_LINK}\n"
            f"Herzlichen Dank — wir freuen uns, Sie bald wieder zu sehen!"
        )

        success = _send_whatsapp(phone, message)

        if success and reservation_id:
            try:
                client = _get_client()
                client.table("reservations").update(
                    {"review_request_sent": True}
                ).eq("id", reservation_id).execute()
            except Exception as e:
                print(f"[reminders] Failed to mark review_request_sent: {e}")

        return success

    except Exception as e:
        print(f"[reminders] send_review_request error: {e}")
        return False


def process_reminder_reply(phone, reply_text):
    """
    Processes YES/NO replies to reminder messages.
    Called by bot.py when it detects a confirmation intent from a known phone number.
    Returns a status string: 'confirmed', 'cancelled', 'unknown'
    """
    try:
        reply = reply_text.strip().upper()
        client = _get_client()

        # Find most recent upcoming confirmed reservation for this phone
        today = datetime.utcnow().strftime("%Y-%m-%d")
        result = (
            client.table("reservations")
            .select("*")
            .eq("phone", phone)
            .eq("status", "confirmed")
            .gte("date", today)
            .order("date")
            .limit(1)
            .execute()
        )

        if not result.data:
            return "unknown"

        res = result.data[0]

        if reply in ("JA", "YES", "J", "Y", "SI", "EVET"):
            client.table("reservations").update(
                {"status": "confirmed", "customer_confirmed": True}
            ).eq("id", res["id"]).execute()
            print(f"[reminders] {phone} confirmed reservation {res['confirmation_number']}")
            return "confirmed"

        if reply in ("NEIN", "NO", "N", "HAYIR"):
            client.table("reservations").update({"status": "cancelled"}).eq("id", res["id"]).execute()
            print(f"[reminders] {phone} cancelled reservation {res['confirmation_number']}")

            # Trigger waitlist notification for freed slot
            from reservations.waitlist import notify_waitlist
            notify_waitlist(res["date"], res["time"], res["party_size"])
            return "cancelled"

        return "unknown"

    except Exception as e:
        print(f"[reminders] process_reminder_reply error: {e}")
        return "unknown"
