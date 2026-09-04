import os
import sys
import pytest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.agent_runner import AGENT_TOOLS, execute_tool_call
from services.tools import report_complaint
from services.prompts import SYSTEM_BASE_INSTRUCTIONS


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
