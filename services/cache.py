import logging
import time
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
        self._fallback_store: dict = {}  # key -> (value, expiry_timestamp | None)
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

    def _fallback_get(self, key: str) -> Optional[str]:
        """Get from fallback store, respecting TTL expiration."""
        entry = self._fallback_store.get(key)
        if entry is None:
            return None
        value, expiry = entry
        if expiry is not None and time.monotonic() > expiry:
            del self._fallback_store[key]
            return None
        return value

    def _fallback_set(self, key: str, value: Any, ex: Optional[int] = None, nx: bool = False) -> bool:
        """Set in fallback store with optional TTL and NX semantics."""
        existing = self._fallback_get(key)
        if nx and existing is not None:
            return False
        expiry = (time.monotonic() + ex) if ex else None
        self._fallback_store[key] = (str(value), expiry)
        return True

    async def get(self, key: str) -> Optional[str]:
        if self._is_connected and self._redis:
            try:
                return await self._redis.get(key)
            except Exception as e:
                logger.warning("Redis GET failed for %s, using fallback: %s", key, e)
        return self._fallback_get(key)

    async def set(self, key: str, value: Any, ex: Optional[int] = None, nx: bool = False) -> bool:
        if self._is_connected and self._redis:
            try:
                res = await self._redis.set(key, value, ex=ex, nx=nx)
                return bool(res)
            except Exception as e:
                logger.warning("Redis SET failed for %s, using fallback: %s", key, e)
        
        return self._fallback_set(key, value, ex=ex, nx=nx)

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
        return self._fallback_get(key) is not None

    async def keys(self, pattern: str = "*") -> list[str]:
        if self._is_connected and self._redis:
            try:
                return await self._redis.keys(pattern)
            except Exception as e:
                logger.warning("Redis KEYS failed for %s, using fallback: %s", pattern, e)
        import fnmatch
        # Clean expired keys during scan
        now = time.monotonic()
        valid_keys = []
        expired_keys = []
        for k, (v, expiry) in self._fallback_store.items():
            if expiry is not None and now > expiry:
                expired_keys.append(k)
            elif fnmatch.fnmatch(k, pattern):
                valid_keys.append(k)
        for k in expired_keys:
            del self._fallback_store[k]
        return valid_keys


redis_client = RedisClientWrapper()


async def init_redis():
    await redis_client.init()
