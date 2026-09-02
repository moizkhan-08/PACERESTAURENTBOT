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
        # In case WAHA passes without signature during local tests or dev
        if settings.DEBUG:
            return True
        return False
        
    expected = hmac.new(
        settings.WAHA_WEBHOOK_SECRET.encode(),
        raw_body,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


@router.post("/pace-restaurant")
async def incoming_waha_webhook(req: Request, background_tasks: BackgroundTasks):
    """
    Ingestion endpoint for WAHA WhatsApp events:
    1. Validates HMAC SHA-256 webhook signature
    2. Enforces ALLOWED_NUMBERS access control gate
    3. Prevents duplicate processing via Redis seen:msg_id keys
    4. Intercepts authorized Admin in-chat commands
    5. Dispatches LLM agent processing asynchronously
    """
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
    data_payload = payload.get("payload", {})
    msg_id = data_payload.get("id")
    sender = data_payload.get("from")
    from_me = data_payload.get("fromMe", False)

    # Ignore system events, outbound messages sent by the bot itself, or group chats
    if from_me or not sender or not msg_id:
        return {"status": "ignored"}

    # Ignore WhatsApp Group messages (JID ends with @g.us)
    if sender and sender.endswith("@g.us"):
        return {"status": "group_ignored"}

    # 1. Access Control Gate
    if not is_number_allowed(sender):
        logger.info("Message from non-allowlisted number ignored: %s", sender)
        return {"status": "not_allowed"}

    # 2. In-Chat Admin Commands Interceptor
    user_text = data_payload.get("body", "").strip()
    if user_text:
        is_admin_cmd = await handle_admin_command(sender, user_text)
        if is_admin_cmd:
            return {"status": "admin_command_executed"}

    # 3. Message Deduplication Layer (Redis 1 hour TTL)
    is_new = await redis_client.set(f"seen:{msg_id}", "1", nx=True, ex=3600)
    if not is_new:
        logger.debug("Duplicate message ignored: %s", msg_id)
        return {"status": "duplicate_ignored"}

    # 4. Asynchronous Task Dispatch
    background_tasks.add_task(process_message, payload)
    return {"status": "queued", "msg_id": msg_id}
