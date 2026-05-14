import os
import requests
from datetime import datetime, timedelta
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESTAURANT_ID = os.getenv("RESTAURANT_ID", "bosphorus-berlin")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_OWNER_CHAT_ID = os.getenv("TELEGRAM_OWNER_CHAT_ID")

AVERAGE_SPEND_PER_COVER = 35.0  # EUR — used for revenue estimates

_supabase = None


def _get_client():
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


def _send_telegram(message):
    """Sends a message to the owner via Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_OWNER_CHAT_ID:
        print(f"[reports] Telegram not configured. Report:\n{message}")
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
        print("[reports] Telegram message sent to owner")
        return True
    except Exception as e:
        print(f"[reports] Telegram send error: {e}")
        return False


def generate_daily_report(target_date=None):
    """
    Generates and sends a daily summary report via Telegram.
    Called by n8n at 22:00 each evening.
    target_date: datetime.date object or None (defaults to today)
    """
    try:
        client = _get_client()
        date = target_date or datetime.utcnow().date()
        date_str = str(date)
        day_name = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %d. %B %Y")

        # Fetch all reservations for the day
        reservations = (
            client.table("reservations")
            .select("*")
            .eq("restaurant_id", RESTAURANT_ID)
            .eq("date", date_str)
            .execute()
        )

        all_res = reservations.data or []
        confirmed = [r for r in all_res if r["status"] == "confirmed"]
        cancelled = [r for r in all_res if r["status"] == "cancelled"]
        no_shows = [r for r in all_res if r["status"] == "no_show"]

        total_covers = sum(r["party_size"] for r in confirmed)
        cancelled_covers = sum(r["party_size"] for r in cancelled)
        no_show_covers = sum(r["party_size"] for r in no_shows)

        revenue_estimate = total_covers * AVERAGE_SPEND_PER_COVER

        # Fetch analytics for today
        analytics = (
            client.table("analytics")
            .select("*")
            .eq("restaurant_id", RESTAURANT_ID)
            .eq("date", date_str)
            .execute()
        )
        analytics_data = analytics.data[0] if analytics.data else {}

        questions_asked = analytics_data.get("questions_asked", 0)
        bookings_made = analytics_data.get("bookings_made", 0)
        reviews_sent = analytics_data.get("reviews_sent", 0)

        # Build report
        report = (
            f"📊 *Tagesbericht Bosphorus Berlin*\n"
            f"_{day_name}_\n\n"
            f"🍽️ *Reservierungen heute:* {len(confirmed)}\n"
            f"👥 *Covers:* {total_covers} / 60\n"
            f"💶 *Umsatzschätzung:* €{revenue_estimate:,.0f}\n\n"
            f"❌ *Stornierungen:* {len(cancelled)} ({cancelled_covers} covers)\n"
            f"🚫 *No-Shows:* {len(no_shows)} ({no_show_covers} covers)\n\n"
            f"💬 *Bot-Anfragen:* {questions_asked}\n"
            f"📅 *Online-Buchungen:* {bookings_made}\n"
            f"⭐ *Bewertungsanfragen gesendet:* {reviews_sent}\n\n"
            f"_Gute Nacht! Ihr Bosphorus Bot_ 🌙"
        )

        return _send_telegram(report)

    except Exception as e:
        print(f"[reports] generate_daily_report error: {e}")
        return False


def generate_weekly_report():
    """
    Sends a weekly summary every Monday morning.
    Covers the past 7 days.
    """
    try:
        client = _get_client()
        today = datetime.utcnow().date()
        week_start = today - timedelta(days=7)
        week_start_str = str(week_start)
        week_end_str = str(today)

        reservations = (
            client.table("reservations")
            .select("*")
            .eq("restaurant_id", RESTAURANT_ID)
            .gte("date", week_start_str)
            .lte("date", week_end_str)
            .execute()
        )

        all_res = reservations.data or []
        confirmed = [r for r in all_res if r["status"] == "confirmed"]
        cancelled = [r for r in all_res if r["status"] == "cancelled"]
        no_shows = [r for r in all_res if r["status"] == "no_show"]

        total_covers = sum(r["party_size"] for r in confirmed)
        revenue_estimate = total_covers * AVERAGE_SPEND_PER_COVER

        no_show_rate = 0
        if confirmed or no_shows:
            no_show_rate = len(no_shows) / (len(confirmed) + len(no_shows)) * 100

        # Analytics aggregation
        analytics = (
            client.table("analytics")
            .select("*")
            .eq("restaurant_id", RESTAURANT_ID)
            .gte("date", week_start_str)
            .lte("date", week_end_str)
            .execute()
        )

        total_questions = sum(r.get("questions_asked", 0) for r in (analytics.data or []))
        total_bookings = sum(r.get("bookings_made", 0) for r in (analytics.data or []))
        total_reviews = sum(r.get("reviews_sent", 0) for r in (analytics.data or []))

        report = (
            f"📈 *Wochenbericht Bosphorus Berlin*\n"
            f"_{week_start.strftime('%d.%m')} – {today.strftime('%d.%m.%Y')}_\n\n"
            f"🍽️ *Reservierungen:* {len(confirmed)}\n"
            f"👥 *Covers gesamt:* {total_covers}\n"
            f"💶 *Umsatzschätzung:* €{revenue_estimate:,.0f}\n\n"
            f"❌ *Stornierungen:* {len(cancelled)}\n"
            f"🚫 *No-Show-Rate:* {no_show_rate:.1f}%\n\n"
            f"💬 *Bot-Anfragen gesamt:* {total_questions}\n"
            f"📅 *Online-Buchungen:* {total_bookings}\n"
            f"⭐ *Bewertungsanfragen:* {total_reviews}\n\n"
            f"_Gute Woche! Ihr Bosphorus Bot_ 🌟"
        )

        return _send_telegram(report)

    except Exception as e:
        print(f"[reports] generate_weekly_report error: {e}")
        return False


def send_custom_alert(message):
    """Sends an ad-hoc alert to the owner (e.g., for urgent review alerts)."""
    return _send_telegram(message)


if __name__ == "__main__":
    print("Generating daily report...")
    generate_daily_report()
