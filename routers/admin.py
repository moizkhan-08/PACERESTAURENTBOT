import logging
from fastapi import APIRouter, Query, Body
from config import settings
from services.db import db
from services.cache import redis_client
from services.hours import get_hours_info
from services.tools import invalidate_menu_cache

logger = logging.getLogger("admin_api")
router = APIRouter()


@router.get("/stats")
async def get_admin_stats():
    """Returns real-time operating metrics, shift info, and bot flags."""
    hours = get_hours_info()
    bot_active = await redis_client.get("flag:bot_active") != "0"
    maint = await redis_client.get("flag:maintenance_only")
    mute_keys = await redis_client.keys("mute:*")

    return {
        "restaurant": settings.RESTAURANT_NAME,
        "city": settings.RESTAURANT_CITY,
        "shift_info": hours,
        "bot_active": bot_active,
        "maintenance_mode": maint if maint else "Disabled",
        "muted_customers_count": len(mute_keys),
        "min_delivery_order": settings.MINIMUM_DELIVERY_ORDER
    }


@router.get("/failed-dispatches")
async def get_failed_dispatches(unresolved_only: bool = Query(default=True)):
    """Retrieves dead-letter queue records for exhausted retries."""
    return await db.get_failed_dispatches(unresolved_only=unresolved_only)


@router.post("/cache/clear-menu")
async def clear_menu_cache():
    """Manually flushes the Redis menu cache."""
    await invalidate_menu_cache()
    return {"status": "success", "message": "Menu cache invalidated."}


@router.post("/bot-toggle")
async def toggle_bot(active: bool = Body(embed=True)):
    """Toggles AI bot ordering globally."""
    await redis_client.set("flag:bot_active", "1" if active else "0")
    return {"status": "success", "bot_active": active}


@router.post("/maintenance")
async def set_maintenance(enabled: bool = Body(..., embed=True), admin_phone: str = Body(default="", embed=True)):
    """Toggles maintenance mode."""
    if enabled:
        phone = admin_phone or settings.ADMIN_WHATSAPP
        await redis_client.set("flag:maintenance_only", phone)
        return {"status": "success", "maintenance": True, "restricted_to": phone}
    else:
        await redis_client.delete("flag:maintenance_only")
        return {"status": "success", "maintenance": False}
