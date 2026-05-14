import os
import requests
from datetime import datetime, timedelta
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESTAURANT_ID = os.getenv("RESTAURANT_ID", "bosphorus-berlin")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")

# Time window for waitlist customer to confirm before slot moves to next person
CONFIRM_WINDOW_MINUTES = 15

_supabase = None


def _get_client():
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


def add_to_waitlist(phone, name, party_size, date, time):
    """
    Adds a customer to the waitlist for a specific date/time.
    Returns the waitlist record on success.
    """
    try:
        client = _get_client()

        # Check they're not already on the waitlist for this slot
        existing = (
            client.table("waitlist")
            .select("id")
            .eq("restaurant_id", RESTAURANT_ID)
            .eq("phone", phone)
            .eq("date", str(date))
            .eq("time", str(time))
            .eq("status", "waiting")
            .execute()
        )
        if existing.data:
            print(f"[waitlist] {phone} already on waitlist for {date} {time}")
            return existing.data[0]

        data = {
            "restaurant_id": RESTAURANT_ID,
            "phone": phone,
            "name": name,
            "party_size": int(party_size),
            "date": str(date),
            "time": str(time),
            "status": "waiting",
            "notified_at": None,
            "created_at": datetime.utcnow().isoformat()
        }

        result = client.table("waitlist").insert(data).execute()
        if result.data:
            print(f"[waitlist] Added {name} ({phone}) to waitlist for {date} {time}")
            return result.data[0]

        raise Exception("Insert returned no data")

    except Exception as e:
        print(f"[waitlist] add_to_waitlist error: {e}")
        raise


def notify_waitlist(date, time, party_size):
    """
    Called when a cancellation creates a free slot.
    Finds the first person on the waitlist whose party fits, notifies them via WhatsApp.
    Returns the notified record or None.
    """
    try:
        client = _get_client()

        result = (
            client.table("waitlist")
            .select("*")
            .eq("restaurant_id", RESTAURANT_ID)
            .eq("date", str(date))
            .eq("time", str(time))
            .eq("status", "waiting")
            .lte("party_size", int(party_size))
            .order("created_at")
            .execute()
        )

        if not result.data:
            print(f"[waitlist] No waiting customers for {date} {time}")
            return None

        candidate = result.data[0]
        _send_waitlist_notification(candidate)

        # Mark as notified
        expires_at = (datetime.utcnow() + timedelta(minutes=CONFIRM_WINDOW_MINUTES)).isoformat()
        client.table("waitlist").update({
            "status": "notified",
            "notified_at": datetime.utcnow().isoformat(),
            "expires_at": expires_at
        }).eq("id", candidate["id"]).execute()

        print(f"[waitlist] Notified {candidate['name']} ({candidate['phone']}) — expires {expires_at}")
        return candidate

    except Exception as e:
        print(f"[waitlist] notify_waitlist error: {e}")
        return None


def remove_from_waitlist(waitlist_id=None, phone=None, date=None, time=None):
    """
    Removes a person from the waitlist (after they confirm a booking, or decline).
    """
    try:
        client = _get_client()

        if waitlist_id:
            client.table("waitlist").update({"status": "removed"}).eq("id", waitlist_id).execute()
        elif phone and date and time:
            client.table("waitlist").update({"status": "removed"}).eq("phone", phone).eq("date", str(date)).eq("time", str(time)).execute()

        print(f"[waitlist] Removed from waitlist — id={waitlist_id} phone={phone}")

    except Exception as e:
        print(f"[waitlist] remove_from_waitlist error: {e}")


def expire_stale_notifications():
    """
    Called periodically (by n8n every 5 mins).
    If a notified customer didn't confirm within CONFIRM_WINDOW_MINUTES,
    moves them to 'expired' and notifies the next person on the waitlist.
    """
    try:
        client = _get_client()
        now = datetime.utcnow().isoformat()

        stale = (
            client.table("waitlist")
            .select("*")
            .eq("status", "notified")
            .lt("expires_at", now)
            .execute()
        )

        for entry in (stale.data or []):
            client.table("waitlist").update({"status": "expired"}).eq("id", entry["id"]).execute()
            print(f"[waitlist] Expired notification for {entry['name']} — trying next in line")
            notify_waitlist(entry["date"], entry["time"], entry["party_size"])

    except Exception as e:
        print(f"[waitlist] expire_stale_notifications error: {e}")


def get_waitlist(date, time):
    """Returns all waiting customers for a slot, in order."""
    try:
        client = _get_client()
        result = (
            client.table("waitlist")
            .select("*")
            .eq("restaurant_id", RESTAURANT_ID)
            .eq("date", str(date))
            .eq("time", str(time))
            .eq("status", "waiting")
            .order("created_at")
            .execute()
        )
        return result.data or []
    except Exception as e:
        print(f"[waitlist] get_waitlist error: {e}")
        return []


def _send_waitlist_notification(entry):
    """Sends WhatsApp message to inform a waitlist customer a table is available."""
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        print(f"[waitlist] WhatsApp not configured — would notify {entry['phone']}")
        return

    message = (
        f"🎉 {entry['name']}, ein Tisch ist frei geworden!\n"
        f"Datum: {entry['date']} um {entry['time']} Uhr für {entry['party_size']} Personen.\n"
        f"Antworten Sie mit JA innerhalb von {CONFIRM_WINDOW_MINUTES} Minuten, um zu bestätigen."
    )

    try:
        url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": entry["phone"],
            "type": "text",
            "text": {"body": message}
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        print(f"[waitlist] WhatsApp notification sent to {entry['phone']}")
    except Exception as e:
        print(f"[waitlist] WhatsApp send error: {e}")
