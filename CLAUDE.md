# Restaurant Bot — Claude Code Context
# sherrybuilds-studio · Berlin · May 2026
# PREMIUM PRODUCT — €2,500 setup + €400/month retainer

## What this is
A premium AI restaurant management bot for Berlin restaurants.
This is not a simple chatbot. This is a full revenue management system delivered via WhatsApp + website widget.
Built by Sherry (sherrybuilds-studio). Architecture based on Montari Oak AI system.

## Business model
- Target: Berlin restaurants with 30+ covers, doing €20k+/month revenue
- Price: €2,500 setup + €400/month retainer
- 10 clients = €4,000/month passive + upsell opportunities
- Each new client = new menu.json + system_prompt.md + OpenTable config. 2hrs work.
- Competitors charge €200/month for a basic booking widget. We charge more and deliver 10x more.

## Why restaurant owners CANNOT ignore this bot
This bot does 7 things no human staff member can do simultaneously:

### 1. NEVER MISSES A CUSTOMER (24/7 availability)
- Answers WhatsApp at 2am when someone plans next week's dinner
- Answers website chat during lunch rush when staff are too busy
- Responds in German, English, Turkish, Arabic, Italian automatically
- Average restaurant loses 15-20 potential bookings/week from missed calls — this captures all of them

### 2. NO-SHOW PROTECTION (saves 20-30% revenue)
- Sends reminder 24hrs before: "Reminder: your table for 4 tomorrow at 7pm. Reply YES to confirm or NO to cancel."
- Sends second reminder 2hrs before if no reply
- If no confirmation, automatically releases table and notifies waitlist
- Tracks no-show rate per customer — flags repeat offenders

### 3. WAITLIST MANAGEMENT (captures lost revenue)
- Fully booked? Bot adds customer to live waitlist
- Cancellation comes in → bot immediately notifies next person on waitlist
- Waitlist customer has 15 minutes to confirm or it moves to next person
- Zero staff involvement required

### 4. REVENUE UPSELLING (increases average spend)
- After booking confirmed → suggests pre-ordering chef's tasting menu
- Birthday/anniversary detected → offers cake pre-order, champagne, decoration
- Repeat customer detected → "Welcome back! Your usual Riesling?"
- Day-before message → "Tomorrow's special: truffle risotto, only 8 portions left"
- Post-meal → "Loved your evening? Our wine club members get 20% off bottles to take home"

### 5. GOOGLE REVIEW AUTOMATION (builds reputation on autopilot)
- 2 hours after reservation time → "Hope the evening was perfect! A 30-second Google review means everything to us." + direct link
- Tracks who left reviews vs who didn't
- Monthly report to owner: X new reviews, average rating, common complaints
- Most restaurants have under 100 Google reviews. This gets them to 500+ in 6 months.

### 6. OWNER INTELLIGENCE DASHBOARD
- Daily Telegram message to owner: reservations today, covers tonight, revenue estimate, cancellations, top questions asked
- Weekly report: busiest times, most asked menu items, no-show rate, review count change
- Monthly: revenue impact estimate, upsell conversion rate
- Owner always knows what's happening without asking staff

### 7. MULTI-CHANNEL (WhatsApp + Website + Instagram DMs)
- Same AI brain across all channels
- WhatsApp: reservations + questions + upsells
- Website chat widget: converts website visitors to bookings
- Instagram DMs: auto-replies to "are you open?" "do you have vegan options?"
- All conversations logged to one Supabase dashboard

## Integrations built into this bot
- OpenTable API — live availability check + direct booking
- Google Reserve — "Book a table" button on Google Maps listing
- Google My Business API — auto-respond to reviews
- Gmail API — confirmation emails with PDF menu attachment
- Stripe — deposit collection for large group bookings (6+ people)
- n8n workflows — all automations (reminders, reviews, reports)
- Supabase — reservations, customers, waitlist, analytics

## Tech stack
- Server: Hostinger VPS (Ubuntu 24) — sherry@100.78.223.103 via Tailscale
- Process manager: PM2
- AI model: anthropic/claude-3.5-haiku via OpenRouter
- Vector DB: ChromaDB (sentence-transformers, all-MiniLM-L6-v2)
- Bot framework: Python + FastAPI
- Messaging: Meta WhatsApp Cloud API
- Database: Supabase PostgreSQL
- Automation: n8n (port 5678)
- Cache: Semantic cache 95% cosine similarity
- Website widget: React embed (5 lines of code for client to install)

## File structure
~/personal/restaurant-bot/
├── .env                          ← NEVER touch, NEVER push to GitHub
├── CLAUDE.md                     ← This file
├── agents/
│   ├── bot.py                    ← Main AI agent (RAG + cache + memory)
│   ├── api.py                    ← FastAPI webhook (secured + rate limited)
│   └── system_prompt.md          ← Restaurant personality + language rules
├── rag/
│   ├── indexer.py                ← Builds ChromaDB from menu.json
│   ├── retriever.py              ← Hybrid search (keyword + semantic)
│   └── cache.py                  ← Semantic cache, 95% threshold
├── data/
│   └── menu.json                 ← Menu, hours, location, policies, specials
├── reservations/
│   ├── booking.py                ← Reservation logic + Supabase
│   ├── availability.py           ← Check available slots
│   ├── waitlist.py               ← Waitlist management
│   └── reminders.py              ← No-show prevention reminders
├── automations/
│   ├── reviews.py                ← Post-visit Google review requests
│   ├── upsell.py                 ← Pre-visit upsell sequences
│   └── reports.py                ← Daily/weekly owner reports via Telegram
└── tests/
    └── eval.py                   ← 10 gold standard test questions

## Secrets — CRITICAL
- .env lives on VPS ONLY
- Never push to GitHub
- Keys needed: OPENROUTER_API_KEY, SUPABASE_URL, SUPABASE_KEY,
  WHATSAPP_TOKEN, VERIFY_TOKEN, GOOGLE_API_KEY, STRIPE_KEY

## Bot personality rules — NON-NEGOTIABLE
- Max 3 lines per WhatsApp reply — never more
- German first, English if customer writes English
- Detect Turkish/Arabic/Italian and respond in that language
- Warm friendly tone — like the best waiter they ever had
- Never invent menu items or prices — only use ChromaDB data
- Always confirm reservations: name + date + time + party size + confirmation number
- If fully booked → waitlist offer immediately, never just say no
- Upsell naturally — never pushy, always helpful
- Remember returning customers by phone number

## Reservation flow
1. Customer: "I want a table for 2 on Friday at 8pm"
2. Bot: checks Supabase availability for that slot
3. If available: asks for name + confirms → saves to Supabase → sends confirmation
4. If full: offers waitlist + nearest available slot
5. 24hrs before: sends reminder → customer confirms or cancels
6. 2hrs before: second reminder if no reply
7. 2hrs after visit: sends Google review request

## Supabase tables needed
- reservations: id, restaurant_id, customer_name, phone, party_size, date, time, status, notes, confirmed_at
- customers: id, phone, name, visit_count, last_visit, preferences, no_show_count
- waitlist: id, restaurant_id, phone, name, party_size, date, time, notified_at, status
- analytics: id, restaurant_id, date, questions_asked, bookings_made, upsells_converted, reviews_sent

## RAG rules
- Check cache BEFORE calling OpenRouter API
- Cache hit = return cached, skip API call entirely
- Token target: under 600 per message
- Hybrid search: keyword + semantic combined
- Index: menu items, descriptions, allergens, prices, hours, location, policies, specials

## What is built
- Folder structure + CLAUDE.md ← YOU ARE HERE

## What to build this session (in order)
1. data/menu.json — full Berlin restaurant sample data
2. rag/indexer.py — ChromaDB builder
3. rag/retriever.py — hybrid search
4. rag/cache.py — semantic cache
5. agents/system_prompt.md — premium restaurant AI personality
6. reservations/booking.py — reservation + Supabase logic
7. reservations/availability.py — slot checking
8. reservations/waitlist.py — waitlist system
9. reservations/reminders.py — no-show prevention
10. agents/bot.py — main AI brain
11. agents/api.py — FastAPI webhook
12. automations/reviews.py — Google review automation
13. automations/reports.py — daily owner Telegram report
14. tests/eval.py — 10 test questions
15. requirements.txt

## Port
Uses port 8001 — Montari Oak runs on 8000, no conflict.

## Code style
- Python 3, no type hints
- f-strings always
- Small single-purpose functions
- English comments only
- Always handle errors with friendly fallback messages
- Always log errors to console with context

## TWO KILLER FEATURES — Added to build list

### KILLER FEATURE 1: Fill Empty Nights (Direct Revenue Generation)
This is the feature that makes owners refer you to every restaurant they know.
Every Tuesday/Wednesday at 5pm, bot broadcasts to all past customers:
"Guten Abend! Heute Abend haben wir noch Tische frei 🍽️
20% Rabatt wenn Sie in den nächsten 2 Stunden buchen.
Antworten Sie mit JA für eine sofortige Bestätigung."
(Good evening! We still have tables free tonight. 20% off if you book in the next 2 hours. Reply YES for instant confirmation.)

Technical implementation:
- automations/broadcast.py — get_past_customers(days=90) from Supabase
- Filter customers who visited on slow days (Mon-Thu)
- Send via WhatsApp broadcast list API
- Track who replied, who booked, revenue generated
- Owner can trigger manually too: sends "BROADCAST" to bot → bot asks for message + discount → sends to all customers
- Report next morning: X messages sent, X bookings made, €X revenue generated

### KILLER FEATURE 2: Bad Review Shield (Instant Google Review Alerts)
Every restaurant owner has been burned by a 1-star review they found 3 days later.
This makes them feel protected — emotional sell, closes deals instantly.

Technical implementation:
- automations/review_monitor.py
- n8n workflow runs every 30 minutes
- Calls Google My Business API → checks for new reviews
- New review detected → immediate Telegram alert to owner with:
  - Star rating + reviewer name + full review text
  - Suggested response generated by Claude (owner can edit and post)
  - If 1-2 stars: URGENT flag + phone call suggestion
  - If 4-5 stars: celebration message + reminder to thank them
- Weekly report: average rating trend, review velocity, common complaints
- automations/review_responder.py — draft AI response for owner to approve

## Updated build list — add these files
16. automations/broadcast.py — WhatsApp broadcast to fill empty nights
17. automations/review_monitor.py — Google review monitoring every 30 mins
18. automations/review_responder.py — AI-drafted review responses for owner

## Why these two close the deal
- Broadcast: owner sees €500 extra revenue on a Tuesday. Tangible, immediate, measurable.
- Review shield: owner feels protected. Emotional. They tell every restaurant friend about it.
- Together: you are not selling a chatbot. You are selling a revenue manager + reputation protector.
- No basic bot on the market in Berlin offers both. €2,500 is cheap for this.
