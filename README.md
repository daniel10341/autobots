# Polymarket Market Maker Bot

A 10-agent market maker bot for Polymarket that profits by buying **both YES and NO** tokens when their combined cost is below $1.00. Since one side always wins and pays out $1.00, the difference is guaranteed profit.

## Strategy

```
Example: Market "Will X happen?"
  YES ask price: $0.47
  NO  ask price: $0.48
  Combined cost: $0.95

  Buy 10 shares of each:
    Cost: $9.50
    Payout: $10.00 (one side ALWAYS wins)
    Profit: $0.50 guaranteed
```

## 10-Agent Architecture

| # | Agent | Role |
|---|-------|------|
| 1 | **Coordinator** | Orchestrates all agents, manages lifecycle |
| 2 | **Market Scanner** | Discovers markets with profitable spreads |
| 3 | **Price Analyzer** | Calculates spreads, identifies opportunities |
| 4 | **Order Book** | Monitors depth, liquidity, slippage |
| 5 | **YES Trader** | Places and manages YES side buy orders |
| 6 | **NO Trader** | Places and manages NO side buy orders |
| 7 | **Risk Manager** | Position limits, exposure caps, drawdown protection |
| 8 | **Portfolio** | Tracks positions, hedged pairs, P&L |
| 9 | **Execution** | Routes orders after risk approval |
| 10 | **Monitor** | Health checks, alerts, logging dashboard |

### Event Flow

```
Market Scanner → discovers markets
    ↓
Price Analyzer → detects spread opportunity (YES + NO < $1)
    ↓
Risk Manager → validates against position/exposure limits
    ↓
Execution Agent → routes paired order
    ↓
YES Trader + NO Trader → place simultaneous buy orders
    ↓
Portfolio Agent → tracks positions and guaranteed profit
    ↓
Monitor Agent → health checks and dashboard
```

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure credentials:**
   ```bash
   cp .env.example .env
   # Edit .env with your Polymarket API credentials
   ```

3. **Run in dry-run mode (recommended first):**
   ```bash
   python -m polymarket_bot
   ```

4. **Run live:**
   ```bash
   python -m polymarket_bot --live
   ```

## CLI Options

```
--live              Enable live trading (default: dry run)
--max-exposure N    Max total USDC exposure (default: 5000)
--order-size N      USDC per side per order (default: 10)
--min-profit N      Min profit margin per pair (default: 0.02)
--max-markets N     Max simultaneous markets (default: 20)
--log-level LEVEL   DEBUG, INFO, WARNING, ERROR (default: INFO)
```

## Configuration

All parameters in `polymarket_bot/config.py`:

- **max_combined_cost**: Max YES+NO cost to enter (default: $0.97)
- **min_profit_margin**: Min profit per pair (default: $0.02)
- **max_position_per_market**: Max exposure per market (default: $500)
- **max_total_exposure**: Max total exposure (default: $5,000)
- **max_drawdown**: Emergency shutdown threshold (default: 10%)

## Monitoring

The bot writes `bot_status.json` every 30 seconds with:
- Agent health status
- Portfolio P&L
- Recent alerts
- Error counts

## Risk Management

- Per-market position limits
- Total portfolio exposure cap
- Max open order count
- Automatic emergency shutdown on drawdown breach
- Liquidity monitoring (warns if depth drops)
