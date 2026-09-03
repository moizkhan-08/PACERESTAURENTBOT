import logging
import json
import asyncio
from datetime import datetime, timezone
from typing import Optional, Any
import httpx
from config import settings
from services.cache import redis_client

logger = logging.getLogger("db")


class SupabaseDB:
    def __init__(self):
        self.base_url = settings.SUPABASE_URL.rstrip("/")
        # Use service key if provided, else fallback to anon key
        self.api_key = settings.SUPABASE_SERVICE_KEY or settings.SUPABASE_KEY
        self.headers = {
            "apikey": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

    def _get_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{self.base_url}/rest/v1",
            headers=self.headers,
            timeout=10.0
        )

    async def get_menu(self, available_only: bool = True) -> list[dict]:
        """Fetch all menu items from MenuPace table, correctly mapping Supabase columns."""
        try:
            params = {}
            if available_only:
                params["Itemavaiablility"] = "eq.true"
            params["select"] = "*"
            
            async with self._get_client() as client:
                res = await client.get(f"/{settings.SUPABASE_MENU_TABLE}", params=params)
                if res.status_code == 200:
                    raw_items = res.json()
                    normalized = []
                    for it in raw_items:
                        name = it.get("Item Name") or it.get("name") or "Unknown"
                        category = it.get("category") or "General"
                        price_raw = it.get("Price (Rs.)") or it.get("price") or 0
                        variant = it.get("Price 2 / Per KG") or it.get("variant")
                        is_avail = it.get("Itemavaiablility", True) if "Itemavaiablility" in it else it.get("available", True)

                        try:
                            price_val = float(str(price_raw).replace(",", "").strip())
                        except Exception:
                            price_val = 0.0

                        normalized.append({
                            "name": name,
                            "category": category,
                            "price": price_val,
                            "variant": variant if variant and variant != "—" else None,
                            "available": bool(is_avail)
                        })
                    return normalized
                logger.error("Failed to fetch menu: %d %s", res.status_code, res.text)
        except Exception as e:
            logger.exception("Error querying Menu table: %s", e)
        return []

    async def get_customer_profile(self, phone: str) -> Optional[dict]:
        """Fetch past customer history from Supabase customers table for personalized greetings."""
        try:
            clean_phone = phone.replace("+", "").strip()
            local_phone = "0" + clean_phone[2:] if clean_phone.startswith("92") else clean_phone
            intl_phone = "92" + clean_phone[1:] if clean_phone.startswith("0") else clean_phone

            async with self._get_client() as client:
                res = await client.get(
                    "/customers",
                    params={
                        "or": f"(phone.eq.{clean_phone},phone.eq.{local_phone},phone.eq.{intl_phone})",
                        "select": "*",
                        "limit": "1"
                    }
                )
                if res.status_code == 200:
                    rows = res.json()
                    if rows:
                        c = rows[0]
                        return {
                            "phone": c.get("phone"),
                            "name": c.get("name"),
                            "default_address": c.get("address"),
                            "total_orders": 1,
                            "is_returning": True
                        }
        except Exception as e:
            logger.warning("Error fetching customer profile: %s", e)
        return None

    async def upsert_customer_profile(self, phone: str, name: str, address: str = "", last_items: str = "") -> bool:
        """Upsert returning customer data into Supabase customers table."""
        try:
            import uuid
            existing = await self.get_customer_profile(phone)
            clean_phone = phone.replace("+", "").strip()
            local_phone = "0" + clean_phone[2:] if clean_phone.startswith("92") else clean_phone

            payload = {
                "name": name,
                "phone": local_phone or clean_phone,
                "address": address or ""
            }

            async with self._get_client() as client:
                if existing and existing.get("phone"):
                    res = await client.patch(
                        "/customers",
                        params={"phone": f"eq.{existing['phone']}"},
                        json=payload
                    )
                else:
                    payload["id"] = f"c_{uuid.uuid4().hex[:10]}"
                    res = await client.post("/customers", json=payload)
                return res.status_code in (200, 201, 204)
        except Exception as e:
            logger.warning("Error upserting customer profile: %s", e)
            return False

    async def save_order(self, order_data: dict) -> dict:
        """
        Idempotent order persistence into pace_orders.
        Uses Redis lock for immediate duplicate prevention,
        and saves mapped fields to the live Supabase pace_orders table.
        """
        import uuid
        import pytz
        PKT = pytz.timezone("Asia/Karachi")
        now_pkt = datetime.now(PKT)

        confirm_key = order_data.get("session_confirm_key")
        lock_key = f"order_idempotency:{confirm_key}" if confirm_key else None

        # 1. Idempotency Check via Redis
        if lock_key:
            try:
                existing_order_json = await redis_client.get(lock_key)
                if existing_order_json:
                    cached = json.loads(existing_order_json)
                    logger.info("Duplicate order prevented for confirm_key %s: %s", confirm_key, cached.get("order_id"))
                    return {"order_id": cached.get("order_id"), "duplicate": True, "data": cached.get("data", order_data)}
            except Exception as lock_err:
                logger.debug("Idempotency cache check notice: %s", lock_err)

        order_id = f"PACE-{now_pkt.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        try:
            subtotal_val = order_data.get("subtotal") or order_data.get("total_bill") or 0
            total_val = order_data.get("total_bill") or 0
            phone_raw = str(order_data.get("phone_number", ""))
            clean_phone = phone_raw.replace("+", "").strip()

            payload = {
                "order_id": order_id,
                "guest_name": order_data.get("customer_name", "Valued Customer"),
                "phone": clean_phone,
                "order_type": order_data.get("order_type", "Delivery"),
                "delivery": order_data.get("delivery_address") or "",
                "dine_pickup_time": order_data.get("pickup_time") or "",
                "items": str(order_data.get("order_items", "")),
                "special_instructions": str(order_data.get("notes") or ""),
                "subtotal": str(int(float(subtotal_val))),
                "delivery_charges": "Delivery charges apply" if order_data.get("order_type") == "Delivery" else "N/A",
                "total_amount": str(float(total_val)),
                "status": "Confirmed",
                "order_date": now_pkt.strftime("%d/%m/%Y"),
                "order_time": now_pkt.strftime("%I:%M %p")
            }

            async with self._get_client() as client:
                res = await client.post(f"/{settings.SUPABASE_TABLE}", json=payload)
                if res.status_code in (200, 201):
                    rows = res.json()
                    created = rows[0] if rows else payload
                    
                    # Store idempotency lock in Redis for 15 minutes
                    if lock_key:
                        try:
                            await redis_client.set(lock_key, json.dumps({"order_id": order_id, "data": created}), ex=900)
                        except Exception:
                            pass

                    # Asynchronously save customer profile to customers table
                    try:
                        customer_name = order_data.get("customer_name")
                        address = order_data.get("delivery_address", "")
                        if customer_name and clean_phone:
                            asyncio.create_task(self.upsert_customer_profile(clean_phone, customer_name, address))
                    except Exception as prof_err:
                        logger.warning("Could not trigger customer profile upsert: %s", prof_err)

                    return {"order_id": order_id, "duplicate": False, "data": created}
                
                logger.error("Failed to insert order: %d %s", res.status_code, res.text)
        except Exception as e:
            logger.exception("Exception inserting order: %s", e)

        return {"order_id": order_id, "duplicate": False, "data": order_data}

    async def get_order_by_confirm_key(self, confirm_key: str) -> Optional[dict]:
        """Find order by session confirm key."""
        try:
            async with self._get_client() as client:
                res = await client.get(
                    f"/{settings.SUPABASE_TABLE}",
                    params={"session_confirm_key": f"eq.{confirm_key}", "select": "*"}
                )
                if res.status_code == 200:
                    rows = res.json()
                    return rows[0] if rows else None
        except Exception as e:
            logger.warning("Error fetching order by confirm_key: %s", e)
        return None

    async def get_order_by_id(self, order_id: str) -> Optional[dict]:
        """Find order by primary order_id."""
        try:
            async with self._get_client() as client:
                res = await client.get(
                    f"/{settings.SUPABASE_TABLE}",
                    params={"order_id": f"eq.{order_id}", "select": "*"}
                )
                if res.status_code == 200:
                    rows = res.json()
                    return rows[0] if rows else None
        except Exception as e:
            logger.warning("Error fetching order by order_id: %s", e)
        return None

    async def update_order_status(self, order_id: str, status: str) -> bool:
        """Update order status ('Confirmed', 'Dispatched', 'Cancelled', 'Expired')."""
        try:
            async with self._get_client() as client:
                res = await client.patch(
                    f"/{settings.SUPABASE_TABLE}",
                    params={"order_id": f"eq.{order_id}"},
                    json={"status": status}
                )
                return res.status_code in (200, 204)
        except Exception as e:
            logger.warning("Error updating status for %s: %s", order_id, e)
            return False

    async def get_stale_pending_orders(self, cutoff_iso: str) -> list[dict]:
        """Fetch confirmed orders created before cutoff that haven't been dispatched."""
        try:
            async with self._get_client() as client:
                res = await client.get(
                    f"/{settings.SUPABASE_TABLE}",
                    params={
                        "status": "eq.Confirmed",
                        "created_at": f"lt.{cutoff_iso}",
                        "select": "*"
                    }
                )
                if res.status_code == 200:
                    return res.json()
        except Exception as e:
            logger.warning("Error querying stale orders: %s", e)
        return []

    async def get_daily_orders(self, start_date_iso: str) -> list[dict]:
        """Fetch orders created today for nightly summary."""
        try:
            async with self._get_client() as client:
                res = await client.get(
                    f"/{settings.SUPABASE_TABLE}",
                    params={
                        "created_at": f"gte.{start_date_iso}",
                        "status": "neq.Expired",
                        "select": "*"
                    }
                )
                if res.status_code == 200:
                    return res.json()
        except Exception as e:
            logger.warning("Error querying daily orders: %s", e)
        return []

    async def log_admin_action(self, actor_jid: str, command: str, target: Optional[str] = None):
        """Audit logging of admin in-chat or REST actions."""
        try:
            async with self._get_client() as client:
                await client.post(
                    "/admin_actions",
                    json={"actor_jid": actor_jid, "command": command, "target": target}
                )
        except Exception as e:
            logger.warning("Failed to log admin action: %s", e)

    async def log_failed_dispatch(self, kind: str, payload: dict, error: str, attempts: int):
        """Dead-letter queue logging for exhausted retries."""
        try:
            async with self._get_client() as client:
                await client.post(
                    "/failed_dispatches",
                    json={
                        "kind": kind,
                        "payload": payload,
                        "error": error,
                        "attempts": attempts,
                        "resolved": False
                    }
                )
            logger.info("Logged exhausted failure to failed_dispatches: %s", kind)
        except Exception as e:
            logger.exception("Failed to write to failed_dispatches: %s", e)

    async def get_failed_dispatches(self, unresolved_only: bool = True) -> list[dict]:
        """Fetch dead-letter records for operator dashboard."""
        try:
            params = {"select": "*", "order": "created_at.desc"}
            if unresolved_only:
                params["resolved"] = "eq.false"
            async with self._get_client() as client:
                res = await client.get("/failed_dispatches", params=params)
                if res.status_code == 200:
                    return res.json()
        except Exception as e:
            logger.warning("Error querying failed_dispatches: %s", e)
        return []


db = SupabaseDB()
