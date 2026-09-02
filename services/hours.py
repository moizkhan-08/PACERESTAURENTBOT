from __future__ import annotations
from datetime import datetime, time
try:
    from zoneinfo import ZoneInfo
    PKT = ZoneInfo("Asia/Karachi")
except ImportError:
    import pytz
    PKT = pytz.timezone("Asia/Karachi")



def get_current_pkt_time() -> datetime:
    """Returns current datetime in Pakistan Standard Time (PKT)."""
    return datetime.now(PKT)


def get_hours_info(dt: datetime | None = None) -> dict:
    """
    Evaluates current Pace Restaurant operational shift based on PKT:
    - 11:00 AM – 3:30 PM: Full Menu (Open)
    - 3:30 PM – 6:30 PM: Sobat Only (Break time / afternoon special)
    - 6:30 PM – 11:30 PM: Full Menu (Open)
    - 11:30 PM – 11:00 AM: Closed
    """
    if dt is None:
        dt = get_current_pkt_time()
    elif dt.tzinfo is None:
        # ZoneInfo uses replace(); pytz uses localize() — handle both
        try:
            dt = dt.replace(tzinfo=PKT)
        except Exception:
            dt = PKT.localize(dt)
    else:
        dt = dt.astimezone(PKT)

    current_time = dt.time()

    # Define shift boundaries
    open_morning = time(11, 0)
    break_start = time(15, 30)
    break_end = time(18, 30)
    close_night = time(23, 30)

    # Shift logic:
    # 1. Closed: before 11:00 or after 23:30
    if current_time < open_morning or current_time >= close_night:
        return {
            "is_open": False,
            "is_break_time": False,
            "agent_type": "closed",
            "message": "Restaurant band hai. Opening time: 11:00 AM",
            "current_time_pkt": dt.strftime("%I:%M %p")
        }

    # 2. Break shift (Sobat Only): 15:30 to 18:30
    if break_start <= current_time < break_end:
        return {
            "is_open": True,
            "is_break_time": True,
            "agent_type": "sobat_only",
            "message": "Is waqt sirf Dera Ismail Khan ki mashhoor Sobat / Paenda dastiyab hai.",
            "current_time_pkt": dt.strftime("%I:%M %p")
        }

    # 3. Full Menu: 11:00–15:30 & 18:30–23:30
    return {
        "is_open": True,
        "is_break_time": False,
        "agent_type": "full_menu",
        "message": "Mukammal menu dastiyab hai.",
        "current_time_pkt": dt.strftime("%I:%M %p")
    }
