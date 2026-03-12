"""Web dashboard — monitor and control the bot from your browser."""

import asyncio
import json
import logging
from datetime import datetime
from aiohttp import web

logger = logging.getLogger(__name__)

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Polymarket Bot Dashboard</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, system-ui, sans-serif;
    background: #0a0a0f;
    color: #e0e0e0;
    min-height: 100vh;
    padding: 16px;
    padding-bottom: 80px;
  }
  h1 { font-size: 20px; color: #00ff88; margin-bottom: 4px; }
  .subtitle { color: #888; font-size: 13px; margin-bottom: 12px; }
  .mode-badge {
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 11px; font-weight: 700; text-transform: uppercase;
  }
  .mode-sim { background: #1a3a2a; color: #00ff88; border: 1px solid #00ff88; }
  .mode-live { background: #3a1a1a; color: #ff4444; border: 1px solid #ff4444; }
  .mode-dry { background: #2a2a1a; color: #ffaa00; border: 1px solid #ffaa00; }

  /* Control Buttons */
  .controls {
    display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap;
  }
  .btn {
    padding: 10px 20px; border-radius: 10px; border: none;
    font-size: 14px; font-weight: 700; cursor: pointer;
    transition: all 0.2s; flex: 1; min-width: 90px;
    text-transform: uppercase; letter-spacing: 1px;
  }
  .btn:active { transform: scale(0.96); }
  .btn-sim {
    background: #1a3a2a; color: #00ff88; border: 2px solid #00ff88;
  }
  .btn-sim:hover, .btn-sim.active { background: #00ff88; color: #000; }
  .btn-live {
    background: #3a1a1a; color: #ff4444; border: 2px solid #ff4444;
  }
  .btn-live:hover, .btn-live.active { background: #ff4444; color: #fff; }
  .btn-stop {
    background: #2a2a1a; color: #ffaa00; border: 2px solid #ffaa00;
  }
  .btn-stop:hover, .btn-stop.active { background: #ffaa00; color: #000; }
  .btn-disabled { opacity: 0.4; pointer-events: none; }

  /* Grid */
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 16px; }
  .card {
    background: #12121a; border: 1px solid #1e1e2e;
    border-radius: 12px; padding: 14px;
  }
  .card-full { grid-column: 1 / -1; }
  .card-label { font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 1px; }
  .card-value { font-size: 24px; font-weight: 700; margin-top: 4px; }
  .green { color: #00ff88; }
  .red { color: #ff4466; }
  .yellow { color: #ffaa00; }
  .blue { color: #4488ff; }
  .white { color: #e0e0e0; }

  /* P&L Section */
  .pnl-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-top: 8px; }
  .pnl-item {
    background: #0a0a14; border-radius: 8px; padding: 10px; text-align: center;
  }
  .pnl-item .card-label { margin-bottom: 4px; }
  .pnl-value { font-size: 18px; font-weight: 700; }
  .pnl-bar {
    height: 6px; border-radius: 3px; background: #1a1a24; margin-top: 8px; overflow: hidden;
  }
  .pnl-bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s; }

  /* Config Panel */
  .config-toggle {
    display: flex; align-items: center; justify-content: space-between;
    cursor: pointer; padding: 8px 0;
  }
  .config-toggle .card-label { cursor: pointer; }
  .config-arrow { transition: transform 0.3s; font-size: 14px; color: #666; }
  .config-arrow.open { transform: rotate(180deg); }
  .config-body { display: none; padding-top: 8px; }
  .config-body.open { display: block; }
  .config-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 0; border-bottom: 1px solid #1a1a24;
  }
  .config-row:last-child { border-bottom: none; }
  .config-name { font-size: 13px; color: #aaa; }
  .config-input {
    background: #0a0a14; border: 1px solid #2a2a3a; border-radius: 8px;
    color: #e0e0e0; padding: 8px 12px; width: 120px; text-align: right;
    font-size: 14px; font-weight: 600;
  }
  .config-input:focus { outline: none; border-color: #00ff88; }
  .config-select {
    background: #0a0a14; border: 1px solid #2a2a3a; border-radius: 8px;
    color: #e0e0e0; padding: 8px 12px; font-size: 14px;
  }
  .btn-save {
    width: 100%; padding: 12px; margin-top: 12px; border-radius: 10px;
    background: #1a2a3a; color: #4488ff; border: 2px solid #4488ff;
    font-size: 14px; font-weight: 700; cursor: pointer;
    text-transform: uppercase; letter-spacing: 1px;
  }
  .btn-save:active { background: #4488ff; color: #fff; }
  .toast {
    position: fixed; top: 20px; left: 50%; transform: translateX(-50%);
    background: #1a3a2a; color: #00ff88; border: 1px solid #00ff88;
    padding: 10px 24px; border-radius: 10px; font-size: 13px; font-weight: 600;
    z-index: 100; display: none; animation: fadeIn 0.3s;
  }
  .toast.error { background: #3a1a1a; color: #ff4466; border-color: #ff4466; }
  @keyframes fadeIn { from { opacity: 0; transform: translateX(-50%) translateY(-10px); } to { opacity: 1; transform: translateX(-50%) translateY(0); } }

  /* Agent grid */
  .agent-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .agent-pill {
    display: flex; align-items: center; gap: 6px;
    background: #1a1a24; border-radius: 8px; padding: 8px 10px; font-size: 12px;
  }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .dot-green { background: #00ff88; box-shadow: 0 0 6px #00ff88; }
  .dot-red { background: #ff4466; box-shadow: 0 0 6px #ff4466; }
  .dot-gray { background: #444; }

  /* Trades */
  .trades-list { max-height: 300px; overflow-y: auto; }
  .trade-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 8px 0; border-bottom: 1px solid #1a1a24; font-size: 12px;
  }
  .trade-side { font-weight: 700; width: 32px; }
  .trade-detail { color: #888; flex: 1; margin-left: 8px; }

  /* Opportunities */
  .opp-row {
    background: #0a1a10; border: 1px solid #1a3a2a;
    border-radius: 8px; padding: 10px; margin-bottom: 6px; font-size: 12px;
  }
  .opp-question { color: #ccc; margin-bottom: 4px; }
  .opp-stats { display: flex; gap: 8px; color: #00ff88; font-weight: 600; flex-wrap: wrap; font-size: 11px; }

  /* Bottom bar */
  .refresh-bar {
    position: fixed; bottom: 0; left: 0; right: 0;
    background: #12121a; border-top: 1px solid #1e1e2e;
    padding: 8px 16px;
    display: flex; justify-content: space-between; align-items: center;
    font-size: 11px; color: #666;
  }
  .pulse { animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }

  /* Confirm modal */
  .modal-overlay {
    display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.8); z-index: 200; align-items: center; justify-content: center;
  }
  .modal-overlay.open { display: flex; }
  .modal {
    background: #12121a; border: 1px solid #2a2a3a; border-radius: 16px;
    padding: 24px; max-width: 340px; width: 90%; text-align: center;
  }
  .modal h2 { color: #ff4444; font-size: 18px; margin-bottom: 12px; }
  .modal p { color: #aaa; font-size: 13px; margin-bottom: 20px; line-height: 1.5; }
  .modal-btns { display: flex; gap: 10px; }
  .modal-btns .btn { flex: 1; padding: 12px; font-size: 13px; }
</style>
</head>
<body>
  <div id="toast" class="toast"></div>

  <!-- Confirm modal for Live mode -->
  <div id="confirm-modal" class="modal-overlay">
    <div class="modal">
      <h2>Go Live?</h2>
      <p>This will use REAL money on Polymarket. Make sure your API keys are configured and you understand the risks.</p>
      <div class="modal-btns">
        <button class="btn btn-stop" onclick="closeModal()">Cancel</button>
        <button class="btn btn-live" onclick="confirmGoLive()">Go Live</button>
      </div>
    </div>
  </div>

  <h1>Polymarket Market Maker</h1>
  <div class="subtitle">
    <span id="mode-badge" class="mode-badge mode-sim">SIMULATION</span>
    <span id="uptime" style="margin-left:8px;"></span>
  </div>

  <!-- Control Buttons -->
  <div class="controls">
    <button class="btn btn-sim" id="btn-sim" onclick="switchMode('simulate')">Simulate</button>
    <button class="btn btn-live" id="btn-live" onclick="showLiveConfirm()">Go Live</button>
    <button class="btn btn-stop" id="btn-stop" onclick="switchMode('stop')">Stop</button>
  </div>

  <!-- P&L Section -->
  <div class="card card-full" style="margin-bottom:12px;">
    <div class="card-label">Profit & Loss</div>
    <div class="card-value" id="pnl-total" style="font-size:32px;">+$0.00</div>
    <div style="font-size:11px;color:#666;margin-top:2px;" id="pnl-pct">0.00%</div>
    <div class="pnl-bar"><div class="pnl-bar-fill" id="pnl-bar" style="width:50%;background:#00ff88;"></div></div>
    <div class="pnl-grid">
      <div class="pnl-item">
        <div class="card-label">Guaranteed</div>
        <div class="pnl-value green" id="pnl-guaranteed">$0.00</div>
      </div>
      <div class="pnl-item">
        <div class="card-label">Unrealized</div>
        <div class="pnl-value yellow" id="pnl-unrealized">$0.00</div>
      </div>
      <div class="pnl-item">
        <div class="card-label">Fees Paid</div>
        <div class="pnl-value red" id="pnl-fees">$0.00</div>
      </div>
    </div>
  </div>

  <!-- Stats Grid -->
  <div class="grid">
    <div class="card">
      <div class="card-label">Balance</div>
      <div class="card-value green" id="balance">$0.00</div>
    </div>
    <div class="card">
      <div class="card-label">Total Trades</div>
      <div class="card-value blue" id="trades">0</div>
    </div>
    <div class="card">
      <div class="card-label">Capital Spent</div>
      <div class="card-value yellow" id="capital-spent">$0.00</div>
      <div class="pnl-bar" style="margin-top:6px;"><div class="pnl-bar-fill" id="cap-bar" style="width:0%;background:#ffaa00;"></div></div>
    </div>
    <div class="card">
      <div class="card-label">Capital Max</div>
      <div class="card-value white" id="capital-max">Unlimited</div>
    </div>
    <div class="card">
      <div class="card-label">Hedged Pairs</div>
      <div class="card-value green" id="hedged">0</div>
    </div>
    <div class="card">
      <div class="card-label">BTC Markets</div>
      <div class="card-value yellow" id="markets">0</div>
    </div>
    <div class="card">
      <div class="card-label">Total Invested</div>
      <div class="card-value blue" id="invested">$0.00</div>
    </div>
    <div class="card">
      <div class="card-label">Win Rate</div>
      <div class="card-value green" id="winrate">-</div>
    </div>
  </div>

  <!-- Config Panel -->
  <div class="card card-full" style="margin-bottom:12px;">
    <div class="config-toggle" onclick="toggleConfig()">
      <div class="card-label">Configuration</div>
      <span class="config-arrow" id="config-arrow">&#9660;</span>
    </div>
    <div class="config-body" id="config-body">
      <div class="config-row">
        <span class="config-name">Capital Max ($)</span>
        <input type="number" class="config-input" id="cfg-capital-max" value="500" min="0" step="100">
      </div>
      <div class="config-row">
        <span class="config-name">Order Size ($)</span>
        <input type="number" class="config-input" id="cfg-order-size" value="10" min="1" step="1">
      </div>
      <div class="config-row">
        <span class="config-name">Max Markets</span>
        <input type="number" class="config-input" id="cfg-max-markets" value="20" min="1" step="1">
      </div>
      <div class="config-row">
        <span class="config-name">Max Combined Cost</span>
        <input type="number" class="config-input" id="cfg-max-cost" value="0.97" min="0.5" max="1.0" step="0.01">
      </div>
      <div class="config-row">
        <span class="config-name">Min Profit Margin</span>
        <input type="number" class="config-input" id="cfg-min-profit" value="0.02" min="-0.05" max="0.5" step="0.01">
      </div>
      <div class="config-row">
        <span class="config-name">Market Focus</span>
        <select class="config-select" id="cfg-btc-only">
          <option value="true">BTC Only</option>
          <option value="false">All Markets</option>
        </select>
      </div>
      <div class="config-row">
        <span class="config-name">Scan Interval (s)</span>
        <input type="number" class="config-input" id="cfg-scan-interval" value="60" min="10" step="5">
      </div>
      <div class="config-row">
        <span class="config-name">Price Update (s)</span>
        <input type="number" class="config-input" id="cfg-price-interval" value="5" min="1" step="1">
      </div>
      <button class="btn-save" onclick="saveConfig()">Save Configuration</button>
    </div>
  </div>

  <!-- Agents -->
  <div class="card card-full" style="margin-bottom:12px;">
    <div class="card-label" style="margin-bottom:8px;">Agents (10)</div>
    <div class="agent-grid" id="agents"></div>
  </div>

  <!-- Opportunities -->
  <div class="card card-full" style="margin-bottom:12px;">
    <div class="card-label" style="margin-bottom:8px;">Active Opportunities</div>
    <div id="opportunities"><span style="color:#444;font-size:12px;">Scanning...</span></div>
  </div>

  <!-- Trades -->
  <div class="card card-full" style="margin-bottom:12px;">
    <div class="card-label" style="margin-bottom:8px;">Recent Trades</div>
    <div class="trades-list" id="trade-list">
      <span style="color:#444;font-size:12px;">No trades yet</span>
    </div>
  </div>

  <div class="refresh-bar">
    <span><span class="pulse" style="color:#00ff88;">&#9679;</span> Live</span>
    <span id="last-update">Connecting...</span>
  </div>

<script>
let currentMode = 'SIMULATION';
let currentConfig = {};

function showToast(msg, isError) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = isError ? 'toast error' : 'toast';
  t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 3000);
}

function toggleConfig() {
  const body = document.getElementById('config-body');
  const arrow = document.getElementById('config-arrow');
  body.classList.toggle('open');
  arrow.classList.toggle('open');
}

function showLiveConfirm() {
  document.getElementById('confirm-modal').classList.add('open');
}
function closeModal() {
  document.getElementById('confirm-modal').classList.remove('open');
}
function confirmGoLive() {
  closeModal();
  switchMode('live');
}

async function switchMode(mode) {
  try {
    const resp = await fetch('/api/mode', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mode: mode})
    });
    const result = await resp.json();
    if (result.ok) {
      showToast('Mode: ' + mode.toUpperCase(), false);
      updateButtons(mode);
    } else {
      showToast(result.error || 'Failed to switch mode', true);
    }
  } catch(e) {
    showToast('Error: ' + e.message, true);
  }
}

async function saveConfig() {
  const config = {
    capital_max: parseFloat(document.getElementById('cfg-capital-max').value) || 0,
    order_size: parseFloat(document.getElementById('cfg-order-size').value) || 10,
    max_markets: parseInt(document.getElementById('cfg-max-markets').value) || 20,
    max_combined_cost: parseFloat(document.getElementById('cfg-max-cost').value) || 0.97,
    min_profit_margin: parseFloat(document.getElementById('cfg-min-profit').value) || 0.02,
    btc_only: document.getElementById('cfg-btc-only').value === 'true',
    market_scan_interval: parseFloat(document.getElementById('cfg-scan-interval').value) || 60,
    price_update_interval: parseFloat(document.getElementById('cfg-price-interval').value) || 5,
  };
  try {
    const resp = await fetch('/api/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(config)
    });
    const result = await resp.json();
    if (result.ok) {
      showToast('Config saved!', false);
    } else {
      showToast(result.error || 'Save failed', true);
    }
  } catch(e) {
    showToast('Error: ' + e.message, true);
  }
}

function updateButtons(mode) {
  document.getElementById('btn-sim').classList.toggle('active', mode === 'simulate' || currentMode === 'SIMULATION');
  document.getElementById('btn-live').classList.toggle('active', mode === 'live' || currentMode === 'LIVE');
  document.getElementById('btn-stop').classList.toggle('active', mode === 'stop');
}

function populateConfig(d) {
  const cfg = d.config || {};
  if (cfg.capital_max !== undefined) document.getElementById('cfg-capital-max').value = cfg.capital_max || 0;
  if (cfg.order_size !== undefined) document.getElementById('cfg-order-size').value = cfg.order_size || 10;
  if (cfg.max_markets !== undefined) document.getElementById('cfg-max-markets').value = cfg.max_markets || 20;
  if (cfg.max_combined_cost !== undefined) document.getElementById('cfg-max-cost').value = cfg.max_combined_cost || 0.97;
  if (cfg.min_profit_margin !== undefined) document.getElementById('cfg-min-profit').value = cfg.min_profit_margin || 0.02;
  if (cfg.btc_only !== undefined) document.getElementById('cfg-btc-only').value = cfg.btc_only ? 'true' : 'false';
  if (cfg.market_scan_interval !== undefined) document.getElementById('cfg-scan-interval').value = cfg.market_scan_interval || 60;
  if (cfg.price_update_interval !== undefined) document.getElementById('cfg-price-interval').value = cfg.price_update_interval || 5;
}

async function fetchData() {
  try {
    const resp = await fetch('/api/status');
    const d = await resp.json();

    currentMode = d.mode || 'SIMULATION';

    // Mode badge
    const badge = document.getElementById('mode-badge');
    if (d.mode === 'SIMULATION') { badge.className = 'mode-badge mode-sim'; badge.textContent = 'SIMULATION'; }
    else if (d.mode === 'LIVE') { badge.className = 'mode-badge mode-live'; badge.textContent = 'LIVE'; }
    else { badge.className = 'mode-badge mode-dry'; badge.textContent = d.mode || 'DRY RUN'; }

    // Button states
    document.getElementById('btn-sim').classList.toggle('active', d.mode === 'SIMULATION');
    document.getElementById('btn-live').classList.toggle('active', d.mode === 'LIVE');

    // Stats
    const sim = d.simulation || {};
    document.getElementById('balance').textContent = '$' + (sim.balance || 0).toFixed(2);
    document.getElementById('trades').textContent = sim.total_trades || 0;

    const portfolio = d.portfolio || {};

    // P&L section
    const guaranteedProfit = portfolio.guaranteed_profit || 0;
    const totalSpent = sim.total_spent || 0;
    const fees = sim.total_fees || 0;
    const unrealized = (sim.balance || 0) - ((sim.starting_balance || 1000) - totalSpent);
    const totalPnl = guaranteedProfit;

    const pnlEl = document.getElementById('pnl-total');
    pnlEl.textContent = (totalPnl >= 0 ? '+$' : '-$') + Math.abs(totalPnl).toFixed(2);
    pnlEl.className = 'card-value ' + (totalPnl >= 0 ? 'green' : 'red');

    const startBal = sim.starting_balance || 1000;
    const pnlPct = startBal > 0 ? (totalPnl / startBal * 100) : 0;
    document.getElementById('pnl-pct').textContent = (pnlPct >= 0 ? '+' : '') + pnlPct.toFixed(2) + '% return';

    // P&L bar (center at 50%, green right if profit, red left if loss)
    const barEl = document.getElementById('pnl-bar');
    const barPct = Math.min(Math.abs(pnlPct), 50);
    if (totalPnl >= 0) {
      barEl.style.width = (50 + barPct) + '%';
      barEl.style.background = 'linear-gradient(90deg, #1a1a24 50%, #00ff88 50%)';
    } else {
      barEl.style.width = (50 + barPct) + '%';
      barEl.style.background = 'linear-gradient(90deg, #ff4466 ' + (50 - barPct) + '%, #1a1a24 50%)';
    }

    document.getElementById('pnl-guaranteed').textContent = '$' + guaranteedProfit.toFixed(2);
    document.getElementById('pnl-unrealized').textContent = '$' + unrealized.toFixed(2);
    document.getElementById('pnl-fees').textContent = '-$' + fees.toFixed(2);

    // Capital
    document.getElementById('capital-spent').textContent = '$' + totalSpent.toFixed(2);
    const capMax = sim.capital_max || 0;
    document.getElementById('capital-max').textContent = capMax > 0 ? '$' + capMax.toFixed(2) : 'Unlimited';

    // Capital bar
    if (capMax > 0) {
      const capPct = Math.min((totalSpent / capMax) * 100, 100);
      document.getElementById('cap-bar').style.width = capPct + '%';
      document.getElementById('cap-bar').style.background = capPct > 90 ? '#ff4466' : '#ffaa00';
    }

    document.getElementById('hedged').textContent = (portfolio.hedged_pairs || 0).toFixed(0);
    document.getElementById('markets').textContent = d.btc_markets || d.markets_tracked || 0;
    document.getElementById('invested').textContent = '$' + (portfolio.total_invested || 0).toFixed(2);

    // Win rate (hedged pairs that are profitable)
    const hedged = portfolio.hedged_pairs || 0;
    if (hedged > 0 && guaranteedProfit > 0) {
      document.getElementById('winrate').textContent = '100%';
      document.getElementById('winrate').className = 'card-value green';
    } else if (sim.total_trades > 0) {
      document.getElementById('winrate').textContent = '-';
    }

    // Populate config from server
    if (d.config && !document.getElementById('config-body').classList.contains('open')) {
      populateConfig(d);
    }

    // Agents
    const agentsEl = document.getElementById('agents');
    agentsEl.innerHTML = '';
    (d.agents || []).forEach(a => {
      const dot = a.healthy ? 'dot-green' : (a.running ? 'dot-red' : 'dot-gray');
      agentsEl.innerHTML += '<div class="agent-pill"><div class="dot ' + dot + '"></div>' + a.name + '<span style="color:#444;margin-left:auto;font-size:10px;">' + (a.cycles || 0) + 'c</span></div>';
    });

    // Opportunities
    const oppEl = document.getElementById('opportunities');
    const opps = d.opportunities || [];
    if (opps.length === 0) {
      oppEl.innerHTML = '<span style="color:#444;font-size:12px;">Scanning for spreads...</span>';
    } else {
      oppEl.innerHTML = opps.map(o => {
        const profitColor = (o.profit || 0) > 0 ? '#00ff88' : (o.profit || 0) < 0 ? '#ff4466' : '#888';
        return '<div class="opp-row"><div class="opp-question">' + (o.question || '').substring(0, 55) +
          '</div><div class="opp-stats"><span>Y@' + (o.yes_ask||0).toFixed(3) +
          '</span><span>N@' + (o.no_ask||0).toFixed(3) +
          '</span><span>=' + (o.combined||0).toFixed(3) +
          '</span><span style="color:' + profitColor + '">$' + (o.profit||0).toFixed(3) + '</span></div></div>';
      }).join('');
    }

    // Trades
    const tradeEl = document.getElementById('trade-list');
    const trades = d.recent_trades || [];
    if (trades.length === 0) {
      tradeEl.innerHTML = '<span style="color:#444;font-size:12px;">No trades yet</span>';
    } else {
      tradeEl.innerHTML = trades.slice(-20).reverse().map(t => {
        return '<div class="trade-row"><span class="trade-side ' + (t.action === 'BUY' ? 'green' : 'red') + '">' + t.action +
          '</span><span class="trade-detail">' + t.size + '@' + (t.fill_price || t.price || 0).toFixed(4) +
          '</span><span style="color:#888;">$' + (t.cost || 0).toFixed(2) + '</span></div>';
      }).join('');
    }

    document.getElementById('last-update').textContent = 'Updated ' + new Date().toLocaleTimeString();
    document.getElementById('uptime').textContent = d.uptime || '';
  } catch(e) {
    document.getElementById('last-update').textContent = 'Error: ' + e.message;
  }
}

fetchData();
setInterval(fetchData, 2000);
</script>
</body>
</html>"""


class Dashboard:
    """Lightweight web dashboard for monitoring and controlling the bot."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        self.host = host
        self.port = port
        self.app = web.Application()
        self.app.router.add_get("/", self._index)
        self.app.router.add_get("/api/status", self._api_status)
        self.app.router.add_post("/api/config", self._api_config)
        self.app.router.add_post("/api/mode", self._api_mode)
        self._runner: web.AppRunner | None = None
        self._data_provider = None
        self._config_handler = None
        self._mode_handler = None
        self._started_at = datetime.utcnow()

    def set_data_provider(self, provider) -> None:
        """Set the callback that returns dashboard data dict."""
        self._data_provider = provider

    def set_config_handler(self, handler) -> None:
        """Set the callback for config updates: handler(config_dict) -> bool."""
        self._config_handler = handler

    def set_mode_handler(self, handler) -> None:
        """Set the callback for mode switches: handler(mode_str) -> bool."""
        self._mode_handler = handler

    async def start(self) -> None:
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info(f"Dashboard running at http://{self.host}:{self.port}")

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    async def _index(self, request: web.Request) -> web.Response:
        return web.Response(text=DASHBOARD_HTML, content_type="text/html")

    async def _api_status(self, request: web.Request) -> web.Response:
        data = {}
        if self._data_provider:
            data = self._data_provider()

        uptime = datetime.utcnow() - self._started_at
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        data["uptime"] = f"{hours}h {minutes}m {seconds}s"

        return web.json_response(data, dumps=lambda x: json.dumps(x, default=str))

    async def _api_config(self, request: web.Request) -> web.Response:
        """Handle config update from dashboard."""
        try:
            body = await request.json()
            if self._config_handler:
                success = self._config_handler(body)
                if success:
                    return web.json_response({"ok": True})
                else:
                    return web.json_response({"ok": False, "error": "Config update failed"})
            return web.json_response({"ok": False, "error": "No config handler"})
        except Exception as e:
            logger.error(f"Config update error: {e}")
            return web.json_response({"ok": False, "error": str(e)})

    async def _api_mode(self, request: web.Request) -> web.Response:
        """Handle mode switch from dashboard."""
        try:
            body = await request.json()
            mode = body.get("mode", "")
            if self._mode_handler:
                success = self._mode_handler(mode)
                if success:
                    return web.json_response({"ok": True, "mode": mode})
                else:
                    return web.json_response({"ok": False, "error": "Mode switch failed"})
            return web.json_response({"ok": False, "error": "No mode handler"})
        except Exception as e:
            logger.error(f"Mode switch error: {e}")
            return web.json_response({"ok": False, "error": str(e)})
