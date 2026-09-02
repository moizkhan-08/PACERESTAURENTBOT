import json
import logging
import uuid
from typing import Optional
from services.cache import redis_client

logger = logging.getLogger("session")
SESSION_TTL = 60 * 30  # 30 min idle timeout


async def get_session(phone: str) -> dict:
    """Retrieves customer session state from Redis."""
    try:
        raw = await redis_client.get(f"session:{phone}")
        if raw:
            return json.loads(raw)
    except Exception as e:
        logger.warning("Error fetching session for %s: %s", phone, e)
    return {}


async def set_session(phone: str, data: dict):
    """Saves customer session state to Redis with 30 minute TTL."""
    try:
        await redis_client.set(f"session:{phone}", json.dumps(data), ex=SESSION_TTL)
    except Exception as e:
        logger.warning("Error saving session for %s: %s", phone, e)


async def clear_session(phone: str):
    """Clears customer session state."""
    try:
        await redis_client.delete(f"session:{phone}")
    except Exception as e:
        logger.warning("Error clearing session for %s: %s", phone, e)


def generate_confirm_key(phone: str) -> str:
    """Generates an idempotency session confirmation key."""
    return f"{phone}:{uuid.uuid4().hex[:12]}"
