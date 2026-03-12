"""Agent 1: Coordinator — Orchestrates the lifecycle of all 10 agents."""

import asyncio
import logging
import signal

from polymarket_bot.config import BotConfig
from polymarket_bot.core.base_agent import BaseAgent
from polymarket_bot.core.message_bus import MessageBus
from polymarket_bot.core.polymarket_client import PolymarketClient
from polymarket_bot.models.events import Event, EventType

from polymarket_bot.agents.market_scanner import MarketScannerAgent
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
    """

    def __init__(self, config: BotConfig) -> None:
        self._message_bus = MessageBus()
        super().__init__("Coordinator", config, self._message_bus)

        self.client = PolymarketClient(
            config.polymarket,
            simulate=config.simulate,
            sim_balance=config.sim_balance,
        )
        self.agents: list[BaseAgent] = []
        self._shutdown_event = asyncio.Event()

    @property
    def cycle_interval(self) -> float:
        return 60.0  # Coordinator checks in every minute

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

        # Create agents in dependency order
        market_scanner = MarketScannerAgent(cfg, bus, client)
        price_analyzer = PriceAnalyzerAgent(cfg, bus, client)
        orderbook = OrderBookAgent(cfg, bus, client)
        risk_manager = RiskManagerAgent(cfg, bus)
        execution = ExecutionAgent(cfg, bus)
        yes_trader = YesTraderAgent(cfg, bus, client)
        no_trader = NoTraderAgent(cfg, bus, client)
        portfolio = PortfolioAgent(cfg, bus)

        agents = [
            market_scanner,
            price_analyzer,
            orderbook,
            risk_manager,
            execution,
            yes_trader,
            no_trader,
            portfolio,
        ]

        # Monitor gets references to all agents for health checks
        monitor = MonitorAgent(cfg, bus, [self] + agents)
        agents.append(monitor)

        return agents

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
            # Simulation: connect to real API for market data, but trade via simulator
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
