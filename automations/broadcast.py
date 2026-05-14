import os
import requests
from datetime import datetime, timedelta
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESTAURANT_ID = os.getenv("RESTAURANT_ID", "bosphorus-berlin")
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_OWNER_CHAT_ID = os.getenv("TELEGRAM_OWNER_CHAT_ID")

AVERAGE_SPEND_PER_COVER = 35.0
RESTAURANT_NAME = "Bosphorus Berlin"

_supabase = None


def _get_client():
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


def get_past_customers(days=90, slow_days_only=False):
    """
    Returns customers who visited within the last `days` days.
    slow_days_only=True filters to customers whose last visit was Mon-Thu
    (higher chance of responding to a slow-night offer).
    """
    try:
        client = _get_client()
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()

        result = (
            client.table("customers")
            .select("*")
            .gte("last_visit", since)
            .execute()
        )

        customers = result.data or []

        if slow_days_only:
            filtered = []
            for c in customers:
                try:
                    last_visit = datetime.fromisoformat(c["last_visit"])
                    if last_visit.weekday() < 4:  # Mon=0 … Thu=3
                        filtered.append(c)
                except Exception:
                    filtered.append(c)
            customers = filtered

        print(f"[broadcast] Found {len(customers)} eligible customers (days={days}, slow_days_only={slow_days_only})")
        return customers

    except Exception as e:
        print(f"[broadcast] get_past_customers error: {e}")
        return []


def send_broadcast(message_text, discount_percent=20, customers=None):
    """
    Sends a WhatsApp broadcast to a list of customers.
    If customers is None, fetches the last 90 days automatically.
    Returns a broadcast_id string used to track replies.
    """
    if customers is None:
        customers = get_past_customers(days=90)

    if not customers:
        print("[broadcast] No customers to broadcast to")
        return None

    broadcast_id = f"BC-{datetime.utcnow().strftime('%Y%m%d%H%M')}"
    sent_count = 0
    failed_count = 0
    sent_phones = []

    for customer in customers:
        phone = customer.get("phone")
        name = customer.get("name", "")
        if not phone:
            continue

        personalised = _personalise_message(message_text, name, discount_percent)
        success = _send_whatsapp(phone, personalised)

        if success:
            sent_count += 1
            sent_phones.append(phone)
        else:
            failed_count += 1

    # Log broadcast to Supabase for tracking
    _log_broadcast(broadcast_id, sent_count, failed_count, sent_phones, discount_percent, message_text)

    print(f"[broadcast] {broadcast_id} — sent: {sent_count}, failed: {failed_count}")
    return broadcast_id


def send_tonight_special(discount_percent=20):
    """
    Pre-built 'fill empty nights' broadcast.
    Sends German WhatsApp to all customers from last 90 days.
    Designed for Tuesday/Wednesday 5pm trigger via n8n.
    """
    message = (
        f"Guten Abend! Heute Abend haben wir noch Tische frei 🍽️\n"
        f"{discount_percent}% Rabatt wenn Sie in den nächsten 2 Stunden buchen.\n"
        f"Antworten Sie mit JA für eine sofortige Bestätigung."
    )
    customers = get_past_customers(days=90, slow_days_only=True)
    return send_broadcast(message, discount_percent=discount_percent, customers=customers)


def track_broadcast_result(phone, action):
    """
    Called by bot.py when a customer replies to a broadcast (JA = booked, other = replied only).
    action: 'replied' | 'booked'
    """
    try:
        client = _get_client()
        today = datetime.utcnow().strftime("%Y-%m-%d")

        # Find today's broadcast log
        result = (
            client.table("broadcast_log")
            .select("*")
            .eq("restaurant_id", RESTAURANT_ID)
            .gte("sent_at", today)
            .order("sent_at", desc=True)
            .limit(1)
            .execute()
        )

        if not result.data:
            return

        log = result.data[0]
        updates = {}

        if action == "replied":
            updates["reply_count"] = log.get("reply_count", 0) + 1
        elif action == "booked":
            updates["booking_count"] = log.get("booking_count", 0) + 1
            updates["reply_count"] = log.get("reply_count", 0) + 1

        if updates:
            client.table("broadcast_log").update(updates).eq("id", log["id"]).execute()
            print(f"[broadcast] Tracked {action} from {phone}")

    except Exception as e:
        print(f"[broadcast] track_broadcast_result error: {e}")


def generate_broadcast_report():
    """
    Sends a Telegram summary to the owner the morning after a broadcast.
    Called by n8n at 09:00 the following day.
    """
    try:
        client = _get_client()
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

        result = (
            client.table("broadcast_log")
            .select("*")
            .eq("restaurant_id", RESTAURANT_ID)
            .gte("sent_at", yesterday)
            .order("sent_at", desc=True)
            .limit(1)
            .execute()
        )

        if not result.data:
            print("[broadcast] No broadcast log found for yesterday")
            return False

        log = result.data[0]
        sent = log.get("sent_count", 0)
        replies = log.get("reply_count", 0)
        bookings = log.get("booking_count", 0)
        discount = log.get("discount_percent", 20)

        reply_rate = (replies / sent * 100) if sent > 0 else 0
        booking_rate = (bookings / sent * 100) if sent > 0 else 0
        revenue_estimate = bookings * 2.5 * AVERAGE_SPEND_PER_COVER  # avg 2.5 covers per booking

        report = (
            f"📣 *Broadcast-Bericht — {yesterday}*\n\n"
            f"📤 *Gesendet:* {sent} Nachrichten\n"
            f"💬 *Antworten:* {replies} ({reply_rate:.1f}%)\n"
            f"📅 *Buchungen:* {bookings} ({booking_rate:.1f}%)\n"
            f"🏷️ *Rabatt angeboten:* {discount}%\n"
            f"💶 *Geschätzter Umsatz:* €{revenue_estimate:,.0f}\n\n"
            f"_Ihr Bosphorus Bot_ 🚀"
        )

        return _send_telegram(report)

    except Exception as e:
        print(f"[broadcast] generate_broadcast_report error: {e}")
        return False


def _personalise_message(template, name, discount_percent):
    """Injects name and discount into the message template."""
    msg = template
    if name and "{name}" in msg:
        msg = msg.replace("{name}", name)
    if "{discount}" in msg:
        msg = msg.replace("{discount}", str(discount_percent))
    return msg


def _send_whatsapp(phone, message):
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        print(f"[broadcast] WhatsApp not configured — would send to {phone}")
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
        print(f"[broadcast] WhatsApp send error to {phone}: {e}")
        return False


def _send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_OWNER_CHAT_ID:
        print(f"[broadcast] Telegram not configured. Report:\n{message}")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_OWNER_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"[broadcast] Telegram send error: {e}")
        return False


def _log_broadcast(broadcast_id, sent_count, failed_count, sent_phones, discount_percent, message_text):
    """Saves broadcast metadata to Supabase for tracking."""
    try:
        client = _get_client()
        client.table("broadcast_log").insert({
            "restaurant_id": RESTAURANT_ID,
            "broadcast_id": broadcast_id,
            "sent_at": datetime.utcnow().isoformat(),
            "sent_count": sent_count,
            "failed_count": failed_count,
            "reply_count": 0,
            "booking_count": 0,
            "discount_percent": discount_percent,
            "message_preview": message_text[:200],
        }).execute()
    except Exception as e:
        print(f"[broadcast] _log_broadcast error (non-fatal): {e}")
