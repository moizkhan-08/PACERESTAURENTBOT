import logging
import re
from config import settings
from services.cache import redis_client
from services.db import db
from services.whatsapp import whatsapp

logger = logging.getLogger("admin_commands")


def get_admin_numbers() -> set[str]:
    """Returns set of normalized admin phone numbers."""
    admins = set()
    for raw in [settings.ADMIN_WHATSAPP, settings.ADMIN_2_WHATSAPP]:
        if raw:
            clean = re.sub(r"\D", "", raw.split("@")[0])
            if clean:
                admins.add(clean)
    return admins


async def handle_admin_command(sender_jid: str, text: str) -> bool:
    """
    Checks if message is an admin command from an authorized admin phone.
    Returns True if handled as an admin command, False otherwise.
    """
    clean_sender = re.sub(r"\D", "", sender_jid.split("@")[0])
    admin_numbers = get_admin_numbers()

    if clean_sender not in admin_numbers:
        return False

    text = text.strip()
    if not (text.startswith("/") or text.lower().startswith("agent47") or text.lower().startswith("mute") or text.lower().startswith("unmute")):
        return False

    parts = text.split()
    raw_command = parts[0].lower()
    command = raw_command.lstrip("/")
    args = parts[1:] if len(parts) > 1 else []
    target = args[0] if args else None
    response_msg = ""

    if command in {"deactivate", "agent47deactivate"}:
        await redis_client.set("flag:bot_active", "0")
        response_msg = "🛑 Bot deactivated for all customers."

    elif command in {"activate", "agent47activate"}:
        await redis_client.set("flag:bot_active", "1")
        response_msg = "✅ Bot activated. Automated ordering resumed."

    elif command == "mute" and args:
        target_phone = re.sub(r"\D", "", args[0])
        await redis_client.set(f"mute:{target_phone}", "1")
        response_msg = f"🔇 Customer {target_phone} has been muted."

    elif command == "unmute" and args:
        if args[0].lower() == "all":
            mute_keys = await redis_client.keys("mute:*")
            for k in mute_keys:
                await redis_client.delete(k)
            response_msg = "🔊 All customer mutes cleared."
        else:
            target_phone = re.sub(r"\D", "", args[0])
            await redis_client.delete(f"mute:{target_phone}")
            response_msg = f"🔊 Customer {target_phone} unmuted."

    elif command == "maintenance" and args:
        mode = args[0].lower()
        if mode == "on":
            await redis_client.set("flag:maintenance_only", clean_sender)
            response_msg = f"🛠️ Maintenance mode ON (Restricted to {clean_sender})."
        elif mode == "off":
            await redis_client.delete("flag:maintenance_only")
            response_msg = "🚀 Maintenance mode OFF. Reopened to all customers."
        else:
            return False

    elif command == "status":
        bot_active = await redis_client.get("flag:bot_active") != "0"
        maint = await redis_client.get("flag:maintenance_only")
        mutes = await redis_client.keys("mute:*")
        response_msg = (
            f"⚙️ *Bot Status*\n"
            f"Active: {'✅ Yes' if bot_active else '❌ No'}\n"
            f"Maintenance: {maint if maint else 'Off'}\n"
            f"Muted Customers: {len(mutes)}"
        )
    else:
        return False

    # Audit logging
    await db.log_admin_action(
        actor_jid=sender_jid,
        command=command,
        target=target
    )

    # Reply to Admin
    await whatsapp.send_text(sender_jid, response_msg)
    logger.info("Admin command '%s' executed by %s", text, sender_jid)
    return True
