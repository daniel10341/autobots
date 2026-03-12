"""Agent 4: Order Book Agent — Monitors depth and liquidity."""

import asyncio
from datetime import datetime

from polymarket_bot.config import BotConfig
from polymarket_bot.core.base_agent import BaseAgent
from polymarket_bot.core.message_bus import MessageBus
from polymarket_bot.core.polymarket_client import PolymarketClient
from polymarket_bot.models.events import Event, EventType
from polymarket_bot.models.market import Side


class OrderBookAgent(BaseAgent):
    """Monitors order book depth and liquidity for tracked markets.

    Provides liquidity intelligence to other agents — warns if liquidity
    dries up or if large orders appear that could move the market.
    """

    def __init__(self, config: BotConfig, message_bus: MessageBus, client: PolymarketClient) -> None:
        super().__init__("OrderBook", config, message_bus)
        self.client = client
        self.tracked_tokens: dict[str, dict] = {}  # token_id -> market info
        self.book_snapshots: dict[str, dict] = {}

    @property
    def cycle_interval(self) -> float:
        return self.config.agents.orderbook_poll_interval

    def _setup_subscriptions(self) -> None:
        self.bus.subscribe(EventType.MARKET_DISCOVERED, self._handle_market_discovered)
        self.bus.subscribe(EventType.MARKET_REMOVED, self._handle_market_removed)

    async def _handle_market_discovered(self, event: Event) -> None:
        cid = event.data.get("condition_id", "")
        yes_tid = event.data.get("yes_token_id", "")
        no_tid = event.data.get("no_token_id", "")
        if yes_tid:
            self.tracked_tokens[yes_tid] = {"condition_id": cid, "side": "YES"}
        if no_tid:
            self.tracked_tokens[no_tid] = {"condition_id": cid, "side": "NO"}

    async def _handle_market_removed(self, event: Event) -> None:
        cid = event.data.get("condition_id", "")
        to_remove = [tid for tid, info in self.tracked_tokens.items() if info["condition_id"] == cid]
        for tid in to_remove:
            self.tracked_tokens.pop(tid, None)
            self.book_snapshots.pop(tid, None)

    async def run_cycle(self) -> None:
        """Poll order books for all tracked tokens."""
        if not self.tracked_tokens:
            return

        for token_id, info in list(self.tracked_tokens.items()):
            try:
                raw_book = await asyncio.get_event_loop().run_in_executor(
                    None, self.client.get_order_book, token_id
                )
                side = Side.YES if info["side"] == "YES" else Side.NO
                book = self.client.parse_order_book(raw_book, token_id, side)

                prev = self.book_snapshots.get(token_id)
                snapshot = {
                    "token_id": token_id,
                    "condition_id": info["condition_id"],
                    "side": info["side"],
                    "best_bid": book.best_bid,
                    "best_ask": book.best_ask,
                    "spread": book.spread,
                    "bid_depth_3": sum(l.size for l in book.bids[:3]),
                    "ask_depth_3": sum(l.size for l in book.asks[:3]),
                    "num_bid_levels": len(book.bids),
                    "num_ask_levels": len(book.asks),
                    "timestamp": datetime.utcnow().isoformat(),
                }
                self.book_snapshots[token_id] = snapshot

                await self.bus.publish(Event(
                    event_type=EventType.ORDERBOOK_UPDATED,
                    source=self.name,
                    data=snapshot,
                ))

                # Detect significant liquidity changes
                if prev:
                    prev_depth = prev.get("bid_depth_3", 0) + prev.get("ask_depth_3", 0)
                    curr_depth = snapshot["bid_depth_3"] + snapshot["ask_depth_3"]
                    if prev_depth > 0 and curr_depth / max(prev_depth, 0.01) < 0.5:
                        self.logger.warning(
                            f"Liquidity dropped >50% on {info['side']} {info['condition_id'][:12]}..."
                        )
                        await self.bus.publish(Event(
                            event_type=EventType.LIQUIDITY_CHANGED,
                            source=self.name,
                            data={**snapshot, "change": "SIGNIFICANT_DROP"},
                            priority=3,
                        ))

            except Exception as e:
                self.logger.error(f"Order book fetch failed for {token_id[:12]}...: {e}")

            await asyncio.sleep(0.15)  # Rate limit
