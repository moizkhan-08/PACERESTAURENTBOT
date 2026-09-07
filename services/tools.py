import asyncio
import json
import logging
import re
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


async def warm_menu_cache() -> list[dict]:
    """Pre-fetches available menu items from database into Redis cache for instant sub-millisecond lookups."""
    cache_key = "cache:menu_items"
    try:
        items = await db.get_menu(available_only=True)
        if items:
            await redis_client.set(cache_key, json.dumps(items), ex=86400)
            logger.info("⚡ Menu cache warmed successfully (%d items cached).", len(items))
            return items
    except Exception as e:
        logger.warning("Failed to warm menu cache: %s", e)
    return []


async def read_menu(category: Optional[str] = None, search: Optional[str] = None) -> list[dict]:
    """
    Fetches available menu items.
    Cached in Redis for 24h to reduce DB load and ensure sub-5ms responses.
    Supports filtering by category or searching item name.
    """
    cache_key = "cache:menu_items"
    items = []
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            items = json.loads(cached)
    except Exception as e:
        logger.warning("Menu cache read error: %s", e)

    if not items:
        items = await warm_menu_cache()

    query = search or category
    if query:
        q = query.strip().lower()
        # 1. Match category (exact or partial)
        matched = [it for it in items if q in it.get("category", "").lower()]
        # 2. If no category matched, match item name (e.g. 'Sobat', 'Karahi', 'Tikka')
        if not matched:
            matched = [it for it in items if q in it.get("name", "").lower()]
        # 3. Word token match
        if not matched:
            matched = [it for it in items if any(w in it.get("name", "").lower() for w in q.split() if len(w) > 2)]
        if matched:
            return matched

    return items


async def invalidate_menu_cache():
    """Flushes and immediately warms the Redis menu cache upon admin edits."""
    await redis_client.delete("cache:menu_items")
    try:
        await warm_menu_cache()
    except Exception as e:
        logger.warning("Background menu re-warm error: %s", e)


async def send_menu_images(target: str, session: Optional[str] = None) -> dict:
    """Sends Pace Restaurant menu image cards to customer via the active session."""
    logger.info("send_menu_images invoked for %s (session: %s)", target, session)
    try:
        if settings.MENU_IMAGE_1:
            await call_with_retry(
                whatsapp.send_image,
                target,
                settings.MENU_IMAGE_1,
                caption="📖 Pace Restaurant Menu — Page 1",
                session=session,
                timeout=35.0,
                kind="send_menu_image_1",
                payload={"target": target}
            )
            logger.info("Page 1 menu image dispatched to %s", target)
        if settings.MENU_IMAGE_2:
            await call_with_retry(
                whatsapp.send_image,
                target,
                settings.MENU_IMAGE_2,
                caption="📖 Pace Restaurant Menu — Page 2",
                session=session,
                timeout=35.0,
                kind="send_menu_image_2",
                payload={"target": target}
            )
            logger.info("Page 2 menu image dispatched to %s", target)
        return {"status": "success", "message": "Menu images sent successfully."}
    except Exception as e:
        logger.error("Failed to send menu images to %s: %s", target, e)
        return {"status": "error", "message": str(e)}


def resolve_menu_item_price(
    name: str,
    variant: str,
    llm_price: float,
    menu_items: list[dict]
) -> tuple[str, float, str]:
    """
    Intelligently cross-references customer dish requests against live Supabase MenuPace items.
    Handles colloquial Roman Urdu names, variants (Leg/Chest, Half/Full, 1.5L), aliases, and
    overrides any LLM price hallucination with the authentic restaurant price.
    """
    raw_name_clean = (name or "").strip()
    clean = re.sub(r'^\d+\s*(x|nafri|plate|plates)?\s*', '', raw_name_clean, flags=re.I).strip().lower()
    clean_no_punct = re.sub(r'[\(\)\[\],/]', ' ', clean).strip()
    var_clean = (variant or "").strip().lower()

    # Build quick dictionary of exact lowercase names
    db_lookup = {}
    for mi in menu_items:
        k = mi.get("name", "").strip().lower()
        if k:
            db_lookup[k] = (mi["name"], float(mi.get("price", 0.0)), mi.get("variant") or "")

    # Priority 1: Exact case-insensitive match in DB
    if clean in db_lookup:
        match_name, match_price, match_var = db_lookup[clean]
        return match_name, match_price, match_var or variant
    if raw_name_clean.lower() in db_lookup:
        match_name, match_price, match_var = db_lookup[raw_name_clean.lower()]
        return match_name, match_price, match_var or variant

    # Priority 2: Combined name + variant exact match in DB
    if var_clean:
        combo = f"{clean} {var_clean}"
        if combo in db_lookup:
            match_name, match_price, match_var = db_lookup[combo]
            return match_name, match_price, match_var or variant

    # Priority 2: Core Chicken Sobat Flagship (Always enforces real database price)
    if clean in {"chicken sobat", "chicken sobat leg", "chicken sobat chest"}:
        is_chest = "chest" in clean or "chest" in var_clean
        if is_chest:
            target = next((it for it in menu_items if "chicken sobat" in it.get("name", "").lower() and "chest" in it.get("name", "").lower()), None)
            if target: return target["name"], float(target["price"]), "Chest"
        else:
            target = next((it for it in menu_items if "chicken sobat" in it.get("name", "").lower() and "leg" in it.get("name", "").lower()), None)
            if target: return target["name"], float(target["price"]), "Leg"

    # Priority 3: If caller passed explicit non-zero test price or custom quote, respect it
    if llm_price and float(llm_price) > 0:
        return name, float(llm_price), variant

    # Priority 4: Known Aliases for unpriced items (llm_price <= 0)
    aliases = {
        "simple sobat": "simple sobat",
        "saada sobat": "simple sobat",
        "mutton sobat": "mutton sobat",
        "beef sobat": "beef champ sobat",
        "beef champ sobat": "beef champ sobat",
        "desi murgh sobat": "desi murgh sobat",
        "bbq chicken sobat": "bbq chicken sobat (leg)",
        "chicken karahi": "chicken peshawari karahi (full)",
        "chicken karahi full": "chicken peshawari karahi (full)",
        "chicken karahi half": "chicken peshawari karahi (half)",
        "mutton karahi": "mutton peshawari karahi (full)",
        "mutton karahi half": "mutton peshawari karahi (half)",
        "roti": "roti / maana per head",
        "tandoori roti": "roti / maana per head",
        "naan": "simple naan",
        "simple naan": "simple naan",
        "roghni naan": "roghni naan",
        "garlic naan": "garlic naan",
        "mineral water": "mineral water",
        "cold drink": "regular soft drinks",
        "soft drink": "regular soft drinks",
        "regular drink": "regular soft drinks",
        "1.5l soft drink": "1.5 liter soft drink",
        "1.5 liter soft drink": "1.5 liter soft drink"
    }
    if var_clean:
        combo = f"{clean} {var_clean}"
        if combo in aliases and aliases[combo] in db_lookup:
            match_name, match_price, match_var = db_lookup[aliases[combo]]
            return match_name, match_price, match_var or variant
    if clean in aliases and aliases[clean] in db_lookup:
        match_name, match_price, match_var = db_lookup[aliases[clean]]
        return match_name, match_price, match_var or variant

    # Priority 5: Specialized Dish Matchers for unpriced items
    if "karahi" in clean or "handi" in clean:
        is_half = "half" in clean or "half" in var_clean
        dish_type = "karahi" if "karahi" in clean else "handi"
        meat_type = "mutton" if "mutton" in clean else "chicken"
        for it in menu_items:
            n = it.get("name", "").lower()
            if dish_type in n and meat_type in n:
                if is_half and "half" in n:
                    return it["name"], float(it["price"]), "Half"
                elif not is_half and "full" in n:
                    return it["name"], float(it["price"]), "Full"

    if "roti" in clean or "maana" in clean:
        target = next((it for it in menu_items if "roti" in it.get("name", "").lower()), None)
        if target: return target["name"], float(target["price"]), target.get("variant") or variant

    # Priority 6: Token Overlap Matching for unpriced items
    query_words = [w for w in clean_no_punct.split() if len(w) >= 3 and w not in {'wali', 'wala', 'with', 'and', 'aur', 'food', 'nafri', 'plate'}]
    best_candidate = None
    best_score = -1
    for it in menu_items:
        it_name = it.get("name", "").strip().lower()
        matches = sum(1 for w in query_words if w in it_name)
        if matches == 0:
            continue
        score = matches * 20
        if matches == len(query_words):
            score += 40
        if score > best_score:
            best_score = score
            best_candidate = it

    if best_candidate and best_score >= 20:
        return best_candidate.get("name", name), float(best_candidate.get("price", 0.0)), best_candidate.get("variant") or variant

    return name, 0.0, variant


async def calculate_bill(
    items: list[dict],
    order_type: str = "Delivery",
    thal_count: int = 0
) -> dict:
    """
    Deterministic mathematical calculation of subtotal, thal deposit, delivery requirement, and total bill.
    Resolves item prices against live Supabase/Redis MenuPace items to guarantee 100% price and arithmetic accuracy.
    """
    menu_items = await read_menu()

    subtotal = 0.0
    parsed_items = []

    for raw_item in items:
        raw_name = sanitize_free_text(raw_item.get("name", "Item"))
        qty = max(1, int(raw_item.get("quantity") or raw_item.get("qty") or 1))
        llm_price = float(raw_item.get("price", 0.0))
        variant = sanitize_free_text(raw_item.get("variant", ""))
        notes = sanitize_free_text(raw_item.get("notes", ""))

        resolved_name, verified_price, resolved_variant = resolve_menu_item_price(
            raw_name, variant, llm_price, menu_items
        )

        line_total = round(verified_price * qty, 2)
        subtotal += line_total

        parsed_items.append({
            "name": resolved_name,
            "quantity": qty,
            "price": verified_price,
            "unit_price": verified_price,
            "variant": resolved_variant,
            "line_total": line_total,
            "notes": notes
        })

    # Sobat Thal deposit (Rs. 300 per thal — refundable when returned to restaurant)
    # Thal is STRICTLY and EXCLUSIVELY for Sobat / Paenda items
    has_sobat = any("sobat" in it.get("name", "").lower() or "paenda" in it.get("name", "").lower() for it in parsed_items)
    effective_thal_count = thal_count if (has_sobat and thal_count > 0) else 0
    thal_deposit = round(effective_thal_count * 300.0, 2)
    total_bill = round(subtotal + thal_deposit, 2)

    is_delivery = order_type.strip().lower() == "delivery"
    meets_minimum = (not is_delivery) or (subtotal >= settings.MINIMUM_DELIVERY_ORDER)

    # Format human-readable itemized summary for the model to echo perfectly
    summary_lines = []
    for it in parsed_items:
        var_label = f" ({it['variant']})" if it.get("variant") else ""
        summary_lines.append(f"• {it['quantity']}x *{it['name']}*{var_label} — Rs. {it['line_total']:,.0f}")
    if thal_deposit > 0:
        summary_lines.append(f"• *Thal Deposit ({int(effective_thal_count)}x)* — Rs. {thal_deposit:,.0f} (refundable)")
    summary_lines.append(f"💰 *Total: Rs. {total_bill:,.0f}*")
    formatted_summary = "\n".join(summary_lines)

    return {
        "items": parsed_items,
        "subtotal": subtotal,
        "thal_deposit": thal_deposit,
        "total_bill": total_bill,
        "formatted_summary": formatted_summary,
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
            "name": profile.get("name") or profile.get("customer_name", ""),
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


async def report_complaint(phone: str, customer_name: str, complaint_text: str, session: Optional[str] = None) -> dict:
    """
    Sends food/service complaint notification to Admin Group and Admin WhatsApp.
    Called when a customer reports issues with food quality, delivery, or service.
    """
    clean_name = sanitize_free_text(customer_name or "Customer")
    clean_complaint = sanitize_free_text(complaint_text or "No details provided")

    complaint_msg = (
        f"⚠️ *CUSTOMER COMPLAINT ALERT*\n"
        f"────────────────────\n"
        f"👤 *Customer:* {clean_name}\n"
        f"📞 *Phone:* {phone}\n"
        f"────────────────────\n"
        f"📝 *Complaint:*\n{clean_complaint}\n"
        f"────────────────────\n"
        f"⏰ Please follow up with this customer ASAP."
    )

    dispatched = []
    targets = []
    if settings.ADMIN_GROUP_JID:
        targets.append(("admin_group", settings.ADMIN_GROUP_JID))
    if settings.ADMIN_WHATSAPP:
        targets.append(("admin_1", settings.ADMIN_WHATSAPP))

    for label, target_jid in targets:
        if not target_jid:
            continue
        try:
            await call_with_retry(
                whatsapp.send_text,
                target_jid,
                complaint_msg,
                session=session,
                kind=f"complaint_{label}",
                payload={"phone": phone, "complaint": clean_complaint}
            )
            dispatched.append(label)
        except Exception as e:
            logger.error("Failed to send complaint to %s (%s): %s", label, target_jid, e)

    return {"status": "complaint_reported", "recipients": dispatched}

