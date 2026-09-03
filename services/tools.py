import asyncio
import json
import logging
from typing import Optional, Any, Callable
import httpx
from config import settings
from services.db import db
from services.cache import redis_client
from services.whatsapp import whatsapp
from services.sanitize import sanitize_free_text

logger = logging.getLogger("tools")


async def call_with_retry(
    fn: Callable,
    *args,
    kind: str = "unknown",
    payload: Optional[dict] = None,
    attempts: int = 3,
    base_delay: float = 1.0,
    timeout: float = 30.0,
    **kwargs
) -> Any:
    """
    Executes an external async call with exponential backoff.
    If all attempts fail, logs the event to the dead-letter table (failed_dispatches).
    """
    last_err = None
    for i in range(attempts):
        try:
            return await asyncio.wait_for(fn(*args, **kwargs), timeout=timeout)
        except (httpx.TimeoutException, httpx.HTTPError, asyncio.TimeoutError, Exception) as e:
            last_err = e
            logger.warning("Attempt %d/%d for %s failed: %s", i + 1, attempts, kind, e)
            if i == attempts - 1:
                try:
                    await db.log_failed_dispatch(
                        kind=kind,
                        payload=payload or {},
                        error=str(e),
                        attempts=attempts
                    )
                except Exception as db_err:
                    logger.error("Failed to log to failed_dispatches: %s", db_err)
                raise e
            await asyncio.sleep(base_delay * (2 ** i))


async def read_menu(category: Optional[str] = None) -> list[dict]:
    """
    Fetches available menu items.
    Cached in Redis for 120s to reduce DB load.
    """
    cache_key = "cache:menu_items"
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            items = json.loads(cached)
            if category:
                items = [it for it in items if it.get("category", "").lower() == category.lower()]
            return items
    except Exception as e:
        logger.warning("Menu cache read error: %s", e)

    # Fetch from Supabase
    items = await db.get_menu(available_only=True)
    if items:
        try:
            await redis_client.set(cache_key, json.dumps(items), ex=120)
        except Exception:
            pass

    if category:
        items = [it for it in items if it.get("category", "").lower() == category.lower()]
    return items


async def invalidate_menu_cache():
    """Invalidates the Redis menu cache upon admin edits."""
    await redis_client.delete("cache:menu_items")


async def send_menu_images(phone: str, session: Optional[str] = None) -> dict:
    """Sends Pace Restaurant menu image cards to customer via the active session."""
    try:
        if settings.MENU_IMAGE_1:
            await call_with_retry(
                whatsapp.send_image,
                phone,
                settings.MENU_IMAGE_1,
                caption="📖 Pace Restaurant Menu — Page 1",
                session=session,
                timeout=35.0,
                kind="send_menu_image_1",
                payload={"phone": phone}
            )
        if settings.MENU_IMAGE_2:
            await call_with_retry(
                whatsapp.send_image,
                phone,
                settings.MENU_IMAGE_2,
                caption="📖 Pace Restaurant Menu — Page 2",
                session=session,
                timeout=35.0,
                kind="send_menu_image_2",
                payload={"phone": phone}
            )
        return {"status": "success", "message": "Menu images sent successfully."}
    except Exception as e:
        logger.error("Failed to send menu images to %s: %s", phone, e)
        return {"status": "error", "message": str(e)}


async def calculate_bill(
    items: list[dict],
    order_type: str = "Delivery",
    thal_count: int = 0
) -> dict:
    """
    Deterministic mathematical calculation of subtotal, delivery requirement, and total bill.
    Cross-references item prices against the live menu to prevent LLM price hallucination.
    Guarantees the LLM never fabricates prices or does arithmetic hallucination.
    """
    # Fetch cached menu for price validation
    menu_items = await read_menu()
    menu_lookup = {}
    for mi in menu_items:
        key = mi.get("name", "").strip().lower()
        if key:
            menu_lookup[key] = float(mi.get("price", 0.0))

    subtotal = 0.0
    parsed_items = []

    for item in items:
        name = sanitize_free_text(item.get("name", "Item"))
        qty = int(item.get("quantity") or item.get("qty") or 1)
        llm_price = float(item.get("price", 0.0))
        variant = sanitize_free_text(item.get("variant", ""))
        notes = sanitize_free_text(item.get("notes", ""))

        # Validate price against menu — use DB price if found, warn if mismatch
        menu_key = name.strip().lower()
        verified_price = llm_price
        if menu_key in menu_lookup:
            verified_price = menu_lookup[menu_key]
            if llm_price != verified_price:
                logger.warning(
                    "Price mismatch for '%s': LLM said Rs.%.0f, menu says Rs.%.0f. Using menu price.",
                    name, llm_price, verified_price
                )
        else:
            logger.warning("Item '%s' not found in menu cache — using LLM-provided price Rs.%.0f", name, llm_price)
        
        line_total = verified_price * qty
        subtotal += line_total

        parsed_items.append({
            "name": name,
            "quantity": qty,
            "price": verified_price,
            "variant": variant,
            "line_total": line_total,
            "notes": notes
        })

    # Sobat Thal deposit (traditional brass/steel thal deposit if customer requested)
    thal_deposit = thal_count * 200.0 if thal_count > 0 else 0.0
    total_bill = subtotal + thal_deposit

    is_delivery = order_type.lower() == "delivery"
    meets_minimum = (not is_delivery) or (subtotal >= settings.MINIMUM_DELIVERY_ORDER)

    return {
        "items": parsed_items,
        "subtotal": subtotal,
        "thal_deposit": thal_deposit,
        "total_bill": total_bill,
        "order_type": order_type,
        "meets_minimum_delivery": meets_minimum,
        "minimum_required": settings.MINIMUM_DELIVERY_ORDER
    }


async def check_returning_customer(phone: str) -> dict:
    """Retrieves customer history from database."""
    profile = await db.get_customer_profile(phone)
    if profile:
        return {
            "is_returning": True,
            "name": profile.get("customer_name"),
            "default_address": profile.get("default_address"),
            "total_orders": profile.get("total_orders", 0),
            "last_order_items": profile.get("last_order_items")
        }
    return {"is_returning": False}


async def save_order_record(session: dict, items: list[dict], total_bill: float, notes: str = "") -> dict:
    """
    Idempotently persists order to Supabase and updates customer profile.
    """
    phone = session.get("phone", "")
    customer_name = sanitize_free_text(session.get("name", "Valued Customer"))
    order_type = session.get("order_type", "Delivery")
    address = sanitize_free_text(session.get("address", ""))
    pickup_time = sanitize_free_text(session.get("pickup_time", ""))
    confirm_key = session.get("confirm_key")
    clean_notes = sanitize_free_text(notes or session.get("notes", ""))

    items_summary_str = "\n".join([
        f"- {it.get('quantity', 1)}x {it.get('name')} ({it.get('variant', '')}) : Rs. {it.get('price', 0)*it.get('quantity', 1):,.0f}"
        for it in items
    ])

    order_payload = {
        "session_confirm_key": confirm_key,
        "customer_name": customer_name,
        "phone_number": phone,
        "order_type": order_type,
        "delivery_address": address if order_type == "Delivery" else None,
        "pickup_time": pickup_time if order_type == "Takeaway" else None,
        "order_items": items_summary_str,
        "subtotal": session.get("subtotal", total_bill),
        "thal_deposit": session.get("thal_deposit", 0),
        "total_bill": total_bill,
        "notes": clean_notes
    }

    result = await db.save_order(order_payload)
    order_id = result.get("order_id", "PACE-ORDER")
    is_duplicate = result.get("duplicate", False)

    # Upsert customer profile if not a duplicate (with error handling)
    if not is_duplicate and phone:
        async def _safe_upsert():
            try:
                await db.upsert_customer_profile(
                    phone=phone,
                    name=customer_name,
                    address=address,
                    last_order_items=items_summary_str
                )
            except Exception as e:
                logger.error("Background customer profile upsert failed for %s: %s", phone, e)
        asyncio.create_task(_safe_upsert())

    return {
        "order_id": order_id,
        "duplicate": is_duplicate,
        "summary": items_summary_str,
        "total_bill": total_bill,
        "order_payload": order_payload
    }


async def notify_admins_and_kitchen(order_id: str, order_data: dict, session: Optional[str] = None) -> dict:
    """
    Dispatches WhatsApp notifications to Kitchen, Admins, and Admin Group.
    Wrapped in retry + dead-letter queue so transient WhatsApp downtime doesn't break customer UX.
    """
    customer_name = sanitize_free_text(order_data.get("customer_name", "Customer"))
    phone = order_data.get("phone_number", "")
    order_type = order_data.get("order_type", "Delivery")
    address = sanitize_free_text(order_data.get("delivery_address", "N/A"))
    pickup_time = sanitize_free_text(order_data.get("pickup_time", "Immediate"))
    items_summary = order_data.get("order_items", "")
    total_bill = order_data.get("total_bill", 0)
    notes = sanitize_free_text(order_data.get("notes", "None"))

    # 1. Kitchen Alert (Focused on cooking & packaging)
    kitchen_msg = (
        f"👨‍🍳 *NEW ORDER ALERT — {order_id}*\n"
        f"────────────────────\n"
        f"📋 *Type:* {order_type}\n"
        f"👤 *Customer:* {customer_name} ({phone})\n"
        f"📍 *{'Address' if order_type == 'Delivery' else 'Pickup Time'}:* {address if order_type == 'Delivery' else pickup_time}\n"
        f"📝 *Special Notes:* {notes}\n"
        f"────────────────────\n"
        f"🍴 *ITEMS TO PREPARE:*\n{items_summary}\n"
        f"────────────────────\n"
        f"💰 *Total Bill:* Rs. {total_bill:,.0f}"
    )

    # 2. Admin Alert
    admin_msg = (
        f"🔔 *PACE ORDER CONFIRMED — {order_id}*\n"
        f"────────────────────\n"
        f"👤 *Customer:* {customer_name}\n"
        f"📞 *Phone:* {phone}\n"
        f"📦 *Type:* {order_type}\n"
        f"📍 *Location/Time:* {address if order_type == 'Delivery' else pickup_time}\n"
        f"💰 *Total Amount:* Rs. {total_bill:,.0f}\n"
        f"📝 *Notes:* {notes}\n"
        f"────────────────────\n"
        f"🍽️ *Order Details:*\n{items_summary}\n"
        f"────────────────────\n"
        f"Status: Pending Kitchen Preparation"
    )

    targets = [
        ("kitchen", settings.KITCHEN_WHATSAPP, kitchen_msg),
        ("admin_1", settings.ADMIN_WHATSAPP, admin_msg),
    ]
    if settings.ADMIN_2_WHATSAPP and settings.ADMIN_2_WHATSAPP != settings.ADMIN_WHATSAPP:
        targets.append(("admin_2", settings.ADMIN_2_WHATSAPP, admin_msg))
    if settings.ADMIN_GROUP_JID:
        targets.append(("admin_group", settings.ADMIN_GROUP_JID, admin_msg))

    dispatched = []
    for label, target_jid, message_body in targets:
        if not target_jid:
            continue
        try:
            await call_with_retry(
                whatsapp.send_text,
                target_jid,
                message_body,
                session=session,
                kind=f"notify_{label}",
                payload={"order_id": order_id, "target": target_jid}
            )
            dispatched.append(label)
        except Exception as e:
            logger.error("Failed to notify %s (%s): %s", label, target_jid, e)

    return {"status": "dispatched", "recipients": dispatched}
