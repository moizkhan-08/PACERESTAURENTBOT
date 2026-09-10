import os
import sys
import pytest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.agent_runner import AGENT_TOOLS, execute_tool_call
from services.tools import report_complaint
from services.prompts import SYSTEM_BASE_INSTRUCTIONS, CLOSED_SYSTEM_PROMPT


def test_agent_tools_schema():
    tool_names = [t["function"]["name"] for t in AGENT_TOOLS]
    assert "report_complaint" in tool_names
    assert "read_menu" in tool_names
    assert "calculate_bill" in tool_names
    assert "send_menu_images" in tool_names
    # Buttons have been removed
    assert "send_order_type_buttons" not in tool_names
    assert "send_confirm_buttons" not in tool_names
    assert "send_thal_choice_buttons" not in tool_names

    for tool in AGENT_TOOLS:
        fn = tool["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        assert fn["parameters"]["type"] == "object"


@pytest.mark.anyio
async def test_report_complaint():
    with patch("services.tools.call_with_retry", new_callable=AsyncMock) as mock_retry:
        res = await report_complaint(
            phone="923001234567",
            complaint_text="Sobat mein namak zyada tha",
            customer_name="Ali"
        )
        assert res["status"] == "complaint_reported"


@pytest.mark.anyio
async def test_execute_complaint_tool_call_simulated():
    session = {"phone": "923001234567", "name": "Ahmad"}

    res, rec = await execute_tool_call(
        tool_name="report_complaint",
        tool_args={"complaint_text": "Delivery late thi", "customer_name": "Ahmad"},
        session=session,
        phone="923001234567",
        dispatch_mode="simulator"
    )
    assert res["status"] == "simulated_complaint"


def test_prompts_instruction():
    assert "report_complaint" in SYSTEM_BASE_INSTRUCTIONS
    # Verify no button tool references remain in prompt
    assert "send_order_type_buttons" not in SYSTEM_BASE_INSTRUCTIONS
    assert "send_confirm_buttons" not in SYSTEM_BASE_INSTRUCTIONS
    assert "send_thal_choice_buttons" not in SYSTEM_BASE_INSTRUCTIONS
    # Verify rule strictly forbidding buttons
    assert "STRICTLY NO BUTTONS IN WHATSAPP CHAT" in SYSTEM_BASE_INSTRUCTIONS


def test_whatsapp_service_has_no_buttons():
    from services.whatsapp import whatsapp
    assert not hasattr(whatsapp, "send_buttons")
    assert not hasattr(whatsapp, "send_list")


def test_no_advance_orders_rules():
    assert "NO ADVANCE ORDERS" in SYSTEM_BASE_INSTRUCTIONS
    assert "advance delivery ya advance takeaway orders KABHI nahi lete" in SYSTEM_BASE_INSTRUCTIONS
    assert "STRICT NO ADVANCE ORDERS" in CLOSED_SYSTEM_PROMPT
    assert "Kya aap subah ke liye advance" not in CLOSED_SYSTEM_PROMPT
    calc_tool = next(t for t in AGENT_TOOLS if t["function"]["name"] == "calculate_bill")
    assert "DO NOT call for advance delivery or advance takeaway orders" in calc_tool["function"]["description"]
    save_tool = next(t for t in AGENT_TOOLS if t["function"]["name"] == "save_order")
    assert "DO NOT call for advance delivery or advance takeaway orders" in save_tool["function"]["description"]


def test_decompose_sobat_items():
    from services.tools import decompose_sobat_items

    # 1. "2 nafr sobat and one piece" -> 1x Chicken Sobat + 1x Simple Sobat
    items_1 = [{"name": "2 nafr sobat and one piece", "quantity": 1}]
    dec_1 = decompose_sobat_items(items_1)
    assert len(dec_1) == 2
    assert dec_1[0]["name"] == "Chicken Sobat"
    assert dec_1[0]["quantity"] == 1
    assert dec_1[1]["name"] == "Simple Sobat"
    assert dec_1[1]["quantity"] == 1

    # 2. "3 nafri sobat 2 piece" -> 2x Chicken Sobat + 1x Simple Sobat
    items_2 = [{"name": "3 nafri sobat 2 piece", "quantity": 1}]
    dec_2 = decompose_sobat_items(items_2)
    assert len(dec_2) == 2
    assert dec_2[0]["name"] == "Chicken Sobat"
    assert dec_2[0]["quantity"] == 2
    assert dec_2[1]["name"] == "Simple Sobat"
    assert dec_2[1]["quantity"] == 1

    # 3. "2 nafri sobat ek leg ek chest" -> 1x Leg + 1x Chest
    items_3 = [{"name": "2 nafri sobat ek leg ek chest", "quantity": 1}]
    dec_3 = decompose_sobat_items(items_3)
    assert len(dec_3) == 2
    assert dec_3[0]["variant"] == "Leg"
    assert dec_3[1]["variant"] == "Chest"

    # 4. Standard non-sobat item should remain unchanged
    items_4 = [{"name": "Chicken Karahi Half", "quantity": 1}]
    dec_4 = decompose_sobat_items(items_4)
    assert dec_4 == items_4


@pytest.mark.anyio
async def test_calculate_bill_decomposes_sobat():
    from services.tools import calculate_bill
    calc = await calculate_bill([{"name": "2 nafr sobat and one piece", "quantity": 1}], order_type="Takeaway")
    assert len(calc["items"]) == 2
    names = [it["name"] for it in calc["items"]]
    assert any("Chicken Sobat" in n for n in names)
    assert any("Simple Sobat" in n for n in names)
    assert calc["total_bill"] == calc["items"][0]["line_total"] + calc["items"][1]["line_total"]


@pytest.mark.anyio
async def test_notify_takeaway_order():
    from services.tools import notify_admins_and_kitchen
    order_data = {
        "customer_name": "Tariq",
        "phone_number": "923001234567",
        "order_type": "Takeaway",
        "pickup_time": "20 min",
        "order_items": "- 1x Chicken Sobat (Leg) : Rs. 520\n- 1x Simple Sobat : Rs. 320",
        "total_bill": 840.0,
        "notes": "Jaldi chahiye"
    }
    with patch("services.tools.call_with_retry", new_callable=AsyncMock) as mock_retry:
        res = await notify_admins_and_kitchen("PACE-9999", order_data)
        assert res["status"] == "dispatched"
        assert "kitchen" in res["recipients"]
        assert "admin_1" in res["recipients"]
        assert "admin_group" in res["recipients"]



