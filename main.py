from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from config import settings
from routers import webhook, admin, test_playground
from services.management import start_scheduler
from services.cache import init_redis, redis_client
from services.logging_setup import init_logging
from services.whatsapp import whatsapp
from services.hours import get_hours_info

logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize Structured Logging & Sentry
    init_logging()
    logger.info("Initializing Pace Restaurant WhatsApp Bot v3...")

    # 2. Connect to Redis (sessions, dedup, cache, distributed locks)
    await init_redis()

    # 3. Start APScheduler Background Cron & Lock-protected jobs
    start_scheduler()

    # 4. Auto-register Webhook with WAHA WhatsApp gateway
    try:
        await whatsapp.register_webhook()
    except Exception as e:
        logger.warning("WAHA webhook registration notice: %s", e)

    logger.info("Pace Restaurant WhatsApp Bot is ready and listening on port %d.", settings.APP_PORT)
    yield
    
    # Teardown
    await redis_client.close()
    logger.info("Application shut down cleanly.")


app = FastAPI(
    title="Pace Restaurant AI WhatsApp Order Bot",
    description="Automated AI Order-Taking, PKT Shift Routing & Dispatch for Pace Restaurant Dera Ismail Khan",
    version="3.0.0",
    lifespan=lifespan
)

# Register Routers
app.include_router(webhook.router, prefix="/webhook", tags=["Webhook"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(test_playground.router, prefix="/test", tags=["Testing Playground"])


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint used by Docker and monitoring."""
    hours = get_hours_info()
    redis_connected = redis_client._is_connected
    
    return {
        "status": "ok",
        "restaurant": settings.RESTAURANT_NAME,
        "location": settings.RESTAURANT_CITY,
        "shift": hours.get("agent_type"),
        "is_open": hours.get("is_open"),
        "time_pkt": hours.get("current_time_pkt"),
        "redis_connected": redis_connected
    }


@app.get("/", tags=["Root"])
async def root():
    return {
        "app": "Pace Restaurant AI WhatsApp Order Bot",
        "version": "3.0.0",
        "docs": "/docs",
        "health": "/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG
    )
