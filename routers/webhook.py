import hmac
import hashlib
import logging
from fastapi import APIRouter, BackgroundTasks, Request, HTTPException, status
from config import settings
from services.cache import redis_client
from services.agent_runner import process_message
from services.access_control import is_number_allowed
from routers.admin_commands import handle_admin_command

logger = logging.getLogger("webhook")
router = APIRouter()


def verify_signature(raw_body: bytes, signature: str) -> bool:
    """Verifies HMAC SHA256 signature from WAHA webhook header."""
    if not settings.WAHA_WEBHOOK_SECRET:
        return True
    if not signature:
        # WAHA is not configured with HMAC signing — allow but warn
        logger.debug("Webhook received without HMAC signature. Consider configuring HMAC in WAHA.")
        return True
        
    expected = hmac.new(
        settings.WAHA_WEBHOOK_SECRET.encode(),
        raw_body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


@router.post("/pace-restaurant")
async def incoming_waha_webhook(req: Request, background_tasks: BackgroundTasks):
    """
    WAHA webhook endpoint for incoming WhatsApp messages.
    Controlled by WAHA_ENABLED feature flag in settings.
    """
    # Feature flag: disable webhook processing when in Web Chatbot testing mode
    if not settings.WAHA_ENABLED:
        logger.info("WAHA webhook event received but ignored (WAHA_ENABLED=false).")
        return {"status": "waha_disabled"}

    raw_body = await req.body()
    signature = (
        req.headers.get("X-Webhook-Hmac")
        or req.headers.get("x-webhook-hmac")
        or req.headers.get("X-Signature")
        or ""
    )

    if not verify_signature(raw_body, signature):
        logger.warning("Webhook signature mismatch. Dropping unauthenticated request.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook HMAC signature"
        )

    try:
        payload = await req.json()
    except Exception:
        return {"status": "invalid_json"}

    event_type = payload.get("event", "message")
    waha_session = payload.get("session") or settings.WAHA_SESSION
    data_payload = payload.get("payload", {})
    msg_id = data_payload.get("id")
    sender = data_payload.get("from")
    from_me = data_payload.get("fromMe", False)

    # Ignore system events or outbound messages sent by the bot itself
    if from_me or not sender or not msg_id:
        return {"status": "ignored"}

    # Extract alternate identifiers for multi-device, linked devices (LID), and group participants
    remote_jid_alt = (
        data_payload.get("_data", {}).get("key", {}).get("remoteJidAlt")
        or data_payload.get("remoteJidAlt")
        or ""
    )
    participant = (
        data_payload.get("participant")
        or data_payload.get("author")
        or data_payload.get("_data", {}).get("key", {}).get("participant")
        or data_payload.get("_data", {}).get("participant")
        or ""
    )

    # Determine who authored the message
    is_group = bool(sender and sender.endswith("@g.us"))
    actor_jid = participant if is_group else (remote_jid_alt or sender)

    # 1. Extract text (supports normal text, button clicks, and list responses)
    user_text = str(
        data_payload.get("body")
        or data_payload.get("selectedDisplayText")
        or data_payload.get("selectedButtonId")
        or data_payload.get("selectedRowId")
        or data_payload.get("title")
        or (data_payload.get("_data", {}) if isinstance(data_payload.get("_data"), dict) else {}).get("body")
        or (data_payload.get("_data", {}) if isinstance(data_payload.get("_data"), dict) else {}).get("selectedDisplayText")
        or (data_payload.get("message", {}) if isinstance(data_payload.get("message"), dict) else {}).get("buttonsResponseMessage", {}).get("selectedDisplayText")
        or (data_payload.get("message", {}) if isinstance(data_payload.get("message"), dict) else {}).get("templateButtonReplyMessage", {}).get("selectedDisplayText")
        or ""
    ).strip()

    # 2. Intercept In-Chat Admin Commands FIRST (works in 1-on-1 chats and in Admin Group)
    if user_text:
        is_admin_cmd, _ = await handle_admin_command(
            sender_jid=sender,
            text=user_text,
            send_whatsapp=True,
            session=waha_session,
            actor_jid=actor_jid,
            remote_jid_alt=remote_jid_alt
        )
        if is_admin_cmd:
            return {"status": "admin_command_executed"}

    # 3. For regular customer order-taking: ignore group messages
    if is_group:
        return {"status": "group_ignored"}

    # 4. Access Control Gate
    effective_check_number = actor_jid or sender
    if not is_number_allowed(effective_check_number):
        logger.info("Message from non-allowlisted number ignored: %s", effective_check_number)
        return {"status": "not_allowed"}

    # 3. Message Deduplication Layer (Redis 1 hour TTL)
    is_new = await redis_client.set(f"seen:{msg_id}", "1", nx=True, ex=3600)
    if not is_new:
        logger.debug("Duplicate message ignored: %s", msg_id)
        return {"status": "duplicate_ignored"}

    # 4. Asynchronous Task Dispatch
    background_tasks.add_task(process_message, payload)
    return {"status": "queued", "msg_id": msg_id}

