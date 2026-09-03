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
    notify_admins_and_kitchen
)
from services.prompts import (
    FULL_MENU_SYSTEM_PROMPT,
    SOBAT_ONLY_SYSTEM_PROMPT,
    CLOSED_SYSTEM_PROMPT
)

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
            "description": "Deterministically calculates total bill, items breakdown, thal deposit, and verifies minimum delivery order.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "quantity": {"type": "integer"},
                                "price": {"type": "number"},
                                "variant": {"type": "string"},
                                "notes": {"type": "string"}
                            },
                            "required": ["name", "price"]
                        }
                    },
                    "order_type": {
                        "type": "string",
                        "enum": ["Delivery", "Takeaway"],
                        "description": "Type of order"
                    },
                    "thal_count": {
                        "type": "integer",
                        "description": "Number of traditional Sobat Thals requested"
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
            "description": "Idempotently saves confirmed customer order into Supabase database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "quantity": {"type": "integer"},
                                "price": {"type": "number"},
                                "variant": {"type": "string"}
                            }
                        }
                    },
                    "total_bill": {"type": "number"},
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
            "description": "Dispatches real-time WhatsApp alert notifications to Kitchen, Admins, and Admin WhatsApp Group.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "customer_name": {"type": "string"},
                    "order_type": {"type": "string"},
                    "total_bill": {"type": "number"},
                    "delivery_address": {"type": "string"},
                    "pickup_time": {"type": "string"},
                    "notes": {"type": "string"}
                },
                "required": ["order_id", "total_bill"]
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
        items = tool_args.get("items") or session.get("items", [])
        total_bill = tool_args.get("total_bill") or session.get("total_bill", 0)
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

    elif tool_name == "notify_admins_and_kitchen":
        order_id = tool_args.get("order_id", "PACE-CONFIRMED")
        
        if dispatch_mode == "whatsapp":
            items_fallback = "\n".join([
                f"- {it.get('quantity', 1)}x {it.get('name')} ({it.get('variant', '')})"
                for it in session.get("items", [])
            ]) if session.get("items") else "Items"
            
            order_summary_data = {
                "customer_name": tool_args.get("customer_name") or session.get("name"),
                "phone_number": phone,
                "order_type": tool_args.get("order_type") or session.get("order_type"),
                "delivery_address": tool_args.get("delivery_address") or session.get("address"),
                "pickup_time": tool_args.get("pickup_time") or session.get("pickup_time"),
                "order_items": (latest_order_record.get("summary") if latest_order_record else None) or items_fallback,
                "total_bill": tool_args.get("total_bill") or session.get("total_bill", 0),
                "notes": tool_args.get("notes") or session.get("notes", "")
            }
            tool_result = await notify_admins_and_kitchen(order_id, order_summary_data, session=waha_session)
        else:
            tool_result = {
                "status": "simulated_dispatch",
                "order_id": order_id,
                "message": f"Order {order_id} alert simulated for kitchen & admin."
            }
        # Reset confirm key for fresh next order
        session["confirm_key"] = None

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
    
    # Inject context metadata
    context_note = f"[Customer Phone: {phone}]"
    if session.get("name"):
        context_note += f" [Customer Name: {session.get('name')}]"
    if session.get("address"):
        context_note += f" [Known Address: {session.get('address')}]"
    context_note += f" [Current Time PKT: {hours.get('current_time_pkt')}]"
    messages.append({"role": "system", "content": context_note})

    # Add past turn history (last 8 turns)
    for h in history[-8:]:
        messages.append(h)

    # Add current user message
    messages.append({"role": "user", "content": user_text})

    final_reply = ""
    latest_order_record = None
    executed_tools = []

    # Deterministic trigger: if customer asks for the menu, guarantee send_menu_images is called
    user_words = set(user_text.lower().split())
    menu_triggers = {"menu", "card", "tasweer", "tasweerein", "pic", "pics", "photo", "photos", "menyu"}
    force_menu = bool(user_words.intersection(menu_triggers)) or any(t in user_text.lower() for t in ["menu dikhao", "menu bhejo", "menu card", "show menu"])

    try:
        for turn_idx in range(5):  # Max 5 tool iterations per turn
            tool_choice = "auto"
            if turn_idx == 0 and force_menu:
                tool_choice = {"type": "function", "function": {"name": "send_menu_images"}}

            response = await openai_client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=messages,
                tools=AGENT_TOOLS,
                tool_choice=tool_choice,
                temperature=0.4
            )

            assistant_msg = response.choices[0].message
            messages.append(assistant_msg)

            if not assistant_msg.tool_calls:
                final_reply = assistant_msg.content or ""
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

    except Exception as e:
        logger.exception("Error in agent runner execution for %s: %s", phone, e)
        final_reply = "Shukriya! Aapke message par thori der mein hamare numainday aapse rabta karenge 😊"

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
    media_info = msg_payload.get("media", {})
    user_text = msg_payload.get("body", "").strip()

    if not phone or msg_payload.get("fromMe", False):
        return

    # Guard: ignore WhatsApp group messages (JID ends with @g.us)
    if sender_jid.endswith("@g.us"):
        logger.debug("Ignoring group message from %s", sender_jid)
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

    waha_session = payload.get("session") or settings.WAHA_SESSION

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
    if not hours["is_open"]:
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

    # 5. Send reply via WhatsApp
    try:
        await whatsapp.stop_typing(sender_jid, session=waha_session)
    except Exception:
        pass

    if final_reply:
        try:
            await whatsapp.send_text(sender_jid, final_reply, session=waha_session)
            logger.info("Outbound WhatsApp reply dispatched to %s via session %s", sender_jid, waha_session)
        except Exception as e:
            logger.error("Failed to dispatch WhatsApp reply to %s: %s", sender_jid, e)

    # 6. Update session history in Redis
    history = session.get("history", [])
    history.append({"role": "user", "content": user_text})
    if final_reply:
        history.append({"role": "assistant", "content": final_reply})
    session["history"] = history[-10:]
    await set_session(phone, session)
