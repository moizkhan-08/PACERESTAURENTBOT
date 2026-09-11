import logging
import re
from typing import Optional
from config import settings
from services.cache import redis_client
from services.db import db
from services.whatsapp import whatsapp
from services.hours import get_hours_info
from services.tools import invalidate_menu_cache

logger = logging.getLogger("admin_commands")


def get_admin_numbers() -> set[str]:
    """Returns set of normalized admin phone numbers and allowlisted devices."""
    admins = set()
    # Configured admin phones
    for raw in [
        settings.ADMIN_WHATSAPP,
        settings.ADMIN_2_WHATSAPP,
        settings.KITCHEN_WHATSAPP,
        settings.RESTAURANT_MOBILE,
        "923306874242",
        "923322716555",
        "923299881590",
        "923379221111"
    ]:
        if raw:
            clean = re.sub(r"\D", "", raw.split("@")[0].split(":")[0])
            if clean:
                admins.add(clean)

    # Allowed test numbers & LIDs (e.g. 69630278291529, 94043224707153)
    if settings.ALLOWED_NUMBERS:
        for n in settings.ALLOWED_NUMBERS.split(","):
            clean = re.sub(r"\D", "", n.strip().split("@")[0].split(":")[0])
            if clean:
                admins.add(clean)

    return admins


def is_authorized_admin(
    sender_jid: str,
    text: str,
    remote_jid_alt: Optional[str] = None
) -> bool:
    """
    Validates if sender is authorized:
    1. Secret 'agent47' password prefix allows execution from any device.
    2. Phone match by exact string or 10-digit phone suffix.
    3. Allowlisted device IDs / LIDs.
    4. Also checks remote_jid_alt if sender is a Linked Device / LID.
    """
    clean_text = text.strip().lower()
    if clean_text.startswith("agent47"):
        return True

    admin_numbers = get_admin_numbers()

    candidates = [sender_jid]
    if remote_jid_alt:
        candidates.append(remote_jid_alt)

    for cand in candidates:
        if not cand:
            continue
        clean_cand = re.sub(r"\D", "", cand.split("@")[0].split(":")[0])
        if not clean_cand:
            continue

        # Exact match
        if clean_cand in admin_numbers:
            return True

        # Suffix match (e.g. 03306874242 vs 923306874242)
        if len(clean_cand) >= 10:
            cand_suffix = clean_cand[-10:]
            for adm in admin_numbers:
                if len(adm) >= 10 and adm[-10:] == cand_suffix:
                    return True

    return False


async def handle_admin_command(
    sender_jid: str,
    text: str,
    send_whatsapp: bool = True,
    session: Optional[str] = None,
    actor_jid: Optional[str] = None,
    remote_jid_alt: Optional[str] = None
) -> tuple[bool, str]:
    """
    Processes in-chat admin commands.
    Returns (is_admin_cmd: bool, response_msg: str).
    """
    text_clean = text.strip()
    lower_text = text_clean.lower()

    # Secret agent47 password prefix allows execution from any device
    is_secret = lower_text.startswith("agent47")
    if is_secret:
        lower_text = lower_text[7:].strip()
        text_clean = text_clean[7:].strip()

    # Strip command prefix character if present ('/', '!', '#', '.')
    if lower_text.startswith(("/", "!", "#", ".")):
        lower_text = lower_text[1:].strip()
        text_clean = text_clean[1:].strip()

    parts = text_clean.split()
    if not parts:
        return False, ""

    raw_cmd = parts[0].lower()

    # Handle 'bot <command>' or 'admin <command>' e.g. 'bot status', 'bot off', 'bot on'
    if raw_cmd in {"bot", "admin"} and len(parts) > 1:
        parts = parts[1:]
        raw_cmd = parts[0].lower()

    known_commands = {
        "status", "orders", "today", "help", "commands",
        "activate", "on", "start",
        "deactivate", "off", "stop",
        "maintenance", "maint",
        "mute", "unmute",
        "clearcache", "clear-cache", "refreshmenu",
        "soldout", "sold-out", "available"
    }

    if raw_cmd not in known_commands:
        return False, ""

    # Authorization check
    effective_actor = actor_jid or sender_jid
    if not is_secret and not is_authorized_admin(effective_actor, text.strip(), remote_jid_alt=remote_jid_alt):
        return False, ""

    clean_sender = re.sub(r"\D", "", effective_actor.split("@")[0].split(":")[0]) or "admin"
    command = raw_cmd
    args = parts[1:] if len(parts) > 1 else []
    target = args[0] if args else None
    response_msg = ""

    # ── 1. Bot Activation Controls ──
    if command in {"deactivate", "off", "stop"}:
        await redis_client.set("flag:bot_active", "0")
        response_msg = "🛑 *Pace Bot Deactivated*\nAutomated order-taking has been paused for all customers."

    elif command in {"activate", "on", "start"}:
        await redis_client.set("flag:bot_active", "1")
        response_msg = "✅ *Pace Bot Activated*\nAutomated order-taking is now active for all customers."

    # ── 2. Maintenance Mode Controls ──
    elif command == "maintenance":
        mode = args[0].lower() if args else ""
        if mode == "on":
            await redis_client.set("flag:maintenance_only", clean_sender)
            response_msg = f"🛠️ *Maintenance Mode ON*\nBot is now restricted to admin testing only ({clean_sender})."
        elif mode == "off":
            await redis_client.delete("flag:maintenance_only")
            response_msg = "🚀 *Maintenance Mode OFF*\nBot is now reopened to all customers."
        else:
            maint = await redis_client.get("flag:maintenance_only")
            response_msg = f"🛠️ Maintenance mode is currently: *{maint if maint else 'Disabled'}*\nUsage: `/maintenance on` or `/maintenance off`"

    # ── 3. Customer Mute Controls ──
    elif command == "mute" and args:
        target_phone = re.sub(r"\D", "", args[0])
        if target_phone:
            await redis_client.set(f"mute:{target_phone}", "1")
            response_msg = f"🔇 *Customer Muted*\nCustomer {target_phone} has been muted. Bot will ignore messages from this number."
        else:
            response_msg = "⚠️ Please provide a valid phone number. Example: `/mute 923001234567`"

    elif command == "unmute" and args:
        if args[0].lower() == "all":
            mute_keys = await redis_client.keys("mute:*")
            for k in mute_keys:
                await redis_client.delete(k)
            response_msg = f"🔊 *All Mutes Cleared*\nUnmuted {len(mute_keys)} customer(s)."
        else:
            target_phone = re.sub(r"\D", "", args[0])
            await redis_client.delete(f"mute:{target_phone}")
            response_msg = f"🔊 *Customer Unmuted*\nCustomer {target_phone} has been unmuted."

    # ── 4. Cache Management ──
    elif command in {"clearcache", "clear-cache", "refreshmenu"}:
        await invalidate_menu_cache()
        response_msg = "🗑️ *Menu Cache Flushed*\nLive menu will reload fresh from database on the next query."

    # ── 4b. Sold Out / Available Item Toggle ──
    elif command in {"soldout", "sold-out"}:
        if not args:
            response_msg = (
                "⚠️ *Usage:*\n"
                "• `/soldout <item name>` — Mark item as sold out\n"
                "• `/soldout list` — Show all sold-out items\n"
                "• `/soldout clear` — Clear all sold-out items"
            )
        elif args[0].lower() == "list":
            members = await redis_client.smembers("soldout:items")
            if members:
                items_list = sorted(m if isinstance(m, str) else m.decode() for m in members)
                lines = ["❌ *Currently Sold Out Items:*", "────────────────────"]
                for i, item in enumerate(items_list, 1):
                    lines.append(f"{i}. {item.title()}")
                lines.append("────────────────────")
                lines.append("💡 Use `/available <item>` to restore")
                response_msg = "\n".join(lines)
            else:
                response_msg = "✅ *No items are currently sold out.* Full menu is available!"
        elif args[0].lower() == "clear":
            await redis_client.delete("soldout:items")
            response_msg = "✅ *All Sold-Out Flags Cleared*\nEntire menu is now available again."
        else:
            item_name = " ".join(args).strip().lower()
            await redis_client.sadd("soldout:items", item_name)
            response_msg = f"❌ *Item Marked Sold Out*\n*{item_name.title()}* is now marked as sold out. Customers will be informed it's unavailable.\n💡 Use `/available {item_name}` to restore."

    elif command == "available":
        if not args:
            response_msg = "⚠️ *Usage:* `/available <item name>` — Restore a sold-out item back to menu"
        else:
            item_name = " ".join(args).strip().lower()
            removed = await redis_client.srem("soldout:items", item_name)
            if removed:
                response_msg = f"✅ *Item Restored*\n*{item_name.title()}* is now available again on the menu!"
            else:
                response_msg = f"ℹ️ *{item_name.title()}* was not in the sold-out list. It's already available."

    # ── 5. Bot Status ──
    elif command == "status":
        bot_active = await redis_client.get("flag:bot_active") != "0"
        maint = await redis_client.get("flag:maintenance_only")
        mutes = await redis_client.keys("mute:*")
        soldout_members = await redis_client.smembers("soldout:items")
        soldout_count = len(soldout_members) if soldout_members else 0
        hours = get_hours_info()
        today_data = await db.get_today_orders_with_stats()
        stats = today_data.get("stats", {})

        response_msg = (
            f"⚙️ *Pace Restaurant — Bot Status*\n"
            f"────────────────────\n"
            f"🤖 *AI Bot:* {'🟢 Active' if bot_active else '🔴 Deactivated'}\n"
            f"🕒 *Shift:* {hours.get('agent_type', 'unknown').upper()} ({hours.get('current_time_pkt', 'PKT')})\n"
            f"🚪 *Restaurant:* {'Open' if hours.get('is_open') else 'Closed'}\n"
            f"🛠️ *Maintenance:* {maint if maint else 'Off'}\n"
            f"🔇 *Muted Customers:* {len(mutes)}\n"
            f"❌ *Sold Out Items:* {soldout_count}\n"
            f"────────────────────\n"
            f"📦 *Today's Orders:* {stats.get('total_orders', 0)}\n"
            f"💰 *Today's Revenue:* Rs. {stats.get('total_revenue', 0):,.0f}\n"
            f"🛵 *Deliveries:* {stats.get('delivery_count', 0)} | 🛍️ *Takeaways:* {stats.get('takeaway_count', 0)}"
        )

    # ── 6. Today's Orders Summary ──
    elif command in {"orders", "today"}:
        today_data = await db.get_today_orders_with_stats()
        stats = today_data.get("stats", {})
        recent = today_data.get("orders", [])[:5]

        lines = [
            f"📋 *Today's Orders Summary*",
            f"────────────────────",
            f"📦 Total Orders: {stats.get('total_orders', 0)}",
            f"💰 Total Revenue: Rs. {stats.get('total_revenue', 0):,.0f}",
            f"🛵 Deliveries: {stats.get('delivery_count', 0)}",
            f"🛍️ Takeaways: {stats.get('takeaway_count', 0)}",
            f"────────────────────"
        ]
        if recent:
            lines.append("*Recent Orders:*")
            for o in recent:
                oid = o.get("order_id", "—")
                cname = o.get("guest_name", "Customer")
                total = o.get("total_amount", 0)
                status = o.get("status", "—")
                lines.append(f"• `{oid}` | {cname} | Rs. {total:,.0f} ({status})")
        else:
            lines.append("No orders received yet today.")

        response_msg = "\n".join(lines)

    # ── 7. Test Mode & Session Reset ──
    elif command in {"testmode", "forceopen"}:
        if args and args[0].lower() in {"on", "enable", "1", "true"}:
            await redis_client.set("flag:force_open", "1")
            response_msg = "🧪 *Test Mode Enabled*\nShift forced to FULL MENU (Open) for testing anytime."
        else:
            await redis_client.delete("flag:force_open")
            response_msg = "🕒 *Test Mode Disabled*\nShift returned to real-time operating hours."

    elif command in {"reset", "clearsession"}:
        target_phone = re.sub(r"\D", "", args[0]) if args else re.sub(r"\D", "", clean_sender)
        if target_phone:
            from services.session import clear_session
            await clear_session(target_phone)
            response_msg = f"🔄 *Session Reset*\nSession history cleared for `{target_phone}`. Next message will be treated as a fresh interaction."
        else:
            response_msg = "⚠️ Could not identify phone number to reset."

    # ── 8. Admin Help Menu ──
    elif command in {"help", "commands"}:
        response_msg = (
            f"👑 *Pace Restaurant — Admin Commands*\n"
            f"────────────────────\n"
            f"• `/status` — View live bot status & today's sales\n"
            f"• `/orders` — View today's orders & revenue breakdown\n"
            f"• `/soldout <item>` — Mark item as sold out\n"
            f"• `/soldout list` — View all sold-out items\n"
            f"• `/soldout clear` — Clear all sold-out flags\n"
            f"• `/available <item>` — Restore sold-out item\n"
            f"• `/testmode on|off` — Force Full Menu open for testing\n"
            f"• `/reset [phone]` — Clear session history for fresh test\n"
            f"• `/activate` — Enable automated AI order-taking\n"
            f"• `/deactivate` — Pause automated AI order-taking\n"
            f"• `/maintenance on|off` — Restrict bot to admin only\n"
            f"• `/mute <phone>` — Mute a disruptive customer\n"
            f"• `/unmute <phone>` — Unmute customer\n"
            f"• `/unmute all` — Clear all customer mutes\n"
            f"• `/clear-cache` — Force reload menu from DB\n"
            f"────────────────────\n"
            f"💡 *Tip:* You can also type commands without `/` (e.g. `status`, `soldout chicken fried rice`)"
        )

    else:
        return False, ""

    # Audit logging
    try:
        await db.log_admin_action(
            actor_jid=clean_sender,
            command=command,
            target=target
        )
    except Exception as e:
        logger.warning("Audit log error: %s", e)

    # WhatsApp reply
    if send_whatsapp:
        try:
            await whatsapp.dynamic_typing_delay(sender_jid, text=response_msg, session=session, min_sec=1.0, max_sec=2.0)
            await whatsapp.send_text(sender_jid, response_msg, session=session)
        except Exception as e:
            logger.warning("Could not send admin reply to %s: %s", sender_jid, e)

    logger.info("Admin command '%s' executed by %s", text_clean, clean_sender)
    return True, response_msg
