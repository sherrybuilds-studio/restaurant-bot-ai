import sys
import os

# Ensure our project root takes precedence over any globally installed packages
# that share module names (e.g. montari-oak-ai/rag/ shadows our rag/ package).
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path = [_project_root] + [p for p in sys.path if "montari-oak" not in p]

import re
import json
import requests
from datetime import datetime
from pathlib import Path

from rag.retriever import retrieve_for_prompt
from rag.cache import cache_lookup, cache_store
from reservations.booking import create_reservation, get_customer, get_reservation
from reservations.availability import check_availability
from reservations.waitlist import add_to_waitlist
from reservations.reminders import process_reminder_reply

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-3.5-haiku"
MAX_HISTORY = 10  # messages per phone number kept in memory

SYSTEM_PROMPT_PATH = Path(__file__).parent / "system_prompt.md"

# In-memory conversation history: { phone: [{"role": ..., "content": ...}] }
_conversations = {}

# Pending reservation state: { phone: {step, data collected so far} }
_pending_reservations = {}


def _load_system_prompt():
    try:
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[bot] Failed to load system prompt: {e}")
        return "You are a helpful restaurant assistant for Bosphorus Berlin."


_system_prompt = _load_system_prompt()


def sanitize_input(text):
    """Strips control characters and trims whitespace. Returns cleaned string."""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    return text.strip()[:2000]  # hard cap at 2000 chars


def detect_intent(message):
    """
    Lightweight rule-based intent detection before hitting the LLM.
    Returns one of: 'reservation', 'cancellation', 'confirmation', 'menu', 'complaint', 'general'
    """
    msg = message.lower()

    confirmation_words = ["ja", "yes", "nein", "no", "bestätigen", "confirm", "cancel", "stornieren", "evet", "hayir"]
    if any(w in msg for w in confirmation_words) and len(msg.split()) <= 3:
        return "confirmation"

    reservation_words = [
        "reservier", "tisch", "buchen", "buchung", "reservat", "book", "table",
        "platz", "plätze", "personen", "persons", "tonight", "heute abend",
        "morgen", "tomorrow", "freitag", "saturday", "sonntag", "friday"
    ]
    if any(w in msg for w in reservation_words):
        return "reservation"

    cancellation_words = ["storno", "stornieren", "cancel", "absagen", "abgesagt"]
    if any(w in msg for w in cancellation_words):
        return "cancellation"

    complaint_words = ["beschwerde", "schlecht", "enttäuscht", "problem", "complaint", "terrible", "awful", "disgusting"]
    if any(w in msg for w in complaint_words):
        return "complaint"

    menu_words = [
        "speise", "menu", "menü", "karte", "gericht", "essen", "food", "dish",
        "vegan", "vegetarisch", "vegetarian", "allergen", "gluten", "halal",
        "preis", "price", "kosten", "cost", "was kostet"
    ]
    if any(w in msg for w in menu_words):
        return "menu"

    return "general"


def _extract_reservation_details(message):
    """
    Tries to extract date, time, party_size from a natural language message.
    Returns a dict with whatever was found (may be incomplete).
    """
    details = {}

    # Party size
    party_match = re.search(r'(\d+)\s*(person|personen|people|guests|gäste|pax)', message.lower())
    if party_match:
        details["party_size"] = int(party_match.group(1))
    else:
        # Try "für X" pattern
        fuer_match = re.search(r'f[üu]r\s+(\d+)', message.lower())
        if fuer_match:
            details["party_size"] = int(fuer_match.group(1))

    # Time — use findall so the party-size digit ("2 Personen") doesn't
    # consume the match before we reach the actual time ("20 Uhr").
    time_matches = re.findall(r'(\d{1,2})[:\.]?(\d{2})?\s*(uhr|pm|am|h\b)', message.lower())
    for grp in time_matches:
        hour = int(grp[0])
        minute = int(grp[1]) if grp[1] else 0
        if grp[2] == "pm" and hour < 12:
            hour += 12
        if 11 <= hour <= 23:
            details["time"] = f"{hour:02d}:{minute:02d}"
            break
    # Fallback: plain hour with no suffix (e.g. "um 20")
    if "time" not in details:
        plain = re.findall(r'um\s+(\d{1,2})', message.lower())
        for h in plain:
            hour = int(h)
            if 11 <= hour <= 23:
                details["time"] = f"{hour:02d}:00"
                break

    # Date — simplified: look for day names or "heute"/"morgen"
    today = datetime.now()
    day_map = {
        "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
        "freitag": 4, "samstag": 5, "sonntag": 6,
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6
    }
    msg_lower = message.lower()
    if "heute" in msg_lower or "today" in msg_lower:
        details["date"] = today.strftime("%Y-%m-%d")
    elif "morgen" in msg_lower or "tomorrow" in msg_lower:
        from datetime import timedelta
        details["date"] = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        for day_name, day_num in day_map.items():
            if day_name in msg_lower:
                days_ahead = (day_num - today.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                from datetime import timedelta
                details["date"] = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
                break

    return details


def _handle_reservation_flow(phone, message, intent):
    """
    State machine for multi-turn reservation collection.
    Returns a response string if we handled it, None if the LLM should handle it.
    """
    state = _pending_reservations.get(phone, {})

    # If customer is confirming/denying a reminder — handle immediately
    if intent == "confirmation":
        result = process_reminder_reply(phone, message)
        if result == "confirmed":
            return "Wunderbar! Ihre Reservierung ist bestätigt. Wir freuen uns sehr auf Sie heute Abend! 🍽️"
        if result == "cancelled":
            return "Schade! Ihre Reservierung wurde storniert. Wir hoffen, Sie bald wiederzusehen. 🙏"
        # Unknown confirmation — fall through to LLM

    if intent != "reservation":
        return None

    # Extract whatever details we can from this message
    details = _extract_reservation_details(message)

    # Merge with any existing state
    for k, v in details.items():
        state[k] = v

    # What are we still missing?
    missing = []
    if "date" not in state:
        missing.append("date")
    if "time" not in state:
        missing.append("time")
    if "party_size" not in state:
        missing.append("party_size")
    if "name" not in state:
        missing.append("name")

    # If name is the only thing missing and the message is a short plain reply,
    # treat the whole message as the customer's name rather than waiting for the LLM.
    if missing == ["name"]:
        candidate = message.strip()
        is_plain_name = (
            1 <= len(candidate.split()) <= 4
            and not re.search(r'\d', candidate)
            and not any(w in candidate.lower() for w in
                        ["tisch", "buchen", "platz", "reservier", "danke", "bitte", "uhr"])
        )
        if is_plain_name:
            state["name"] = candidate.title()
            missing = []

    if missing:
        _pending_reservations[phone] = state
        return None  # Let LLM ask for missing details naturally

    # We have everything — attempt booking
    try:
        avail = check_availability(state["date"], state["time"], state["party_size"])

        if avail["available"]:
            res = create_reservation(
                customer_name=state["name"],
                phone=phone,
                party_size=state["party_size"],
                date=state["date"],
                time=state["time"]
            )
            # Clear pending state
            _pending_reservations.pop(phone, None)

            date_fmt = datetime.strptime(state["date"], "%Y-%m-%d").strftime("%A, %d. %B %Y")
            return (
                f"Perfekt! Ihr Tisch für {state['party_size']} Personen am {date_fmt} um {state['time']} Uhr ist reserviert. ✅\n"
                f"Name: {state['name']} | Bestätigungsnr.: {res['confirmation_number']}\n"
                f"Wir freuen uns auf Sie! Sie erhalten 24h vorher eine Erinnerung."
            )
        else:
            _pending_reservations.pop(phone, None)
            next_slot = avail.get("next_available")
            next_text = f" Der nächste freie Tisch wäre: {next_slot}." if next_slot else ""
            add_to_waitlist(phone, state["name"], state["party_size"], state["date"], state["time"])
            return (
                f"Leider ist dieser Termin bereits ausgebucht. Ich habe Sie auf die Warteliste gesetzt! 📋\n"
                f"Sobald ein Tisch frei wird, benachrichtige ich Sie sofort.{next_slot and ' ' + next_slot or ''}\n"
                f"Möchten Sie lieber direkt einen anderen Termin wählen?"
            )

    except Exception as e:
        print(f"[bot] Reservation creation error: {e}")
        _pending_reservations.pop(phone, None)
        return "Entschuldigung, es gab einen technischen Fehler. Bitte rufen Sie uns direkt an: +49 30 2809 4417."


def _build_llm_messages(phone, user_message, context):
    """Builds the messages array for the OpenRouter API call."""
    history = _conversations.get(phone, [])

    # Check for returning customer greeting
    customer = get_customer(phone)
    customer_note = ""
    if customer and customer.get("visit_count", 0) > 1:
        customer_note = f"\n\n[SYSTEM NOTE: Returning customer. Name: {customer['name']}, visits: {customer['visit_count']}, preferences: {customer.get('preferences', 'none known')}]"

    system = _system_prompt + customer_note
    if context:
        system += f"\n\n## RETRIEVED CONTEXT\n{context}"

    messages = [{"role": "system", "content": system}]
    messages.extend(history[-MAX_HISTORY:])
    messages.append({"role": "user", "content": user_message})

    return messages


def _call_openrouter(messages):
    """Calls OpenRouter API. Returns response text or raises."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://bosphorus-berlin.de",
        "X-Title": "Bosphorus Berlin Bot"
    }

    # Estimate token budget: keep under 600 tokens for response
    payload = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": 200,
        "temperature": 0.4
    }

    resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()

    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def process_message(phone, message_text):
    """
    Main entry point. Called by api.py for every incoming WhatsApp message.
    Returns the bot's response string.
    """
    try:
        phone = str(phone).strip()
        message_text = sanitize_input(message_text)

        if not message_text:
            return "Hallo! Wie kann ich Ihnen helfen? 😊"

        print(f"[bot] Message from {phone}: {message_text[:80]}")

        # 1. If a reservation is already in progress for this phone, always run the
        #    flow first — the next message may be a name or other detail regardless
        #    of what intent it would normally detect.
        if phone in _pending_reservations:
            reservation_response = _handle_reservation_flow(phone, message_text, "reservation")
            if reservation_response:
                _update_history(phone, message_text, reservation_response)
                return reservation_response

        # 2. Check semantic cache (only for non-in-progress flows)
        cached = cache_lookup(message_text)
        if cached:
            return cached

        # 3. Detect intent
        intent = detect_intent(message_text)

        # 4. Try to handle reservation/cancellation/confirmation flow
        if intent in ("reservation", "cancellation", "confirmation"):
            reservation_response = _handle_reservation_flow(phone, message_text, intent)
            if reservation_response:
                _update_history(phone, message_text, reservation_response)
                # Don't cache reservation responses — they are state-dependent
                return reservation_response

        # 4. Retrieve relevant context from ChromaDB
        context = retrieve_for_prompt(message_text, n_results=3)

        # 5. Build messages and call LLM
        messages = _build_llm_messages(phone, message_text, context)
        response = _call_openrouter(messages)

        # 6. Update conversation history
        _update_history(phone, message_text, response)

        # 7. Cache general Q&A responses (not reservation/complaint flows)
        if intent in ("menu", "general"):
            cache_store(message_text, response)

        return response

    except Exception as e:
        print(f"[bot] process_message error for {phone}: {e}")
        return (
            "Entschuldigung, ich habe gerade einen technischen Moment. "
            "Bitte versuchen Sie es erneut oder rufen Sie uns an: +49 30 2809 4417. 🙏"
        )


def _update_history(phone, user_message, bot_response):
    """Appends turn to conversation history, trimming to MAX_HISTORY."""
    if phone not in _conversations:
        _conversations[phone] = []

    _conversations[phone].append({"role": "user", "content": user_message})
    _conversations[phone].append({"role": "assistant", "content": bot_response})

    # Keep only the last MAX_HISTORY messages
    if len(_conversations[phone]) > MAX_HISTORY * 2:
        _conversations[phone] = _conversations[phone][-(MAX_HISTORY * 2):]


def clear_conversation(phone):
    """Resets conversation history for a phone number."""
    _conversations.pop(phone, None)
    _pending_reservations.pop(phone, None)


if __name__ == "__main__":
    print("Bosphorus Berlin Bot — local test mode")
    print("Type your message and press Enter. 'quit' to exit.\n")
    test_phone = "49301234567"
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break
        if user_input.lower() in ("quit", "exit", "q"):
            break
        if not user_input:
            continue
        response = process_message(test_phone, user_input)
        print(f"Bot: {response}\n")
