import json
import logging
from typing import Optional, Any
from openai import AsyncOpenAI
from config import settings
from services.cache import redis_client
from services.session import get_session, set_session, generate_confirm_key
from services.hours import get_hours_info
from services.whatsapp import whatsapp
from services.audio import transcribe_audio_payload
from services.sanitize import sanitize_free_text
from services.tools import (
    read_menu,
    send_menu_images,
    calculate_bill,
    check_returning_customer,
    save_order_record,
    notify_admins_and_kitchen,
    report_complaint
)
from services.prompts import (
    FULL_MENU_SYSTEM_PROMPT,
    SOBAT_ONLY_SYSTEM_PROMPT,
    CLOSED_SYSTEM_PROMPT
)
from routers.admin_commands import handle_admin_command

logger = logging.getLogger("agent_runner")

# ── Module-level singleton OpenAI client (reuses HTTP connection pool) ──
openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# OpenAI Function Tool Definitions
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_menu",
            "description": "Reads live Pace Restaurant menu items, categories, variants, and prices from the database. Call this whenever a customer asks about prices, dish options, or what is available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Item name, food dish, or category to search for, e.g. 'Sobat', 'Karahi', 'Boti', 'Tikka', 'Daal', 'Roti', 'Bar B Q', 'Pace Specialities', 'Chinese', 'Rice'"
                    },
                    "category": {
                        "type": "string",
                        "description": "Optional category filter"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_menu_images",
            "description": "Sends high-resolution Pace Restaurant menu card images directly to the customer WhatsApp chat. Call this whenever the customer asks for the menu, menu card, food options, or pictures.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_bill",
            "description": "Deterministically calculates total bill, items breakdown, thal deposit, and verifies minimum delivery order. STRICTLY for immediate live orders during open hours. DO NOT call for advance delivery or advance takeaway orders.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "List of dishes to calculate. Provide dish name and quantity. Do NOT calculate or multiply totals yourself.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Name of dish from menu (e.g. Chicken Sobat, Chicken Karahi, Roti)"},
                                "quantity": {"type": "integer", "description": "Number of items or nafri"},
                                "unit_price": {"type": "number", "description": "Optional unit price of 1 single item. NEVER pass multiplied total."},
                                "price": {"type": "number", "description": "Optional unit price of 1 single item. NEVER pass multiplied total."},
                                "variant": {"type": "string", "description": "Variant (Leg, Chest, Half, Full, etc.)"},
                                "notes": {"type": "string"}
                            },
                            "required": ["name"]
                        }
                    },
                    "order_type": {
                        "type": "string",
                        "enum": ["Delivery", "Takeaway"],
                        "description": "Type of order"
                    },
                    "thal_count": {
                        "type": "integer",
                        "description": "Number of traditional Sobat Thals requested. STRICTLY ONLY for Sobat / Paenda orders. Must be 0 for all other dishes (Karahi, BBQ, Rice, etc.)."
                    }
                },
                "required": ["items"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_order",
            "description": "Idempotently saves confirmed customer order into Supabase database. STRICTLY for immediate live orders during open hours. DO NOT call for advance delivery or advance takeaway orders.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "Confirmed items list. Price must be the UNIT price of a single item (e.g. 480 for 1 Sobat, NOT 1440).",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "quantity": {"type": "integer"},
                                "price": {"type": "number", "description": "Unit price of 1 item"},
                                "variant": {"type": "string"}
                            }
                        }
                    },
                    "total_bill": {"type": "number", "description": "EXACT total bill from calculate_bill. Do NOT recalculate or multiply."},
                    "customer_name": {"type": "string"},
                    "order_type": {"type": "string", "enum": ["Delivery", "Takeaway"]},
                    "delivery_address": {"type": "string"},
                    "pickup_time": {"type": "string"},
                    "notes": {"type": "string"}
                },
                "required": ["items", "total_bill", "order_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "notify_admins_and_kitchen",
            "description": "Dispatches real-time WhatsApp alert notifications to Kitchen, Admins, and Admin WhatsApp Group. MANDATORY FOR BOTH TAKEAWAY AND DELIVERY ORDERS immediately upon customer confirmation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "customer_name": {"type": "string"},
                    "order_type": {"type": "string", "enum": ["Delivery", "Takeaway"]},
                    "total_bill": {"type": "number", "description": "EXACT total bill from calculate_bill / save_order."},
                    "delivery_address": {"type": "string"},
                    "pickup_time": {"type": "string"},
                    "notes": {"type": "string"}
                },
                "required": ["order_id", "total_bill"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "report_complaint",
            "description": "Reports a customer food/service complaint to the Admin WhatsApp Group and Admin phone. Call this when a customer complains about food quality, taste, delivery issues, cold food, late delivery, wrong order, or any service problem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "complaint_text": {
                        "type": "string",
                        "description": "Summary of the customer's complaint in their own words"
                    },
                    "customer_name": {
                        "type": "string",
                        "description": "Name of the complaining customer if known"
                    }
                },
                "required": ["complaint_text"]
            }
        }
    }
]


async def execute_tool_call(
    tool_name: str,
    tool_args: dict,
    session: dict,
    phone: str,
    dispatch_mode: str = "whatsapp",
    latest_order_record: Optional[dict] = None,
    waha_session: Optional[str] = None,
    sender_jid: Optional[str] = None
) -> tuple[dict, Optional[dict]]:
    """
    Executes a single tool call and returns (tool_result, updated_latest_order_record).
    Shared between WhatsApp webhook flow and Web Simulator.
    
    dispatch_mode: 'whatsapp' sends real WhatsApp messages, 'simulator' mocks them.
    """
    tool_result = {}
    new_order_record = latest_order_record

    if tool_name == "read_menu":
        category = tool_args.get("category")
        query = tool_args.get("query")
        tool_result = await read_menu(category=category, search=query)

    elif tool_name == "send_menu_images":
        target = sender_jid or phone
        if dispatch_mode == "whatsapp":
            tool_result = await send_menu_images(target, session=waha_session)
        else:
            tool_result = {
                "status": "success",
                "message": "Menu images displayed to customer in simulator.",
                "menu_images": [settings.MENU_IMAGE_1, settings.MENU_IMAGE_2]
            }

    elif tool_name == "calculate_bill":
        items = tool_args.get("items", [])
        order_type = tool_args.get("order_type", "Delivery")
        thal_count = tool_args.get("thal_count", 0)
        calc = await calculate_bill(items, order_type, thal_count)
        tool_result = calc
        
        # Update session staging
        session["items"] = calc["items"]
        session["subtotal"] = calc["subtotal"]
        session["thal_deposit"] = calc["thal_deposit"]
        session["total_bill"] = calc["total_bill"]
        session["order_type"] = order_type
        if not session.get("confirm_key"):
            session["confirm_key"] = generate_confirm_key(phone)

    elif tool_name == "save_order":
        # Deterministic precedence: session items & total_bill have verified math from calculate_bill
        items = session.get("items") or tool_args.get("items", [])
        total_bill = session.get("total_bill") or tool_args.get("total_bill", 0)
        notes = tool_args.get("notes", "")
        
        if tool_args.get("customer_name"):
            session["name"] = tool_args["customer_name"]
        if tool_args.get("order_type"):
            session["order_type"] = tool_args["order_type"]
        if tool_args.get("delivery_address"):
            session["address"] = tool_args["delivery_address"]
        if tool_args.get("pickup_time"):
            session["pickup_time"] = tool_args["pickup_time"]
        
        saved = await save_order_record(session, items, total_bill, notes)
        tool_result = saved
        new_order_record = saved

    elif tool_name == "report_complaint":
        complaint_text = tool_args.get("complaint_text", "No details")
        cust_name = tool_args.get("customer_name") or session.get("name", "")

        if dispatch_mode == "whatsapp":
            tool_result = await report_complaint(
                phone=phone,
                customer_name=cust_name,
                complaint_text=complaint_text,
                session=waha_session
            )
        else:
            tool_result = {
                "status": "simulated_complaint",
                "message": f"Complaint reported for {phone}: {complaint_text}"
            }


    elif tool_name == "notify_admins_and_kitchen":
        order_id = tool_args.get("order_id", "PACE-CONFIRMED")
        
        # Priority for total_bill: latest_order_record -> session -> tool_args
        verified_total = 0.0
        if latest_order_record and latest_order_record.get("total_bill"):
            verified_total = float(latest_order_record["total_bill"])
        elif session.get("total_bill"):
            verified_total = float(session["total_bill"])
        elif tool_args.get("total_bill"):
            verified_total = float(tool_args["total_bill"])

        items_summary = (latest_order_record.get("summary") if latest_order_record else None)
        if not items_summary:
            items_summary = "\n".join([
                f"- {it.get('quantity', 1)}x {it.get('name')} ({it.get('variant', '')})"
                for it in session.get("items", [])
            ]) if session.get("items") else "Items"
            
        saved_payload = latest_order_record.get("order_payload", {}) if latest_order_record else {}
        order_summary_data = {
            "customer_name": saved_payload.get("customer_name") or tool_args.get("customer_name") or session.get("name"),
            "phone_number": phone,
            "order_type": saved_payload.get("order_type") or tool_args.get("order_type") or session.get("order_type", "Takeaway"),
            "delivery_address": saved_payload.get("delivery_address") or tool_args.get("delivery_address") or session.get("address"),
            "pickup_time": saved_payload.get("pickup_time") or tool_args.get("pickup_time") or session.get("pickup_time"),
            "order_items": items_summary,
            "total_bill": verified_total,
            "notes": saved_payload.get("notes") or tool_args.get("notes") or session.get("notes", "")
        }

        if dispatch_mode == "whatsapp":
            tool_result = await notify_admins_and_kitchen(order_id, order_summary_data, session=waha_session)
        else:
            tool_result = {
                "status": "simulated_dispatch",
                "order_id": order_id,
                "total_bill": verified_total,
                "order_items": items_summary,
                "message": f"Order {order_id} alert simulated for kitchen & admin (Total: Rs. {verified_total:,.0f})."
            }
        # Reset confirm key and clear staged cart so future orders start fresh
        session["confirm_key"] = None
        session.pop("items", None)
        session.pop("subtotal", None)
        session.pop("thal_deposit", None)
        session.pop("total_bill", None)
        session.pop("order_type", None)
        session.pop("pickup_time", None)
        session.pop("notes", None)

    return tool_result, new_order_record


async def run_agent_loop(
    phone: str,
    user_text: str,
    session: dict,
    system_prompt: str,
    hours: dict,
    dispatch_mode: str = "whatsapp",
    waha_session: Optional[str] = None,
    sender_jid: Optional[str] = None
) -> tuple[str, list[dict]]:
    """
    Core OpenAI tool-calling execution loop. Shared between WhatsApp and Web Simulator.
    
    Returns: (final_reply_text, list_of_executed_tool_calls)
    """
    # Build conversation messages
    history = session.get("history", [])
    messages = [{"role": "system", "content": system_prompt}]
    
    # Inject context metadata for smarter, personalized responses
    time_pkt = hours.get("current_time_pkt", "")
    # Determine time-of-day period for greeting style
    time_period = "day"
    try:
        hour_num = int(time_pkt.split(":")[0])
        ampm = time_pkt.strip()[-2:].upper()
        if ampm == "PM" and hour_num != 12:
            hour_num += 12
        elif ampm == "AM" and hour_num == 12:
            hour_num = 0
        if 6 <= hour_num < 12:
            time_period = "morning"
        elif 12 <= hour_num < 17:
            time_period = "afternoon"
        elif 17 <= hour_num < 21:
            time_period = "evening"
        else:
            time_period = "night"
    except Exception:
        pass

    context_note = f"[Customer Phone: {phone}] [Time PKT: {time_pkt}] [Time Period: {time_period}]"
    if session.get("name"):
        context_note += f" [Returning Customer Name: {session['name']}]"
    if session.get("address"):
        context_note += f" [Known Address: {session['address']}]"
    if session.get("order_type"):
        context_note += f" [Order Stage: {session['order_type']} in progress]"
    if session.get("total_bill"):
        sub_str = f", Subtotal: Rs. {session['subtotal']:,.0f}" if session.get("subtotal") else ""
        thal_str = f", Thal Deposit: Rs. {session['thal_deposit']:,.0f}" if session.get("thal_deposit") else ""
        context_note += f" [Verified Bill: Rs. {session['total_bill']:,.0f}{sub_str}{thal_str} - DO NOT RECALCULATE OR MULTIPLY]"
    if session.get("order_type", "").strip().lower() == "delivery":
        context_note += " [Delivery Order: Include '🛵 Delivery charges will apply' in Order Summary. DO NOT state any exact delivery fee amount]"
    messages.append({"role": "system", "content": context_note})

    # Add past turn history (last 12 turns for better order flow context)
    for h in history[-12:]:
        messages.append(h)

    # Add current user message
    messages.append({"role": "user", "content": user_text})

    final_reply = ""
    latest_order_record = None
    executed_tools = []

    # Deterministic trigger: send_menu_images ONLY on first greeting OR explicit menu request
    user_words = set(user_text.lower().split())
    menu_triggers = {"menu", "card", "tasweer", "tasweerein", "pic", "pics", "photo", "photos", "menyu"}
    force_menu = bool(user_words.intersection(menu_triggers)) or any(t in user_text.lower() for t in ["menu dikhao", "menu bhejo", "menu card", "show menu"])

    greeting_triggers = {
        "salam", "assalam", "asalam", "slaam", "aoa",
        "hi", "hello", "hey", "start", "aadaab", "adab", "good"
    }
    is_greeting = bool(user_words.intersection(greeting_triggers)) or any(
        g in user_text.lower() for g in ["assalam o alaikum", "assalamu alaikum", "good morning", "good evening", "good afternoon"]
    )
    is_first_interaction = len(history) == 0 or not any(h.get("role") == "assistant" for h in history)

    # Menu pics ONLY on: (1) first interaction greeting, or (2) user explicitly asks for menu
    should_send_menu = force_menu or (is_first_interaction and is_greeting)

    if is_greeting and is_first_interaction:
        if not hours.get("is_open", True):
            messages.append({
                "role": "system",
                "content": (
                    "MANDATORY GREETING INSTRUCTION (RESTAURANT IS CLOSED):\n"
                    "1) Greet warmly (e.g. 'Assalam-o-Alaikum! 🌟').\n"
                    "2) Welcome to Pace Restaurant (e.g. '*Pace Restaurant, Dera Ismail Khan* mein khush amdeed! 🍽️').\n"
                    "3) State clearly that restaurant is currently closed and opening time is 11:00 AM PKT.\n"
                    "4) Inform that we DO NOT take advance orders (neither delivery nor takeaway), and live orders will be taken starting at 11:00 AM.\n"
                    "5) Explicitly mention menu card sent 👆 for viewing."
                )
            })
        else:
            messages.append({
                "role": "system",
                "content": (
                    "MANDATORY GREETING INSTRUCTION:\n"
                    "1) Greet warmly (e.g. 'Assalam-o-Alaikum! 🌟').\n"
                    "2) Welcome to Pace Restaurant (e.g. '*Pace Restaurant, Dera Ismail Khan* mein khush amdeed! 🍽️').\n"
                    "3) Explicitly mention menu card sent 👆 ('Yeh raha humara menu card 👆').\n"
                    "4) Ask for choice: Delivery or Takeaway? ('Aap *Delivery* karwana chahte hain ya *Takeaway*?')"
                )
            })

    try:
        for turn_idx in range(5):  # Max 5 tool iterations per turn
            tool_choice = "auto"
            if turn_idx == 0 and should_send_menu:
                tool_choice = {"type": "function", "function": {"name": "send_menu_images"}}

            response = await openai_client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=messages,
                tools=AGENT_TOOLS,
                tool_choice=tool_choice,
                temperature=0.4,
                max_tokens=500
            )

            assistant_msg = response.choices[0].message
            messages.append(assistant_msg)

            if not assistant_msg.tool_calls:
                final_reply = assistant_msg.content or ""
                # NEVER leave customer with empty reply — retry once
                if not final_reply.strip() and turn_idx == 0:
                    logger.warning("Empty reply from model for %s, retrying once", phone)
                    messages.append({"role": "user", "content": "(Customer is waiting for your response. Please reply helpfully.)"})
                    continue
                break

            # Process tool calls
            for tool_call in assistant_msg.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments or "{}")

                logger.info("Executing tool %s with args %s for %s", tool_name, tool_args, phone)

                tool_result, latest_order_record = await execute_tool_call(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    session=session,
                    phone=phone,
                    dispatch_mode=dispatch_mode,
                    latest_order_record=latest_order_record,
                    waha_session=waha_session,
                    sender_jid=sender_jid
                )

                executed_tools.append({
                    "name": tool_name,
                    "args": tool_args,
                    "result": tool_result
                })

                # Append tool response
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": json.dumps(tool_result)
                })

        # Safeguard: If save_order was executed (latest_order_record exists) but notify_admins_and_kitchen
        # was not executed by the LLM (which happens frequently on Takeaway orders), auto-notify now:
        if latest_order_record and not any(t.get("name") == "notify_admins_and_kitchen" for t in executed_tools):
            logger.info("Auto-executing notify_admins_and_kitchen for saved order %s", latest_order_record.get("order_id"))
            saved_p = latest_order_record.get("order_payload", {})
            notify_res, _ = await execute_tool_call(
                tool_name="notify_admins_and_kitchen",
                tool_args={
                    "order_id": latest_order_record.get("order_id"),
                    "customer_name": saved_p.get("customer_name") or session.get("name"),
                    "order_type": saved_p.get("order_type") or session.get("order_type", "Takeaway"),
                    "total_bill": latest_order_record.get("total_bill"),
                    "delivery_address": saved_p.get("delivery_address") or session.get("address"),
                    "pickup_time": saved_p.get("pickup_time") or session.get("pickup_time"),
                    "notes": saved_p.get("notes") or session.get("notes", "")
                },
                session=session,
                phone=phone,
                dispatch_mode=dispatch_mode,
                latest_order_record=latest_order_record,
                waha_session=waha_session,
                sender_jid=sender_jid
            )
            executed_tools.append({
                "name": "notify_admins_and_kitchen",
                "args": {"order_id": latest_order_record.get("order_id")},
                "result": notify_res
            })

    except Exception as e:
        logger.exception("Error in agent runner execution for %s: %s", phone, e)
        final_reply = "Ji, aapka message mil gaya hai! Abhi thori mushkil aa rahi hai — please 1-2 minute baad dobara try karein ya call karein: " + settings.RESTAURANT_PHONE + " 😊"

    # Final safeguard: NEVER return empty string to customer
    if not final_reply.strip():
        final_reply = "Ji zaroor! Aap kya order karna chahengey? Main aapki madad ke liye haazir hoon 😊"

    return final_reply, executed_tools


async def process_message(payload: dict):
    """
    Main background processor for incoming WhatsApp message events.
    1. Checks mute and maintenance flags
    2. Transcribes voice notes if present
    3. Selects agent shift (Full Menu / Sobat Only / Closed)
    4. Executes OpenAI Tool Calling loop
    5. Dispatches reply to WhatsApp
    """
    msg_payload = payload.get("payload", {})
    sender_jid = msg_payload.get("from", "")
    # Check if there is an alternate real phone JID in remoteJidAlt (common for WhatsApp Linked Devices)
    remote_jid_alt = msg_payload.get("_data", {}).get("key", {}).get("remoteJidAlt", "")
    real_phone_jid = remote_jid_alt or sender_jid
    phone = real_phone_jid.split("@")[0]
    msg_id = msg_payload.get("id")
    has_media = msg_payload.get("hasMedia", False)
    media_info = msg_payload.get("media", {}) if isinstance(msg_payload.get("media"), dict) else {}
    user_text = str(
        msg_payload.get("body")
        or msg_payload.get("selectedDisplayText")
        or msg_payload.get("selectedButtonId")
        or msg_payload.get("selectedRowId")
        or msg_payload.get("title")
        or (msg_payload.get("_data", {}) if isinstance(msg_payload.get("_data"), dict) else {}).get("body")
        or (msg_payload.get("_data", {}) if isinstance(msg_payload.get("_data"), dict) else {}).get("selectedDisplayText")
        or (msg_payload.get("message", {}) if isinstance(msg_payload.get("message"), dict) else {}).get("buttonsResponseMessage", {}).get("selectedDisplayText")
        or (msg_payload.get("message", {}) if isinstance(msg_payload.get("message"), dict) else {}).get("templateButtonReplyMessage", {}).get("selectedDisplayText")
        or ""
    ).strip()

    if not phone or msg_payload.get("fromMe", False):
        return

    raw_session = payload.get("session")
    waha_session = str(raw_session).strip() if raw_session else (settings.WAHA_SESSION or "Pace")

    # Guard: check for in-chat admin commands before bot_active / maintenance checks
    if user_text:
        is_admin_cmd, _ = await handle_admin_command(
            sender_jid=sender_jid,
            text=user_text,
            send_whatsapp=True,
            session=waha_session,
            actor_jid=real_phone_jid,
            remote_jid_alt=remote_jid_alt
        )
        if is_admin_cmd:
            return

    # Check Bot Active flag
    bot_active = await redis_client.get("flag:bot_active")
    if bot_active == "0":
        logger.info("Bot is deactivated globally. Ignoring message from %s", phone)
        return

    # Check Maintenance flag
    maintenance_only = await redis_client.get("flag:maintenance_only")
    if maintenance_only and phone not in {maintenance_only, settings.ADMIN_WHATSAPP}:
        logger.info("Bot in maintenance mode. Ignoring message from non-admin %s", phone)
        return

    # Check User Mute flag
    is_muted = await redis_client.get(f"mute:{phone}")
    if is_muted == "1":
        logger.info("Customer %s is currently muted. Ignoring.", phone)
        return

    # Mark as seen & show typing indicator
    try:
        await whatsapp.send_seen(sender_jid, msg_id, session=waha_session)
        await whatsapp.start_typing(sender_jid, session=waha_session)
    except Exception as e:
        logger.warning("Could not set typing/seen for %s: %s", sender_jid, e)

    # 1. Handle Voice Note
    if has_media or media_info:
        mimetype = media_info.get("mimetype", "")
        if "audio" in mimetype or "ogg" in mimetype or "mp3" in mimetype or msg_payload.get("type") == "ptt":
            transcribed = await transcribe_audio_payload(media_info, phone)
            if transcribed:
                user_text = transcribed
            else:
                user_text = "[Voice Note received but could not be transcribed]"

    if not user_text:
        try:
            await whatsapp.stop_typing(sender_jid, session=waha_session)
        except Exception:
            pass
        return

    # 2. Retrieve session state & history
    session = await get_session(phone)
    if not session:
        # Check returning customer profile for initial context
        profile = await check_returning_customer(phone)
        session = {
            "phone": phone,
            "name": profile.get("name") if profile.get("is_returning") else "",
            "address": profile.get("default_address") if profile.get("is_returning") else "",
            "history": [],
            "confirm_key": None
        }

    # 3. Determine operational shift
    hours = get_hours_info()
    force_open = await redis_client.get("flag:force_open") == "1"
    if force_open:
        system_prompt = FULL_MENU_SYSTEM_PROMPT
    elif not hours["is_open"]:
        system_prompt = CLOSED_SYSTEM_PROMPT
    elif hours["is_break_time"]:
        system_prompt = SOBAT_ONLY_SYSTEM_PROMPT
    else:
        system_prompt = FULL_MENU_SYSTEM_PROMPT

    # 4. Run shared agent loop
    final_reply, _ = await run_agent_loop(
        phone=phone,
        user_text=user_text,
        session=session,
        system_prompt=system_prompt,
        hours=hours,
        dispatch_mode="whatsapp",
        waha_session=waha_session,
        sender_jid=sender_jid
    )

    # 5. Send reply via WhatsApp with dynamic human-like delay (1 - 2 - 3 seconds)
    if final_reply:
        # Simulate realistic human typing delay (1-3s) to prevent Meta/WhatsApp bot restrictions
        await whatsapp.dynamic_typing_delay(sender_jid, text=final_reply, session=waha_session)
        try:
            await whatsapp.stop_typing(sender_jid, session=waha_session)
        except Exception:
            pass

        try:
            await whatsapp.send_text(sender_jid, final_reply, session=waha_session)
            logger.info("Outbound WhatsApp reply dispatched to %s via session %s", sender_jid, waha_session)
        except Exception as e:
            logger.warning("Failed to dispatch WhatsApp reply to %s: %s. Attempting fallback to %s", sender_jid, e, real_phone_jid)
            if real_phone_jid and real_phone_jid != sender_jid:
                try:
                    await whatsapp.send_text(real_phone_jid, final_reply, session=waha_session)
                    logger.info("Outbound WhatsApp reply dispatched to fallback JID %s", real_phone_jid)
                except Exception as e2:
                    logger.error("Failed to dispatch to fallback JID %s: %s", real_phone_jid, e2)
    else:
        try:
            await whatsapp.stop_typing(sender_jid, session=waha_session)
        except Exception:
            pass

    # 6. Update session history in Redis
    history = session.get("history", [])
    history.append({"role": "user", "content": user_text})
    if final_reply:
        history.append({"role": "assistant", "content": final_reply})
    session["history"] = history[-12:]
    await set_session(phone, session)
