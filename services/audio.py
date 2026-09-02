import logging
import io
import httpx
from openai import AsyncOpenAI
from config import settings
from services.db import db

logger = logging.getLogger("audio")


async def transcribe_audio_payload(media_info: dict, chat_id: str) -> str:
    """
    Downloads audio/voice note from WAHA and transcribes using OpenAI or Groq Whisper.
    Logs dead-letter errors to Supabase failed_dispatches on exhausted retries.
    """
    media_url = media_info.get("url")
    mimetype = media_info.get("mimetype", "audio/ogg")
    
    if not media_url:
        logger.warning("No media URL found in audio payload for %s", chat_id)
        return ""

    audio_bytes = None
    
    # 1. Download audio file with retry
    headers = {"X-Api-Key": settings.WAHA_API_KEY} if settings.WAHA_API_KEY else {}
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
                res = await client.get(media_url)
                if res.status_code == 200:
                    audio_bytes = res.content
                    break
        except Exception as e:
            if attempt == 2:
                logger.error("Failed to download voice note audio after 3 attempts: %s", e)
                await db.log_failed_dispatch(
                    kind="voice_download",
                    payload={"chat_id": chat_id, "url": media_url},
                    error=str(e),
                    attempts=3
                )
                return ""
    
    if not audio_bytes:
        return ""

    # 2. Transcribe using OpenAI Whisper or Groq Whisper
    filename = "voice_note.ogg" if "ogg" in mimetype else "voice_note.mp3"
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = filename

    # Primary: OpenAI Whisper
    if settings.OPENAI_API_KEY:
        try:
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            transcription = await client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                prompt="Pace Restaurant Dera Ismail Khan, Sobat, Paenda, Karahi, Handi, Biryani, BBQ, Urdu, Saraiki, English order details."
            )
            text = transcription.text.strip()
            logger.info("Transcribed voice note from %s: '%s'", chat_id, text)
            return text
        except Exception as e:
            logger.error("OpenAI Whisper transcription failed: %s", e)
            await db.log_failed_dispatch(
                kind="whisper",
                payload={"chat_id": chat_id, "filename": filename},
                error=str(e),
                attempts=1
            )

    # Secondary / Fallback: Groq Whisper if key exists
    if settings.GROQ_API_KEY:
        try:
            audio_file.seek(0)
            headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}"}
            files = {"file": (filename, audio_file.read(), mimetype)}
            data = {"model": "whisper-large-v3"}
            async with httpx.AsyncClient(timeout=20.0) as http_c:
                res = await http_c.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers=headers,
                    files=files,
                    data=data
                )
                if res.status_code == 200:
                    text = res.json().get("text", "").strip()
                    logger.info("Transcribed voice note via Groq from %s: '%s'", chat_id, text)
                    return text
        except Exception as e:
            logger.error("Groq Whisper transcription failed: %s", e)

    return ""
