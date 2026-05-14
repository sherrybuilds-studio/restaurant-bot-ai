import os
import hmac
import hashlib
import logging
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import PlainTextResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from agents.bot import process_message, sanitize_input

VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
WHATSAPP_APP_SECRET = os.getenv("WHATSAPP_APP_SECRET")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("api")

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Bosphorus Berlin Bot", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Patterns that suggest injection attacks
INJECTION_PATTERNS = [
    "ignore previous instructions",
    "ignore all instructions",
    "you are now",
    "disregard your",
    "act as if",
    "new instruction",
]


def _check_injection(text):
    lowered = text.lower()
    for pattern in INJECTION_PATTERNS:
        if pattern in lowered:
            log.warning(f"Injection attempt blocked: {text[:100]}")
            raise HTTPException(status_code=400, detail="Invalid input")


def _verify_signature(request_body: bytes, signature_header: str):
    """HMAC-SHA256 verification of WhatsApp webhook payload."""
    if not WHATSAPP_APP_SECRET:
        return  # Skip verification if secret not configured (dev mode)

    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(status_code=403, detail="Missing signature")

    expected = hmac.new(
        WHATSAPP_APP_SECRET.encode(),
        request_body,
        hashlib.sha256
    ).hexdigest()

    received = signature_header[len("sha256="):]

    if not hmac.compare_digest(expected, received):
        raise HTTPException(status_code=403, detail="Signature mismatch")


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "service": "bosphorus-berlin-bot", "port": 8001})


@app.get("/webhook")
@limiter.limit("30/minute")
async def verify_webhook(request: Request):
    """WhatsApp webhook verification challenge."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        log.info("Webhook verified successfully")
        return PlainTextResponse(challenge)

    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
@limiter.limit("10/minute")
async def receive_message(request: Request):
    """Main WhatsApp webhook — receives and processes incoming messages."""
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    _verify_signature(raw_body, signature)

    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    try:
        entry = data.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            return JSONResponse({"status": "no_messages"})

        message = messages[0]
        phone = message.get("from", "")
        msg_type = message.get("type", "")

        if msg_type != "text":
            log.info(f"Non-text message type '{msg_type}' from {phone} — ignored")
            return JSONResponse({"status": "ignored", "reason": "non-text"})

        text = message.get("text", {}).get("body", "")
        text = sanitize_input(text)
        _check_injection(text)

        if not text:
            return JSONResponse({"status": "empty_message"})

        log.info(f"Processing message from {phone}: {text[:60]}")
        response = process_message(phone, text)

        # Send WhatsApp reply via Cloud API
        _send_reply(phone, response)

        return JSONResponse({"status": "ok"})

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Webhook processing error: {e}", exc_info=True)
        return JSONResponse({"status": "error"}, status_code=200)


def _send_reply(phone, text):
    """Sends a reply back via WhatsApp Cloud API."""
    import requests as req_lib
    whatsapp_token = os.getenv("WHATSAPP_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_ID")

    if not whatsapp_token or not phone_id:
        log.warning(f"WhatsApp not configured — reply to {phone}: {text[:80]}")
        return

    try:
        url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
        headers = {
            "Authorization": f"Bearer {whatsapp_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": text}
        }
        resp = req_lib.post(url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        log.info(f"Reply sent to {phone}")
    except Exception as e:
        log.error(f"Failed to send reply to {phone}: {e}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("agents.api:app", host="0.0.0.0", port=8001, reload=False)
