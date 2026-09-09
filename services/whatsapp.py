import asyncio
import logging
import random
from typing import Optional
import httpx
from config import settings

logger = logging.getLogger("whatsapp")


def format_jid(target: str) -> str:
    """
    Formats phone number, LID, or group ID into standard WhatsApp JID.
    Crucially strips any device suffix (e.g. :1, :2) from contact JIDs
    which causes WAHA / Baileys to fail with 500 not-acceptable.
    """
    if not target:
        return ""
    target = target.strip()
    # If it's a group or LID, keep domain as-is, but strip device suffix if present
    if "@g.us" in target or "@lid" in target:
        parts = target.split("@")
        user_part = parts[0].split(":")[0]
        return f"{user_part}@{parts[1]}"
    
    # Strip any domain and device suffix
    phone_part = target.split("@")[0].split(":")[0]
    import re
    digits = re.sub(r"\D", "", phone_part)
    return f"{digits}@s.whatsapp.net"



class WahaClient:
    def __init__(self):
        self.base_url = settings.WAHA_API_URL.rstrip("/")
        self.session = settings.WAHA_SESSION or "Pace"
        self.headers = {
            "X-Api-Key": settings.WAHA_API_KEY,
            "Content-Type": "application/json"
        }
        # Persistent HTTP client for connection pooling
        self._client: Optional[httpx.AsyncClient] = None

    def _resolve_session(self, session: Optional[str] = None) -> str:
        """Ensures the WAHA instance/session strictly resolves to Pace across all endpoints."""
        return settings.WAHA_SESSION or "Pace"

    def _get_client(self) -> httpx.AsyncClient:
        """Returns or creates a persistent httpx.AsyncClient with connection pooling."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self.headers,
                timeout=15.0
            )
        return self._client

    async def close(self):
        """Closes the persistent HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.close()

    async def send_text(self, to: str, text: str, session: Optional[str] = None) -> dict:
        """Sends a text message via WAHA /api/sendText."""
        chat_id = format_jid(to)
        active_session = self._resolve_session(session)
        payload = {
            "session": active_session,
            "chatId": chat_id,
            "text": text
        }
        
        client = self._get_client()
        res = await client.post("/api/sendText", json=payload)
        if res.status_code in (200, 201):
            return res.json()
        logger.error("WAHA sendText failed to %s: %d %s", chat_id, res.status_code, res.text)
        res.raise_for_status()
        return {}

    async def send_image(self, to: str, image_url: str, caption: str = "", session: Optional[str] = None) -> dict:
        """Sends an image with caption via WAHA /api/sendImage."""
        chat_id = format_jid(to)
        active_session = self._resolve_session(session)
        payload = {
            "session": active_session,
            "chatId": chat_id,
            "file": {
                "url": image_url
            },
            "caption": caption
        }

        client = self._get_client()
        res = await client.post("/api/sendImage", json=payload, timeout=20.0)
        if res.status_code in (200, 201):
            return res.json()
        logger.error("WAHA sendImage failed to %s: %d %s", chat_id, res.status_code, res.text)
        res.raise_for_status()
        return {}

    async def send_seen(self, chat_id: str, message_id: Optional[str] = None, session: Optional[str] = None):
        """Marks message as seen."""
        try:
            active_session = self._resolve_session(session)
            payload = {
                "session": active_session,
                "chatId": format_jid(chat_id),
            }
            if message_id:
                payload["messageId"] = message_id

            client = self._get_client()
            await client.post("/api/sendSeen", json=payload, timeout=5.0)
        except Exception as e:
            logger.debug("WAHA sendSeen notice: %s", e)

    async def start_typing(self, chat_id: str, session: Optional[str] = None):
        """Shows typing indicator in WhatsApp chat."""
        try:
            active_session = self._resolve_session(session)
            payload = {
                "session": active_session,
                "chatId": format_jid(chat_id),
            }
            client = self._get_client()
            await client.post("/api/startTyping", json=payload, timeout=5.0)
        except Exception:
            pass

    async def stop_typing(self, chat_id: str, session: Optional[str] = None):
        """Clears typing indicator in WhatsApp chat."""
        try:
            active_session = self._resolve_session(session)
            payload = {
                "session": active_session,
                "chatId": format_jid(chat_id),
            }
            client = self._get_client()
            await client.post("/api/stopTyping", json=payload, timeout=5.0)
        except Exception:
            pass

    async def dynamic_typing_delay(
        self,
        chat_id: str,
        text: str = "",
        session: Optional[str] = None,
        min_sec: Optional[float] = None,
        max_sec: Optional[float] = None
    ) -> float:
        """
        Simulates realistic human typing behavior with a dynamic 1-3 second delay.
        Activates the WhatsApp 'typing...' indicator while waiting to mimic natural
        keystroke pacing and prevent automated bot detection or Meta account restrictions.
        """
        min_s = min_sec if min_sec is not None else settings.DYNAMIC_DELAY_MIN
        max_s = max_sec if max_sec is not None else settings.DYNAMIC_DELAY_MAX

        if max_s <= 0:
            return 0.0

        # Random delay jitter between min_s (1.0s) and max_s (3.0s)
        base_delay = random.uniform(min_s, max_s)
        if text:
            # Scaled slightly based on message length (longer messages get realistic typing time)
            length_factor = min(len(text) / 250.0, 0.7)
            delay = min(max_s, max(min_s, base_delay + length_factor * 0.5))
        else:
            delay = base_delay

        delay = round(delay, 2)
        active_session = self._resolve_session(session)
        logger.info("Human typing simulation for %s (session: %s): typing indicator active for %.2fs", chat_id, active_session, delay)
        try:
            await self.start_typing(chat_id, session=active_session)
            await asyncio.sleep(delay)
        except Exception as e:
            logger.debug("Typing delay notice: %s", e)
        return delay

    async def register_webhook(self) -> bool:
        """
        Idempotent webhook registration with WAHA.
        Registers the HMAC secret and subscription events.
        """
        active_session = self._resolve_session(None)
        webhook_url = f"http://pace-bot:{settings.APP_PORT}/webhook/pace-restaurant"
        payload = {
            "name": active_session,
            "config": {
                "webhooks": [
                    {
                        "url": webhook_url,
                        "events": ["session.status", "message", "messages.upsert", "message.any"],
                        "hmac": {"key": settings.WAHA_WEBHOOK_SECRET}
                    }
                ]
            }
        }
        
        try:
            client = self._get_client()
            res = await client.post("/api/sessions/start", json=payload, timeout=10.0)
            if res.status_code in (200, 201, 400, 409):
                logger.info("WAHA session %s started / configured with webhook.", active_session)
                return True
            logger.warning("WAHA webhook registration response: %d %s", res.status_code, res.text)
        except Exception as e:
            logger.warning("Could not automatically register webhook with WAHA (%s): %s", self.base_url, e)
        return False


whatsapp = WahaClient()
