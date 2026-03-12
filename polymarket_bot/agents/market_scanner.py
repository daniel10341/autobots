"""Agent 2: Market Scanner — Discovers markets with profitable spreads."""

import asyncio

from polymarket_bot.config import BotConfig
from polymarket_bot.core.base_agent import BaseAgent
from polymarket_bot.core.message_bus import MessageBus
from polymarket_bot.core.polymarket_client import PolymarketClient
from polymarket_bot.models.events import Event, EventType


class MarketScannerAgent(BaseAgent):
    """Scans Polymarket for active binary markets that meet our criteria.

    Publishes MARKET_DISCOVERED events when it finds markets with
    sufficient liquidity and volume for market-making.
    """

    def __init__(self, config: BotConfig, message_bus: MessageBus, client: PolymarketClient) -> None:
        super().__init__("MarketScanner", config, message_bus)
        self.client = client
        self.known_markets: dict[str, dict] = {}

    @property
    def cycle_interval(self) -> float:
        return self.config.agents.market_scan_interval

    def _setup_subscriptions(self) -> None:
        self.bus.subscribe(EventType.MARKET_REMOVED, self._handle_market_removed)

    async def _handle_market_removed(self, event: Event) -> None:
        cid = event.data.get("condition_id", "")
        self.known_markets.pop(cid, None)
        self.logger.info(f"Removed market {cid[:12]}... from scan list")

    async def run_cycle(self) -> None:
        """Scan for new markets meeting our criteria."""
        if self.config.btc_only:
            return  # BTC scanner handles discovery in btc-only mode
        self.logger.debug("Scanning for markets...")

        try:
            raw_markets = await self.client.get_active_markets(limit=100)
        except Exception as e:
            self.logger.error(f"Failed to fetch markets: {e}")
            return

        trading = self.config.trading
        new_count = 0

        for raw in raw_markets:
            market = self.client.parse_market(raw)

            # Skip if we already know about it
            if market.condition_id in self.known_markets:
                continue

            # Must have both tokens
            if not market.yes_token or not market.no_token:
                continue

            # In simulation mode, accept any market with both tokens
            if not self.config.simulate:
                if market.liquidity < trading.min_market_liquidity:
                    continue
                if market.volume_24h < trading.min_volume_24h:
                    continue

            # Check if we're at max markets
            if len(self.known_markets) >= trading.max_markets:
                break

            self.known_markets[market.condition_id] = {
                "condition_id": market.condition_id,
                "question": market.question,
                "slug": market.slug,
                "yes_token_id": market.yes_token.token_id,
                "no_token_id": market.no_token.token_id,
                "liquidity": market.liquidity,
                "volume_24h": market.volume_24h,
            }

            await self.bus.publish(Event(
                event_type=EventType.MARKET_DISCOVERED,
                source=self.name,
                data=self.known_markets[market.condition_id],
            ))
            new_count += 1

        if new_count:
            self.logger.info(f"Discovered {new_count} new markets (tracking {len(self.known_markets)} total)")
