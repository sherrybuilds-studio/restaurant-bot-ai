import os
import requests

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "anthropic/claude-3.5-haiku"
RESTAURANT_NAME = "Bosphorus Berlin"


def draft_response(review_text, star_rating):
    """
    Generates a warm, professional German-language response to a Google review.
    The response is a draft for the owner to review and post — never auto-posted.
    Returns a response string.
    """
    try:
        tone_instruction = _tone_for_rating(star_rating)
        prompt = _build_prompt(review_text, star_rating, tone_instruction)

        response = _call_openrouter(prompt)
        print(f"[review_responder] Draft generated for {star_rating}-star review")
        return response

    except Exception as e:
        print(f"[review_responder] draft_response error: {e}")
        return _fallback_response(star_rating)


def draft_response_for_owner(review_text, star_rating, reviewer_name=""):
    """
    Extended version that also returns metadata alongside the draft.
    Useful when calling from review_monitor or a dashboard.
    Returns dict with draft, tone, and a ready-to-copy string.
    """
    draft = draft_response(review_text, star_rating)
    tone = _tone_for_rating(star_rating)

    return {
        "draft": draft,
        "star_rating": star_rating,
        "reviewer_name": reviewer_name,
        "tone": tone,
        "ready_to_post": draft,
        "instructions": (
            "Öffnen Sie Google My Business → Bewertungen → Auf diese Bewertung antworten. "
            "Passen Sie den Text nach Belieben an, bevor Sie ihn posten."
        )
    }


def _tone_for_rating(stars):
    if stars <= 2:
        return (
            "The review is negative (1-2 stars). Express sincere apology. "
            "Acknowledge the specific complaint without being defensive. "
            "Invite the reviewer to contact you directly (phone or email) to resolve the issue. "
            "Do not offer discounts or free meals in the public response — do this privately."
        )
    if stars == 3:
        return (
            "The review is mixed (3 stars). Thank them for the honest feedback. "
            "Acknowledge what could have been better. "
            "Express genuine desire to do better and invite them to return."
        )
    return (
        "The review is positive (4-5 stars). Express warm, genuine gratitude. "
        "Mention something specific from their review if possible. "
        "Invite them to return — perhaps mention a seasonal special or upcoming event."
    )


def _build_prompt(review_text, stars, tone_instruction):
    return f"""You are writing a Google review response on behalf of {RESTAURANT_NAME}, a premium Turkish restaurant in Berlin Mitte.

RULES:
- Language: German. Always German, regardless of the review language.
- Tone: Warm, personal, like a proud restaurant owner — never corporate or robotic.
- Length: 3-5 sentences maximum. Concise and genuine.
- Never use generic phrases like "Dear Guest" (use "Liebe/r [Name]" if name was in the review, otherwise "Liebe Gäste").
- Never promise specific compensation in a public reply.
- Sign off as: "Herzliche Grüße, das Team vom {RESTAURANT_NAME}"

REVIEW ({stars} stars):
{review_text if review_text else "(No text provided — just a star rating)"}

TONE GUIDANCE:
{tone_instruction}

Write only the response text. No preamble, no explanation."""


def _call_openrouter(prompt):
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://bosphorus-berlin.de",
        "X-Title": "Bosphorus Berlin Review Responder"
    }
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 300,
        "temperature": 0.5
    }

    resp = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=20)
    resp.raise_for_status()

    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def _fallback_response(stars):
    """Returns a safe canned response if the API call fails."""
    if stars <= 2:
        return (
            "Vielen Dank für Ihr Feedback. Es tut uns sehr leid, dass Ihr Besuch nicht Ihren Erwartungen entsprach. "
            "Bitte kontaktieren Sie uns direkt unter +49 30 2809 4417, damit wir die Situation persönlich besprechen können. "
            "Herzliche Grüße, das Team vom Bosphorus Berlin"
        )
    if stars == 3:
        return (
            "Vielen Dank für Ihre ehrliche Bewertung! Wir nehmen Ihr Feedback sehr ernst und arbeiten kontinuierlich daran, uns zu verbessern. "
            "Wir würden uns freuen, Sie bald wieder bei uns begrüßen zu dürfen. "
            "Herzliche Grüße, das Team vom Bosphorus Berlin"
        )
    return (
        "Herzlichen Dank für Ihre wunderbare Bewertung! Es freut uns sehr, dass Sie einen schönen Abend bei uns hatten. "
        "Wir freuen uns schon auf Ihren nächsten Besuch! "
        "Herzliche Grüße, das Team vom Bosphorus Berlin"
    )
