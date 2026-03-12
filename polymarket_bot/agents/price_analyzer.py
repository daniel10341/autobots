"""Agent 3: Price Analyzer — Detects spread arbitrage opportunities."""

import asyncio
from datetime import datetime

from polymarket_bot.config import BotConfig
from polymarket_bot.core.base_agent import BaseAgent
from polymarket_bot.core.message_bus import MessageBus
from polymarket_bot.core.polymarket_client import PolymarketClient
from polymarket_bot.models.events import Event, EventType
from polymarket_bot.models.market import Side


class PriceAnalyzerAgent(BaseAgent):
    """Monitors prices on tracked markets and identifies profitable spreads.

    Core logic: If YES ask + NO ask < $1.00, there's a guaranteed profit.
    Publishes SPREAD_OPPORTUNITY when the combined cost is below our threshold.
    """

    def __init__(self, config: BotConfig, message_bus: MessageBus, client: PolymarketClient) -> None:
        super().__init__("PriceAnalyzer", config, message_bus)
        self.client = client
        self.tracked_markets: dict[str, dict] = {}
        self.last_prices: dict[str, dict] = {}
        self.active_opportunities: dict[str, dict] = {}

    @property
    def cycle_interval(self) -> float:
        return self.config.agents.price_update_interval

    def _setup_subscriptions(self) -> None:
        self.bus.subscribe(EventType.MARKET_DISCOVERED, self._handle_market_discovered)
        self.bus.subscribe(EventType.MARKET_REMOVED, self._handle_market_removed)

    async def _handle_market_discovered(self, event: Event) -> None:
        cid = event.data.get("condition_id", "")
        self.tracked_markets[cid] = event.data
        self.logger.debug(f"Now tracking prices for: {event.data.get('question', '')[:50]}")

    async def _handle_market_removed(self, event: Event) -> None:
        cid = event.data.get("condition_id", "")
        self.tracked_markets.pop(cid, None)
        self.last_prices.pop(cid, None)
        self.active_opportunities.pop(cid, None)

    async def run_cycle(self) -> None:
        """Check prices on all tracked markets for spread opportunities."""
        if not self.tracked_markets:
            return

        for cid, market_data in list(self.tracked_markets.items()):
            await self._analyze_market(cid, market_data)
            await asyncio.sleep(0.2)  # Rate limit

    async def _analyze_market(self, condition_id: str, market_data: dict) -> None:
        """Analyze a single market for spread opportunity."""
        yes_token_id = market_data.get("yes_token_id", "")
        no_token_id = market_data.get("no_token_id", "")

        if not yes_token_id or not no_token_id:
            return

        try:
            # Fetch order books for both sides
            yes_book_raw = await asyncio.get_event_loop().run_in_executor(
                None, self.client.get_order_book, yes_token_id
            )
            no_book_raw = await asyncio.get_event_loop().run_in_executor(
                None, self.client.get_order_book, no_token_id
            )

            yes_book = self.client.parse_order_book(yes_book_raw, yes_token_id, Side.YES)
            no_book = self.client.parse_order_book(no_book_raw, no_token_id, Side.NO)
        except Exception as e:
            self.logger.error(f"Failed to fetch order books for {condition_id[:12]}...: {e}")
            return

        yes_ask = yes_book.best_ask
        no_ask = no_book.best_ask
        combined_cost = yes_ask + no_ask
        profit_per_pair = 1.0 - combined_cost

        # Store latest prices
        self.last_prices[condition_id] = {
            "yes_ask": yes_ask,
            "yes_bid": yes_book.best_bid,
            "no_ask": no_ask,
            "no_bid": no_book.best_bid,
            "combined_cost": combined_cost,
            "profit_per_pair": profit_per_pair,
            "timestamp": datetime.utcnow().isoformat(),
        }

        await self.bus.publish(Event(
            event_type=EventType.PRICE_UPDATED,
            source=self.name,
            data={
                "condition_id": condition_id,
                **self.last_prices[condition_id],
            },
        ))

        trading = self.config.trading

        # In simulation mode, widen thresholds to show the strategy in action
        if self.config.simulate:
            max_cost = 1.02  # Accept up to 2c loss in sim to demonstrate trading
            min_profit = -0.02
        else:
            max_cost = trading.max_combined_cost
            min_profit = trading.min_profit_margin

        # Check if this is a profitable opportunity
        if combined_cost < max_cost and profit_per_pair >= min_profit:
            opportunity = {
                "condition_id": condition_id,
                "question": market_data.get("question", ""),
                "yes_token_id": yes_token_id,
                "no_token_id": no_token_id,
                "yes_ask": yes_ask,
                "no_ask": no_ask,
                "combined_cost": combined_cost,
                "profit_per_pair": profit_per_pair,
                "yes_depth": yes_book.depth_at_price(yes_ask + trading.slippage_tolerance, "ask"),
                "no_depth": no_book.depth_at_price(no_ask + trading.slippage_tolerance, "ask"),
                "timestamp": datetime.utcnow().isoformat(),
            }

            self.active_opportunities[condition_id] = opportunity
            self.logger.info(
                f"OPPORTUNITY: {market_data.get('question', '')[:50]} | "
                f"YES@{yes_ask:.3f} + NO@{no_ask:.3f} = {combined_cost:.3f} | "
                f"Profit: ${profit_per_pair:.3f}/pair"
            )

            await self.bus.publish(Event(
                event_type=EventType.SPREAD_OPPORTUNITY,
                source=self.name,
                data=opportunity,
                priority=5,
            ))
        elif condition_id in self.active_opportunities:
            # Opportunity closed
            del self.active_opportunities[condition_id]
            await self.bus.publish(Event(
                event_type=EventType.SPREAD_CLOSED,
                source=self.name,
                data={"condition_id": condition_id},
            ))
