import json
import logging
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from openai import AsyncOpenAI

from config import settings
from services.cache import redis_client
from services.session import get_session, set_session, clear_session, generate_confirm_key
from services.hours import get_hours_info
from services.audio import transcribe_audio_payload
from services.tools import (
    read_menu,
    send_menu_images,
    calculate_bill,
    check_returning_customer,
    save_order_record,
    notify_admins_and_kitchen
)
from services.prompts import (
    FULL_MENU_SYSTEM_PROMPT,
    SOBAT_ONLY_SYSTEM_PROMPT,
    CLOSED_SYSTEM_PROMPT
)
from services.agent_runner import AGENT_TOOLS

logger = logging.getLogger("test_playground")
router = APIRouter()


@router.post("/chat")
async def simulate_chat_turn(payload: dict):
    """
    Simulates a full agent chat turn with real-time tool call inspection.
    Payload:
    - phone: str (e.g. '923306874242')
    - message: str
    - override_shift: optional str ('full_menu', 'sobat_only', 'closed')
    """
    phone = payload.get("phone", "923306874242").strip()
    user_text = payload.get("message", "").strip()
    override_shift = payload.get("override_shift")

    if not user_text:
        raise HTTPException(status_code=400, detail="Message content cannot be empty")

    # 1. Fetch Session
    session = await get_session(phone)
    if not session:
        profile = await check_returning_customer(phone)
        session = {
            "phone": phone,
            "name": profile.get("name") if profile.get("is_returning") else "",
            "address": profile.get("default_address") if profile.get("is_returning") else "",
            "history": [],
            "confirm_key": None
        }

    # 2. Determine Shift
    hours = get_hours_info()
    if override_shift == "closed":
        system_prompt = CLOSED_SYSTEM_PROMPT
        agent_type = "closed"
    elif override_shift == "sobat_only":
        system_prompt = SOBAT_ONLY_SYSTEM_PROMPT
        agent_type = "sobat_only"
    elif override_shift == "full_menu":
        system_prompt = FULL_MENU_SYSTEM_PROMPT
        agent_type = "full_menu"
    else:
        agent_type = hours.get("agent_type")
        if not hours["is_open"]:
            system_prompt = CLOSED_SYSTEM_PROMPT
        elif hours["is_break_time"]:
            system_prompt = SOBAT_ONLY_SYSTEM_PROMPT
        else:
            system_prompt = FULL_MENU_SYSTEM_PROMPT

    # 3. Build Conversation Messages
    history = session.get("history", [])
    messages = [{"role": "system", "content": system_prompt}]
    
    context_note = f"[Customer Phone: {phone}]"
    if session.get("name"):
        context_note += f" [Customer Name: {session.get('name')}]"
    if session.get("address"):
        context_note += f" [Known Address: {session.get('address')}]"
    context_note += f" [Current Time PKT: {hours.get('current_time_pkt')}]"
    messages.append({"role": "system", "content": context_note})

    for h in history[-8:]:
        messages.append(h)

    messages.append({"role": "user", "content": user_text})

    # 4. Agent Tool Calling Execution
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    final_reply = ""
    latest_order_record = None
    executed_tools = []

    try:
        for _ in range(5):
            response = await client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=messages,
                tools=AGENT_TOOLS,
                tool_choice="auto",
                temperature=0.4
            )

            assistant_msg = response.choices[0].message
            messages.append(assistant_msg)

            if not assistant_msg.tool_calls:
                final_reply = assistant_msg.content or ""
                break

            for tool_call in assistant_msg.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments or "{}")
                tool_result = {}

                if tool_name == "read_menu":
                    category = tool_args.get("category")
                    tool_result = await read_menu(category)

                elif tool_name == "send_menu_images":
                    tool_result = await send_menu_images(phone)

                elif tool_name == "calculate_bill":
                    items = tool_args.get("items", [])
                    order_type = tool_args.get("order_type", "Delivery")
                    thal_count = tool_args.get("thal_count", 0)
                    calc = calculate_bill(items, order_type, thal_count)
                    tool_result = calc
                    
                    session["items"] = calc["items"]
                    session["subtotal"] = calc["subtotal"]
                    session["thal_deposit"] = calc["thal_deposit"]
                    session["total_bill"] = calc["total_bill"]
                    session["order_type"] = order_type
                    if not session.get("confirm_key"):
                        session["confirm_key"] = generate_confirm_key(phone)

                elif tool_name == "save_order":
                    items = tool_args.get("items") or session.get("items", [])
                    total_bill = tool_args.get("total_bill") or session.get("total_bill", 0)
                    notes = tool_args.get("notes", "")
                    
                    if tool_args.get("customer_name"):
                        session["name"] = tool_args["customer_name"]
                    if tool_args.get("order_type"):
                        session["order_type"] = tool_args["order_type"]
                    if tool_args.get("delivery_address"):
                        session["address"] = tool_args["delivery_address"]
                    if tool_args.get("pickup_time"):
                        session["pickup_time"] = tool_args["pickup_time"]
                    
                    saved = await save_order_record(session, items, total_bill, notes)
                    tool_result = saved
                    latest_order_record = saved

                elif tool_name == "notify_admins_and_kitchen":
                    order_id = tool_args.get("order_id", "PACE-CONFIRMED")
                    items_fallback = "\n".join([
                        f"- {it.get('quantity', 1)}x {it.get('name')} ({it.get('variant', '')})"
                        for it in session.get("items", [])
                    ]) if session.get("items") else "Items"

                    order_summary_data = {
                        "customer_name": tool_args.get("customer_name") or session.get("name"),
                        "phone_number": phone,
                        "order_type": tool_args.get("order_type") or session.get("order_type"),
                        "delivery_address": tool_args.get("delivery_address") or session.get("address"),
                        "pickup_time": tool_args.get("pickup_time") or session.get("pickup_time"),
                        "order_items": (latest_order_record.get("summary") if latest_order_record else None) or items_fallback,
                        "total_bill": tool_args.get("total_bill") or session.get("total_bill", 0),
                        "notes": tool_args.get("notes") or session.get("notes", "")
                    }
                    tool_result = await notify_admins_and_kitchen(order_id, order_summary_data)
                    session["confirm_key"] = None

                executed_tools.append({
                    "name": tool_name,
                    "args": tool_args,
                    "result": tool_result
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": json.dumps(tool_result)
                })

    except Exception as e:
        logger.exception("Test chat error: %s", e)
        final_reply = f"Error executing agent loop: {str(e)}"

    # Update session history
    history.append({"role": "user", "content": user_text})
    if final_reply:
        history.append({"role": "assistant", "content": final_reply})
    session["history"] = history[-10:]
    await set_session(phone, session)

    return {
        "reply": final_reply,
        "shift": agent_type,
        "time_pkt": hours.get("current_time_pkt"),
        "session": session,
        "tool_calls": executed_tools
    }


@router.post("/reset")
async def reset_test_session(payload: dict):
    """Clears Redis session state for a phone number."""
    phone = payload.get("phone", "923306874242").strip()
    await clear_session(phone)
    return {"status": "success", "message": f"Session cleared for {phone}"}


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def get_test_playground_page():
    """Serves the WhatsApp Web Agent Simulator UI."""
    return HTMLResponse(content=HTML_TEST_UI)


HTML_TEST_UI = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pace Restaurant AI Agent — Interactive Web Simulator</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #0b141a;
            --bg-panel: #111b21;
            --bg-chat: #0d1418;
            --bg-msg-user: #005c4b;
            --bg-msg-bot: #202c33;
            --accent-green: #00a884;
            --accent-light: #25d366;
            --text-primary: #e9edef;
            --text-secondary: #8696a0;
            --border-color: #222d34;
            --gold-accent: #f7ca18;
            --card-glass: rgba(32, 44, 51, 0.85);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Outfit', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }

        body {
            background-color: var(--bg-dark);
            color: var(--text-primary);
            height: 100vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* Top Header Navigation */
        header {
            background-color: var(--bg-panel);
            border-bottom: 1px solid var(--border-color);
            padding: 12px 24px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            z-index: 10;
        }

        .brand-container {
            display: flex;
            align-items: center;
            gap: 14px;
        }

        .logo-icon {
            width: 42px;
            height: 42px;
            background: linear-gradient(135deg, var(--accent-green), #028a6c);
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
            box-shadow: 0 4px 12px rgba(0, 168, 132, 0.3);
        }

        .brand-title {
            font-size: 18px;
            font-weight: 700;
            letter-spacing: -0.3px;
        }

        .brand-subtitle {
            font-size: 12px;
            color: var(--text-secondary);
        }

        .header-controls {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .setting-group {
            display: flex;
            align-items: center;
            gap: 8px;
            background-color: var(--bg-dark);
            padding: 6px 12px;
            border-radius: 8px;
            border: 1px solid var(--border-color);
        }

        .setting-label {
            font-size: 12px;
            color: var(--text-secondary);
            font-weight: 500;
        }

        input[type="text"], select {
            background: transparent;
            border: none;
            color: var(--text-primary);
            font-size: 13px;
            font-weight: 600;
            outline: none;
        }

        select option {
            background-color: var(--bg-panel);
            color: var(--text-primary);
        }

        .btn {
            background-color: var(--accent-green);
            color: #fff;
            border: none;
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .btn:hover {
            background-color: var(--accent-light);
            box-shadow: 0 4px 12px rgba(37, 211, 102, 0.3);
        }

        .btn-outline {
            background: transparent;
            border: 1px solid var(--border-color);
            color: var(--text-primary);
        }

        .btn-outline:hover {
            background-color: rgba(255, 255, 255, 0.05);
            border-color: var(--text-secondary);
        }

        .btn-danger {
            background-color: #d9534f;
        }

        .btn-danger:hover {
            background-color: #c9302c;
            box-shadow: 0 4px 12px rgba(217, 83, 79, 0.3);
        }

        /* Main Grid Workspace */
        .workspace {
            display: grid;
            grid-template-columns: 1fr 420px;
            flex: 1;
            overflow: hidden;
        }

        /* Left Chat Simulator */
        .chat-section {
            display: flex;
            flex-direction: column;
            background-color: var(--bg-chat);
            position: relative;
            background-image: radial-gradient(rgba(255, 255, 255, 0.03) 1px, transparent 0);
            background-size: 24px 24px;
        }

        .chat-body {
            flex: 1;
            overflow-y: auto;
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }

        .message-bubble {
            max-width: 75%;
            padding: 10px 14px;
            border-radius: 12px;
            font-size: 14px;
            line-height: 1.5;
            position: relative;
            animation: fadeIn 0.2s ease-out;
            white-space: pre-wrap;
            word-wrap: break-word;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(6px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .msg-user {
            align-self: flex-end;
            background-color: var(--bg-msg-user);
            color: #fff;
            border-bottom-right-radius: 2px;
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
        }

        .msg-bot {
            align-self: flex-start;
            background-color: var(--bg-msg-bot);
            color: var(--text-primary);
            border-bottom-left-radius: 2px;
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.3);
            border-left: 3px solid var(--accent-green);
        }

        .msg-time {
            font-size: 10px;
            color: var(--text-secondary);
            margin-top: 4px;
            text-align: right;
            display: block;
        }

        .typing-indicator {
            align-self: flex-start;
            background-color: var(--bg-msg-bot);
            padding: 10px 16px;
            border-radius: 12px;
            display: none;
            align-items: center;
            gap: 6px;
            font-size: 13px;
            color: var(--text-secondary);
            border-left: 3px solid var(--accent-green);
        }

        .dot {
            width: 6px;
            height: 6px;
            background-color: var(--text-secondary);
            border-radius: 50%;
            animation: bounce 1.4s infinite ease-in-out;
        }

        .dot:nth-child(2) { animation-delay: 0.2s; }
        .dot:nth-child(3) { animation-delay: 0.4s; }

        @keyframes bounce {
            0%, 80%, 100% { transform: scale(0); }
            40% { transform: scale(1); }
        }

        /* Chat Footer Input */
        .chat-footer {
            background-color: var(--bg-panel);
            padding: 14px 20px;
            display: flex;
            align-items: center;
            gap: 12px;
            border-top: 1px solid var(--border-color);
        }

        .input-box {
            flex: 1;
            background-color: var(--bg-dark);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            padding: 12px 18px;
            color: var(--text-primary);
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s ease;
        }

        .input-box:focus {
            border-color: var(--accent-green);
        }

        .quick-chips {
            display: flex;
            gap: 8px;
            padding: 8px 20px;
            background-color: var(--bg-panel);
            border-top: 1px solid var(--border-color);
            overflow-x: auto;
        }

        .chip {
            background-color: var(--bg-dark);
            border: 1px solid var(--border-color);
            color: var(--text-primary);
            padding: 6px 12px;
            border-radius: 16px;
            font-size: 12px;
            font-weight: 500;
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.2s ease;
        }

        .chip:hover {
            border-color: var(--accent-green);
            color: var(--accent-light);
            background-color: rgba(0, 168, 132, 0.1);
        }

        /* Right Inspector Drawer */
        .inspector-section {
            background-color: var(--bg-panel);
            border-left: 1px solid var(--border-color);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .inspector-header {
            padding: 16px 20px;
            border-bottom: 1px solid var(--border-color);
            font-size: 15px;
            font-weight: 700;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .badge {
            background-color: rgba(0, 168, 132, 0.15);
            color: var(--accent-light);
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }

        .inspector-body {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 18px;
        }

        .info-card {
            background-color: var(--card-glass);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 16px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
        }

        .card-title {
            font-size: 13px;
            font-weight: 700;
            color: var(--gold-accent);
            margin-bottom: 10px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .tool-call-item {
            background-color: var(--bg-dark);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 10px;
            margin-bottom: 10px;
            font-family: monospace;
            font-size: 12px;
        }

        .tool-name {
            color: var(--accent-light);
            font-weight: 700;
            margin-bottom: 4px;
        }

        pre {
            background-color: #050a0e;
            padding: 10px;
            border-radius: 6px;
            color: #a9b7c6;
            font-size: 11px;
            overflow-x: auto;
            max-height: 180px;
            border: 1px solid #1a262f;
        }

        .empty-state {
            text-align: center;
            color: var(--text-secondary);
            font-size: 13px;
            padding: 30px 10px;
        }
    </style>
</head>
<body>

    <header>
        <div class="brand-container">
            <div class="logo-icon">🍲</div>
            <div>
                <div class="brand-title">Pace Restaurant AI Order Assistant</div>
                <div class="brand-subtitle">Interactive Web Testing & Function Call Inspector</div>
            </div>
        </div>

        <div class="header-controls">
            <div class="setting-group">
                <span class="setting-label">📱 Customer Phone:</span>
                <input type="text" id="phoneInput" value="923306874242" style="width: 120px;">
            </div>

            <div class="setting-group">
                <span class="setting-label">🕒 Simulated Shift:</span>
                <select id="shiftSelect">
                    <option value="">Live PKT Clock</option>
                    <option value="full_menu">Full Menu Shift</option>
                    <option value="sobat_only">Sobat Special (3:30–6:30 PM)</option>
                    <option value="closed">Closed Shift (Night)</option>
                </select>
            </div>

            <button class="btn btn-danger" onclick="resetSession()">🔄 Reset Session</button>
        </div>
    </header>

    <div class="workspace">
        <!-- Left Chat Interface -->
        <div class="chat-section">
            <div class="chat-body" id="chatBody">
                <div class="message-bubble msg-bot">
                    Assalam-o-Alaikum! 🌟 Pace Restaurant Dera Ismail Khan mein khush amadeed!<br>
                    Main aapki kia khidmat kar sakta hoon? Aap live order, menu card, ya special Sobat ke baare mein pooch sakte hain 😊
                    <span class="msg-time">System Ready</span>
                </div>
            </div>

            <div class="typing-indicator" id="typingIndicator">
                <span>Pace AI Agent is typing</span>
                <div class="dot"></div>
                <div class="dot"></div>
                <div class="dot"></div>
            </div>

            <div class="quick-chips">
                <div class="chip" onclick="sendQuickMsg('Menu card dikhao')">📖 Show Menu Card</div>
                <div class="chip" onclick="sendQuickMsg('1 Full Sobat delivery karni hai')">🫕 Order 1 Sobat Delivery</div>
                <div class="chip" onclick="sendQuickMsg('Sobat ki price kia hai?')">💰 Check Sobat Price</div>
                <div class="chip" onclick="sendQuickMsg('Aapki location kahan hai?')">📍 Restaurant Address</div>
                <div class="chip" onclick="sendQuickMsg('Haan confirm hai order')">✅ Confirm Order (YES)</div>
            </div>

            <div class="chat-footer">
                <input type="text" class="input-box" id="userMsgInput" placeholder="Type Roman Urdu or English message here..." onkeypress="handleKeyPress(event)">
                <button class="btn" onclick="sendUserMessage()">Send 🚀</button>
            </div>
        </div>

        <!-- Right Tool & State Inspector -->
        <div class="inspector-section">
            <div class="inspector-header">
                <span>⚡ Live Tool Calling & State</span>
                <span class="badge" id="shiftBadge">Auto Shift</span>
            </div>

            <div class="inspector-body">
                <div class="info-card">
                    <div class="card-title">🛠️ Executed Tools (This Turn)</div>
                    <div id="toolsLogContainer">
                        <div class="empty-state">No tool call triggered yet. Send a message to test agent execution!</div>
                    </div>
                </div>

                <div class="info-card">
                    <div class="card-title">📦 Session State (Redis Staging)</div>
                    <pre id="sessionDataPre">{
  "status": "No active session staged"
}</pre>
                </div>
            </div>
        </div>
    </div>

    <script>
        const chatBody = document.getElementById('chatBody');
        const userMsgInput = document.getElementById('userMsgInput');
        const typingIndicator = document.getElementById('typingIndicator');
        const toolsLogContainer = document.getElementById('toolsLogContainer');
        const sessionDataPre = document.getElementById('sessionDataPre');
        const shiftBadge = document.getElementById('shiftBadge');

        function getCurrentTimeStr() {
            const d = new Date();
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }

        function appendMessage(text, isUser) {
            const bubble = document.createElement('div');
            bubble.className = `message-bubble ${isUser ? 'msg-user' : 'msg-bot'}`;
            bubble.innerHTML = text.replace(/\\n/g, '<br>');

            const timeSpan = document.createElement('span');
            timeSpan.className = 'msg-time';
            timeSpan.innerText = getCurrentTimeStr();
            bubble.appendChild(timeSpan);

            chatBody.appendChild(bubble);
            chatBody.scrollTop = chatBody.scrollHeight;
        }

        function handleKeyPress(e) {
            if (e.key === 'Enter') {
                sendUserMessage();
            }
        }

        function sendQuickMsg(text) {
            userMsgInput.value = text;
            sendUserMessage();
        }

        async function sendUserMessage() {
            const text = userMsgInput.value.trim();
            const phone = document.getElementById('phoneInput').value.trim() || '923306874242';
            const overrideShift = document.getElementById('shiftSelect').value;

            if (!text) return;

            // Render user bubble
            appendMessage(text, true);
            userMsgInput.value = '';

            // Show typing indicator
            typingIndicator.style.display = 'flex';
            chatBody.scrollTop = chatBody.scrollHeight;

            try {
                const res = await fetch('/test/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        phone: phone,
                        message: text,
                        override_shift: overrideShift || null
                    })
                });

                const data = await res.json();
                typingIndicator.style.display = 'none';

                if (data.reply) {
                    appendMessage(data.reply, false);
                } else {
                    appendMessage("⚠️ Agent returned empty response.", false);
                }

                // Update Inspector
                renderInspector(data);

            } catch (err) {
                typingIndicator.style.display = 'none';
                appendMessage("❌ Network error connecting to test endpoint.", false);
                console.error(err);
            }
        }

        function renderInspector(data) {
            shiftBadge.innerText = (data.shift || 'FULL MENU').toUpperCase();

            // Render Tools Log
            if (data.tool_calls && data.tool_calls.length > 0) {
                toolsLogContainer.innerHTML = '';
                data.tool_calls.forEach(tc => {
                    const item = document.createElement('div');
                    item.className = 'tool-call-item';
                    item.innerHTML = `
                        <div class="tool-name">🔧 ${tc.name}</div>
                        <div style="font-size: 10px; color: var(--text-secondary); margin-bottom: 4px;">ARGS:</div>
                        <pre>${JSON.stringify(tc.args, null, 2)}</pre>
                        <div style="font-size: 10px; color: var(--text-secondary); margin-top: 6px; margin-bottom: 4px;">RESULT:</div>
                        <pre>${JSON.stringify(tc.result, null, 2)}</pre>
                    `;
                    toolsLogContainer.appendChild(item);
                });
            } else {
                toolsLogContainer.innerHTML = '<div class="empty-state">No function tools triggered in this turn. Agent answered directly.</div>';
            }

            // Render Session Pre
            if (data.session) {
                sessionDataPre.innerText = JSON.stringify(data.session, null, 2);
            }
        }

        async function resetSession() {
            const phone = document.getElementById('phoneInput').value.trim() || '923306874242';
            try {
                await fetch('/test/reset', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ phone: phone })
                });
                alert(`Session cleared for ${phone}! Next message will start fresh.`);
                sessionDataPre.innerText = '{\n  "status": "Session reset"\n}';
                toolsLogContainer.innerHTML = '<div class="empty-state">Session reset. Send a message to test starting flow.</div>';
            } catch (err) {
                alert('Error resetting session.');
            }
        }
    </script>
</body>
</html>
"""
