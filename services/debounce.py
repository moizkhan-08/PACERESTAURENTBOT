import asyncio
import logging
from typing import Callable, Any, Dict, List, Optional
from services.audio import transcribe_audio_payload
from services.whatsapp import whatsapp

logger = logging.getLogger("debounce")


def extract_text_from_data(data_payload: dict) -> str:
    """Extracts raw text, button clicks, or list selection from a WAHA payload dict."""
    return str(
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


class MessageDebouncer:
    """
    Sliding window message aggregator for incoming customer WhatsApp messages.
    When a customer sends multiple messages in quick succession (e.g., within 2 seconds),
    the debounce timer resets on each new message. Once 2 seconds of silence elapse,
    all buffered messages are combined into a single unified payload and processed once.
    """
    def __init__(self, delay: float = 2.0, max_buffer: int = 10):
        self.delay = delay
        self.max_buffer = max_buffer
        self._buffers: Dict[str, List[dict]] = {}
        self._tasks: Dict[str, asyncio.Task] = {}

    async def add_message(
        self,
        key: str,
        payload: dict,
        process_callback: Callable[[dict], Any],
        waha_session: Optional[str] = None
    ):
        """
        Adds a message to the customer's buffer and resets the 2-second debounce timer.
        key: unique customer identifier (e.g. sender_jid or phone)
        payload: the full webhook payload dict
        process_callback: async function to call with the combined payload (e.g. process_message)
        """
        if key not in self._buffers:
            self._buffers[key] = []
        self._buffers[key].append(payload)

        # Send immediate typing indicator so customer knows bot is actively listening
        try:
            await whatsapp.start_typing(key, session=waha_session)
        except Exception:
            pass

        # If buffer reaches max_buffer, trigger immediately without waiting
        if len(self._buffers[key]) >= self.max_buffer:
            logger.info("Buffer limit reached (%d) for %s, dispatching immediately", self.max_buffer, key)
            if key in self._tasks and not self._tasks[key].done():
                self._tasks[key].cancel()
            self._tasks[key] = asyncio.create_task(
                self._dispatch_now(key, process_callback)
            )
            return

        # Cancel previous timer task to slide the window forward (reset 2s timer)
        if key in self._tasks and not self._tasks[key].done():
            self._tasks[key].cancel()
            logger.info("⏳ Debounce timer reset (2.0s) for %s. Current buffer size: %d", key, len(self._buffers[key]))
        else:
            logger.info("⏳ Debounce timer started (2.0s) for %s", key)

        # Start a new 2.0-second sliding window timer
        self._tasks[key] = asyncio.create_task(
            self._timer_expired(key, process_callback)
        )

    async def _timer_expired(self, key: str, process_callback: Callable[[dict], Any]):
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            # Timer was reset by another incoming message within the delay window
            return

        await self._dispatch_now(key, process_callback)

    async def _dispatch_now(self, key: str, process_callback: Callable[[dict], Any]):
        messages = self._buffers.pop(key, [])
        self._tasks.pop(key, None)

        if not messages:
            return

        if len(messages) == 1:
            # Single message sent — process directly
            combined_payload = messages[0]
        else:
            logger.info("📦 Aggregating %d rapid messages from %s into a single prompt", len(messages), key)
            # Use the latest message as the base payload (preserves latest msg_id, headers, timestamps)
            combined_payload = messages[-1]
            phone = key.split("@")[0]

            extracted_texts = []
            for msg in messages:
                data = msg.get("payload", {})
                has_media = data.get("hasMedia", False)
                media_info = data.get("media", {}) if isinstance(data.get("media"), dict) else {}
                mimetype = media_info.get("mimetype", "")

                # Handle voice note within the rapid stream
                if (has_media or media_info) and ("audio" in mimetype or "ogg" in mimetype or "mp3" in mimetype or data.get("type") == "ptt"):
                    try:
                        transcribed = await transcribe_audio_payload(media_info, phone)
                        if transcribed:
                            extracted_texts.append(transcribed)
                    except Exception as e:
                        logger.warning("Voice note transcription error during debounce: %s", e)
                else:
                    txt = extract_text_from_data(data)
                    if txt:
                        extracted_texts.append(txt)

            combined_text = "\n".join(extracted_texts).strip()
            if not combined_text:
                combined_text = extract_text_from_data(combined_payload.get("payload", {}))

            # Update the base payload with the aggregated text and mark media as processed
            if "payload" in combined_payload:
                combined_payload["payload"]["body"] = combined_text
                combined_payload["payload"]["hasMedia"] = False
                if "_data" in combined_payload["payload"] and isinstance(combined_payload["payload"]["_data"], dict):
                    combined_payload["payload"]["_data"]["body"] = combined_text

        # Dispatch the unified payload
        try:
            await process_callback(combined_payload)
        except Exception as e:
            logger.error("Error executing debounced message for %s: %s", key, e, exc_info=True)


# Global debouncer singleton with 2.0-second sliding window
message_debouncer = MessageDebouncer(delay=2.0)
