import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import hmac
import hashlib
import json
from datetime import datetime, time
try:
    from zoneinfo import ZoneInfo
    PKT = ZoneInfo("Asia/Karachi")
except ImportError:
    import pytz
    PKT = pytz.timezone("Asia/Karachi")

from config import settings

from services.sanitize import sanitize_free_text
from services.access_control import is_number_allowed, normalize_phone
from services.hours import get_hours_info
from services.tools import calculate_bill
from routers.webhook import verify_signature



def test_sanitize():
    raw = "Hello\u200bWorld```drop table```"
    cleaned = sanitize_free_text(raw)
    assert "\u200b" not in cleaned
    assert "```" not in cleaned
    assert "drop table" in cleaned
    print("[PASS] test_sanitize passed")


def test_access_control():
    # When ALLOWED_NUMBERS_ONLY is False
    settings.ALLOWED_NUMBERS_ONLY = False
    assert is_number_allowed("923001234567@s.whatsapp.net") is True

    # When ALLOWED_NUMBERS_ONLY is True
    settings.ALLOWED_NUMBERS_ONLY = True
    settings.ALLOWED_NUMBERS = "923306874242, 923379221111"
    assert is_number_allowed("923306874242@s.whatsapp.net") is True
    assert is_number_allowed("923379221111@s.whatsapp.net") is True
    assert is_number_allowed("923009999999@s.whatsapp.net") is False
    settings.ALLOWED_NUMBERS_ONLY = False  # Reset
    print("[PASS] test_access_control passed")


def test_hours_routing():
    # 1. Lunch Full Menu: 13:00 PKT
    dt_lunch = datetime(2026, 9, 2, 13, 0, tzinfo=PKT)
    info = get_hours_info(dt_lunch)
    assert info["is_open"] is True
    assert info["is_break_time"] is False
    assert info["agent_type"] == "full_menu"

    # 2. Sobat Shift: 16:30 PKT
    dt_sobat = datetime(2026, 9, 2, 16, 30, tzinfo=PKT)
    info = get_hours_info(dt_sobat)
    assert info["is_open"] is True
    assert info["is_break_time"] is True
    assert info["agent_type"] == "sobat_only"

    # 3. Dinner Full Menu: 20:00 PKT
    dt_dinner = datetime(2026, 9, 2, 20, 0, tzinfo=PKT)
    info = get_hours_info(dt_dinner)
    assert info["is_open"] is True
    assert info["is_break_time"] is False
    assert info["agent_type"] == "full_menu"

    # 4. Closed: 02:00 PKT
    dt_night = datetime(2026, 9, 2, 2, 0, tzinfo=PKT)
    info = get_hours_info(dt_night)
    assert info["is_open"] is False
    assert info["agent_type"] == "closed"
    print("[PASS] test_hours_routing passed")


def test_calculator_math():
    items = [
        {"name": "Full Chicken Sobat", "quantity": 1, "price": 1200.0, "variant": "Thal"},
        {"name": "Mineral Water Large", "quantity": 2, "price": 120.0, "variant": "1.5L"}
    ]
    # Delivery with Thal deposit (1 thal = Rs. 200 deposit)
    calc = calculate_bill(items, order_type="Delivery", thal_count=1)
    assert calc["subtotal"] == 1440.0
    assert calc["thal_deposit"] == 200.0
    assert calc["total_bill"] == 1640.0
    assert calc["meets_minimum_delivery"] is True

    # Below minimum delivery check
    small_items = [{"name": "Roti", "quantity": 2, "price": 40.0}]
    calc_small = calculate_bill(small_items, order_type="Delivery")
    assert calc_small["subtotal"] == 80.0
    assert calc_small["meets_minimum_delivery"] is False  # Min is 300
    print("[PASS] test_calculator_math passed")


def test_webhook_signature():
    payload = json.dumps({"event": "message", "payload": {"id": "123"}}).encode()
    secret = settings.WAHA_WEBHOOK_SECRET
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_signature(payload, sig) is True
    assert verify_signature(payload, "invalid_sig") is False
    print("[PASS] test_webhook_signature passed")


if __name__ == "__main__":
    print("Running Pace Restaurant WhatsApp Bot Unit Tests...")
    test_sanitize()
    test_access_control()
    test_hours_routing()
    test_calculator_math()
    test_webhook_signature()
    print("\nALL UNIT TESTS PASSED SUCCESSFULLY!")

