import logging
import asyncio
from typing import Optional, Any

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

from config import settings


logger = logging.getLogger("cache")


class RedisClientWrapper:
    """Async Redis wrapper with resilient fallback for local tests."""
    def __init__(self):
        self._redis: Optional[Any] = None
        self._fallback_store: dict = {}
        self._is_connected: bool = False

    async def init(self):
        if aioredis is None:
            self._is_connected = False
            logger.warning("Redis library not installed. Using fallback in-memory cache.")
            return

        try:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5
            )
            await self._redis.ping()
            self._is_connected = True
            logger.info("Connected to Redis successfully at %s", settings.REDIS_URL)
        except Exception as e:
            self._is_connected = False
            logger.warning("Could not connect to Redis (%s). Using fallback in-memory cache: %s", settings.REDIS_URL, e)


    async def close(self):
        if self._redis:
            await self._redis.close()

    async def get(self, key: str) -> Optional[str]:
        if self._is_connected and self._redis:
            try:
                return await self._redis.get(key)
            except Exception as e:
                logger.warning("Redis GET failed for %s, using fallback: %s", key, e)
        return self._fallback_store.get(key)

    async def set(self, key: str, value: Any, ex: Optional[int] = None, nx: bool = False) -> bool:
        if self._is_connected and self._redis:
            try:
                res = await self._redis.set(key, value, ex=ex, nx=nx)
                return bool(res)
            except Exception as e:
                logger.warning("Redis SET failed for %s, using fallback: %s", key, e)
        
        if nx and key in self._fallback_store:
            return False
        self._fallback_store[key] = str(value)
        return True

    async def delete(self, key: str) -> int:
        if self._is_connected and self._redis:
            try:
                return await self._redis.delete(key)
            except Exception as e:
                logger.warning("Redis DELETE failed for %s, using fallback: %s", key, e)
        if key in self._fallback_store:
            del self._fallback_store[key]
            return 1
        return 0

    async def exists(self, key: str) -> bool:
        if self._is_connected and self._redis:
            try:
                return bool(await self._redis.exists(key))
            except Exception as e:
                logger.warning("Redis EXISTS failed for %s, using fallback: %s", key, e)
        return key in self._fallback_store

    async def keys(self, pattern: str = "*") -> list[str]:
        if self._is_connected and self._redis:
            try:
                return await self._redis.keys(pattern)
            except Exception as e:
                logger.warning("Redis KEYS failed for %s, using fallback: %s", pattern, e)
        import fnmatch
        return [k for k in self._fallback_store.keys() if fnmatch.fnmatch(k, pattern)]


redis_client = RedisClientWrapper()


async def init_redis():
    await redis_client.init()
