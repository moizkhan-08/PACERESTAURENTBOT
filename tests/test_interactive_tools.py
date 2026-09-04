import os
import sys
import pytest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.agent_runner import AGENT_TOOLS, execute_tool_call
from services.tools import (
    send_order_type_buttons,
    send_confirm_buttons,
    send_thal_choice_buttons
)
from services.prompts import SYSTEM_BASE_INSTRUCTIONS


def test_agent_tools_schema():
    tool_names = [t["function"]["name"] for t in AGENT_TOOLS]
    assert "send_order_type_buttons" in tool_names
    assert "send_confirm_buttons" in tool_names
    assert "send_thal_choice_buttons" in tool_names
    assert "report_complaint" in tool_names

    for tool in AGENT_TOOLS:
        fn = tool["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        assert fn["parameters"]["type"] == "object"


@pytest.mark.anyio
async def test_send_order_type_buttons():
    with patch("services.tools.whatsapp.send_buttons", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "ok"}
        res = await send_order_type_buttons("923001234567")
        assert res["status"] == "buttons_sent"
        assert res["type"] == "order_type"
        mock_send.assert_awaited_once()


@pytest.mark.anyio
async def test_send_confirm_buttons():
    with patch("services.tools.whatsapp.send_buttons", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "ok"}
        res = await send_confirm_buttons("923001234567", "Total: Rs. 1500")
        assert res["status"] == "buttons_sent"
        assert res["type"] == "confirm"
        mock_send.assert_awaited_once()


@pytest.mark.anyio
async def test_send_thal_choice_buttons():
    with patch("services.tools.whatsapp.send_buttons", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": "ok"}
        res = await send_thal_choice_buttons("923001234567")
        assert res["status"] == "buttons_sent"
        assert res["type"] == "thal_choice"
        mock_send.assert_awaited_once()


@pytest.mark.anyio
async def test_execute_tool_call_simulated():
    session = {"phone": "923001234567", "name": "Ahmad"}

    # Test order type buttons in simulator mode
    res1, rec1 = await execute_tool_call(
        tool_name="send_order_type_buttons",
        tool_args={},
        session=session,
        phone="923001234567",
        dispatch_mode="simulator"
    )
    assert res1["status"] == "simulated_buttons"
    assert res1["type"] == "order_type"

    # Test confirm buttons in simulator mode
    res2, rec2 = await execute_tool_call(
        tool_name="send_confirm_buttons",
        tool_args={"order_summary": "1x Chicken Karahi - Rs. 1200"},
        session=session,
        phone="923001234567",
        dispatch_mode="simulator"
    )
    assert res2["status"] == "simulated_buttons"
    assert res2["type"] == "confirm"

    # Test thal choice buttons in simulator mode
    res3, rec3 = await execute_tool_call(
        tool_name="send_thal_choice_buttons",
        tool_args={},
        session=session,
        phone="923001234567",
        dispatch_mode="simulator"
    )
    assert res3["status"] == "simulated_buttons"
    assert res3["type"] == "thal_choice"


def test_prompts_instruction():
    assert "send_order_type_buttons" in SYSTEM_BASE_INSTRUCTIONS
    assert "send_confirm_buttons" in SYSTEM_BASE_INSTRUCTIONS
    assert "send_thal_choice_buttons" in SYSTEM_BASE_INSTRUCTIONS
    assert "report_complaint" in SYSTEM_BASE_INSTRUCTIONS
