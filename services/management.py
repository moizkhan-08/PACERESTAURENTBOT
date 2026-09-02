import logging
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
try:
    from zoneinfo import ZoneInfo
    PKT = ZoneInfo("Asia/Karachi")
except ImportError:
    import pytz
    PKT = pytz.timezone("Asia/Karachi")


from config import settings
from services.locks import distributed_lock
from services.db import db
from services.whatsapp import whatsapp
from services.tools import call_with_retry

logger = logging.getLogger("management")

scheduler = AsyncIOScheduler(timezone=PKT)


async def expire_stale_orders():
    """
    Checks for pending order drafts older than ORDER_CONFIRM_TIMEOUT_MIN.
    Runs under a distributed lock so multiple replicas don't send duplicate timeouts.
    """
    async with distributed_lock("expire_stale_orders", ttl=90) as acquired:
        if not acquired:
            return

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.ORDER_CONFIRM_TIMEOUT_MIN)
        cutoff_iso = cutoff.isoformat()

        try:
            stale_orders = await db.get_stale_pending_orders(cutoff_iso)
            for row in stale_orders:
                order_id = row.get("order_id")
                phone = row.get("phone_number")
                if not order_id or not phone:
                    continue

                await db.update_order_status(order_id, "Expired")
                logger.info("Marked order %s as Expired due to timeout.", order_id)

                await call_with_retry(
                    whatsapp.send_text,
                    phone,
                    "Aapka order draft timeout ho gaya hai. Dobara order karne ke liye kuch bhi likh dein 😊",
                    kind="expire_notice",
                    payload={"order_id": order_id, "phone": phone}
                )
        except Exception as e:
            logger.error("Error during expire_stale_orders: %s", e)


async def send_nightly_report():
    """
    Sends nightly business summary report to Admin WhatsApp & Admin Group.
    Runs under a distributed lock at 23:35 PKT.
    """
    async with distributed_lock("nightly_report", ttl=300) as acquired:
        if not acquired:
            return

        now_pkt = datetime.now(PKT)
        start_of_day_pkt = now_pkt.replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_day_utc = start_of_day_pkt.astimezone(timezone.utc).isoformat()

        try:
            today_orders = await db.get_daily_orders(start_of_day_utc)
            total_orders = len(today_orders)
            total_revenue = sum(float(o.get("total_bill", 0)) for o in today_orders)
            delivery_count = sum(1 for o in today_orders if o.get("order_type") == "Delivery")
            takeaway_count = total_orders - delivery_count

            report = (
                f"📊 *Pace Restaurant — Daily Business Report*\n"
                f"📅 Date: {now_pkt.strftime('%d-%b-%Y')}\n"
                f"────────────────────\n"
                f"📦 Total Confirmed Orders: {total_orders}\n"
                f"💰 Total Revenue: Rs. {total_revenue:,.0f}\n"
                f"🛵 Delivery Orders: {delivery_count}\n"
                f"🛍️ Takeaway Orders: {takeaway_count}\n"
                f"────────────────────\n"
                f"Report generated automatically."
            )

            if settings.ADMIN_WHATSAPP:
                await call_with_retry(
                    whatsapp.send_text,
                    settings.ADMIN_WHATSAPP,
                    report,
                    kind="nightly_report_admin",
                    payload={"date": now_pkt.strftime('%Y-%m-%d')}
                )

            if settings.ADMIN_GROUP_JID:
                await call_with_retry(
                    whatsapp.send_text,
                    settings.ADMIN_GROUP_JID,
                    report,
                    kind="nightly_report_group",
                    payload={"date": now_pkt.strftime('%Y-%m-%d')}
                )

            logger.info("Nightly report sent successfully: %d orders, Rs %f", total_orders, total_revenue)
        except Exception as e:
            logger.error("Error generating nightly report: %s", e)


def start_scheduler():
    """Initializes APScheduler background jobs."""
    # Run every 2 minutes to check stale drafts
    scheduler.add_job(
        expire_stale_orders,
        trigger=IntervalTrigger(minutes=2),
        id="expire_stale_orders",
        replace_existing=True
    )

    # Run every night at 23:35 PKT (after restaurant closes at 23:30)
    scheduler.add_job(
        send_nightly_report,
        trigger=CronTrigger(hour=23, minute=35, timezone=PKT),
        id="nightly_report",
        replace_existing=True
    )

    scheduler.start()
    logger.info("APScheduler started with PKT timezone jobs.")
