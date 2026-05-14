import os
import requests
from datetime import datetime, timedelta
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESTAURANT_ID = os.getenv("RESTAURANT_ID", "bosphorus-berlin")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_PLACE_ID = os.getenv("GOOGLE_PLACE_ID", "ChIJ_bosphorus_berlin_place_id")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_OWNER_CHAT_ID = os.getenv("TELEGRAM_OWNER_CHAT_ID")

STAR_EMOJIS = {1: "⭐", 2: "⭐⭐", 3: "⭐⭐⭐", 4: "⭐⭐⭐⭐", 5: "⭐⭐⭐⭐⭐"}

_supabase = None


def _get_client():
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


def check_new_reviews():
    """
    Calls Google My Business API to fetch recent reviews.
    Compares against already-seen review IDs stored in Supabase.
    Returns list of new review dicts.

    NOTE: Owner must set GOOGLE_API_KEY and GOOGLE_PLACE_ID in .env.
    API endpoint: https://mybusiness.googleapis.com/v4/accounts/{account}/locations/{location}/reviews
    """
    if not GOOGLE_API_KEY:
        print("[review_monitor] GOOGLE_API_KEY not set — skipping review check")
        return []

    try:
        # Google My Business Reviews API
        # Full URL requires account_id + location_id, both from GOOGLE_PLACE_ID env var
        # Format: accounts/{account_id}/locations/{location_id}
        url = (
            f"https://mybusiness.googleapis.com/v4/{GOOGLE_PLACE_ID}/reviews"
            f"?key={GOOGLE_API_KEY}&pageSize=10&orderBy=updateTime+desc"
        )

        resp = requests.get(url, timeout=15)

        if resp.status_code == 401:
            print("[review_monitor] Google API auth failed — check GOOGLE_API_KEY")
            return []

        if resp.status_code == 404:
            print("[review_monitor] Google place not found — check GOOGLE_PLACE_ID")
            return []

        resp.raise_for_status()
        data = resp.json()
        reviews = data.get("reviews", [])

        seen_ids = _get_seen_review_ids()
        new_reviews = []

        for review in reviews:
            review_id = review.get("reviewId", "")
            if review_id and review_id not in seen_ids:
                new_reviews.append(_normalise_review(review))

        print(f"[review_monitor] Found {len(new_reviews)} new reviews")
        return new_reviews

    except requests.exceptions.RequestException as e:
        print(f"[review_monitor] Google API request error: {e}")
        return []
    except Exception as e:
        print(f"[review_monitor] check_new_reviews error: {e}")
        return []


def _normalise_review(raw):
    """Extracts the fields we care about from a raw Google review object."""
    rating_map = {
        "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5
    }
    star_str = raw.get("starRating", "THREE")
    stars = rating_map.get(star_str, 3)

    reviewer = raw.get("reviewer", {})
    return {
        "review_id": raw.get("reviewId", ""),
        "reviewer_name": reviewer.get("displayName", "Anonymous"),
        "stars": stars,
        "text": raw.get("comment", "").strip(),
        "time": raw.get("updateTime", datetime.utcnow().isoformat()),
        "reply": raw.get("reviewReply", {}).get("comment", "")
    }


def send_review_alert(review):
    """
    Sends an immediate Telegram alert to the owner for a new review.
    1-2 stars → URGENT flag + suggested call to action.
    4-5 stars → celebration message.
    Calls review_responder to generate a suggested response.
    """
    try:
        from automations.review_responder import draft_response

        stars = review["stars"]
        star_display = STAR_EMOJIS.get(stars, "⭐")
        reviewer = review["reviewer_name"]
        text = review["text"] or "(No text)"

        # Generate AI-suggested response
        suggested_response = draft_response(text, stars)

        if stars <= 2:
            urgency = "🚨 *DRINGEND — NEGATIVE BEWERTUNG*"
            action = "⚠️ _Empfehlung: Sofort anrufen und persönlich entschuldigen._"
        elif stars == 3:
            urgency = "⚠️ *Neue Bewertung — Handlungsbedarf*"
            action = "_Antworten Sie zeitnah und bieten Sie an, es beim nächsten Besuch besser zu machen._"
        else:
            urgency = "🎉 *Neue positive Bewertung!*"
            action = "_Herzlichen Glückwunsch! Bedanken Sie sich persönlich._"

        message = (
            f"{urgency}\n\n"
            f"{star_display} *{reviewer}*\n"
            f"_{text}_\n\n"
            f"{action}\n\n"
            f"*Vorgeschlagene Antwort:*\n{suggested_response}\n\n"
            f"_Zum Antworten: Google My Business öffnen → Bewertungen → Antworten_"
        )

        success = _send_telegram(message)

        if success:
            _mark_review_seen(review)

        return success

    except Exception as e:
        print(f"[review_monitor] send_review_alert error: {e}")
        return False


def run_review_check():
    """
    Main entry point. Called by n8n every 30 minutes.
    Checks for new reviews and alerts owner for each one found.
    """
    new_reviews = check_new_reviews()

    if not new_reviews:
        return 0

    alerted = 0
    for review in new_reviews:
        success = send_review_alert(review)
        if success:
            alerted += 1

    print(f"[review_monitor] Alerted owner about {alerted} new review(s)")

    if alerted > 0:
        _update_weekly_stats(new_reviews)

    return alerted


def generate_weekly_review_report():
    """
    Sends a weekly review summary to the owner every Monday morning.
    Covers the past 7 days of reviews tracked in Supabase.
    """
    try:
        client = _get_client()
        since = (datetime.utcnow() - timedelta(days=7)).isoformat()

        result = (
            client.table("review_log")
            .select("*")
            .eq("restaurant_id", RESTAURANT_ID)
            .gte("received_at", since)
            .execute()
        )

        reviews = result.data or []
        if not reviews:
            _send_telegram("📊 *Wochenbericht Bewertungen:* Keine neuen Bewertungen diese Woche.")
            return

        total = len(reviews)
        avg_stars = sum(r.get("stars", 0) for r in reviews) / total
        by_stars = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for r in reviews:
            by_stars[r.get("stars", 3)] = by_stars.get(r.get("stars", 3), 0) + 1

        report = (
            f"⭐ *Wochenbericht Bewertungen — Bosphorus Berlin*\n\n"
            f"📊 *Neue Bewertungen:* {total}\n"
            f"📈 *Durchschnitt:* {avg_stars:.1f} / 5.0\n\n"
            f"5⭐: {by_stars[5]}x\n"
            f"4⭐: {by_stars[4]}x\n"
            f"3⭐: {by_stars[3]}x\n"
            f"2⭐: {by_stars[2]}x\n"
            f"1⭐: {by_stars[1]}x\n\n"
            f"_Ihr Bosphorus Bot_ 🌟"
        )

        _send_telegram(report)

    except Exception as e:
        print(f"[review_monitor] generate_weekly_review_report error: {e}")


def _get_seen_review_ids():
    """Returns a set of review IDs already logged to Supabase."""
    try:
        client = _get_client()
        result = (
            client.table("review_log")
            .select("review_id")
            .eq("restaurant_id", RESTAURANT_ID)
            .execute()
        )
        return {r["review_id"] for r in (result.data or [])}
    except Exception as e:
        print(f"[review_monitor] _get_seen_review_ids error: {e}")
        return set()


def _mark_review_seen(review):
    """Saves a review to the review_log table so it's not alerted again."""
    try:
        client = _get_client()
        client.table("review_log").insert({
            "restaurant_id": RESTAURANT_ID,
            "review_id": review["review_id"],
            "reviewer_name": review["reviewer_name"],
            "stars": review["stars"],
            "text": review["text"][:500],
            "received_at": review["time"],
            "alerted_at": datetime.utcnow().isoformat()
        }).execute()
    except Exception as e:
        print(f"[review_monitor] _mark_review_seen error (non-fatal): {e}")


def _update_weekly_stats(reviews):
    """Updates running star-count stats in analytics table."""
    try:
        client = _get_client()
        today = datetime.utcnow().strftime("%Y-%m-%d")

        for review in reviews:
            stars = review.get("stars", 0)
            if stars >= 4:
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
                        "positive_reviews": record.get("positive_reviews", 0) + 1
                    }).eq("id", record["id"]).execute()

    except Exception as e:
        print(f"[review_monitor] _update_weekly_stats error (non-fatal): {e}")


def _send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_OWNER_CHAT_ID:
        print(f"[review_monitor] Telegram not configured. Alert:\n{message[:200]}")
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
        print(f"[review_monitor] Telegram send error: {e}")
        return False
