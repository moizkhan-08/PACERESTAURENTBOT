from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from config import settings
from routers import webhook, admin, test_playground, dashboard
from services.management import start_scheduler
from services.cache import init_redis, redis_client
from services.whatsapp import whatsapp
from services.logging_setup import init_logging
from services.hours import get_hours_info

logger = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize Structured Logging & Sentry
    init_logging()
    logger.info("Initializing Pace Restaurant AI Bot in Web Chatbot Testing Mode...")

    # 2. Connect to Redis (sessions, dedup, cache, distributed locks)
    await init_redis()

    # 3. Start APScheduler Background Cron & Lock-protected jobs
    start_scheduler()

    # 4. WhatsApp Gateway status
    if settings.WAHA_ENABLED:
        logger.info("WAHA WhatsApp Gateway integration enabled (Session: %s).", settings.WAHA_SESSION)
    else:
        logger.info("WAHA integration disabled (Operating in Web Simulator Mode).")

    logger.info("Pace Restaurant AI Bot is ready and listening on port %d.", settings.APP_PORT)
    yield
    
    # Teardown
    await whatsapp.close()
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
app.include_router(dashboard.router, prefix="/dashboard", tags=["Admin Dashboard"])


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
    """Redirect root directly to the Web Chatbot Simulator."""
    return RedirectResponse(url="/test")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG
    )
