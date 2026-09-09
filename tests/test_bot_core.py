import os
import sys
import pytest
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

from unittest.mock import AsyncMock, patch

from services.sanitize import sanitize_free_text
from services.access_control import is_number_allowed, normalize_phone
from services.hours import get_hours_info
from services.tools import calculate_bill, save_order_record
from services.agent_runner import execute_tool_call
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


@pytest.mark.anyio
async def test_calculator_math():
    items = [
        {"name": "Full Chicken Sobat", "quantity": 1, "price": 1200.0, "variant": "Thal"},
        {"name": "Mineral Water Large", "quantity": 2, "price": 120.0, "variant": "1.5L"}
    ]
    # Delivery with Thal deposit (1 thal = Rs. 300 deposit)
    # calculate_bill is now async (validates prices against menu cache)
    calc = await calculate_bill(items, order_type="Delivery", thal_count=1)
    assert calc["subtotal"] == 1440.0
    assert calc["thal_deposit"] == 300.0
    assert calc["total_bill"] == 1740.0
    assert calc["meets_minimum_delivery"] is True

    # Below minimum delivery check
    small_items = [{"name": "Roti", "quantity": 2, "price": 40.0}]
    calc_small = await calculate_bill(small_items, order_type="Delivery")
    assert calc_small["subtotal"] == 80.0
    assert calc_small["meets_minimum_delivery"] is False  # Min is 300

    # Non-Sobat items must NEVER incur thal deposit even if thal_count > 0 is passed
    karahi_items = [{"name": "Chicken Karahi Half", "quantity": 1, "price": 900.0}]
    calc_karahi = await calculate_bill(karahi_items, order_type="Delivery", thal_count=1)
    assert calc_karahi["thal_deposit"] == 0.0
    assert calc_karahi["total_bill"] == 900.0
    print("[PASS] test_calculator_math passed")


def test_webhook_signature():
    payload = json.dumps({"event": "message", "payload": {"id": "123"}}).encode()
    secret = settings.WAHA_WEBHOOK_SECRET
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    assert verify_signature(payload, sig) is True
    assert verify_signature(payload, "invalid_sig") is False
    print("[PASS] test_webhook_signature passed")


@pytest.mark.anyio
async def test_save_order_record_math_protection():
    # Simulate 3x Chicken Sobat Leg with Thal (1,440 + 300 = 1,740)
    items = [
        {
            "name": "Chicken Sobat (Leg)",
            "quantity": 3,
            "price": 480.0,
            "unit_price": 480.0,
            "line_total": 1440.0,
            "variant": "Leg"
        }
    ]
    session = {
        "phone": "923306874242",
        "name": "Moiz",
        "order_type": "Delivery",
        "address": "Cantt DI Khan",
        "items": items,
        "subtotal": 1440.0,
        "thal_deposit": 300.0,
        "total_bill": 1740.0,
        "confirm_key": "TEST-KEY-1"
    }

    with patch("services.db.db.save_order", new_callable=AsyncMock) as mock_save, \
         patch("services.db.db.upsert_customer_profile", new_callable=AsyncMock) as mock_profile:
        mock_save.return_value = {"order_id": "PACE-1001", "duplicate": False}

        # Simulate LLM erroneously passing total_bill=4320 and price=1440
        hallucinated_items = [{"name": "Chicken Sobat (Leg)", "quantity": 3, "price": 1440.0}]
        res = await save_order_record(
            session=session,
            items=hallucinated_items,
            total_bill=4320.0
        )

        assert res["total_bill"] == 1740.0
        assert res["order_payload"]["subtotal"] == 1440.0
        assert res["order_payload"]["thal_deposit"] == 300.0
        assert res["order_payload"]["total_bill"] == 1740.0
        assert "Rs. 1,440" in res["summary"]
        assert "4,320" not in res["summary"]
        assert "Thal Deposit" in res["summary"]


@pytest.mark.anyio
async def test_execute_tool_call_save_and_notify_protection():
    session = {
        "phone": "923306874242",
        "name": "Moiz",
        "order_type": "Delivery",
        "address": "Cantt DI Khan",
        "items": [
            {
                "name": "Chicken Sobat (Leg)",
                "quantity": 3,
                "price": 480.0,
                "unit_price": 480.0,
                "line_total": 1440.0,
                "variant": "Leg"
            }
        ],
        "subtotal": 1440.0,
        "thal_deposit": 300.0,
        "total_bill": 1740.0,
        "confirm_key": "TEST-KEY-2"
    }

    with patch("services.db.db.save_order", new_callable=AsyncMock) as mock_save, \
         patch("services.db.db.upsert_customer_profile", new_callable=AsyncMock):
        mock_save.return_value = {"order_id": "PACE-1002", "duplicate": False}

        # 1. execute_tool_call for save_order with hallucinated 4320
        save_res, order_rec = await execute_tool_call(
            tool_name="save_order",
            tool_args={"customer_name": "Moiz", "order_type": "Delivery", "total_bill": 4320.0},
            session=session,
            phone="923306874242",
            dispatch_mode="simulator"
        )
        assert save_res["total_bill"] == 1740.0
        assert order_rec["total_bill"] == 1740.0

        # 2. execute_tool_call for notify_admins_and_kitchen with hallucinated 4320
        notify_res, _ = await execute_tool_call(
            tool_name="notify_admins_and_kitchen",
            tool_args={"order_id": "PACE-1002", "total_bill": 4320.0},
            session=session,
            phone="923306874242",
            dispatch_mode="simulator",
            latest_order_record=order_rec
        )
        assert notify_res["total_bill"] == 1740.0
        assert "1,740" in notify_res["message"]


if __name__ == "__main__":
    print("Running Pace Restaurant WhatsApp Bot Unit Tests...")
    test_sanitize()
    test_access_control()
    test_hours_routing()
    test_calculator_math()
    test_webhook_signature()
    print("\nALL UNIT TESTS PASSED SUCCESSFULLY!")

