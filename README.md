# 🍽️ Restaurant Bot AI
> Premium WhatsApp AI assistant for Berlin restaurants — built by [sherrybuilds-studio](https://github.com/sherrybuilds-studio)

## What it does
A full revenue management system delivered via WhatsApp. Not just a chatbot.

| Feature | What it means for the restaurant |
|---|---|
| 24/7 WhatsApp + website chat | Never misses a customer inquiry |
| Smart reservations | Books tables, sends RES-XXXX confirmation |
| No-show prevention | 24h + 2h reminders, auto-releases table |
| Waitlist management | Fills cancelled slots automatically |
| Empty night broadcast | Tuesday 5pm WhatsApp blast to past customers — fills slow nights |
| Google review shield | Instant Telegram alert for every new review, 🚨 URGENT flag for 1-2 stars |
| AI review responses | Claude drafts German response for owner to approve |
| Daily owner report | Telegram summary every morning — covers, revenue, cancellations |
| Menu RAG | Answers allergen, price, ingredient questions from ChromaDB |
| Multilingual | German, English, Turkish, Arabic auto-detected |

## Tech stack
- **AI** — claude-3.5-haiku via OpenRouter
- **Vector DB** — ChromaDB with all-MiniLM-L6-v2 embeddings
- **Search** — Hybrid semantic + keyword (70/30)
- **Backend** — FastAPI + uvicorn on port 8001
- **Database** — Supabase PostgreSQL
- **Security** — HMAC-SHA256 webhook verification, slowapi rate limiting, prompt injection blocking
- **Automation** — n8n workflows for reminders, broadcasts, review monitoring
- **Messaging** — Meta WhatsApp Cloud API

## Eval score
RESULTS: 10/10 passed
SCORE:   100%
AVG RETRIEVAL SCORE: 0.6464

## File structure
restaurant-bot/
├── agents/          # bot.py, api.py, system_prompt.md
├── automations/     # broadcast.py, reviews.py, review_monitor.py, review_responder.py, reports.py
├── reservations/    # booking.py, availability.py, waitlist.py, reminders.py
├── rag/             # indexer.py, retriever.py, cache.py
├── data/            # menu.json (25 items, 46 indexed docs)
└── tests/           # eval.py (10 gold standard questions)

## Pricing (for clients)
- **Setup:** €2,500 (one-time)
- **Monthly retainer:** €400/month
- Includes: WhatsApp integration, menu RAG setup, Supabase tables, n8n workflows, owner Telegram dashboard

## Built by
[sherrybuilds-studio](https://github.com/sherrybuilds-studio) — Berlin-based AI automation developer
