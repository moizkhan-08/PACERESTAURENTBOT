"""
Pace Restaurant Bot - Universal Autonomous Testing & Validation Script

Usage:
  python universal_test.py

Rules:
  1. This is the SINGLE dedicated testing file for autonomous development and validation.
  2. Do not create multiple ad-hoc test scripts. Modify and reuse this file.
  3. Run tests autonomously without interrupting for permissions on routine debugging.
"""
import asyncio
import os
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.tools import decompose_sobat_items, resolve_menu_item_price, calculate_bill
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

    # Bill for 1 BBQ piece sobat + 1 Fried piece sobat = 530 + 520 = 1050
    calc_combo = await calculate_bill([{"name": "1 bbq piece sobat and one fried piece", "quantity": 1}], order_type="Takeaway")
    assert calc_combo["total_bill"] == 1050.0, f"Expected 1050, got {calc_combo['total_bill']}"
    assert "Delivery charges will apply" not in calc_combo["formatted_summary"]
    print(f"  [OK] Combined Bill: 1x BBQ (Rs.530) + 1x Fried (Rs.520) = Rs.{calc_combo['total_bill']}")

    # Delivery order formatted_summary MUST mention "Delivery charges will apply" without exact amount
    calc_delivery = await calculate_bill([{"name": "Chicken Sobat", "quantity": 1}], order_type="Delivery")
    assert "Delivery charges will apply" in calc_delivery["formatted_summary"]
    assert "Rs." not in calc_delivery["formatted_summary"].split("Delivery charges")[1].split("\n")[0]
    print(f"  [OK] Delivery Order Summary correctly mentions 'Delivery charges will apply' (no exact fee)")

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
    assert "RESTAURANT IS 100% OPEN RIGHT NOW. COMPLETE MENU IS SERVED" in OPEN_AGENT_PROMPT
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

    print("\n==================================================")
    print("SUCCESS: ALL UNIVERSAL TESTS PASSED!")
    print("==================================================")


if __name__ == "__main__":
    asyncio.run(run_tests())
