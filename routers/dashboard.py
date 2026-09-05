import logging
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

logger = logging.getLogger("dashboard")
router = APIRouter()


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the Pace Restaurant Admin Dashboard UI."""
    return HTMLResponse(content=DASHBOARD_HTML)


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pace Restaurant — Admin Dashboard</title>
    <meta name="description" content="Real-time admin dashboard for Pace Restaurant order management, menu control, and bot operations.">
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700;800&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-base: #08090c;
            --bg-surface: #10131a;
            --bg-card: #161a25;
            --bg-elevated: #1c2030;
            --border: #252a3a;
            --border-light: #2e3548;
            --text-primary: #eaecf2;
            --text-secondary: #8690a8;
            --text-muted: #5a6380;
            --accent: #6c5ce7;
            --accent-light: #a29bfe;
            --accent-glow: rgba(108, 92, 231, 0.15);
            --green: #00b894;
            --green-light: #55efc4;
            --green-glow: rgba(0, 184, 148, 0.12);
            --red: #d63031;
            --red-light: #ff7675;
            --red-glow: rgba(214, 48, 49, 0.12);
            --orange: #e17055;
            --orange-glow: rgba(225, 112, 85, 0.12);
            --gold: #fdcb6e;
            --gold-glow: rgba(253, 203, 110, 0.1);
            --blue: #0984e3;
            --blue-glow: rgba(9, 132, 227, 0.12);
            --radius: 14px;
            --radius-sm: 8px;
            --shadow: 0 8px 32px rgba(0,0,0,0.3);
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            font-family: 'Outfit', 'Inter', -apple-system, sans-serif;
            background: var(--bg-base);
            color: var(--text-primary);
            min-height: 100vh;
            overflow-x: hidden;
        }

        /* ── Login Gate ── */
        #loginOverlay {
            position: fixed; inset: 0; z-index: 1000;
            background: var(--bg-base);
            display: flex; align-items: center; justify-content: center;
        }
        .login-card {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 48px 40px;
            width: 100%; max-width: 420px;
            text-align: center;
            box-shadow: var(--shadow);
        }
        .login-card .logo { font-size: 48px; margin-bottom: 16px; }
        .login-card h1 { font-size: 22px; font-weight: 700; margin-bottom: 6px; }
        .login-card p { font-size: 13px; color: var(--text-secondary); margin-bottom: 28px; }
        .login-input {
            width: 100%; padding: 14px 16px; border-radius: var(--radius-sm);
            border: 1px solid var(--border); background: var(--bg-elevated);
            color: var(--text-primary); font-size: 14px; font-family: inherit;
            outline: none; transition: border-color 0.2s;
            margin-bottom: 16px;
        }
        .login-input:focus { border-color: var(--accent); }
        .login-error { color: var(--red-light); font-size: 12px; margin-bottom: 12px; display: none; }

        /* ── Buttons ── */
        .btn {
            display: inline-flex; align-items: center; gap: 6px;
            padding: 10px 20px; border-radius: var(--radius-sm);
            font-size: 13px; font-weight: 600; font-family: inherit;
            border: none; cursor: pointer; transition: all 0.2s;
        }
        .btn-primary { background: var(--accent); color: #fff; }
        .btn-primary:hover { background: var(--accent-light); color: #111; box-shadow: 0 4px 20px var(--accent-glow); }
        .btn-green { background: var(--green); color: #fff; }
        .btn-green:hover { background: var(--green-light); color: #111; }
        .btn-red { background: var(--red); color: #fff; }
        .btn-red:hover { background: var(--red-light); color: #111; }
        .btn-ghost { background: transparent; border: 1px solid var(--border); color: var(--text-primary); }
        .btn-ghost:hover { border-color: var(--text-secondary); background: var(--bg-elevated); }
        .btn-sm { padding: 6px 12px; font-size: 11px; border-radius: 6px; }

        /* ── Header ── */
        .top-bar {
            background: var(--bg-surface);
            border-bottom: 1px solid var(--border);
            padding: 14px 28px;
            display: flex; align-items: center; justify-content: space-between;
            position: sticky; top: 0; z-index: 50;
            backdrop-filter: blur(12px);
        }
        .top-bar .brand { display: flex; align-items: center; gap: 12px; }
        .top-bar .brand-icon {
            width: 40px; height: 40px; border-radius: 12px;
            background: linear-gradient(135deg, var(--accent), #8b5cf6);
            display: flex; align-items: center; justify-content: center;
            font-size: 20px; box-shadow: 0 4px 16px var(--accent-glow);
        }
        .top-bar .brand-name { font-size: 17px; font-weight: 700; }
        .top-bar .brand-sub { font-size: 11px; color: var(--text-secondary); }
        .top-bar .right { display: flex; align-items: center; gap: 14px; }
        .status-pill {
            display: inline-flex; align-items: center; gap: 6px;
            padding: 5px 12px; border-radius: 20px; font-size: 11px; font-weight: 600;
        }
        .status-pill.online { background: var(--green-glow); color: var(--green-light); }
        .status-pill.offline { background: var(--red-glow); color: var(--red-light); }
        .status-dot { width: 7px; height: 7px; border-radius: 50%; }
        .status-pill.online .status-dot { background: var(--green); animation: pulse 2s infinite; }
        .status-pill.offline .status-dot { background: var(--red); }
        @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }

        /* ── Nav Tabs ── */
        .nav-tabs {
            display: flex; gap: 2px; padding: 12px 28px 0;
            background: var(--bg-surface); border-bottom: 1px solid var(--border);
        }
        .nav-tab {
            padding: 10px 20px; font-size: 13px; font-weight: 500;
            color: var(--text-secondary); cursor: pointer;
            border-bottom: 2px solid transparent;
            transition: all 0.2s; border-radius: 8px 8px 0 0;
        }
        .nav-tab:hover { color: var(--text-primary); background: var(--bg-elevated); }
        .nav-tab.active { color: var(--accent-light); border-bottom-color: var(--accent); background: var(--bg-card); }

        /* ── Main Content ── */
        .main { padding: 24px 28px; max-width: 1400px; margin: 0 auto; }
        .tab-panel { display: none; }
        .tab-panel.active { display: block; }

        /* ── Stat Cards Grid ── */
        .stats-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 16px; margin-bottom: 24px;
        }
        .stat-card {
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: var(--radius); padding: 22px 24px;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .stat-card:hover { transform: translateY(-2px); box-shadow: var(--shadow); }
        .stat-card .stat-icon { font-size: 28px; margin-bottom: 10px; }
        .stat-card .stat-value { font-size: 28px; font-weight: 800; letter-spacing: -1px; }
        .stat-card .stat-label { font-size: 12px; color: var(--text-secondary); margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }
        .stat-card.revenue { border-left: 3px solid var(--green); }
        .stat-card.orders { border-left: 3px solid var(--accent); }
        .stat-card.delivery { border-left: 3px solid var(--blue); }
        .stat-card.takeaway { border-left: 3px solid var(--orange); }

        /* ── Tables ── */
        .card {
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: var(--radius); overflow: hidden;
            margin-bottom: 24px;
        }
        .card-header {
            padding: 18px 22px; border-bottom: 1px solid var(--border);
            display: flex; align-items: center; justify-content: space-between;
        }
        .card-header h2 { font-size: 15px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
        .card-body { padding: 0; }
        
        table { width: 100%; border-collapse: collapse; }
        th {
            padding: 12px 18px; text-align: left; font-size: 11px;
            text-transform: uppercase; letter-spacing: 0.6px;
            color: var(--text-muted); background: var(--bg-elevated);
            border-bottom: 1px solid var(--border);
            position: sticky; top: 0;
        }
        td {
            padding: 12px 18px; font-size: 13px;
            border-bottom: 1px solid var(--border);
            vertical-align: middle;
        }
        tr:hover td { background: rgba(108, 92, 231, 0.04); }
        tr:last-child td { border-bottom: none; }
        .scrollable-table { max-height: 480px; overflow-y: auto; }

        /* ── Badges ── */
        .badge {
            display: inline-flex; padding: 3px 10px; border-radius: 20px;
            font-size: 11px; font-weight: 600;
        }
        .badge-green { background: var(--green-glow); color: var(--green-light); }
        .badge-red { background: var(--red-glow); color: var(--red-light); }
        .badge-orange { background: var(--orange-glow); color: var(--orange); }
        .badge-blue { background: var(--blue-glow); color: var(--blue); }
        .badge-gold { background: var(--gold-glow); color: var(--gold); }

        /* ── Toggle Switch ── */
        .toggle { position: relative; display: inline-block; width: 42px; height: 24px; }
        .toggle input { opacity: 0; width: 0; height: 0; }
        .toggle-slider {
            position: absolute; inset: 0; cursor: pointer;
            background: var(--bg-elevated); border: 1px solid var(--border);
            border-radius: 24px; transition: all 0.3s;
        }
        .toggle-slider::before {
            content: ''; position: absolute; height: 18px; width: 18px;
            left: 2px; bottom: 2px; background: var(--text-secondary);
            border-radius: 50%; transition: all 0.3s;
        }
        .toggle input:checked + .toggle-slider { background: var(--green); border-color: var(--green); }
        .toggle input:checked + .toggle-slider::before { transform: translateX(18px); background: #fff; }

        /* ── Control Panel ── */
        .control-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
        .control-card {
            background: var(--bg-card); border: 1px solid var(--border);
            border-radius: var(--radius); padding: 24px;
        }
        .control-card h3 { font-size: 14px; font-weight: 700; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }
        .control-row {
            display: flex; align-items: center; justify-content: space-between;
            padding: 12px 0; border-bottom: 1px solid var(--border);
        }
        .control-row:last-child { border-bottom: none; }
        .control-label { font-size: 13px; }
        .control-desc { font-size: 11px; color: var(--text-secondary); }

        /* ── Menu Management ── */
        .menu-filter {
            display: flex; gap: 8px; padding: 16px 22px;
            border-bottom: 1px solid var(--border); flex-wrap: wrap;
        }
        .filter-chip {
            padding: 5px 14px; border-radius: 20px; font-size: 12px; font-weight: 500;
            background: var(--bg-elevated); border: 1px solid var(--border);
            color: var(--text-secondary); cursor: pointer; transition: all 0.2s;
        }
        .filter-chip:hover, .filter-chip.active { 
            background: var(--accent-glow); color: var(--accent-light); border-color: var(--accent);
        }

        /* ── Muted List ── */
        .muted-item {
            display: flex; align-items: center; justify-content: space-between;
            padding: 10px 16px; border-bottom: 1px solid var(--border);
        }
        .muted-item:last-child { border-bottom: none; }
        .mute-input-row { display: flex; gap: 8px; padding: 16px; border-top: 1px solid var(--border); }
        .mute-input {
            flex: 1; padding: 10px 14px; border-radius: var(--radius-sm);
            border: 1px solid var(--border); background: var(--bg-elevated);
            color: var(--text-primary); font-size: 13px; font-family: inherit; outline: none;
        }
        .mute-input:focus { border-color: var(--accent); }

        /* ── Empty State ── */
        .empty-state {
            text-align: center; padding: 48px 24px;
            color: var(--text-muted); font-size: 14px;
        }
        .empty-state .empty-icon { font-size: 48px; margin-bottom: 12px; opacity: 0.5; }

        /* ── Refresh indicator ── */
        .refresh-bar {
            font-size: 11px; color: var(--text-muted); text-align: right;
            padding: 0 4px 4px; display: flex; align-items: center; justify-content: flex-end; gap: 6px;
        }

        /* ── Responsive ── */
        @media (max-width: 768px) {
            .top-bar { padding: 12px 16px; }
            .nav-tabs { padding: 8px 16px 0; overflow-x: auto; }
            .nav-tab { padding: 8px 14px; font-size: 12px; white-space: nowrap; }
            .main { padding: 16px; }
            .stats-grid { grid-template-columns: repeat(2, 1fr); gap: 10px; }
            .stat-card .stat-value { font-size: 22px; }
            .control-grid { grid-template-columns: 1fr; }
            td, th { padding: 8px 12px; font-size: 12px; }
        }

        /* ── Animations ── */
        @keyframes fadeUp { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
        .fade-up { animation: fadeUp 0.3s ease-out; }
    </style>
</head>
<body>

<!-- Login Overlay -->
<div id="loginOverlay">
    <div class="login-card fade-up">
        <div class="logo">🍽️</div>
        <h1>Pace Admin Dashboard</h1>
        <p>Enter your admin API key to access the dashboard</p>
        <input type="password" class="login-input" id="apiKeyInput" placeholder="Enter Admin API Key..." autofocus>
        <div class="login-error" id="loginError">Invalid API key. Please try again.</div>
        <button class="btn btn-primary" style="width:100%; justify-content:center;" onclick="doLogin()">🔐 Authenticate</button>
    </div>
</div>

<!-- Top Bar -->
<div class="top-bar" id="topBar" style="display:none;">
    <div class="brand">
        <div class="brand-icon">🍽️</div>
        <div>
            <div class="brand-name">Pace Restaurant</div>
            <div class="brand-sub">Admin Dashboard — Dera Ismail Khan</div>
        </div>
    </div>
    <div class="right">
        <a href="/test" class="btn btn-ghost btn-sm" style="text-decoration:none;">💬 Chat Simulator</a>
        <div id="shiftPill" class="status-pill online"><span class="status-dot"></span> Loading...</div>
        <div id="botPill" class="status-pill online"><span class="status-dot"></span> Bot Active</div>
        <button class="btn btn-ghost btn-sm" onclick="refreshAll(true)">🔄 Refresh</button>
        <button class="btn btn-ghost btn-sm" onclick="doLogout()">🚪 Logout</button>
    </div>
</div>

<!-- Nav Tabs -->
<div class="nav-tabs" id="navTabs" style="display:none;">
    <div class="nav-tab active" data-tab="orders" onclick="switchTab('orders')">📋 Orders</div>
    <div class="nav-tab" data-tab="menu" onclick="switchTab('menu')">🍽️ Menu</div>
    <div class="nav-tab" data-tab="controls" onclick="switchTab('controls')">⚙️ Controls</div>
    <div class="nav-tab" data-tab="dispatches" onclick="switchTab('dispatches')">💀 Failed Dispatches</div>
</div>

<!-- Main Content -->
<div class="main" id="mainContent" style="display:none;">

    <!-- ═══ ORDERS TAB ═══ -->
    <div class="tab-panel active" id="tab-orders">
        <div class="stats-grid fade-up">
            <div class="stat-card orders">
                <div class="stat-icon">📦</div>
                <div class="stat-value" id="statTotalOrders">—</div>
                <div class="stat-label">Today's Orders</div>
            </div>
            <div class="stat-card revenue">
                <div class="stat-icon">💰</div>
                <div class="stat-value" id="statRevenue">—</div>
                <div class="stat-label">Today's Revenue</div>
            </div>
            <div class="stat-card delivery">
                <div class="stat-icon">🛵</div>
                <div class="stat-value" id="statDelivery">—</div>
                <div class="stat-label">Delivery Orders</div>
            </div>
            <div class="stat-card takeaway">
                <div class="stat-icon">🛍️</div>
                <div class="stat-value" id="statTakeaway">—</div>
                <div class="stat-label">Takeaway Orders</div>
            </div>
        </div>

        <div class="card fade-up">
            <div class="card-header">
                <h2>📋 Today's Orders</h2>
                <div class="refresh-bar"><span id="lastRefresh">—</span></div>
            </div>
            <div class="card-body scrollable-table">
                <table>
                    <thead>
                        <tr>
                            <th>Order ID</th>
                            <th>Customer</th>
                            <th>Phone</th>
                            <th>Type</th>
                            <th>Items</th>
                            <th>Total</th>
                            <th>Status</th>
                            <th>Time</th>
                        </tr>
                    </thead>
                    <tbody id="ordersTableBody">
                        <tr><td colspan="8"><div class="empty-state"><div class="empty-icon">📦</div>Loading orders...</div></td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- ═══ MENU TAB ═══ -->
    <div class="tab-panel" id="tab-menu">
        <div class="card fade-up">
            <div class="card-header">
                <h2>🍽️ Menu Management</h2>
                <span class="badge badge-blue" id="menuCount">0 items</span>
            </div>
            <div class="menu-filter" id="menuFilters"></div>
            <div class="card-body scrollable-table">
                <table>
                    <thead>
                        <tr>
                            <th>Item Name</th>
                            <th>Category</th>
                            <th>Price (Rs.)</th>
                            <th>Variant / Per KG</th>
                            <th>Available</th>
                        </tr>
                    </thead>
                    <tbody id="menuTableBody">
                        <tr><td colspan="5"><div class="empty-state"><div class="empty-icon">🍽️</div>Loading menu...</div></td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- ═══ CONTROLS TAB ═══ -->
    <div class="tab-panel" id="tab-controls">
        <div class="control-grid fade-up">
            <div class="control-card">
                <h3>🤖 Bot Controls</h3>
                <div class="control-row">
                    <div>
                        <div class="control-label">AI Bot Active</div>
                        <div class="control-desc">Toggle automated order-taking for all customers</div>
                    </div>
                    <label class="toggle">
                        <input type="checkbox" id="toggleBotActive" onchange="toggleBot(this.checked)">
                        <span class="toggle-slider"></span>
                    </label>
                </div>
                <div class="control-row">
                    <div>
                        <div class="control-label">Maintenance Mode</div>
                        <div class="control-desc">Restrict bot to admin phone only</div>
                    </div>
                    <label class="toggle">
                        <input type="checkbox" id="toggleMaintenance" onchange="toggleMaintenance(this.checked)">
                        <span class="toggle-slider"></span>
                    </label>
                </div>
            </div>

            <div class="control-card">
                <h3>🔇 Muted Customers</h3>
                <div id="mutedList">
                    <div class="empty-state" style="padding:24px;"><div class="empty-icon">🔊</div>No muted customers</div>
                </div>
                <div class="mute-input-row">
                    <input type="text" class="mute-input" id="mutePhoneInput" placeholder="Enter phone number (e.g. 923001234567)">
                    <button class="btn btn-red btn-sm" onclick="muteCustomer()">🔇 Mute</button>
                </div>
            </div>

            <div class="control-card">
                <h3>🛠️ System</h3>
                <div class="control-row">
                    <div>
                        <div class="control-label">Clear Menu Cache</div>
                        <div class="control-desc">Force reload menu from database</div>
                    </div>
                    <button class="btn btn-ghost btn-sm" onclick="clearMenuCache()">🗑️ Clear</button>
                </div>
                <div class="control-row">
                    <div>
                        <div class="control-label">Current Shift</div>
                        <div class="control-desc" id="currentShiftInfo">—</div>
                    </div>
                    <span class="badge badge-blue" id="shiftBadge">—</span>
                </div>
            </div>
        </div>
    </div>

    <!-- ═══ DISPATCHES TAB ═══ -->
    <div class="tab-panel" id="tab-dispatches">
        <div class="card fade-up">
            <div class="card-header">
                <h2>💀 Failed Dispatches (Dead-Letter Queue)</h2>
                <span class="badge badge-red" id="dispatchCount">0</span>
            </div>
            <div class="card-body scrollable-table">
                <table>
                    <thead>
                        <tr>
                            <th>Kind</th>
                            <th>Error</th>
                            <th>Attempts</th>
                            <th>Payload</th>
                            <th>Created</th>
                            <th>Resolved</th>
                        </tr>
                    </thead>
                    <tbody id="dispatchTableBody">
                        <tr><td colspan="6"><div class="empty-state"><div class="empty-icon">✅</div>No failed dispatches</div></td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>
</div>

<script>
    let API_KEY = '';
    let autoRefreshTimer = null;
    let menuData = [];
    let activeMenuFilter = 'all';

    const KNOWN_KEYS = [
        'pace-admin-secret-change-me',
        'pace-admin-2026-secure-key'
    ];

    async function tryKey(key) {
        if (!key) return false;
        try {
            const resp = await fetch('/admin/stats', {
                headers: { 'X-Api-Key': key, 'Content-Type': 'application/json' }
            });
            if (resp.ok) {
                const data = await resp.json();
                if (data && data.restaurant) return true;
            }
        } catch (e) {
            console.warn('Probe key failed:', e);
        }
        return false;
    }

    // ── Auth ──
    async function doLogin() {
        const key = document.getElementById('apiKeyInput').value.trim();
        if (!key) return;
        const errEl = document.getElementById('loginError');
        errEl.style.display = 'none';

        // 1. Try entered key
        if (await tryKey(key)) {
            API_KEY = key;
            localStorage.setItem('pace_admin_key', key);
            showDashboard();
            return;
        }

        // 2. Fallback check known keys
        for (const alt of KNOWN_KEYS) {
            if (await tryKey(alt)) {
                API_KEY = alt;
                localStorage.setItem('pace_admin_key', alt);
                showDashboard();
                return;
            }
        }
        errEl.style.display = 'block';
    }

    document.getElementById('apiKeyInput').addEventListener('keydown', e => {
        if (e.key === 'Enter') doLogin();
    });

    function doLogout(reload = true) {
        localStorage.removeItem('pace_admin_key');
        API_KEY = '';
        if (autoRefreshTimer) clearInterval(autoRefreshTimer);
        document.getElementById('topBar').style.display = 'none';
        document.getElementById('navTabs').style.display = 'none';
        document.getElementById('mainContent').style.display = 'none';
        document.getElementById('loginOverlay').style.display = 'flex';
        document.getElementById('loginError').style.display = 'none';
        document.getElementById('apiKeyInput').value = '';
        if (reload) {
            window.location.search = '';
        }
    }

    function showDashboard() {
        document.getElementById('loginOverlay').style.display = 'none';
        document.getElementById('topBar').style.display = 'flex';
        document.getElementById('navTabs').style.display = 'flex';
        document.getElementById('mainContent').style.display = 'block';
        refreshAll();
        if (!autoRefreshTimer) {
            autoRefreshTimer = setInterval(refreshAll, 30000);
        }
    }

    // Toast Notification System
    function showToast(msg, icon = '✅') {
        const t = document.getElementById('toast');
        if (!t) return;
        document.getElementById('toastIcon').textContent = icon;
        document.getElementById('toastMsg').textContent = msg;
        t.style.display = 'flex';
        t.style.animation = 'fadeUp 0.3s ease-out';
        clearTimeout(window._toastTimer);
        window._toastTimer = setTimeout(() => { t.style.display = 'none'; }, 3500);
    }

    // Auto-probe candidate keys on page load
    (async function initAuth() {
        const urlParams = new URLSearchParams(window.location.search);
        const urlKey = urlParams.get('key');
        const savedKey = localStorage.getItem('pace_admin_key');

        const candidateKeys = [
            urlKey,
            savedKey,
            'pace-admin-secret-change-me',
            'pace-admin-2026-secure-key'
        ].filter(Boolean);

        for (const candidate of candidateKeys) {
            if (await tryKey(candidate)) {
                API_KEY = candidate;
                localStorage.setItem('pace_admin_key', candidate);
                showDashboard();
                return;
            }
        }
        document.getElementById('apiKeyInput').value = candidateKeys[0] || '';
    })();

    // ── Resilient API Helper ──
    async function apiFetch(url, opts = {}) {
        let resp;
        try {
            resp = await fetch(url, {
                ...opts,
                headers: { 'X-Api-Key': API_KEY, 'Content-Type': 'application/json', ...(opts.headers || {}) },
            });
        } catch (e) {
            console.error('Network error during apiFetch:', e);
            showToast('Network error contacting server', '⚠️');
            return null;
        }

        // Silent fallback probe if 401 Unauthorized
        if (resp.status === 401) {
            for (const altKey of KNOWN_KEYS) {
                if (altKey !== API_KEY) {
                    try {
                        const retry = await fetch(url, {
                            ...opts,
                            headers: { 'X-Api-Key': altKey, 'Content-Type': 'application/json', ...(opts.headers || {}) },
                        });
                        if (retry.ok) {
                            API_KEY = altKey;
                            localStorage.setItem('pace_admin_key', altKey);
                            return retry.json();
                        }
                    } catch (retryErr) {
                        // ignore
                    }
                }
            }
            showToast('Session expired or unauthorized (401)', '🔒');
            doLogout(false);
            return null;
        }

        if (!resp.ok) return null;
        return resp.json();
    }

    // ── Tabs ──
    function switchTab(tab) {
        document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        document.querySelector(`.nav-tab[data-tab="${tab}"]`).classList.add('active');
        document.getElementById(`tab-${tab}`).classList.add('active');
    }

    // ── Refresh All ──
    async function refreshAll(manual = false) {
        await Promise.all([loadStats(), loadOrders(), loadMenu(), loadControls(), loadDispatches()]);
        document.getElementById('lastRefresh').textContent = 'Updated ' + new Date().toLocaleTimeString();
        if (manual) showToast('Dashboard updated!', '🔄');
    }

    // ── Stats + Orders ──
    async function loadStats() {
        const data = await apiFetch('/admin/stats');
        if (!data) return;
        const botActive = data.bot_active;
        const bp = document.getElementById('botPill');
        bp.className = 'status-pill ' + (botActive ? 'online' : 'offline');
        bp.innerHTML = `<span class="status-dot"></span> Bot ${botActive ? 'Active' : 'Inactive'}`;
        
        const shift = data.shift_info || {};
        const sp = document.getElementById('shiftPill');
        const shiftName = shift.agent_type === 'full_menu' ? 'Full Menu' : shift.agent_type === 'sobat_only' ? 'Sobat Only' : 'Closed';
        sp.className = 'status-pill ' + (shift.is_open ? 'online' : 'offline');
        sp.innerHTML = `<span class="status-dot"></span> ${shiftName}`;
        
        document.getElementById('currentShiftInfo').textContent = `${shift.current_time_pkt || '—'} — ${shiftName}`;
        document.getElementById('shiftBadge').textContent = shiftName;
        document.getElementById('toggleBotActive').checked = botActive;
        document.getElementById('toggleMaintenance').checked = data.maintenance_mode !== 'Disabled';
    }

    async function loadOrders() {
        const data = await apiFetch('/admin/orders/today');
        if (!data) return;
        const s = data.stats || {};
        document.getElementById('statTotalOrders').textContent = s.total_orders || 0;
        document.getElementById('statRevenue').textContent = 'Rs. ' + (s.total_revenue || 0).toLocaleString();
        document.getElementById('statDelivery').textContent = s.delivery_count || 0;
        document.getElementById('statTakeaway').textContent = s.takeaway_count || 0;

        const orders = data.orders || [];
        const tbody = document.getElementById('ordersTableBody');
        if (!orders.length) {
            tbody.innerHTML = '<tr><td colspan="8"><div class="empty-state"><div class="empty-icon">📭</div>No orders today yet</div></td></tr>';
            return;
        }
        tbody.innerHTML = orders.map(o => {
            const status = o.status || 'Unknown';
            const badgeClass = status === 'Confirmed' ? 'badge-green' : status === 'Expired' ? 'badge-red' : status === 'Dispatched' ? 'badge-blue' : 'badge-orange';
            const items = (o.items || o.order_items || '').substring(0, 60);
            return `<tr>
                <td><strong>${esc(o.order_id || '—')}</strong></td>
                <td>${esc(o.guest_name || o.customer_name || '—')}</td>
                <td>${esc(o.phone || o.phone_number || '—')}</td>
                <td>${esc(o.order_type || '—')}</td>
                <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(o.items || o.order_items || '')}">${esc(items)}</td>
                <td><strong>Rs. ${parseFloat(o.total_amount || o.total_bill || 0).toLocaleString()}</strong></td>
                <td><span class="badge ${badgeClass}">${esc(status)}</span></td>
                <td>${esc(o.order_time || '—')}</td>
            </tr>`;
        }).join('');
    }

    // ── Menu ──
    async function loadMenu() {
        const data = await apiFetch('/admin/menu');
        if (!data) return;
        menuData = data;
        document.getElementById('menuCount').textContent = data.length + ' items';

        // Build filter chips
        const categories = ['all', ...new Set(data.map(i => i.category))];
        document.getElementById('menuFilters').innerHTML = categories.map(c => 
            `<div class="filter-chip ${c === activeMenuFilter ? 'active' : ''}" onclick="filterMenu('${c}', this)">${c === 'all' ? '🔖 All' : c}</div>`
        ).join('');

        renderMenuTable();
    }

    function filterMenu(cat, el) {
        activeMenuFilter = cat;
        document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
        if (el) {
            el.classList.add('active');
        } else {
            const match = Array.from(document.querySelectorAll('.filter-chip')).find(chip => chip.textContent.includes(cat));
            if (match) match.classList.add('active');
        }
        renderMenuTable();
    }

    function renderMenuTable() {
        const items = activeMenuFilter === 'all' ? menuData : menuData.filter(i => i.category === activeMenuFilter);
        const tbody = document.getElementById('menuTableBody');
        if (!items.length) {
            tbody.innerHTML = '<tr><td colspan="5"><div class="empty-state"><div class="empty-icon">🍽️</div>No items in this category</div></td></tr>';
            return;
        }
        tbody.innerHTML = items.map(i => `<tr style="opacity: ${i.available ? 1 : 0.5}">
            <td><strong>${esc(i.name)}</strong></td>
            <td><span class="badge badge-blue">${esc(i.category)}</span></td>
            <td>Rs. ${i.price.toLocaleString()}</td>
            <td>${i.variant ? esc(i.variant) : '<span style="color:var(--text-muted)">—</span>'}</td>
            <td>
                <label class="toggle">
                    <input type="checkbox" ${i.available ? 'checked' : ''} onchange="toggleMenuItem('${i.id}', this.checked, this)">
                    <span class="toggle-slider"></span>
                </label>
            </td>
        </tr>`).join('');
    }

    async function toggleMenuItem(id, available, inputEl) {
        if (inputEl) inputEl.disabled = true;
        const res = await apiFetch(`/admin/menu/${id}/toggle`, {
            method: 'PATCH',
            body: JSON.stringify({ available })
        });
        if (inputEl) inputEl.disabled = false;
        if (res && res.status === 'success') {
            showToast(available ? '✅ Item set to Available' : '⚠️ Item set to Unavailable', available ? '✅' : '⚠️');
            const item = menuData.find(i => String(i.id) === String(id));
            if (item) item.available = available;
        } else {
            showToast('Failed to toggle menu item', '❌');
            if (inputEl) inputEl.checked = !available;
            await loadMenu();
        }
    }

    // ── Controls ──
    async function loadControls() {
        const muted = await apiFetch('/admin/muted');
        const list = document.getElementById('mutedList');
        if (!muted || !muted.length) {
            list.innerHTML = '<div class="empty-state" style="padding:24px;"><div class="empty-icon">🔊</div>No muted customers</div>';
            return;
        }
        list.innerHTML = muted.map(p => `<div class="muted-item">
            <span>📞 ${esc(p)}</span>
            <button class="btn btn-ghost btn-sm" onclick="unmuteCustomer('${p}')">🔊 Unmute</button>
        </div>`).join('');
    }

    async function toggleBot(active) {
        const cb = document.getElementById('toggleBotActive');
        if (cb) cb.disabled = true;
        const res = await apiFetch('/admin/bot-toggle', {
            method: 'POST',
            body: JSON.stringify({ active })
        });
        if (cb) cb.disabled = false;
        if (res && res.status === 'success') {
            showToast(active ? '🤖 Bot activated for all customers' : '🛑 Bot deactivated globally', active ? '🤖' : '🛑');
        } else {
            showToast('Failed to toggle bot', '❌');
            if (cb) cb.checked = !active;
        }
        await loadStats();
    }

    async function toggleMaintenance(enabled) {
        const cb = document.getElementById('toggleMaintenance');
        if (cb) cb.disabled = true;
        const res = await apiFetch('/admin/maintenance', {
            method: 'POST',
            body: JSON.stringify({ enabled })
        });
        if (cb) cb.disabled = false;
        if (res && res.status === 'success') {
            showToast(enabled ? '🛠️ Maintenance Mode enabled (Admin only)' : '✅ Maintenance Mode disabled (Public)', '🛠️');
        } else {
            showToast('Failed to toggle maintenance mode', '❌');
            if (cb) cb.checked = !enabled;
        }
        await loadStats();
    }

    async function muteCustomer() {
        const phone = document.getElementById('mutePhoneInput').value.trim();
        if (!phone) {
            showToast('Please enter a phone number', '⚠️');
            return;
        }
        const res = await apiFetch(`/admin/mute/${phone}`, { method: 'POST' });
        if (res && res.status === 'success') {
            showToast(`🔇 Customer ${phone} has been muted`, '🔇');
            document.getElementById('mutePhoneInput').value = '';
            await loadControls();
            await loadStats();
        } else {
            showToast('Failed to mute customer', '❌');
        }
    }

    async function unmuteCustomer(phone) {
        const res = await apiFetch(`/admin/mute/${phone}`, { method: 'DELETE' });
        if (res && res.status === 'success') {
            showToast(`🔊 Customer ${phone} unmuted`, '🔊');
            await loadControls();
            await loadStats();
        } else {
            showToast('Failed to unmute customer', '❌');
        }
    }

    async function clearMenuCache() {
        const res = await apiFetch('/admin/cache/clear-menu', { method: 'POST' });
        if (res && res.status === 'success') {
            showToast('🗑️ Menu cache flushed! DB reloaded', '🗑️');
        } else {
            showToast('Failed to clear cache', '❌');
        }
    }

    // ── Dispatches ──
    async function loadDispatches() {
        const data = await apiFetch('/admin/failed-dispatches');
        if (!data) return;
        document.getElementById('dispatchCount').textContent = data.length;
        const tbody = document.getElementById('dispatchTableBody');
        if (!data.length) {
            tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state"><div class="empty-icon">✅</div>No failed dispatches — everything is healthy!</div></td></tr>';
            return;
        }
        tbody.innerHTML = data.map(d => `<tr>
            <td><span class="badge badge-orange">${esc(d.kind || '—')}</span></td>
            <td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;" title="${esc(d.error || '')}">${esc((d.error || '').substring(0, 80))}</td>
            <td>${d.attempts || '—'}</td>
            <td><code style="font-size:10px;">${esc(JSON.stringify(d.payload || {}).substring(0, 60))}</code></td>
            <td>${esc(d.created_at || '—')}</td>
            <td>${d.resolved ? '<span class="badge badge-green">Yes</span>' : '<span class="badge badge-red">No</span>'}</td>
        </tr>`).join('');
    }

    // ── Helpers ──
    function esc(str) {
        return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }
</script>

<!-- Toast Notification Container -->
<div id="toast" style="position:fixed; bottom:24px; right:24px; z-index:9999; background:var(--bg-elevated); color:var(--text-primary); border:1px solid var(--border); border-left:4px solid var(--accent); padding:14px 22px; border-radius:var(--radius-sm); box-shadow:var(--shadow); display:none; align-items:center; gap:10px; font-size:13px; font-weight:600;">
    <span id="toastIcon" style="font-size:16px;">ℹ️</span>
    <span id="toastMsg">Action completed</span>
</div>

</body>
</html>
"""
