import os
from datetime import datetime, timedelta
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESTAURANT_ID = os.getenv("RESTAURANT_ID", "bosphorus-berlin")
RESTAURANT_CAPACITY = 60

# Time slots offered (24h format strings)
TIME_SLOTS = [
    "12:00", "12:30", "13:00", "13:30", "14:00", "14:30",
    "17:00", "17:30", "18:00", "18:30", "19:00", "19:30",
    "20:00", "20:30", "21:00", "21:30", "22:00"
]

_supabase = None


def _get_client():
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


def _covers_at_slot(date, time):
    """Returns total covers booked for a given date+time slot."""
    try:
        client = _get_client()
        result = (
            client.table("reservations")
            .select("party_size")
            .eq("restaurant_id", RESTAURANT_ID)
            .eq("date", str(date))
            .eq("time", str(time))
            .neq("status", "cancelled")
            .execute()
        )
        return sum(r["party_size"] for r in (result.data or []))
    except Exception as e:
        print(f"[availability] _covers_at_slot error: {e}")
        return 0


def check_availability(date, time, party_size):
    """
    Returns dict:
      { available: True/False, covers_used: int, capacity: int,
        next_available: str or None }
    next_available is set only when available=False.
    """
    try:
        party_size = int(party_size)
        covers_used = _covers_at_slot(date, time)
        remaining = RESTAURANT_CAPACITY - covers_used
        available = remaining >= party_size

        result = {
            "available": available,
            "covers_used": covers_used,
            "remaining": remaining,
            "capacity": RESTAURANT_CAPACITY,
            "next_available": None
        }

        if not available:
            result["next_available"] = _find_next_available(date, time, party_size)

        return result

    except Exception as e:
        print(f"[availability] check_availability error: {e}")
        # Fail open so the bot can still take reservations if Supabase is down
        return {"available": True, "covers_used": 0, "remaining": RESTAURANT_CAPACITY,
                "capacity": RESTAURANT_CAPACITY, "next_available": None}


def _find_next_available(start_date, start_time, party_size):
    """
    Searches the next 7 days (starting from start_date) for the nearest
    slot that can fit party_size. Returns a human-readable string or None.
    """
    try:
        base = datetime.strptime(str(start_date), "%Y-%m-%d")

        for day_offset in range(0, 8):
            check_date = base + timedelta(days=day_offset)
            check_date_str = check_date.strftime("%Y-%m-%d")
            weekday = check_date.weekday()  # 0=Mon … 6=Sun

            for slot in TIME_SLOTS:
                # Skip lunch slots Mon-Thu (restaurant only opens at 17:00 those days)
                slot_hour = int(slot.split(":")[0])
                if weekday < 4 and slot_hour < 17:
                    continue
                # Skip the original slot on day 0
                if day_offset == 0 and slot <= start_time:
                    continue

                covers_used = _covers_at_slot(check_date_str, slot)
                if RESTAURANT_CAPACITY - covers_used >= party_size:
                    day_name = check_date.strftime("%A, %d. %B")
                    return f"{day_name} um {slot} Uhr"

        return None

    except Exception as e:
        print(f"[availability] _find_next_available error: {e}")
        return None


def get_available_slots(date, party_size):
    """Returns a list of available time slots for a given date and party size."""
    try:
        party_size = int(party_size)
        date_obj = datetime.strptime(str(date), "%Y-%m-%d")
        weekday = date_obj.weekday()
        available_slots = []

        for slot in TIME_SLOTS:
            slot_hour = int(slot.split(":")[0])
            if weekday < 4 and slot_hour < 17:
                continue
            covers_used = _covers_at_slot(date, slot)
            if RESTAURANT_CAPACITY - covers_used >= party_size:
                available_slots.append(slot)

        return available_slots

    except Exception as e:
        print(f"[availability] get_available_slots error: {e}")
        return []
