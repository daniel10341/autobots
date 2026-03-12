"""Web dashboard — monitor the bot from your browser."""

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
  }
  h1 {
    font-size: 20px;
    color: #00ff88;
    margin-bottom: 4px;
  }
  .subtitle { color: #888; font-size: 13px; margin-bottom: 16px; }
  .mode-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
  }
  .mode-sim { background: #1a3a2a; color: #00ff88; border: 1px solid #00ff88; }
  .mode-live { background: #3a1a1a; color: #ff4444; border: 1px solid #ff4444; }
  .mode-dry { background: #2a2a1a; color: #ffaa00; border: 1px solid #ffaa00; }

  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 16px; }
  .card {
    background: #12121a;
    border: 1px solid #1e1e2e;
    border-radius: 12px;
    padding: 14px;
  }
  .card-full { grid-column: 1 / -1; }
  .card-label { font-size: 11px; color: #666; text-transform: uppercase; letter-spacing: 1px; }
  .card-value { font-size: 24px; font-weight: 700; margin-top: 4px; }
  .green { color: #00ff88; }
  .red { color: #ff4466; }
  .yellow { color: #ffaa00; }
  .blue { color: #4488ff; }

  .agent-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .agent-pill {
    display: flex; align-items: center; gap: 6px;
    background: #1a1a24;
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 12px;
  }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .dot-green { background: #00ff88; box-shadow: 0 0 6px #00ff88; }
  .dot-red { background: #ff4466; box-shadow: 0 0 6px #ff4466; }
  .dot-gray { background: #444; }

  .trades-list { max-height: 300px; overflow-y: auto; }
  .trade-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 8px 0;
    border-bottom: 1px solid #1a1a24;
    font-size: 12px;
  }
  .trade-side { font-weight: 700; width: 32px; }
  .trade-detail { color: #888; flex: 1; margin-left: 8px; }

  .opp-row {
    background: #0a1a10;
    border: 1px solid #1a3a2a;
    border-radius: 8px;
    padding: 10px;
    margin-bottom: 6px;
    font-size: 12px;
  }
  .opp-question { color: #ccc; margin-bottom: 4px; }
  .opp-stats { display: flex; gap: 12px; color: #00ff88; font-weight: 600; }

  .refresh-bar {
    position: fixed; bottom: 0; left: 0; right: 0;
    background: #12121a; border-top: 1px solid #1e1e2e;
    padding: 8px 16px;
    display: flex; justify-content: space-between; align-items: center;
    font-size: 11px; color: #666;
  }
  .pulse { animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
</style>
</head>
<body>
  <h1>Polymarket Market Maker</h1>
  <div class="subtitle">
    <span id="mode-badge" class="mode-badge mode-sim">SIMULATION</span>
    <span id="uptime" style="margin-left:8px;"></span>
  </div>

  <div class="grid">
    <div class="card">
      <div class="card-label">Balance</div>
      <div class="card-value green" id="balance">$0.00</div>
    </div>
    <div class="card">
      <div class="card-label">P&L</div>
      <div class="card-value" id="pnl">$0.00</div>
    </div>
    <div class="card">
      <div class="card-label">Trades</div>
      <div class="card-value blue" id="trades">0</div>
    </div>
    <div class="card">
      <div class="card-label">Markets</div>
      <div class="card-value yellow" id="markets">0</div>
    </div>
    <div class="card">
      <div class="card-label">Hedged Pairs</div>
      <div class="card-value green" id="hedged">0</div>
    </div>
    <div class="card">
      <div class="card-label">Guaranteed Profit</div>
      <div class="card-value green" id="guaranteed">$0.00</div>
    </div>
  </div>

  <div class="card card-full" style="margin-bottom:12px;">
    <div class="card-label" style="margin-bottom:8px;">Agents (10)</div>
    <div class="agent-grid" id="agents"></div>
  </div>

  <div class="card card-full" style="margin-bottom:12px;">
    <div class="card-label" style="margin-bottom:8px;">Active Opportunities</div>
    <div id="opportunities"><span style="color:#444;font-size:12px;">Scanning...</span></div>
  </div>

  <div class="card card-full" style="margin-bottom:60px;">
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
async function fetchData() {
  try {
    const resp = await fetch('/api/status');
    const d = await resp.json();

    // Mode
    const badge = document.getElementById('mode-badge');
    if (d.mode === 'SIMULATION') { badge.className = 'mode-badge mode-sim'; badge.textContent = 'SIMULATION'; }
    else if (d.mode === 'LIVE') { badge.className = 'mode-badge mode-live'; badge.textContent = 'LIVE'; }
    else { badge.className = 'mode-badge mode-dry'; badge.textContent = 'DRY RUN'; }

    // Stats
    const sim = d.simulation || {};
    document.getElementById('balance').textContent = '$' + (sim.balance || 0).toFixed(2);
    const pnl = sim.pnl || 0;
    const pnlEl = document.getElementById('pnl');
    pnlEl.textContent = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toFixed(2);
    pnlEl.className = 'card-value ' + (pnl >= 0 ? 'green' : 'red');
    document.getElementById('trades').textContent = sim.total_trades || 0;
    document.getElementById('markets').textContent = d.markets_tracked || 0;

    const portfolio = d.portfolio || {};
    document.getElementById('hedged').textContent = (portfolio.hedged_pairs || 0).toFixed(1);
    document.getElementById('guaranteed').textContent = '$' + (portfolio.guaranteed_profit || 0).toFixed(2);

    // Agents
    const agentsEl = document.getElementById('agents');
    agentsEl.innerHTML = '';
    (d.agents || []).forEach(a => {
      const dot = a.healthy ? 'dot-green' : (a.running ? 'dot-red' : 'dot-gray');
      agentsEl.innerHTML += `<div class="agent-pill"><div class="dot ${dot}"></div>${a.name}<span style="color:#444;margin-left:auto;font-size:10px;">${a.cycles || 0}c</span></div>`;
    });

    // Opportunities
    const oppEl = document.getElementById('opportunities');
    const opps = d.opportunities || [];
    if (opps.length === 0) {
      oppEl.innerHTML = '<span style="color:#444;font-size:12px;">Scanning for spreads...</span>';
    } else {
      oppEl.innerHTML = opps.map(o => `
        <div class="opp-row">
          <div class="opp-question">${(o.question || '').substring(0, 60)}</div>
          <div class="opp-stats">
            <span>YES@${(o.yes_ask || 0).toFixed(3)}</span>
            <span>NO@${(o.no_ask || 0).toFixed(3)}</span>
            <span>= ${(o.combined || 0).toFixed(3)}</span>
            <span>Profit: $${(o.profit || 0).toFixed(3)}</span>
          </div>
        </div>
      `).join('');
    }

    // Trades
    const tradeEl = document.getElementById('trade-list');
    const trades = d.recent_trades || [];
    if (trades.length === 0) {
      tradeEl.innerHTML = '<span style="color:#444;font-size:12px;">No trades yet</span>';
    } else {
      tradeEl.innerHTML = trades.slice(-20).reverse().map(t => `
        <div class="trade-row">
          <span class="trade-side ${t.action === 'BUY' ? 'green' : 'red'}">${t.action}</span>
          <span class="trade-detail">${t.size}@${(t.fill_price || t.price || 0).toFixed(4)}</span>
          <span style="color:#888;">$${(t.cost || 0).toFixed(2)}</span>
        </div>
      `).join('');
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
    """Lightweight web dashboard for monitoring the bot."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        self.host = host
        self.port = port
        self.app = web.Application()
        self.app.router.add_get("/", self._index)
        self.app.router.add_get("/api/status", self._api_status)
        self._runner: web.AppRunner | None = None
        self._data_provider = None
        self._started_at = datetime.utcnow()

    def set_data_provider(self, provider) -> None:
        """Set the callback that returns dashboard data dict."""
        self._data_provider = provider

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
