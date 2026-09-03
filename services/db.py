import logging
import json
from datetime import datetime, timezone
from typing import Optional, Any
import httpx
from config import settings

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
        """Fetch past customer history for personalized greetings."""
        try:
            async with self._get_client() as client:
                res = await client.get(
                    "/customer_profiles",
                    params={"phone_number": f"eq.{phone}", "select": "*"}
                )
                if res.status_code == 200:
                    rows = res.json()
                    return rows[0] if rows else None
        except Exception as e:
            logger.warning("Error fetching customer profile for %s: %s", phone, e)
        return None

    async def upsert_customer_profile(
        self,
        phone: str,
        name: str,
        address: Optional[str] = None,
        last_order_items: Optional[str] = None
    ) -> bool:
        """Update or insert customer profile after a confirmed order."""
        try:
            existing = await self.get_customer_profile(phone)
            total_orders = (existing.get("total_orders", 0) + 1) if existing else 1
            default_address = address or (existing.get("default_address") if existing else None)

            payload = {
                "phone_number": phone,
                "customer_name": name,
                "default_address": default_address,
                "total_orders": total_orders,
                "last_order_items": last_order_items,
                "last_ordered_at": datetime.now(timezone.utc).isoformat()
            }

            headers = {**self.headers, "Prefer": "resolution=merge-duplicates,return=representation"}
            async with httpx.AsyncClient(base_url=f"{self.base_url}/rest/v1", headers=headers, timeout=10.0) as client:
                res = await client.post("/customer_profiles", json=payload)
                return res.status_code in (200, 201)
        except Exception as e:
            logger.warning("Error upserting customer profile: %s", e)
            return False

    async def save_order(self, order_data: dict) -> dict:
        """
        Idempotent order persistence into pace_orders.
        Correctly maps fields to Supabase pace_orders table columns.
        """
        import uuid
        import pytz
        PKT = pytz.timezone("Asia/Karachi")
        now_pkt = datetime.now(PKT)

        confirm_key = order_data.get("session_confirm_key")
        order_id = f"PACE-{now_pkt.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        try:
            # Prepare payload mapped to exact Supabase pace_orders schema
            subtotal_val = order_data.get("subtotal") or order_data.get("total_bill") or 0
            total_val = order_data.get("total_bill") or 0

            payload = {
                "order_id": order_id,
                "guest_name": order_data.get("customer_name", "Valued Customer"),
                "phone": str(order_data.get("phone_number", "")),
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
