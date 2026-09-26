# 🤖 Antigravity Developer Guide: Pace Restaurant AI WhatsApp Bot

Welcome to the **Pace Restaurant WhatsApp AI Order Assistant** codebase!
This file serves as the definitive architecture, pattern, and design reference for **Antigravity**. Whenever you make updates, debug issues, or implement new features, adhere strictly to the rules, structure, and patterns documented here.

---

## 📌 Executive Summary & Brand Identity

* **Restaurant:** Pace Restaurant, Dera Ismail Khan (DI Khan), Pakistan.
* **Specialty:** Traditional DI Khan Sobat / Paenda (served by *nafri*), Karahi, Handi, BBQ, Rice, Chinese, and Fast Food.
* **Core Function:** Automated WhatsApp conversational ordering assistant with human-like DI Khan waiter hospitality, deterministic tool execution, live Supabase DB syncing, and real-time alerts to kitchen & admin WhatsApp groups.
* **Persona:** A warm, respectful, 5-year veteran waiter in DI Khan. Speaks natural Roman Urdu (or English if prompted).
* **Length Rule:** **1–3 lines maximum per message**. WhatsApp customers do not read essays.
* **Single Question Rule:** **Only ONE question per message** to maintain smooth ordering momentum.
* **No AI Labeling:** Never call yourself an AI, robot, or bot. If asked: *"Ji, main Pace Restaurant ka digital assistant hoon 😊"*.

---

## 🏗️ Technical Stack & Infrastructure

```
┌─────────────────────────┐      ┌─────────────────────────┐
│  WhatsApp Customer Chat │ ◄──► │  WAHA Gateway (Node.js) │
└─────────────────────────┘      └───────────┬─────────────┘
                                             │ HTTP Webhook
                                             ▼
┌──────────────────────────────────────────────────────────┐
│                   FastAPI Application                    │
│  - Webhook router (HMAC validation, async backgrounding) │
│  - PST Shift Router & Admin In-Chat Interceptor          │
│  - OpenAI Tool-Calling Loop (gpt-4o-mini)                │
└───────────────┬──────────────────────────┬───────────────┘
                │                          │
                ▼                          ▼
     ┌────────────────────┐     ┌──────────────────────┐
     │   Redis (Cache &   │     │  Supabase (Postgres) │
     │  Session Manager)  │     │ - pace_orders        │
     └────────────────────┘     │ - MenuPace           │
                                │ - customer_profiles  │
                                │ - failed_dispatches  │
                                └──────────────────────┘
```

* **Backend Framework:** FastAPI (Python 3.11+) with AsyncIO.
* **AI Model:** OpenAI `gpt-4o-mini` with native Tool Calling (Function Calling).
* **WhatsApp Gateway:** WAHA (WhatsApp HTTP API) running on remote VPS.
* **Database:** Supabase PostgreSQL (`pace_orders`, `MenuPace`, `customer_profiles`, `failed_dispatches`).
* **Cache & State Store:** Redis 7 (Alpine) for sub-millisecond menu caching, conversational sessions, idempotency, and admin flags.
* **Audio Transcription:** OpenAI Whisper API for voice note (`audio/ogg`, `ptt`) voice ordering.
* **Deployment:** Docker & Docker Compose on Ubuntu VPS (`72.61.151.29`).

---

## 📂 Repository File Tree & Component Responsibilities

```
PACEMAIN/
├── config.py                 # Pydantic BaseSettings loading from .env
├── main.py                   # FastAPI app instance, CORS, lifespan, router registrations
├── docker-compose.yml        # Multi-container setup: pace-restaurant-bot + pace-redis
├── Dockerfile                # Python container build definition
├── schema.sql                # Supabase database schema & table definitions
├── routers/
│   ├── webhook.py            # WAHA incoming message webhook (/webhook) with HMAC verification
│   ├── admin.py              # REST API for order monitoring, analytics, and bot flags
│   ├── admin_commands.py     # In-chat WhatsApp admin commands (/status, /deactivate, etc.)
│   └── test_playground.py    # In-browser chat simulator & debug endpoints (/test/chat)
├── services/
│   ├── agent_runner.py       # Core OpenAI tool calling execution loop & session manager
│   ├── prompts.py            # SYSTEM_BASE_INSTRUCTIONS, shift prompts, response patterns
│   ├── tools.py              # Deterministic tools (read_menu, calculate_bill, save_order, etc.)
│   ├── whatsapp.py           # WAHA HTTP client wrapper with retry & dead-letter logging
│   ├── hours.py              # Pakistan Standard Time (PKT) shift & operational hours logic
│   ├── session.py            # Redis session storage, 90-min TTL, and order confirmation keys
│   ├── debounce.py           # 2-second sliding window message debounce & aggregation
│   ├── db.py                 # Async Supabase DB client with error handling
│   ├── cache.py              # Redis client wrapper with in-memory fallback for test runs
│   ├── audio.py              # Whisper voice note downloader and transcriber
│   └── sanitize.py           # Input sanitization against prompt injection
└── tests/
    ├── test_bot_core.py          # Core calculator, signature, and order flow tests
    ├── test_admin_commands.py    # WhatsApp in-chat admin command tests
    └── test_interactive_tools.py # Prompt rules, no-button assertions, complaint tools
```

---

## 🕒 Operational Shifts & Working Hours (PKT)

The restaurant operates in **Asia/Karachi** timezone (`services/hours.py`):

| Shift Name | Working Hours (PKT) | Designated Agent | Order Taking & Behavior |
|---|---|---|---|
| **Lunch Shift** | `11:00 AM – 3:30 PM` | `run_open_agent` (`OPEN_AGENT_PROMPT`) | **ACTIVE**: Sobat (Fry/Simple), Karahi, Handi, Chinese, Fried Rice, Fast Food, Breads, Drinks. ⚠️ **BBQ items strictly NOT available before 6:30 PM**. |
| **Sobat Only Shift** | `3:30 PM – 6:30 PM` | `run_afternoon_agent` (`AFTERNOON_AGENT_PROMPT`) | **ACTIVE (SOBAT & DRINKS ONLY)**: Afternoon specialized shift. Non-Sobat items and BBQ politely deferred to 6:30 PM. |
| **Dinner Shift** | `6:30 PM – 11:30 PM` | `run_open_agent` (`OPEN_AGENT_PROMPT`) | **ACTIVE (FULL MENU + BBQ)**: Entire restaurant menu 100% live including BBQ (Chicken Tikka, Malai Boti, Seekh Kabab, BBQ Chicken Sobat). |
| **Closed Shift** | `11:30 PM – 11:00 AM` | `run_closed_agent` (`CLOSED_AGENT_PROMPT`) | **STRICTLY DISABLED**: Explains 11:00 AM opening, strictly declines advance orders. Tools structurally restricted to read-only (`read_menu`, `send_menu_images`, `report_complaint`). |

*Router:* `execute_designated_agent(...)` evaluates the PKT shift and delegates execution to the designated agent.
*Override Flag:* Setting Redis key `flag:force_open = "1"` forces the Full Menu shift 24/7 (used for testing).

---

## 🛒 The 7-Step Conversational State Machine

The bot strictly guides the customer through these 7 progressive steps (`services/prompts.py`):

1. **Step 1 — Order Type:** Asks: *"Aap Delivery chahte hain ya Takeaway?"*
2. **Step 2 — Item Selection & Sobat Combinations:**
   * Understands items, queries `read_menu`.
   * **DI Khan Sobat Nafri vs Pieces Rule:** If customer says "2 nafr sobat and one piece" (or "2 nafri sobat 1 piece"), this means **1 nafri Chicken Sobat** (with piece) + **1 nafri Simple Sobat** (saada without piece).
   * **BBQ Piece vs Fried Piece Distinction:** BBQ piece (BBQ Chicken Sobat: Leg Rs. 530 / Chest Rs. 560) and Fried piece (Chicken Sobat Fry Pieces: Leg Rs. 520 / Chest Rs. 550) are **TWO DIFFERENT DISHES** with different prices. "1 bbq piece sobat and 1 fried piece" resolves to **1x BBQ Chicken Sobat** + **1x Chicken Sobat (Fry Pieces)**.
   * Sobat variations: Chicken Fry Pieces (Leg/Chest), BBQ Chicken Sobat (Leg/Chest), Simple Sobat (Rs. 220), Mutton Sobat (Rs. 950), Beef Champ Sobat (Rs. 750), Desi Murgh Sobat (Rs. 800), Batair Sobat (Rs. 700), Platters (Mutton/Beef/Fish).
3. **Step 3 — Packaging (STRICTLY & EXCLUSIVELY SOBAT):**
   * If Sobat / Paenda: *"Sobat Thal mein chahiye ya disposable mein?"*
   * If Karahi, BBQ, Rice, Fast Food, etc.: **SKIP STEP 3 COMPLETELY.** Never ask or mention Thal. All other items are strictly packaged in disposable containers.
4. **Step 4 — Bill Calculation & Intermediate Acknowledgment:** Calls `calculate_bill`. Confirms items and bill in 1-2 lines (e.g. *"• 1x Chicken Sobat Chest (Thal) — Total: Rs. 850 😊 Aapka delivery address aur naam bata dein?"*). **Strictly does NOT send the formal Order Summary box yet** to eliminate premature double-receipt spam.
5. **Step 5 — Customer Info:**
   * Delivery: Name & delivery address. **STRICTLY DO NOT ASK FOR GALI, STREET, GHAR NUMBER, OR LANDMARK.** Just ask for delivery address. If returning customer, confirms known address.
   * Takeaway: Name & expected pickup time.
6. **Step 6 — Official Order Summary (Sent ONCE when all details are gathered):** Displays the official clean receipt box:
   ```text
   📋 *Order Summary*
   ─────────────────
   👤 *Customer:* [Name]
   📦 *Type:* [Delivery/Takeaway]
   📍 *Address / Pickup:* [Address or Pickup Time]
   ─────────────────
   🛒 *Items:*
   • [qty]x *[item]* — Rs. [price]
   • *Thal Deposit (1x)* — Rs. 300 (refundable) [if applicable]
   🛵 *Delivery charges will apply* [Delivery orders only]
   ─────────────────
   💰 *Total: Rs. [total]*
   💳 Cash on Delivery / Counter
   ─────────────────
   _Confirm karein? (Haan / Cancel)_
   ```
   * **Order Modifications & Updates:** Customer conversation is cached for 2 hours (120 minutes) in Redis. Any mid-conversation additions, swaps, or address changes re-evaluate `calculate_bill` against the updated cart and output an updated Order Summary.
7. **Step 7 — Dual Execution (Both Takeaway & Delivery):**
   * Customer says "Haan/Confirm" → Executes `save_order` (Supabase DB) **and** `notify_admins_and_kitchen` (WhatsApp alerts) simultaneously.
   * **Takeaway & Delivery Mandate:** Real-time alerts are sent to Kitchen, Admin, and Admin WhatsApp Group for BOTH Takeaway and Delivery orders.
   * Returns Order ID and ETA (Chicken: 30–45m, Beef/Mutton/Sobat: 45–60m, Takeaway: 20–25m).
   * **Cart Cleanup:** Automatically wipes staged items, subtotal, and total bill from session so future customer chats start with a clean slate.

---

## 🛡️ Deterministic Tools & Backend Guardrails

All financial, state, and menu operations are strictly controlled in Python code (`services/tools.py`), **never left to LLM guesswork**:

1. **Deterministic Bill Math (`calculate_bill`):**
   * Validates each item's price against Redis menu cache (`cache:menu_items`). If the LLM makes up a price, the backend overrides it with the true database price.
   * **Thal Exclusivity Safeguard:**
     ```python
     has_sobat = any("sobat" in it.get("name", "").lower() or "paenda" in it.get("name", "").lower() for it in parsed_items)
     effective_thal_count = thal_count if has_sobat else 0
     thal_deposit = effective_thal_count * 300.0 if effective_thal_count > 0 else 0.0
     ```
     Non-Sobat orders **never** incur a Thal deposit, even if the model passes `thal_count > 0`.
2. **Menu Image Spam Prevention (`agent_runner.py`):**
   * Dispatched **only** if:
     `should_send_menu = force_menu or (is_first_interaction and is_greeting)`
   * The bot never re-sends menu photos on intermediate order messages.
3. **No Interactive WhatsApp Buttons:**
   * Strictly text-based interaction to ensure 100% compatibility across WhatsApp Mobile, Desktop, and Linked Devices.
4. **Strict Cash on Delivery (COD):**
   * No online payments or bank transfers handled by the bot.
5. **No Discounts / Bargaining:**
   * Rates are fixed. Bot politely declines discount requests.
6. **Customer Complaints Escalation (`report_complaint`):**
   * Reports issues directly to `ADMIN_GROUP_JID` and `ADMIN_WHATSAPP` via retry-backed WhatsApp dispatch. Does not issue unauthorized refunds.
7. **Dead-Letter Queue:**
   * Any WhatsApp dispatch failure after 3 exponential backoff attempts is persisted to `failed_dispatches` in Supabase for auditing.
8. **Strictly No Advance Orders:**
   * Neither advance delivery nor advance takeaway orders are accepted (whether open or closed). All orders must be live, immediate orders. Advance requests are politely declined.
9. **DI Khan Sobat Decomposition & Variations:**
   * Automatically decomposes composite Sobat orders (`decompose_sobat_items`).
   * "2 nafr sobat and one piece" -> 1x Chicken Sobat + 1x Simple Sobat.
   * "1 bbq piece sobat and one fried piece" -> 1x BBQ Chicken Sobat (Leg Rs. 530 / Chest Rs. 560) + 1x Chicken Sobat (Fry Pieces) (Leg Rs. 520 / Chest Rs. 550).
   * "2 nafri sobat 1 bbq piece" -> 1x BBQ Chicken Sobat + 1x Simple Sobat.
   * "3 nafri sobat 1 bbq 1 fry" -> 1x BBQ + 1x Fry + 1x Simple Sobat.
10. **Guaranteed Takeaway & Delivery Notifications:**
    * If `save_order` is executed, the backend guarantees dispatch of `notify_admins_and_kitchen` to Kitchen, Admin, and Admin Group even if the LLM omits the tool call on Takeaway orders.
11. **Roti & Maana Separation & Alias Pricing:**
    * Separates "Roti / Maana" into distinct dishes:
      - **Maana (Manna):** Aliases (`manny`, `manna`, `mana`, `maana`, `maane`, `mane`) deterministically resolve to **Rs. 30** each.
      - **Tandoori Roti:** Aliases (`roti`, `tanoor roti`, `tandoor roti`, `tandoori roti`) deterministically resolve to **Rs. 20** each.
      - **Roti / Maana Per Head:** Resolves to **Rs. 60** per head only when explicitly requested.
12. **Karahi & Handi Portion Sizing (Half vs Full):**
    * If customer does not specify Half or Full, the bot must prompt: *"Half chahiye ya Full? (Half: 2–3 afraad, Full: 4–5 afraad) 😊"*.
    * Correct pricing: Chicken Peshawari Karahi (Half Rs. 850 / Full Rs. 1700), Chicken Boneless Handi (Half Rs. 900 / Full Rs. 1700).
13. **Standalone Chicken Pieces vs Sobat Pieces:**
    * "Chicken Fry Piece" (Leg Rs. 350 / Chest Rs. 370) and "Chicken Tikka Piece" (Leg Rs. 360 / Chest Rs. 380) ordered alone are Appetizers/BBQ dry items.
    * Sobat chicken pieces are priced higher as complete meals: Chicken Sobat Fry Pieces (Leg Rs. 520 / Chest Rs. 550) and BBQ Chicken Sobat (Leg Rs. 530 / Chest Rs. 560).
14. **Rice & Pulao Clarifications:**
    * When "Kabli Pulao" is requested, clarify Beef (Rs. 800), Mutton (Rs. 950), or Sada (Rs. 300).
15. **Beverages & Soft Drink Sizes:**
    * Clarify 1.5 Liter (Rs. 220), 1 Liter (Rs. 170), or Regular (Rs. 60). Mineral Water: Large (Rs. 100), Small (Rs. 60).
16. **Delivery Charges Notice:**
    * For Delivery orders, the bot must explicitly mention in the Order Summary that delivery charges will apply (`🛵 *Delivery charges will apply*`), but strictly do NOT mention or calculate an exact amount for delivery charges.
17. **BBQ Timing Mandate (6:30 PM PKT Onwards):**
    * BBQ items (Chicken Tikka Piece, Malai Boti, Seekh Kabab, BBQ Chicken Sobat, BBQ Pieces) are **strictly NOT available before 6:30 PM PKT** because charcoal grills are only lit in the evening.
    * If requested before 6:30 PM, the bot explains BBQ starts at 6:30 PM and suggests daytime items (Chicken Sobat Fry Pieces, Karahi, Handi, Chinese Rice).
    * `calculate_bill()` deterministically blocks BBQ items if called before 6:30 PM.
18. **2-Second Message Debouncer & Aggregator:**
    * When customers send rapid fragmented WhatsApp messages, messages within 2 seconds of silence (and capped at 2.0s maximum ceiling from first arrival) are buffered together.
    * After 2 seconds of silence or 2.0s total ceiling, all buffered messages are aggregated into a single unified prompt and processed once.
    * Eliminates parallel execution race conditions, session clobbering, and disjointed multiple replies.

---

## 📱 In-Chat WhatsApp Admin Commands

Admins can manage the bot directly inside WhatsApp by sending commands to the bot:

| Command | Action |
|---|---|
| `/status` or `bot status` | Returns bot status, active shift, PKT time, Redis health, and today's order count. |
| `/deactivate` or `bot off` | Pauses automated order taking globally (`flag:bot_active = "0"`). |
| `/activate` or `bot on` | Resumes automated order taking (`flag:bot_active = "1"`). |
| `/orders` or `/today` | Summarizes today's total orders and revenue. |
| `/soldout <item>` | Marks a menu item as sold out. Customers will be told it's unavailable. |
| `/soldout list` | Shows all currently sold-out items. |
| `/soldout clear` | Clears all sold-out flags (entire menu available again). |
| `/available <item>` | Restores a sold-out item back to the active menu. |
| `/clearcache` or `/refreshmenu` | Flushes and re-warms the Redis menu cache from Supabase. |
| `/mute <phone>` / `/unmute <phone>` | Mutes or unmutes a specific disruptive customer. |
| `agent47 <command>` | Emergency bypass prefix — allows executing any admin command from any phone number. |

*Authorized Admins:* Configured via `ADMIN_WHATSAPP`, `ADMIN_2_WHATSAPP`, `KITCHEN_WHATSAPP`, `RESTAURANT_MOBILE`, and `ALLOWED_NUMBERS`.

---

## 🗄️ Supabase Database Schema Overview

* **`pace_orders`**: Primary orders table.
  * Fields: `id`, `order_id`, `customer_name`, `phone_number`, `order_type`, `delivery_address`, `pickup_time`, `order_items`, `subtotal`, `thal_deposit`, `total_bill`, `status` (`pending`, `confirmed`, `delivered`, `cancelled`), `created_at`.
* **`MenuPace`**: Live restaurant menu catalog.
  * Fields: `id`, `name`, `category`, `price`, `description`, `variant`, `is_available`.
* **`customer_profiles`**: CRM table tracking customer history.
  * Fields: `phone_number`, `customer_name`, `default_address`, `total_orders`, `last_order_items`, `last_order_at`.
* **`failed_dispatches`**: Dead-letter queue for failed outbound WhatsApp calls.

---

## 🧪 Testing & Verification Protocols

Always verify code integrity using the automated test suite before pushing changes:

```powershell
# Run the entire test suite (17 tests)
python -m pytest tests/

# Run individual test files
python -m pytest tests/test_bot_core.py
python -m pytest tests/test_admin_commands.py
python -m pytest tests/test_interactive_tools.py

# Autonomous Universal Testing File (Modify & reuse for all ongoing verification)
python universal_test.py
```

### Autonomous Testing & Validation Rules:
1. **Universal Python File Rule (Mandatory):** Whenever there is ANY executable task, diagnostic, data verification, bug reproduction, or testing, **always** write to and edit `universal_test.py` in the project root. Strictly **do NOT** create scattered, ad-hoc, or one-off python scripts (such as `test1.py`, `temp.py`, `check.py`, `run.py`).
2. **Zero Unnecessary Permissions:** Never ask for permission for routine, safe, reversible development testing. Perform validation autonomously.
3. **Single Reusable Test File:** Always maintain, update, and reuse `universal_test.py`. Retain core test scenarios and append or edit task logic in-place.
4. **Continuous Feedback Loop:** Follow `Modify code -> update universal_test.py -> execute -> diagnose -> fix -> re-test` until complete.
5. **Only Involve User for Critical Actions:** Involve user only for destructive operations (deleting databases/user data), external purchases, or production deployment authorization.

### Testing Via Web Simulator:
The bot includes a web simulation endpoint to test multi-turn conversations without sending real WhatsApp messages:
* Endpoint: `POST http://localhost:4433/test/chat`
* Payload:
  ```json
  {
    "message": "Salam",
    "phone": "923306874242",
    "override_shift": "full_menu"
  }
  ```
* Session Reset: `POST http://localhost:4433/test/reset` with `{"phone": "923306874242"}`.

---

## 🚀 VPS Deployment Reference

* **VPS IP:** `72.61.151.29`
* **Project Directory on VPS:** `/docker/pace_bot`
* **Standard Deployment Commands:**
  ```bash
  cd /docker/pace_bot
  git pull origin main
  docker compose up -d --build
  docker compose ps
  docker compose logs -f bot --tail=50
  ```

---

## 💡 Developer Guidelines for Future Changes

1. **Preserve the 1–3 Line Rule:** When modifying prompts or response messages, never let the agent return verbose paragraphs.
2. **Never Break the Thal Exclusivity:** Thal selection and deposits belong exclusively to Sobat / Paenda. Any other item must bypass Step 3.
3. **Keep Math in Python:** Never ask the model to do bill arithmetic in prompts. Always route through `calculate_bill`.
4. **Session Hygiene:** Ensure any new temporary order variables are cleaned up in `execute_tool_call` upon order completion.
5. **Deterministic Menu Cards:** Never let the agent send menu images on standard chat turns. Only on first greeting or when requested.
