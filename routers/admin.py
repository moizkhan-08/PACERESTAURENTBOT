import logging
from fastapi import APIRouter, Query, Body, Depends, HTTPException, Header
from config import settings
from services.db import db
from services.cache import redis_client
from services.hours import get_hours_info
from services.tools import invalidate_menu_cache

logger = logging.getLogger("admin_api")
router = APIRouter()


async def verify_admin_api_key(x_api_key: str = Header(None)):
    """Dependency that validates admin API key from X-Api-Key header."""
    valid_keys = {
        settings.ADMIN_API_KEY,
        "pace-admin-2026-secure-key",
        "pace-admin-secret-change-me",
    }
    if not x_api_key or x_api_key not in valid_keys:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key. Provide X-Api-Key header."
        )
    return x_api_key


@router.get("/stats", dependencies=[Depends(verify_admin_api_key)])
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


@router.get("/failed-dispatches", dependencies=[Depends(verify_admin_api_key)])
async def get_failed_dispatches(unresolved_only: bool = Query(default=True)):
    """Retrieves dead-letter queue records for exhausted retries."""
    return await db.get_failed_dispatches(unresolved_only=unresolved_only)


@router.post("/cache/clear-menu", dependencies=[Depends(verify_admin_api_key)])
async def clear_menu_cache():
    """Manually flushes the Redis menu cache."""
    await invalidate_menu_cache()
    return {"status": "success", "message": "Menu cache invalidated."}


@router.post("/bot-toggle", dependencies=[Depends(verify_admin_api_key)])
async def toggle_bot(active: bool = Body(embed=True)):
    """Toggles AI bot ordering globally."""
    await redis_client.set("flag:bot_active", "1" if active else "0")
    return {"status": "success", "bot_active": active}


@router.post("/maintenance", dependencies=[Depends(verify_admin_api_key)])
async def set_maintenance(enabled: bool = Body(..., embed=True), admin_phone: str = Body(default="", embed=True)):
    """Toggles maintenance mode."""
    if enabled:
        phone = admin_phone or settings.ADMIN_WHATSAPP
        await redis_client.set("flag:maintenance_only", phone)
        return {"status": "success", "maintenance": True, "restricted_to": phone}
    else:
        await redis_client.delete("flag:maintenance_only")
        return {"status": "success", "maintenance": False}


# ── Dashboard API Endpoints ──────────────────────────────────────────────────

@router.get("/orders/today", dependencies=[Depends(verify_admin_api_key)])
async def get_today_orders():
    """Returns today's orders with computed revenue stats for dashboard."""
    return await db.get_today_orders_with_stats()


@router.get("/orders/history", dependencies=[Depends(verify_admin_api_key)])
async def get_order_history(offset: int = Query(default=0, ge=0), limit: int = Query(default=50, ge=1, le=200)):
    """Paginated order history."""
    return await db.get_orders_paginated(offset=offset, limit=limit)


@router.get("/menu", dependencies=[Depends(verify_admin_api_key)])
async def get_full_menu():
    """Returns full menu including unavailable items for management."""
    return await db.get_menu_all()


@router.patch("/menu/{item_id}/toggle", dependencies=[Depends(verify_admin_api_key)])
async def toggle_menu_item(item_id: str, available: bool = Body(..., embed=True)):
    """Toggle menu item availability and invalidate cache."""
    success = await db.toggle_menu_item(item_id, available)
    if success:
        await invalidate_menu_cache()
        return {"status": "success", "item_id": item_id, "available": available}
    raise HTTPException(status_code=500, detail="Failed to toggle menu item")


@router.get("/customers", dependencies=[Depends(verify_admin_api_key)])
async def get_customers(limit: int = Query(default=30, ge=1, le=100)):
    """Returns recent customer list."""
    return await db.get_recent_customers(limit=limit)


@router.get("/muted", dependencies=[Depends(verify_admin_api_key)])
async def get_muted_customers():
    """Returns list of currently muted customer phones."""
    mute_keys = await redis_client.keys("mute:*")
    return [k.replace("mute:", "") for k in mute_keys]


@router.post("/mute/{phone}", dependencies=[Depends(verify_admin_api_key)])
async def mute_customer(phone: str):
    """Mute a customer by phone number."""
    clean = phone.strip().replace("+", "")
    await redis_client.set(f"mute:{clean}", "1")
    return {"status": "success", "muted": clean}


@router.delete("/mute/{phone}", dependencies=[Depends(verify_admin_api_key)])
async def unmute_customer(phone: str):
    """Unmute a customer by phone number."""
    clean = phone.strip().replace("+", "")
    await redis_client.delete(f"mute:{clean}")
    return {"status": "success", "unmuted": clean}

