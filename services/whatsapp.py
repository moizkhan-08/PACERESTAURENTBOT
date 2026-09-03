import logging
import httpx
from typing import Optional
from config import settings

logger = logging.getLogger("whatsapp")


def format_jid(target: str) -> str:
    """Formats phone number or group ID into standard WhatsApp JID."""
    if not target:
        return ""
    target = target.strip()
    if "@" in target:
        return target
    # Clean non-digits
    import re
    digits = re.sub(r"\D", "", target)
    return f"{digits}@s.whatsapp.net"


class WahaClient:
    def __init__(self):
        self.base_url = settings.WAHA_API_URL.rstrip("/")
        self.session = settings.WAHA_SESSION
        self.headers = {
            "X-Api-Key": settings.WAHA_API_KEY,
            "Content-Type": "application/json"
        }
        # Persistent HTTP client for connection pooling
        self._client: Optional[httpx.AsyncClient] = None

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

    async def send_text(self, to: str, text: str) -> dict:
        """Sends a text message via WAHA /api/sendText."""
        chat_id = format_jid(to)
        payload = {
            "session": self.session,
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

    async def send_image(self, to: str, image_url: str, caption: str = "") -> dict:
        """Sends an image with caption via WAHA /api/sendImage."""
        chat_id = format_jid(to)
        payload = {
            "session": self.session,
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

    async def send_seen(self, chat_id: str, message_id: Optional[str] = None):
        """Marks message as seen."""
        try:
            payload = {
                "session": self.session,
                "chatId": format_jid(chat_id),
            }
            if message_id:
                payload["messageId"] = message_id

            client = self._get_client()
            await client.post("/api/sendSeen", json=payload, timeout=5.0)
        except Exception as e:
            logger.debug("WAHA sendSeen notice: %s", e)

    async def start_typing(self, chat_id: str):
        """Shows typing indicator in WhatsApp chat."""
        try:
            payload = {
                "session": self.session,
                "chatId": format_jid(chat_id),
            }
            client = self._get_client()
            await client.post("/api/startTyping", json=payload, timeout=5.0)
        except Exception:
            pass

    async def stop_typing(self, chat_id: str):
        """Clears typing indicator in WhatsApp chat."""
        try:
            payload = {
                "session": self.session,
                "chatId": format_jid(chat_id),
            }
            client = self._get_client()
            await client.post("/api/stopTyping", json=payload, timeout=5.0)
        except Exception:
            pass

    async def register_webhook(self) -> bool:
        """
        Idempotent webhook registration with WAHA.
        Registers the HMAC secret and subscription events.
        """
        webhook_url = f"http://pace-bot:{settings.APP_PORT}/webhook/pace-restaurant"
        payload = {
            "name": self.session,
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
                logger.info("WAHA session %s started / configured with webhook.", self.session)
                return True
            logger.warning("WAHA webhook registration response: %d %s", res.status_code, res.text)
        except Exception as e:
            logger.warning("Could not automatically register webhook with WAHA (%s): %s", self.base_url, e)
        return False


whatsapp = WahaClient()
