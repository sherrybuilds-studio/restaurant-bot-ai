import os
import random
import string
from datetime import datetime
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RESTAURANT_ID = os.getenv("RESTAURANT_ID", "bosphorus-berlin")

_supabase = None


def _get_client():
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


def _generate_confirmation_number():
    digits = ''.join(random.choices(string.digits, k=4))
    return f"RES-{digits}"


def create_reservation(customer_name, phone, party_size, date, time, notes=""):
    """
    Creates a reservation in Supabase.
    Returns dict with confirmation_number on success, raises on failure.
    """
    try:
        client = _get_client()
        confirmation_number = _generate_confirmation_number()

        data = {
            "restaurant_id": RESTAURANT_ID,
            "customer_name": customer_name,
            "phone": phone,
            "party_size": int(party_size),
            "date": str(date),
            "time": str(time),
            "status": "confirmed",
            "notes": notes,
            "confirmation_number": confirmation_number,
            "confirmed_at": datetime.utcnow().isoformat()
        }

        result = client.table("reservations").insert(data).execute()

        if result.data:
            record = result.data[0]
            print(f"[booking] Created reservation {confirmation_number} for {customer_name} — {date} {time}, party {party_size}")
            _upsert_customer(phone, customer_name)
            return {
                "success": True,
                "confirmation_number": confirmation_number,
                "id": record.get("id"),
                "customer_name": customer_name,
                "date": str(date),
                "time": str(time),
                "party_size": int(party_size)
            }

        raise Exception("Insert returned no data")

    except Exception as e:
        print(f"[booking] create_reservation error: {e}")
        raise


def get_reservation(confirmation_number=None, phone=None):
    """
    Fetch a reservation by confirmation number or phone number.
    Returns the most recent match or None.
    """
    try:
        client = _get_client()
        query = client.table("reservations").select("*")

        if confirmation_number:
            query = query.eq("confirmation_number", confirmation_number)
        elif phone:
            query = query.eq("phone", phone).order("confirmed_at", desc=True).limit(1)
        else:
            return None

        result = query.execute()
        return result.data[0] if result.data else None

    except Exception as e:
        print(f"[booking] get_reservation error: {e}")
        return None


def cancel_reservation(confirmation_number, phone=None):
    """
    Marks a reservation as cancelled.
    Returns True on success, False on not found or error.
    """
    try:
        client = _get_client()
        query = (
            client.table("reservations")
            .update({"status": "cancelled"})
            .eq("confirmation_number", confirmation_number)
        )
        if phone:
            query = query.eq("phone", phone)

        result = query.execute()
        if result.data:
            print(f"[booking] Cancelled reservation {confirmation_number}")
            return True
        return False

    except Exception as e:
        print(f"[booking] cancel_reservation error: {e}")
        return False


def get_reservations_for_date(date):
    """Returns all non-cancelled reservations for a given date."""
    try:
        client = _get_client()
        result = (
            client.table("reservations")
            .select("*")
            .eq("restaurant_id", RESTAURANT_ID)
            .eq("date", str(date))
            .neq("status", "cancelled")
            .execute()
        )
        return result.data or []
    except Exception as e:
        print(f"[booking] get_reservations_for_date error: {e}")
        return []


def _upsert_customer(phone, name):
    """Creates or updates a customer record, incrementing visit count."""
    try:
        client = _get_client()
        existing = client.table("customers").select("*").eq("phone", phone).execute()

        if existing.data:
            record = existing.data[0]
            client.table("customers").update({
                "visit_count": record.get("visit_count", 0) + 1,
                "last_visit": datetime.utcnow().isoformat(),
                "name": name
            }).eq("phone", phone).execute()
        else:
            client.table("customers").insert({
                "phone": phone,
                "name": name,
                "visit_count": 1,
                "last_visit": datetime.utcnow().isoformat(),
                "no_show_count": 0
            }).execute()

    except Exception as e:
        print(f"[booking] _upsert_customer error (non-fatal): {e}")


def get_customer(phone):
    """Returns customer record by phone, or None."""
    try:
        client = _get_client()
        result = client.table("customers").select("*").eq("phone", phone).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print(f"[booking] get_customer error: {e}")
        return None


def mark_no_show(confirmation_number):
    """Marks reservation as no-show and increments customer no_show_count."""
    try:
        client = _get_client()
        res = client.table("reservations").select("phone").eq("confirmation_number", confirmation_number).execute()

        client.table("reservations").update({"status": "no_show"}).eq("confirmation_number", confirmation_number).execute()

        if res.data:
            phone = res.data[0]["phone"]
            existing = client.table("customers").select("no_show_count").eq("phone", phone).execute()
            if existing.data:
                current = existing.data[0].get("no_show_count", 0)
                client.table("customers").update({"no_show_count": current + 1}).eq("phone", phone).execute()

        print(f"[booking] Marked {confirmation_number} as no-show")

    except Exception as e:
        print(f"[booking] mark_no_show error: {e}")
