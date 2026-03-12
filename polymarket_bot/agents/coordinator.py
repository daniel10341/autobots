"""Agent 1: Coordinator — Orchestrates the lifecycle of all 10 agents."""

import asyncio
import logging
import signal

from polymarket_bot.config import BotConfig
from polymarket_bot.core.base_agent import BaseAgent
from polymarket_bot.core.message_bus import MessageBus
from polymarket_bot.core.polymarket_client import PolymarketClient
from polymarket_bot.core.dashboard import Dashboard
from polymarket_bot.models.events import Event, EventType

from polymarket_bot.agents.market_scanner import MarketScannerAgent
from polymarket_bot.agents.btc_scanner import BtcScannerAgent
from polymarket_bot.agents.price_analyzer import PriceAnalyzerAgent
from polymarket_bot.agents.orderbook_agent import OrderBookAgent
from polymarket_bot.agents.yes_trader import YesTraderAgent
from polymarket_bot.agents.no_trader import NoTraderAgent
from polymarket_bot.agents.risk_manager import RiskManagerAgent
from polymarket_bot.agents.portfolio_agent import PortfolioAgent
from polymarket_bot.agents.execution_agent import ExecutionAgent
from polymarket_bot.agents.monitor_agent import MonitorAgent

logger = logging.getLogger(__name__)


class CoordinatorAgent(BaseAgent):
    """Top-level orchestrator that manages all 9 other agents.

    Responsibilities:
    - Initialize and connect the Polymarket client
    - Start all agents in the correct order
    - Handle graceful shutdown (SIGINT/SIGTERM)
    - Respond to EMERGENCY_SHUTDOWN events
    - Host the web dashboard
    """

    def __init__(self, config: BotConfig) -> None:
        self._message_bus = MessageBus()
        super().__init__("Coordinator", config, self._message_bus)

        self.client = PolymarketClient(
            config.polymarket,
            simulate=config.simulate,
            sim_balance=config.sim_balance,
            capital_max=config.trading.capital_max,
        )
        self.agents: list[BaseAgent] = []
        self._shutdown_event = asyncio.Event()
        self.dashboard = Dashboard(port=config.dashboard_port)

        # Store references for dashboard data
        self._price_analyzer = None
        self._portfolio = None
        self._market_scanner = None
        self._execution = None

    @property
    def cycle_interval(self) -> float:
        return 60.0

    def _setup_subscriptions(self) -> None:
        self.bus.subscribe(EventType.EMERGENCY_SHUTDOWN, self._handle_emergency)

    async def _handle_emergency(self, event: Event) -> None:
        logger.critical(f"EMERGENCY SHUTDOWN: {event.data}")
        self._shutdown_event.set()

    def _create_agents(self) -> list[BaseAgent]:
        """Instantiate all 9 worker agents."""
        bus = self._message_bus
        cfg = self.config
        client = self.client

        market_scanner = MarketScannerAgent(cfg, bus, client)
        btc_scanner = BtcScannerAgent(cfg, bus, client)
        price_analyzer = PriceAnalyzerAgent(cfg, bus, client)
        orderbook = OrderBookAgent(cfg, bus, client)
        risk_manager = RiskManagerAgent(cfg, bus)
        execution = ExecutionAgent(cfg, bus)
        yes_trader = YesTraderAgent(cfg, bus, client)
        no_trader = NoTraderAgent(cfg, bus, client)
        portfolio = PortfolioAgent(cfg, bus)

        # Keep references for dashboard
        self._market_scanner = market_scanner
        self._btc_scanner = btc_scanner
        self._price_analyzer = price_analyzer
        self._portfolio = portfolio
        self._execution = execution

        # Start order matters: downstream agents must subscribe before
        # upstream agents publish events. Scanners go LAST.
        agents = [
            price_analyzer,
            orderbook,
            risk_manager,
            execution,
            yes_trader,
            no_trader,
            portfolio,
            market_scanner,
            btc_scanner,
        ]

        monitor = MonitorAgent(cfg, bus, [self] + agents)
        agents.append(monitor)

        return agents

    def _get_dashboard_data(self) -> dict:
        """Build the data dict for the web dashboard."""
        # Mode
        if self.config.simulate:
            mode = "SIMULATION"
        elif self.config.dry_run:
            mode = "DRY RUN"
        else:
            mode = "LIVE"

        # Agent statuses
        agent_statuses = [self.status] + [a.status for a in self.agents]

        # Simulation data
        sim_data = {}
        if self.client.sim_exchange:
            sim_data = self.client.sim_exchange.summary()

        # Opportunities from price analyzer
        opportunities = []
        if self._price_analyzer:
            for cid, opp in self._price_analyzer.active_opportunities.items():
                opportunities.append({
                    "condition_id": cid,
                    "question": opp.get("question", ""),
                    "yes_ask": opp.get("yes_ask", 0),
                    "no_ask": opp.get("no_ask", 0),
                    "combined": opp.get("combined_cost", 0),
                    "profit": opp.get("profit_per_pair", 0),
                })

        # Portfolio
        portfolio_data = {}
        if self._portfolio:
            total_guaranteed = sum(p.guaranteed_profit for p in self._portfolio.positions.values())
            total_hedged = sum(p.hedged_pairs for p in self._portfolio.positions.values())
            portfolio_data = {
                "hedged_pairs": total_hedged,
                "guaranteed_profit": total_guaranteed,
                "total_invested": self._portfolio.total_invested,
            }

        # Recent trades
        recent_trades = []
        if self.client.sim_exchange:
            recent_trades = self.client.sim_exchange.trade_history[-20:]

        # Markets tracked
        markets_tracked = len(self._market_scanner.known_markets) if self._market_scanner else 0
        btc_markets = len(self._btc_scanner.active_markets) if self._btc_scanner else 0

        # BTC 5m market info
        btc_5m = []
        if self._btc_scanner:
            for slug, data in self._btc_scanner.active_markets.items():
                btc_5m.append({
                    "question": data.get("question", ""),
                    "yes_price": data.get("yes_price", 0),
                    "no_price": data.get("no_price", 0),
                    "window_start": data.get("window_start", 0),
                    "window_end": data.get("window_end", 0),
                })

        # Current config for the config panel
        config_data = {
            "capital_max": self.config.trading.capital_max,
            "order_size": self.config.trading.default_order_size,
            "max_markets": self.config.trading.max_markets,
            "max_combined_cost": self.config.trading.max_combined_cost,
            "min_profit_margin": self.config.trading.min_profit_margin,
            "btc_only": self.config.btc_only,
            "market_scan_interval": self.config.agents.market_scan_interval,
            "price_update_interval": self.config.agents.price_update_interval,
        }

        return {
            "mode": mode,
            "agents": agent_statuses,
            "simulation": sim_data,
            "portfolio": portfolio_data,
            "opportunities": opportunities,
            "btc_5m": btc_5m,
            "btc_markets": btc_markets,
            "recent_trades": recent_trades,
            "markets_tracked": markets_tracked,
            "config": config_data,
        }

    def _handle_config_update(self, config_dict: dict) -> bool:
        """Apply config changes from the dashboard."""
        try:
            trading = self.config.trading
            agents = self.config.agents

            if "capital_max" in config_dict:
                trading.capital_max = float(config_dict["capital_max"])
                if self.client.sim_exchange:
                    self.client.sim_exchange.capital_max = trading.capital_max
            if "order_size" in config_dict:
                trading.default_order_size = float(config_dict["order_size"])
            if "max_markets" in config_dict:
                trading.max_markets = int(config_dict["max_markets"])
            if "max_combined_cost" in config_dict:
                trading.max_combined_cost = float(config_dict["max_combined_cost"])
            if "min_profit_margin" in config_dict:
                trading.min_profit_margin = float(config_dict["min_profit_margin"])
            if "btc_only" in config_dict:
                self.config.btc_only = bool(config_dict["btc_only"])
            if "market_scan_interval" in config_dict:
                agents.market_scan_interval = float(config_dict["market_scan_interval"])
            if "price_update_interval" in config_dict:
                agents.price_update_interval = float(config_dict["price_update_interval"])

            logger.info(f"Config updated from dashboard: {config_dict}")
            return True
        except Exception as e:
            logger.error(f"Config update failed: {e}")
            return False

    def _handle_mode_switch(self, mode: str) -> bool:
        """Switch bot mode from the dashboard."""
        try:
            if mode == "simulate":
                self.config.simulate = True
                self.config.dry_run = True
                if not self.client.sim_exchange:
                    from polymarket_bot.core.simulator import SimulatedExchange
                    self.client.sim_exchange = SimulatedExchange(
                        starting_balance=self.config.sim_balance,
                        capital_max=self.config.trading.capital_max,
                    )
                    self.client.simulate = True
                logger.info("Switched to SIMULATION mode")
            elif mode == "live":
                self.config.simulate = False
                self.config.dry_run = False
                self.client.simulate = False
                logger.info("Switched to LIVE mode")
            elif mode == "stop":
                logger.info("Stop requested from dashboard")
                self._shutdown_event.set()
            else:
                return False
            return True
        except Exception as e:
            logger.error(f"Mode switch failed: {e}")
            return False

    async def initialize(self) -> None:
        """Connect to Polymarket and set up all agents."""
        if self.config.simulate:
            mode = f"SIMULATION (${self.config.sim_balance:.0f} virtual balance)"
        elif self.config.dry_run:
            mode = "DRY RUN"
        else:
            mode = "LIVE TRADING"

        logger.info("=" * 60)
        logger.info("POLYMARKET MARKET MAKER BOT")
        logger.info(f"Mode: {mode}")
        logger.info("=" * 60)

        if self.config.simulate:
            logger.info("Connecting to Polymarket API for real market data...")
            self.client.connect()
            logger.info(f"Simulation exchange initialized with ${self.config.sim_balance:.0f} USDC")
        elif not self.config.dry_run:
            logger.info("Connecting to Polymarket CLOB API...")
            self.client.connect()
        else:
            logger.info("Dry run mode — skipping API connection")

        self.agents = self._create_agents()
        logger.info(f"Created {len(self.agents)} worker agents (+1 coordinator = 10 total)")

    async def run(self) -> None:
        """Main entry point — start everything and run until shutdown."""
        await self.initialize()

        # Start dashboard with data provider and control handlers
        self.dashboard.set_data_provider(self._get_dashboard_data)
        self.dashboard.set_config_handler(self._handle_config_update)
        self.dashboard.set_mode_handler(self._handle_mode_switch)
        await self.dashboard.start()

        # Start the message bus
        await self._message_bus.start()

        # Start coordinator itself
        self._setup_subscriptions()

        # Start all worker agents with staggered delays
        for i, agent in enumerate(self.agents):
            await agent.start()
            if i < len(self.agents) - 1:
                await asyncio.sleep(self.config.agents.agent_startup_delay)

        logger.info("All 10 agents running!")
        logger.info(f"Dashboard: http://localhost:{self.config.dashboard_port}")
        logger.info("-" * 60)

        # Register signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: self._shutdown_event.set())

        # Run until shutdown
        await self._shutdown_event.wait()
        await self.shutdown()

    async def shutdown(self) -> None:
        """Graceful shutdown — stop all agents and clean up."""
        logger.info("Initiating graceful shutdown...")

        # Stop dashboard
        await self.dashboard.stop()

        # Stop agents in reverse order
        for agent in reversed(self.agents):
            try:
                await asyncio.wait_for(agent.stop(), timeout=self.config.agents.shutdown_timeout)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout stopping {agent.name}")
            except Exception as e:
                logger.error(f"Error stopping {agent.name}: {e}")

        # Stop message bus
        await self._message_bus.stop()

        # Print simulation summary if applicable
        if self.config.simulate and self.client.sim_exchange:
            logger.info("\n" + self.client.sim_exchange.print_summary())

        # Close API client
        await self.client.close()

        logger.info("Shutdown complete. Goodbye!")

    async def run_cycle(self) -> None:
        """Coordinator's periodic check — just logs agent health summary."""
        healthy = sum(1 for a in self.agents if a.is_healthy)
        total = len(self.agents)
        logger.info(f"Coordinator check: {healthy}/{total} agents healthy")
