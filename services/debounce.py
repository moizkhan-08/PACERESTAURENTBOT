import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Callable, Any, Dict, List, Optional
from services.audio import transcribe_audio_payload
from services.whatsapp import whatsapp
from config import settings

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


@dataclass
class CustomerDebounceState:
    buffer: List[dict] = field(default_factory=list)
    pending_buffer: List[dict] = field(default_factory=list)
    first_arrival: float = 0.0
    timer_task: Optional[asyncio.Task] = None
    is_processing: bool = False
    waha_session: Optional[str] = None


class MessageDebouncer:
    """
    Production-grade Message Debounce & Buffer System.
    Features:
    1. Sliding Window (DEBOUNCE_SECONDS = 2.0): Resets on each new message.
    2. Max-Wait Ceiling (MAX_WAIT_SECONDS = 2.0): Force-flushes after 2s from first arrival.
    3. 3-State Concurrency Machine (IDLE, BUFFERING, PROCESSING): Messages arriving while an agent is running are safely held in pending_buffer and drained sequentially.
    4. Media-Aware Aggregation: Transcribes voice notes using their specific media payload before merging.
    5. Proactive Typing Presence: Emits startTyping signal to WAHA immediately upon arrival and during debounce.
    6. Automatic Memory Eviction: Cleans up customer state when IDLE.
    """
    def __init__(self, debounce_seconds: float = 2.0, max_wait_seconds: float = 2.0):
        self.debounce_seconds = debounce_seconds
        self.max_wait_seconds = max_wait_seconds
        self._states: Dict[str, CustomerDebounceState] = {}
        self._lock = asyncio.Lock()

    async def add_message(
        self,
        key: str,
        payload: dict,
        process_callback: Callable[[dict], Any],
        waha_session: Optional[str] = None
    ):
        """
        Enqueues an incoming customer message into the debounce system.
        """
        # Proactively send typing indicator to WhatsApp
        try:
            await whatsapp.start_typing(key, session=waha_session)
        except Exception:
            pass

        async with self._lock:
            if key not in self._states:
                self._states[key] = CustomerDebounceState(waha_session=waha_session)
            state = self._states[key]
            state.waha_session = waha_session

            # If the agent is currently processing a turn for this customer,
            # hold this new message in the pending_buffer to prevent concurrent race conditions!
            if state.is_processing:
                state.pending_buffer.append(payload)
                logger.info("Customer %s is currently PROCESSING. Message held in pending_buffer (size: %d)", key, len(state.pending_buffer))
                return

            # Customer is in BUFFERING state
            now = time.monotonic()
            if not state.buffer:
                state.first_arrival = now
            state.buffer.append(payload)

            elapsed = now - state.first_arrival

            # Check Max-Wait Ceiling (e.g. 5.0s)
            if elapsed >= self.max_wait_seconds:
                logger.info("⏱️ Max-wait ceiling reached (%.2fs >= %.2fs) for %s. Force-flushing %d messages.", elapsed, self.max_wait_seconds, key, len(state.buffer))
                if state.timer_task and not state.timer_task.done():
                    state.timer_task.cancel()
                state.timer_task = None
                asyncio.create_task(self._execute_cycle(key, process_callback))
                return

            # Calculate remaining time before max-wait ceiling is reached
            remaining_to_ceiling = max(0.1, self.max_wait_seconds - elapsed)
            effective_delay = min(self.debounce_seconds, remaining_to_ceiling)

            # Cancel previous sliding timer task
            if state.timer_task and not state.timer_task.done():
                state.timer_task.cancel()
                logger.info("⏳ Sliding debounce timer reset (%.2fs) for %s (buffer size: %d, elapsed: %.2fs)", effective_delay, key, len(state.buffer), elapsed)
            else:
                logger.info("⏳ Debounce timer started (%.2fs) for %s", effective_delay, key)

            state.timer_task = asyncio.create_task(
                self._timer_worker(key, effective_delay, process_callback)
            )

    async def _timer_worker(self, key: str, delay: float, process_callback: Callable[[dict], Any]):
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return

        async with self._lock:
            state = self._states.get(key)
            if not state or state.is_processing:
                return
            state.timer_task = None

        # Execute cycle
        await self._execute_cycle(key, process_callback)

    async def _execute_cycle(self, key: str, process_callback: Callable[[dict], Any]):
        async with self._lock:
            state = self._states.get(key)
            if not state:
                return
            messages = state.buffer
            state.buffer = []
            state.first_arrival = 0.0
            state.is_processing = True

        if not messages:
            async with self._lock:
                state.is_processing = False
                if not state.pending_buffer:
                    self._states.pop(key, None)
            return

        try:
            # Combine messages
            combined_payload = await self._combine_messages(key, messages)
            # Dispatch agent processing
            await process_callback(combined_payload)
        except Exception as e:
            logger.error("Error executing debounced cycle for %s: %s", key, e, exc_info=True)
        finally:
            # Post-execution queue drain check
            async with self._lock:
                state = self._states.get(key)
                if state:
                    if state.pending_buffer:
                        # Move pending messages to active buffer and trigger subsequent cycle
                        logger.info("📦 Draining %d pending messages for customer %s into next cycle", len(state.pending_buffer), key)
                        state.buffer = state.pending_buffer
                        state.pending_buffer = []
                        state.first_arrival = time.monotonic()
                        state.is_processing = False
                        # Give a short debounce window (e.g. 1.0s) for the next batch
                        state.timer_task = asyncio.create_task(
                            self._timer_worker(key, min(self.debounce_seconds, 1.0), process_callback)
                        )
                    else:
                        state.is_processing = False
                        # Clean up idle state to prevent memory leaks
                        self._states.pop(key, None)
                        logger.debug("Customer %s state transitioned to IDLE and evicted from memory.", key)

    async def _combine_messages(self, key: str, messages: List[dict]) -> dict:
        if len(messages) == 1:
            return messages[0]

        logger.info("📦 Aggregating %d rapid messages from %s into a single prompt", len(messages), key)
        combined_payload = messages[-1]
        phone = key.split("@")[0]

        extracted_texts = []
        for msg in messages:
            data = msg.get("payload", {})
            has_media = data.get("hasMedia", False)
            media_info = data.get("media", {}) if isinstance(data.get("media"), dict) else {}
            mimetype = media_info.get("mimetype", "")

            # If this individual message is an audio / voice note, transcribe it using its own media payload!
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

        if "payload" in combined_payload:
            combined_payload["payload"]["body"] = combined_text
            combined_payload["payload"]["hasMedia"] = False
            if "_data" in combined_payload["payload"] and isinstance(combined_payload["payload"]["_data"], dict):
                combined_payload["payload"]["_data"]["body"] = combined_text

        return combined_payload


# Global debouncer singleton (2.0s sliding silence window, 2.0s max-wait ceiling)
message_debouncer = MessageDebouncer(
    debounce_seconds=settings.DEBOUNCE_SECONDS,
    max_wait_seconds=settings.MAX_WAIT_SECONDS
)
