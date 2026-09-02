import contextlib
import logging
from services.cache import redis_client

logger = logging.getLogger("locks")


@contextlib.asynccontextmanager
async def distributed_lock(name: str, ttl: int = 120):
    """
    Distributed lock pattern using Redis SETNX with TTL.
    Prevents duplicate background execution across multiple container replicas.
    """
    token = await redis_client.set(f"lock:{name}", "1", nx=True, ex=ttl)
    acquired = bool(token)
    try:
        yield acquired
    finally:
        if acquired:
            try:
                await redis_client.delete(f"lock:{name}")
            except Exception as e:
                logger.warning("Failed to release lock %s: %s", name, e)
