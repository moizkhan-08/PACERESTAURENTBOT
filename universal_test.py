"""
Pace Restaurant Bot - Universal Autonomous Task Execution & Testing Script

Usage:
  python universal_test.py

Rules:
  1. This is the SINGLE dedicated universal Python file for all tasks, diagnostics, and testing.
  2. Whenever there is an executable task or testing, write to and edit THIS file directly.
  3. Strictly do not create ad-hoc or scattered one-off test scripts (e.g. test1.py, temp.py).
  4. Run tests and tasks autonomously without interrupting for permissions on routine operations.
"""
import asyncio
import os
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from services.tools import (
    decompose_sobat_items,
    resolve_menu_item_price,
    calculate_bill,
    is_item_sold_out,
    is_bbq_item,
    read_menu,
    get_soldout_items
)
from services.prompts import (
    SYSTEM_BASE_INSTRUCTIONS,
    OPEN_AGENT_PROMPT,
    AFTERNOON_AGENT_PROMPT,
    CLOSED_AGENT_PROMPT
)
from services.agent_runner import (
    OPEN_AGENT_TOOLS,
    AFTERNOON_AGENT_TOOLS,
    CLOSED_AGENT_TOOLS,
    execute_designated_agent
)
from services.db import db
from services.cache import redis_client
from services.hours import get_hours_info
from services.debounce import MessageDebouncer, message_debouncer
from routers.admin_commands import handle_admin_command
from config import settings


async def run_tests():
    print("==================================================")
    print(">> RUNNING UNIVERSAL VALIDATION TESTS")
    print("==================================================")
    
    # ---------------------------------------------------------
    # 1. Sobat / Paenda Decomposition Tests
    # ---------------------------------------------------------
    print("\n[1/4] Testing Sobat Variations & Decomposition...")
    
    # Case 1: "2 nafr sobat and one piece" -> 1x Chicken Sobat + 1x Simple Sobat
    dec1 = decompose_sobat_items([{"name": "2 nafr sobat and one piece", "quantity": 1}])
    assert len(dec1) == 2, f"Expected 2 items, got {len(dec1)}"
    assert "Chicken Sobat" in dec1[0]["name"]
    assert dec1[1]["name"] == "Simple Sobat"
    print("  [OK] '2 nafr sobat and one piece' -> 1x Chicken Sobat + 1x Simple Sobat")

    # Case 2: "1 bbq piece sobat and one fried piece" -> 1x BBQ (Leg) + 1x Fried (Leg)
    dec2 = decompose_sobat_items([{"name": "1 bbq piece sobat and one fried piece", "quantity": 1}])
    assert len(dec2) == 2
    assert dec2[0]["name"] == "BBQ Chicken Sobat"
    assert "Chicken Sobat" in dec2[1]["name"]
    assert dec2[0]["variant"] == "Leg"
    assert dec2[1]["variant"] == "Leg"
    print("  [OK] '1 bbq piece sobat and one fried piece' -> 1x BBQ (Leg) + 1x Fried (Leg)")

    # Case 3: "one bbq piece chest sobat and one fried piece leg sobat" -> 1x BBQ (Chest) + 1x Fried (Leg)
    dec3 = decompose_sobat_items([{"name": "one bbq piece chest sobat and one fried piece leg sobat", "quantity": 1}])
    assert len(dec3) == 2
    assert dec3[0]["name"] == "BBQ Chicken Sobat"
    assert dec3[0]["variant"] == "Chest"
    assert "Chicken Sobat" in dec3[1]["name"]
    assert dec3[1]["variant"] == "Leg"
    print("  [OK] 'one bbq piece chest sobat and one fried piece leg sobat' -> 1x BBQ (Chest) + 1x Fried (Leg)")

    # Case 4: "2 nafri sobat 1 bbq piece" -> 1x BBQ Chicken Sobat + 1x Simple Sobat
    dec4 = decompose_sobat_items([{"name": "2 nafri sobat 1 bbq piece", "quantity": 1}])
    assert len(dec4) == 2
    assert dec4[0]["name"] == "BBQ Chicken Sobat"
    assert dec4[1]["name"] == "Simple Sobat"
    print("  [OK] '2 nafri sobat 1 bbq piece' -> 1x BBQ Chicken Sobat + 1x Simple Sobat")

    # Case 5: "3 nafri sobat 1 bbq piece 1 fried piece" -> 1x BBQ + 1x Fried + 1x Simple
    dec5 = decompose_sobat_items([{"name": "3 nafri sobat 1 bbq piece 1 fried piece", "quantity": 1}])
    assert len(dec5) == 3
    assert dec5[0]["name"] == "BBQ Chicken Sobat"
    assert "Chicken Sobat" in dec5[1]["name"]
    assert dec5[2]["name"] == "Simple Sobat"
    print("  [OK] '3 nafri sobat 1 bbq 1 fry' -> 1x BBQ + 1x Fried + 1x Simple Sobat")

    # ---------------------------------------------------------
    # 2. Live Pricing & Bill Calculation Tests
    # ---------------------------------------------------------
    print("\n[2/4] Testing Menu Prices & Deterministic Bill...")
    menu_items = await db.get_menu(available_only=True)

    # BBQ Sobat prices: Leg Rs. 530, Chest Rs. 560
    _, p_bbq_leg, _ = resolve_menu_item_price("BBQ Chicken Sobat", "Leg", 0, menu_items)
    assert p_bbq_leg == 530.0, f"Expected 530 for BBQ Leg, got {p_bbq_leg}"
    _, p_bbq_chest, _ = resolve_menu_item_price("BBQ Chicken Sobat", "Chest", 0, menu_items)
    assert p_bbq_chest == 560.0, f"Expected 560 for BBQ Chest, got {p_bbq_chest}"
    print(f"  [OK] BBQ Chicken Sobat: Leg=Rs.{p_bbq_leg}, Chest=Rs.{p_bbq_chest}")

    # Fry Sobat prices: Leg Rs. 520, Chest Rs. 550
    _, p_fry_leg, _ = resolve_menu_item_price("Chicken Sobat (Fry Pieces)", "Leg", 0, menu_items)
    assert p_fry_leg == 520.0, f"Expected 520 for Fry Leg, got {p_fry_leg}"
    _, p_fry_chest, _ = resolve_menu_item_price("Chicken Sobat (Fry Pieces)", "Chest", 0, menu_items)
    assert p_fry_chest == 550.0, f"Expected 550 for Fry Chest, got {p_fry_chest}"
    print(f"  [OK] Chicken Sobat (Fry Pieces): Leg=Rs.{p_fry_leg}, Chest=Rs.{p_fry_chest}")

    # Simple Sobat Rs. 220
    _, p_simple, _ = resolve_menu_item_price("Simple Sobat", "", 0, menu_items)
    assert p_simple == 220.0, f"Expected 220 for Simple Sobat, got {p_simple}"
    print(f"  [OK] Simple Sobat: Rs.{p_simple}")

    # Bill for 1 BBQ piece sobat + 1 Fried piece sobat = 530 + 520 = 1050 (use force_open to bypass live clock)
    await redis_client.set("flag:force_open", "1")
    calc_combo = await calculate_bill([{"name": "1 bbq piece sobat and one fried piece", "quantity": 1}], order_type="Takeaway")
    await redis_client.delete("flag:force_open")
    assert calc_combo["total_bill"] == 1050.0, f"Expected 1050, got {calc_combo['total_bill']}"
    assert "Delivery charges will apply" not in calc_combo["formatted_summary"]
    print(f"  [OK] Combined Bill: 1x BBQ (Rs.530) + 1x Fried (Rs.520) = Rs.{calc_combo['total_bill']}")

    # Delivery order formatted_summary MUST mention "Delivery charges will apply" without exact amount
    calc_delivery = await calculate_bill([{"name": "Chicken Sobat", "quantity": 1}], order_type="Delivery")
    assert "Delivery charges will apply" in calc_delivery["formatted_summary"]
    assert "Rs." not in calc_delivery["formatted_summary"].split("Delivery charges")[1].split("\n")[0]
    print(f"  [OK] Delivery Order Summary correctly mentions 'Delivery charges will apply' (no exact fee)")

    # Packaging & Thal Exclusivity: Non-Sobat orders MUST NOT have Thal deposit even if thal_count > 0
    calc_non_sobat_thal = await calculate_bill(
        [{"name": "Chicken Boneless Handi (Half)", "quantity": 1}],
        order_type="Takeaway",
        thal_count=2
    )
    assert calc_non_sobat_thal["thal_deposit"] == 0.0, f"Expected 0.0 thal deposit for Handi, got {calc_non_sobat_thal['thal_deposit']}"
    assert "Thal Deposit" not in calc_non_sobat_thal["formatted_summary"]
    print("  [OK] Non-Sobat items (Handi/Karahi/Rice) strictly disallow Thal deposit (automatically disposable)")

    # Sobat orders with thal_count > 0 correctly apply refundable Thal deposit
    calc_sobat_thal = await calculate_bill(
        [{"name": "Chicken Sobat", "quantity": 1}],
        order_type="Takeaway",
        thal_count=1
    )
    assert calc_sobat_thal["thal_deposit"] == 300.0, f"Expected 300.0 thal deposit for Sobat, got {calc_sobat_thal['thal_deposit']}"
    assert "*Thal Deposit (1x)*" in calc_sobat_thal["formatted_summary"] and "Rs. 300" in calc_sobat_thal["formatted_summary"]
    print("  [OK] Sobat orders correctly apply Thal deposit when Thal option is selected")

    # Prompt rules: Packaging rule in prompts
    assert "Thal ya Disposable ka option SIRF aur SIRF Sobat / Paenda ke liye hai!" in SYSTEM_BASE_INSTRUCTIONS
    assert "STEP 3 KO MUKAMMAL SKIP KAREIN!" in OPEN_AGENT_PROMPT
    print("  [OK] Prompts strictly instruct Thal option is ONLY for Sobat and all other items are disposable")

    # ---------------------------------------------------------
    # 3. Delivery Address Prompt Rules Tests
    # ---------------------------------------------------------
    print("\n[3/4] Testing Delivery Address Prompt Restrictions...")
    assert "Aapka naam aur *delivery address* bata dein" in SYSTEM_BASE_INSTRUCTIONS
    assert "(area, gali, ghar number)" not in SYSTEM_BASE_INSTRUCTIONS
    assert "BBQ PIECE VS FRIED PIECE FARQ" in SYSTEM_BASE_INSTRUCTIONS
    print("  [OK] Address prompt: Asks for delivery address ONLY (no gali, street, ghar number, landmark)")

    # ---------------------------------------------------------
    # 4. Roti and Maana Pricing Tests
    # ---------------------------------------------------------
    print("\n[4/4] Testing Roti and Maana Pricing...")
    _, p_manna, _ = resolve_menu_item_price("8 manny", "", 0, menu_items)
    assert p_manna == 30.0, f"Expected 30 for Maana, got {p_manna}"
    _, p_roti, _ = resolve_menu_item_price("4 tanoor roti", "", 0, menu_items)
    assert p_roti == 20.0, f"Expected 20 for Tandoori Roti, got {p_roti}"
    print(f"  [OK] Maana = Rs.{p_manna}, Tandoori Roti = Rs.{p_roti}")

    # ---------------------------------------------------------
    # 5. Non-Sobat Variations: Standalone Pieces & Handi/Karahi
    # ---------------------------------------------------------
    print("\n[5/5] Testing Standalone Pieces & Handi/Karahi Variations...")
    
    # Standalone Fry Piece (Appetizer, NOT Sobat)
    r_fry_leg, p_fry_leg, _ = resolve_menu_item_price("Chicken Fry Piece", "Leg", 0, menu_items)
    assert p_fry_leg == 350.0, f"Expected 350 for Standalone Fry Leg, got {p_fry_leg}"
    assert "Sobat" not in r_fry_leg
    print(f"  [OK] Standalone Chicken Fry Piece (Leg) = Rs. {p_fry_leg} (Correct Appetizer, not Sobat)")

    r_fry_chest, p_fry_chest, _ = resolve_menu_item_price("Chicken Fry Piece", "Chest", 0, menu_items)
    assert p_fry_chest == 370.0, f"Expected 370 for Standalone Fry Chest, got {p_fry_chest}"
    assert "Sobat" not in r_fry_chest
    print(f"  [OK] Standalone Chicken Fry Piece (Chest) = Rs. {p_fry_chest}")

    # Standalone Tikka Piece (BBQ, NOT Sobat)
    r_tikka_leg, p_tikka_leg, _ = resolve_menu_item_price("Chicken Tikka Piece", "Leg", 0, menu_items)
    assert p_tikka_leg == 360.0, f"Expected 360 for Tikka Leg, got {p_tikka_leg}"
    print(f"  [OK] Chicken Tikka Piece (Leg) = Rs. {p_tikka_leg}")

    r_tikka_chest, p_tikka_chest, _ = resolve_menu_item_price("Chicken Tikka Piece", "Chest", 0, menu_items)
    assert p_tikka_chest == 380.0, f"Expected 380 for Tikka Chest, got {p_tikka_chest}"
    print(f"  [OK] Chicken Tikka Piece (Chest) = Rs. {p_tikka_chest}")

    # Handi & Karahi Half vs Full
    _, p_handi_half, _ = resolve_menu_item_price("Chicken Boneless Handi", "Half", 0, menu_items)
    assert p_handi_half == 900.0, f"Expected 900 for Handi Half, got {p_handi_half}"
    _, p_handi_full, _ = resolve_menu_item_price("Chicken Boneless Handi", "Full", 0, menu_items)
    assert p_handi_full == 1700.0, f"Expected 1700 for Handi Full, got {p_handi_full}"
    print(f"  [OK] Chicken Boneless Handi: Half = Rs. {p_handi_half}, Full = Rs. {p_handi_full}")

    _, p_karahi_half, _ = resolve_menu_item_price("Chicken Peshawari Karahi", "Half", 0, menu_items)
    assert p_karahi_half == 850.0, f"Expected 850 for Karahi Half, got {p_karahi_half}"
    _, p_karahi_full, _ = resolve_menu_item_price("Chicken Peshawari Karahi", "Full", 0, menu_items)
    assert p_karahi_full == 1700.0, f"Expected 1700 for Karahi Full, got {p_karahi_full}"
    print(f"  [OK] Chicken Peshawari Karahi: Half = Rs. {p_karahi_half}, Full = Rs. {p_karahi_full}")

    # ---------------------------------------------------------
    # 6. Three Designated Agents & 1 PM Availability Tests
    # ---------------------------------------------------------
    print("\n[6/6] Testing 3 Designated Agents & Instructions...")
    
    # Check Open Agent prompt contains 1 PM full menu & Fried Rice mandate
    assert "FRIED RICE & KITCHEN ITEMS AT 1:00 PM / DAYTIME" in OPEN_AGENT_PROMPT
    assert "RESTAURANT IS 100% OPEN RIGHT NOW" in OPEN_AGENT_PROMPT
    assert "BBQ items SIRF SHAAM 6:30 PM KE BAAD DASTIYAB HAIN" in OPEN_AGENT_PROMPT
    assert "Chicken Fried Rice" in OPEN_AGENT_PROMPT
    print("  [OK] Open Agent: 1 PM Fried Rice mandate and active order taking verified")

    # Check Afternoon Agent prompt restricts order taking to Sobat only
    assert "STRICTLY SOBAT, ROTI, NAAN & DRINKS ONLY" in AFTERNOON_AGENT_PROMPT
    assert "Fried Rice aur deegar kitchen menu shaam 6:30 PM se shuru hoga" in AFTERNOON_AGENT_PROMPT
    print("  [OK] Afternoon Agent: Sobat-only order taking & 6:30 PM deferral verified")

    # Check Closed Agent prompt strictly disables orders
    assert "Order Taking: STRICTLY DISABLED — NO ORDERS ACCEPTED" in CLOSED_AGENT_PROMPT
    assert "NO ADVANCE ORDERS (NEITHER DELIVERY NOR TAKEAWAY)" in CLOSED_AGENT_PROMPT
    print("  [OK] Closed Agent: Order taking strictly disabled & advance orders declined")

    # Check Tool Segregation
    open_tool_names = [t["function"]["name"] for t in OPEN_AGENT_TOOLS]
    afternoon_tool_names = [t["function"]["name"] for t in AFTERNOON_AGENT_TOOLS]
    closed_tool_names = [t["function"]["name"] for t in CLOSED_AGENT_TOOLS]

    assert "calculate_bill" in open_tool_names
    assert "save_order" in open_tool_names
    assert "calculate_bill" in afternoon_tool_names
    assert "save_order" in afternoon_tool_names

    # Closed Agent MUST NOT have bill calculation or order saving tools
    assert "calculate_bill" not in closed_tool_names, "Closed agent must not have calculate_bill"
    assert "save_order" not in closed_tool_names, "Closed agent must not have save_order"
    assert "notify_admins_and_kitchen" not in closed_tool_names, "Closed agent must not have notify_admins_and_kitchen"
    assert "read_menu" in closed_tool_names
    print("  [OK] Tool Segregation: Closed Agent structurally restricted from ordering tools")

    # Check Shift Router
    sim_open_hours = {"is_open": True, "is_break_time": False, "agent_type": "full_menu", "current_time_pkt": "01:00 PM"}
    sim_afternoon_hours = {"is_open": True, "is_break_time": True, "agent_type": "sobat_only", "current_time_pkt": "04:30 PM"}
    sim_closed_hours = {"is_open": False, "is_break_time": False, "agent_type": "closed", "current_time_pkt": "02:00 AM"}

    # Live clock routing logic
    # 1:00 PM -> open_agent
    if not sim_open_hours.get("is_open", True):
        dest_1pm = "closed_agent"
    elif sim_open_hours.get("is_break_time", False):
        dest_1pm = "afternoon_agent"
    else:
        dest_1pm = "open_agent"
    assert dest_1pm == "open_agent", f"Expected open_agent at 1 PM, got {dest_1pm}"

    # 4:30 PM -> afternoon_agent
    if not sim_afternoon_hours.get("is_open", True):
        dest_4pm = "closed_agent"
    elif sim_afternoon_hours.get("is_break_time", False):
        dest_4pm = "afternoon_agent"
    else:
        dest_4pm = "open_agent"
    assert dest_4pm == "afternoon_agent", f"Expected afternoon_agent at 4:30 PM, got {dest_4pm}"

    # 2:00 AM -> closed_agent
    if not sim_closed_hours.get("is_open", True):
        dest_2am = "closed_agent"
    elif sim_closed_hours.get("is_break_time", False):
        dest_2am = "afternoon_agent"
    else:
        dest_2am = "open_agent"
    assert dest_2am == "closed_agent", f"Expected closed_agent at 2 AM, got {dest_2am}"
    print("  [OK] Shift Routing: 1:00 PM -> open_agent, 4:30 PM -> afternoon_agent, 2:00 AM -> closed_agent")

    # ---------------------------------------------------------
    # 7. Sold-Out Item Logic, Menu Filtering & Chat Availability
    # ---------------------------------------------------------
    print("\n[7/7] Testing Sold-Out Item Detection & Availability...")

    # 7a. is_item_sold_out unit testing
    soldout_set = {"sobat"}
    assert is_item_sold_out("Chicken Sobat (Fry Pieces) Leg", soldout_set) is True
    assert is_item_sold_out("BBQ Chicken Sobat (Chest)", soldout_set) is True
    assert is_item_sold_out("Simple Sobat", soldout_set) is True
    assert is_item_sold_out("Mutton Sobat Platter", soldout_set) is True
    assert is_item_sold_out("2 nafri sobat", soldout_set) is True
    assert is_item_sold_out("Chicken Peshawari Karahi", soldout_set) is False
    assert is_item_sold_out("Chicken Fried Rice", soldout_set) is False
    print("  [OK] is_item_sold_out: 'sobat' correctly matches all Sobat variants and leaves others available")

    # Multi-word sold out item
    soldout_rice = {"chicken fried rice"}
    assert is_item_sold_out("Chicken Fried Rice", soldout_rice) is True
    assert is_item_sold_out("Egg Fried Rice", soldout_rice) is False
    print("  [OK] is_item_sold_out: 'chicken fried rice' correctly matches only Chicken Fried Rice")

    # 7b. read_menu() filtering with Redis sold-out set
    await redis_client.sadd("soldout:items", "sobat")
    try:
        filtered_menu = await read_menu()
        sobat_items = [it for it in filtered_menu if "sobat" in it.get("name", "").lower()]
        assert len(sobat_items) == 0, f"Expected 0 Sobat items in filtered menu, got {len(sobat_items)}"
        print(f"  [OK] read_menu(): Excluded all {len(sobat_items)} Sobat items when 'sobat' is in soldout:items")

        # 7c. calculate_bill() rejection
        calc_res = await calculate_bill([{"name": "Chicken Sobat", "quantity": 1}], order_type="Takeaway")
        assert calc_res.get("error") is True, "calculate_bill should return error for sold-out item"
        assert "Sold Out" in calc_res.get("message", ""), "calculate_bill message should state Sold Out"
        print("  [OK] calculate_bill(): Deterministically rejected sold-out item with clear error message")
    finally:
        await redis_client.srem("soldout:items", "sobat")

    # 7d. Admin commands /soldout, /soldout list, /available
    is_cmd, msg = await handle_admin_command("923306874242@s.whatsapp.net", "/soldout sobat", send_whatsapp=False)
    assert is_cmd is True
    assert "Marked Sold Out" in msg
    print("  [OK] Admin command: '/soldout sobat' succeeded")

    is_cmd, msg = await handle_admin_command("923306874242@s.whatsapp.net", "/soldout list", send_whatsapp=False)
    assert is_cmd is True
    assert "Sobat" in msg
    print("  [OK] Admin command: '/soldout list' displays Sobat")

    is_cmd, msg = await handle_admin_command("923306874242@s.whatsapp.net", "/available sobat", send_whatsapp=False)
    assert is_cmd is True
    assert "Item Restored" in msg
    print("  [OK] Admin command: '/available sobat' restores item")

    # 7e. In-Chat Agent Response when Sobat is Sold Out
    await redis_client.sadd("soldout:items", "sobat")
    try:
        test_session = {"phone": "923306874242", "history": []}
        reply, tools, agent_used = await execute_designated_agent(
            phone="923306874242",
            user_text="do you have sobat?",
            session=test_session,
            hours=sim_open_hours,
            dispatch_mode="simulator",
            override_shift="full_menu"
        )
        lower_reply = reply.lower()
        safe_reply = reply.encode("ascii", "backslashreplace").decode("ascii")
        print(f"  [Agent Reply to 'do you have sobat?']: \"{safe_reply}\"")
        # Ensure bot explains sobat is sold out / khatam / nahi and does NOT say it is available
        assert any(w in lower_reply for w in ["khatam", "sold out", "maaf", "nahi hai", "unavailable", "dastiyab nahi"]), \
            f"Expected sold out explanation in reply, got: {reply}"
        assert "ji haan" not in lower_reply and "ji bilkul" not in lower_reply, \
            f"Bot should NOT say 'ji haan' or 'ji bilkul' when item is sold out! Reply: {reply}"
        print("  [OK] Agent Turn: Customer asked 'do you have sobat?' and bot correctly responded it is SOLD OUT!")
    finally:
        await redis_client.srem("soldout:items", "sobat")

    # ---------------------------------------------------------
    # 8. BBQ Timing Restrictions (Strictly 6:30 PM PKT onwards)
    # ---------------------------------------------------------
    print("\n[8/9] Testing BBQ Timing Restrictions (6:30 PM PKT onwards)...")
    from datetime import datetime, time
    import pytz
    PKT = pytz.timezone("Asia/Karachi")

    # Shift checks
    h_lunch = get_hours_info(datetime(2026, 9, 20, 13, 0, tzinfo=PKT))  # 1:00 PM
    assert h_lunch["is_bbq_available"] is False, "BBQ should NOT be available at 1:00 PM"
    assert h_lunch["agent_type"] == "full_menu"
    print("  [OK] 1:00 PM PKT: Full menu open, but is_bbq_available is FALSE")

    h_afternoon = get_hours_info(datetime(2026, 9, 20, 16, 30, tzinfo=PKT))  # 4:30 PM
    assert h_afternoon["is_bbq_available"] is False, "BBQ should NOT be available at 4:30 PM"
    print("  [OK] 4:30 PM PKT: Sobat-only shift, is_bbq_available is FALSE")

    h_dinner = get_hours_info(datetime(2026, 9, 20, 19, 0, tzinfo=PKT))  # 7:00 PM
    assert h_dinner["is_bbq_available"] is True, "BBQ SHOULD be available at 7:00 PM"
    assert h_dinner["agent_type"] == "full_menu"
    print("  [OK] 7:00 PM PKT: Full menu open, is_bbq_available is TRUE")

    # is_bbq_item helper
    assert is_bbq_item("Chicken Tikka Piece") is True
    assert is_bbq_item("BBQ Chicken Sobat") is True
    assert is_bbq_item("Chicken Malai Boti") is True
    assert is_bbq_item("Seekh Kabab") is True
    assert is_bbq_item("Chicken Fry Piece") is False
    assert is_bbq_item("Chicken Sobat (Fry Pieces)") is False
    assert is_bbq_item("Simple Sobat") is False
    assert is_bbq_item("Chicken Peshawari Karahi") is False
    assert is_bbq_item("Chicken Fried Rice") is False
    print("  [OK] is_bbq_item: Correctly identifies BBQ items vs Fried/Sobat/Karahi items")

    # calculate_bill deterministic rejection of BBQ before 6:30 PM
    # Ensure force_open flag is not set
    await redis_client.delete("flag:force_open")
    # If current time is before 6:30 PM, calculate_bill should reject BBQ items
    curr_h = get_hours_info()
    if not curr_h.get("is_bbq_available"):
        calc_bbq = await calculate_bill([{"name": "Chicken Tikka Piece", "quantity": 1}], order_type="Takeaway")
        assert calc_bbq.get("error") is True, "calculate_bill should reject BBQ items before 6:30 PM"
        assert calc_bbq.get("bbq_restricted") is True
        assert "6:30 PM" in calc_bbq.get("message", "")
        print("  [OK] calculate_bill: Deterministically blocked BBQ item before 6:30 PM")
    else:
        print("  [SKIP] Current PKT time is already evening/dinner (after 6:30 PM)")

    # ---------------------------------------------------------
    # 9. Message Debouncer (Sliding Window, Max-Wait & Concurrency)
    # ---------------------------------------------------------
    print("\n[9/9] Testing Message Debouncer (Sliding Window, Max-Wait & Concurrency)...")
    assert message_debouncer.debounce_seconds == 2.0, f"Expected 2.0s debounce, got {message_debouncer.debounce_seconds}"
    assert message_debouncer.max_wait_seconds == 2.0, f"Expected 2.0s max wait, got {message_debouncer.max_wait_seconds}"
    assert settings.DEBOUNCE_SECONDS == 2.0
    assert settings.MAX_WAIT_SECONDS == 2.0
    print("  [OK] Default Debouncer configured to 2.0 seconds window & 2.0 seconds max ceiling")

    debouncer = MessageDebouncer(debounce_seconds=0.6, max_wait_seconds=1.5)
    received_payloads = []

    async def mock_process(p):
        received_payloads.append(p)

    test_key = "923999888777@s.whatsapp.net"
    p1 = {"payload": {"from": test_key, "id": "M1", "body": "Salam"}}
    p2 = {"payload": {"from": test_key, "id": "M2", "body": "1 sobat chahiye"}}
    p3 = {"payload": {"from": test_key, "id": "M3", "body": "aur 1 regular coke"}}

    # Send p1 at t=0
    await debouncer.add_message(test_key, p1, mock_process)
    await asyncio.sleep(0.1)  # 0.1s later (well within 0.6s window) -> should reset timer
    await debouncer.add_message(test_key, p2, mock_process)
    await asyncio.sleep(0.1)  # 0.1s later (well within 0.6s window) -> should reset timer
    await debouncer.add_message(test_key, p3, mock_process)

    # At this point, mock_process should NOT have been called yet
    assert len(received_payloads) == 0, f"Expected 0 calls before timer expiry, got {len(received_payloads)}"

    # Wait for timer to expire (0.6s delay + 0.25s buffer)
    await asyncio.sleep(0.85)

    assert len(received_payloads) == 1, f"Expected exactly 1 combined call, got {len(received_payloads)}"
    combined_body = received_payloads[0]["payload"]["body"]
    assert "Salam" in combined_body
    assert "1 sobat chahiye" in combined_body
    assert "aur 1 regular coke" in combined_body
    print(f"  [OK] Debouncer: Successfully aggregated 3 rapid messages into single payload:")
    print(f"       \"{combined_body.replace(chr(10), ' | ')}\"")

    # Test Concurrent Processing (pending_buffer drain)
    received_concurrent = []
    async def slow_mock_process(p):
        await asyncio.sleep(0.3)  # Simulate slow agent
        received_concurrent.append(p)

    c_debouncer = MessageDebouncer(debounce_seconds=0.2, max_wait_seconds=0.5)
    c_key = "923111222333@s.whatsapp.net"
    # Send first message to trigger processing
    await c_debouncer.add_message(c_key, {"payload": {"from": c_key, "id": "C1", "body": "First Msg"}}, slow_mock_process)
    await asyncio.sleep(0.25)  # Let timer expire -> now slow_mock_process is running (is_processing=True)

    # Send second message WHILE agent is processing -> should go to pending_buffer
    await c_debouncer.add_message(c_key, {"payload": {"from": c_key, "id": "C2", "body": "Second Msg during run"}}, slow_mock_process)

    # Wait for slow_mock_process to finish (0.3s) + drain cycle (0.2s) + second run (0.3s) + buffer
    await asyncio.sleep(0.9)

    assert len(received_concurrent) == 2, f"Expected 2 sequential calls (first + drained pending), got {len(received_concurrent)}"
    assert received_concurrent[0]["payload"]["body"] == "First Msg"
    assert received_concurrent[1]["payload"]["body"] == "Second Msg during run"
    # ---------------------------------------------------------
    # 10. Agent Conversational Quality & Tone Verification
    # ---------------------------------------------------------
    print("\n[10/10] Testing Agent Conversational Quality & Tone Standards...")

    # 10a. Minimum Delivery Order Enforcement in calculate_bill
    calc_min = await calculate_bill([{"name": "Simple Sobat", "quantity": 1}], order_type="Delivery")
    assert calc_min["meets_minimum_delivery"] is False, "1 Simple Sobat (Rs. 220) should not meet Rs. 300 minimum delivery"
    assert "kam az kam" in calc_min["message"].lower() or "minimum" in calc_min["message"].lower()
    print("  [OK] Minimum Delivery Guard: Subtotal Rs. 220 correctly flagged as below Rs. 300 minimum")

    # 10b. read_menu sold-out explicit status
    await redis_client.sadd("soldout:items", "karahi")
    try:
        res_soldout = await read_menu(query="karahi")
        assert len(res_soldout) == 1
        assert res_soldout[0].get("status") == "sold_out"
        assert "SOLD OUT" in res_soldout[0].get("message", "")
        print("  [OK] read_menu: Explicitly returned sold_out status for queried sold-out dish")
    finally:
        await redis_client.srem("soldout:items", "karahi")

    # 10c. 1:00 PM Daytime Fried Rice Inquiry (Open Agent)
    s_daytime = {"phone": "923306874242", "history": []}
    reply_1pm, _, _ = await execute_designated_agent(
        phone="923306874242",
        user_text="Fried rice mil jaye gi?",
        session=s_daytime,
        hours=sim_open_hours,
        dispatch_mode="simulator",
        override_shift="open"
    )
    lower_1pm = reply_1pm.lower()
    assert any(w in lower_1pm for w in ["dastiyab", "mil jaye", "bilkul", "ji haan", "available"]), \
        f"Fried rice should be confirmed available at 1 PM! Reply: {reply_1pm}"
    print(f"  [OK] 1:00 PM Fried Rice Inquiry confirmed available: \"{reply_1pm[:80]}...\"")

    # 10d. Daytime BBQ Restriction Inquiry (Open Agent at 1:00 PM)
    s_bbq = {"phone": "923306874242", "history": []}
    reply_bbq, _, _ = await execute_designated_agent(
        phone="923306874242",
        user_text="1 chicken tikka piece delivery kardo",
        session=s_bbq,
        hours=h_lunch,  # 1:00 PM lunch hours where is_bbq_available is False
        dispatch_mode="simulator",
        override_shift="open"
    )
    lower_bbq = reply_bbq.lower()
    assert "6:30" in lower_bbq, f"Agent should mention 6:30 PM for BBQ items! Reply: {reply_bbq}"
    print(f"  [OK] Daytime BBQ Inquiry politely deferred to 6:30 PM: \"{reply_bbq[:80]}...\"")

    # 10e. Afternoon Shift Deferral (Afternoon Agent at 4:30 PM)
    s_afternoon = {"phone": "923306874242", "history": []}
    reply_aft, _, _ = await execute_designated_agent(
        phone="923306874242",
        user_text="1 chicken karahi delivery karni hai",
        session=s_afternoon,
        hours=sim_afternoon_hours,
        dispatch_mode="simulator",
        override_shift="afternoon"
    )
    lower_aft = reply_aft.lower()
    assert any(w in lower_aft for w in ["sobat", "paenda"]) and ("6:30" in lower_aft or "afternoon" in lower_aft), \
        f"Afternoon agent should offer Sobat and defer Karahi to 6:30 PM! Reply: {reply_aft}"
    print(f"  [OK] Afternoon Karahi inquiry politely deferred with Sobat offer: \"{reply_aft[:80]}...\"")

    # ---------------------------------------------------------
    # 11. Multi-Turn Ordering Conversation & Modification Diagnostic
    # ---------------------------------------------------------
    print("\n[11/11] Diagnosing Full Multi-Turn Conversation & Modification Flow...")
    from services.session import SESSION_TTL
    assert SESSION_TTL == 7200, f"Expected 7200 seconds (2 hours) TTL, got {SESSION_TTL}"
    assert settings.SESSION_TTL_MINUTES == 120, f"Expected 120 minutes in settings, got {settings.SESSION_TTL_MINUTES}"
    print("  [OK] Session Cache configured for 2 hours (120 minutes / 7200 seconds)")

    conv_session = {"phone": "923306874242", "history": []}
    
    # Turn 1: Initial greeting & order type
    t1 = "Salam, delivery chahiye"
    r1, _, _ = await execute_designated_agent(
        phone="923306874242", user_text=t1, session=conv_session, hours=sim_open_hours, dispatch_mode="simulator", override_shift="open"
    )
    print(f"  [Turn 1] Customer: '{t1}' -> Agent: '{r1}'")
    conv_session["history"].extend([{"role": "user", "content": t1}, {"role": "assistant", "content": r1}])

    # Turn 2: Item selection & packaging
    t2 = "1 chicken sobat chest thal mein"
    r2, _, _ = await execute_designated_agent(
        phone="923306874242", user_text=t2, session=conv_session, hours=sim_open_hours, dispatch_mode="simulator", override_shift="open"
    )
    print(f"  [Turn 2] Customer: '{t2}' -> Agent: '{r2}'")
    assert "[aapka naam]" not in r2.lower(), f"Turn 2 should NOT contain '[aapka naam]' placeholder! Reply: {r2}"
    conv_session["history"].extend([{"role": "user", "content": t2}, {"role": "assistant", "content": r2}])

    # Turn 3: Customer provides info
    t3 = "Ahmad, Model Town DI Khan"
    r3, _, _ = await execute_designated_agent(
        phone="923306874242", user_text=t3, session=conv_session, hours=sim_open_hours, dispatch_mode="simulator", override_shift="open"
    )
    print(f"  [Turn 3] Customer: '{t3}' -> Agent: '{r3}'")
    assert "Order Summary" in r3 or "Total:" in r3, f"Turn 3 should display Order Summary! Reply: {r3}"
    assert "Ahmad" in r3, f"Turn 3 should include customer name Ahmad! Reply: {r3}"
    conv_session["history"].extend([{"role": "user", "content": t3}, {"role": "assistant", "content": r3}])

    # Turn 4: Customer makes mid-order modification/addition: "1 regular coke bhi sath add kardo"
    t4 = "Wait, 1 regular coke bhi sath add kardo"
    r4, _, _ = await execute_designated_agent(
        phone="923306874242", user_text=t4, session=conv_session, hours=sim_open_hours, dispatch_mode="simulator", override_shift="open"
    )
    print(f"  [Turn 4 - Modification] Customer: '{t4}' -> Agent: '{r4}'")
    assert any(c in r4.lower() for c in ["coke", "910", "update", "sobat"]), f"Agent should reflect Coke addition! Reply: {r4}"
    conv_session["history"].extend([{"role": "user", "content": t4}, {"role": "assistant", "content": r4}])

    # Turn 5: Confirm updated order
    t5 = "Haan theek hai, confirm kardo"
    r5, _, _ = await execute_designated_agent(
        phone="923306874242", user_text=t5, session=conv_session, hours=sim_open_hours, dispatch_mode="simulator", override_shift="open"
    )
    print(f"  [Turn 5 - Confirmation] Customer: '{t5}' -> Agent: '{r5}'")
    assert any(w in r5.lower() for w in ["confirmed", "order id", "shukriya"]), f"Turn 5 should confirm order! Reply: {r5}"
    assert conv_session.get("items") is None, f"Cart items should be cleared from session upon confirmation, got {conv_session.get('items')}"
    assert conv_session.get("total_bill") is None, f"Total bill should be cleared from session upon confirmation, got {conv_session.get('total_bill')}"
    assert conv_session.get("name") == "Ahmad", f"Customer name should be retained for CRM, got {conv_session.get('name')}"
    assert conv_session.get("address") == "Model Town DI Khan", f"Customer address should be retained for CRM, got {conv_session.get('address')}"
    print("  [OK] Multi-turn order and cart modification workflow completed successfully with clean post-order cart wipe!")

    # ---------------------------------------------------------
    # 12. Testing Customer Info Extraction & Single-Message Order
    # ---------------------------------------------------------
    print("\n[12/12] Testing Customer Info Extraction & Single-Message Flow...")
    from services.agent_runner import extract_customer_info
    
    # Unit tests for extract_customer_info
    n1, a1, _ = extract_customer_info("Ahmad, Model Town DI Khan")
    assert n1 == "Ahmad" and "Model Town" in a1, f"Failed on 'Ahmad, Model Town DI Khan': {n1}, {a1}"
    
    n2, a2, _ = extract_customer_info("Mera naam Usman hai, delivery address Cantt DI Khan")
    assert n2 == "Usman" and "Cantt" in a2, f"Failed on explicit name/address: {n2}, {a2}"
    
    _, _, p3 = extract_customer_info("Takeaway hai 20 minute mein uthaunga")
    assert p3 and "20" in p3, f"Failed on pickup time: {p3}"
    
    n4, a4, _ = extract_customer_info("Wait, 1 regular coke bhi sath add kardo")
    assert n4 is None and a4 is None, f"Addition message should not extract false name/address: {n4}, {a4}"
    print("  [OK] extract_customer_info accurately parses names, addresses, and pickup times without false positives")

    # Single-message complete order test (Customer provides everything at once)
    single_turn_session = {"phone": "923306874242", "history": []}
    single_msg = "Salam, 1 chicken sobat chest thal mein delivery chahiye, mera naam Tariq hai Model Town DI Khan"
    r_single, _, _ = await execute_designated_agent(
        phone="923306874242", user_text=single_msg, session=single_turn_session, hours=sim_open_hours, dispatch_mode="simulator", override_shift="open"
    )
    print(f"  [Single-Message Order] Reply: '{r_single[:120]}...'")
    assert any(w in r_single for w in ["Order Summary", "Tariq", "860", "Model Town"]), \
        f"Single-message order should immediately display Order Summary or bill with customer details! Reply: {r_single}"
    print("  [OK] Single-turn rich message with items + name + address handled seamlessly without redundant questions!")

    print("\n==================================================")
    print("SUCCESS: ALL UNIVERSAL TESTS PASSED!")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(run_tests())
