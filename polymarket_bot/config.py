"""Configuration for Polymarket Market Maker Bot."""

import os
from dataclasses import dataclass, field


@dataclass
class PolymarketConfig:
    """Connection and API configuration."""

    # Polymarket CLOB API
    clob_api_url: str = "https://clob.polymarket.com"
    gamma_api_url: str = "https://gamma-api.polymarket.com"

    # Wallet credentials (set via environment variables)
    private_key: str = field(default_factory=lambda: os.environ.get("POLY_PRIVATE_KEY", ""))
    api_key: str = field(default_factory=lambda: os.environ.get("POLY_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.environ.get("POLY_API_SECRET", ""))
    api_passphrase: str = field(default_factory=lambda: os.environ.get("POLY_API_PASSPHRASE", ""))

    # Chain config
    chain_id: int = 137  # Polygon mainnet

    def validate(self) -> bool:
        if not self.private_key:
            raise ValueError("POLY_PRIVATE_KEY environment variable is required")
        if not self.api_key:
            raise ValueError("POLY_API_KEY environment variable is required")
        return True


@dataclass
class TradingConfig:
    """Market maker trading parameters."""

    # Spread requirements — combined YES+NO cost must be below this to enter
    max_combined_cost: float = 0.97  # Buy both sides only if total < $0.97
    min_profit_margin: float = 0.02  # Minimum $0.02 profit per pair

    # Order sizing
    default_order_size: float = 10.0  # USDC per side
    max_order_size: float = 100.0
    min_order_size: float = 1.0

    # Risk limits
    max_position_per_market: float = 500.0  # Max USDC exposure per market
    max_total_exposure: float = 5000.0  # Max total USDC across all markets
    max_open_orders: int = 50
    max_markets: int = 20  # Max concurrent markets

    # Execution
    order_refresh_interval: float = 30.0  # Seconds between order refreshes
    price_staleness_threshold: float = 5.0  # Re-quote if price moves this many cents
    slippage_tolerance: float = 0.01  # 1% max slippage

    # Market filters
    min_market_liquidity: float = 1000.0  # Min USDC liquidity
    min_volume_24h: float = 500.0
    max_spread: float = 0.15  # Skip markets with >15c spread on either side


@dataclass
class AgentConfig:
    """Agent timing and behavior configuration."""

    # Scan intervals (seconds)
    market_scan_interval: float = 60.0
    price_update_interval: float = 5.0
    orderbook_poll_interval: float = 3.0
    risk_check_interval: float = 10.0
    portfolio_update_interval: float = 15.0
    health_check_interval: float = 30.0

    # Coordinator
    agent_startup_delay: float = 2.0  # Stagger agent startup
    shutdown_timeout: float = 30.0

    # Retry
    max_retries: int = 3
    retry_backoff: float = 2.0


@dataclass
class BotConfig:
    """Top-level configuration combining all sub-configs."""

    polymarket: PolymarketConfig = field(default_factory=PolymarketConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    agents: AgentConfig = field(default_factory=AgentConfig)

    # Logging
    log_level: str = "INFO"
    log_file: str = "polymarket_bot.log"

    # Dry run mode — simulates trades without placing real orders
    dry_run: bool = True
