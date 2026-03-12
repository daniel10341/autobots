"""BTC 5-Minute Market Scanner — Discovers rolling BTC Up/Down markets."""

import asyncio
import time

from polymarket_bot.config import BotConfig
from polymarket_bot.core.base_agent import BaseAgent
from polymarket_bot.core.message_bus import MessageBus
from polymarket_bot.core.polymarket_client import PolymarketClient
from polymarket_bot.models.events import Event, EventType


class BtcScannerAgent(BaseAgent):
    """Scans for Polymarket's recurring BTC 5-minute Up/Down markets.

    These markets follow the slug pattern: btc-updown-5m-{unix_timestamp}
    where the timestamp is rounded to the nearest 5-minute boundary.
    A new market opens every 5 minutes with fresh condition IDs and tokens.

    This agent discovers the current and upcoming windows and publishes
    them as MARKET_DISCOVERED events for the rest of the pipeline.
    """

    WINDOW_SECONDS = 300  # 5 minutes

    def __init__(self, config: BotConfig, message_bus: MessageBus, client: PolymarketClient) -> None:
        super().__init__("BtcScanner", config, message_bus)
        self.client = client
        self.active_markets: dict[str, dict] = {}  # slug -> market data
        self.seen_slugs: set[str] = set()

    @property
    def cycle_interval(self) -> float:
        # Check every 30 seconds so we catch new windows promptly
        return 30.0

    def _setup_subscriptions(self) -> None:
        pass

    def _get_window_timestamps(self, count: int = 3) -> list[int]:
        """Get timestamps for current and upcoming 5-minute windows."""
        now = int(time.time())
        base = now - (now % self.WINDOW_SECONDS)
        return [base + (i * self.WINDOW_SECONDS) for i in range(count)]

    async def run_cycle(self) -> None:
        """Discover current and upcoming BTC 5m markets."""
        timestamps = self._get_window_timestamps(count=3)
        new_count = 0

        for ts in timestamps:
            slug = f"btc-updown-5m-{ts}"

            if slug in self.seen_slugs:
                continue

            try:
                resp = await self.client._http.get(
                    f"{self.client.config.gamma_api_url}/events",
                    params={"slug": slug},
                )
                resp.raise_for_status()
                events = resp.json()

                if not events:
                    continue

                event = events[0]
                markets = event.get("markets", [])
                if not markets:
                    continue

                market_raw = markets[0]
                market = self.client.parse_market(market_raw)

                if not market.yes_token or not market.no_token:
                    continue

                self.seen_slugs.add(slug)

                market_data = {
                    "condition_id": market.condition_id,
                    "question": event.get("title", market_raw.get("question", "")),
                    "slug": slug,
                    "yes_token_id": market.yes_token.token_id,
                    "no_token_id": market.no_token.token_id,
                    "yes_price": market.yes_token.price,
                    "no_price": market.no_token.price,
                    "liquidity": event.get("liquidity", 0),
                    "volume_24h": event.get("volume24hr", 0),
                    "window_start": ts,
                    "window_end": ts + self.WINDOW_SECONDS,
                    "market_type": "btc_5m",
                }

                self.active_markets[slug] = market_data

                self.logger.info(
                    f"BTC 5m market: {market_data['question']} | "
                    f"UP@{market.yes_token.price:.3f} DOWN@{market.no_token.price:.3f} | "
                    f"Liquidity: ${event.get('liquidity', 0):.0f}"
                )

                await self.bus.publish(Event(
                    event_type=EventType.MARKET_DISCOVERED,
                    source=self.name,
                    data=market_data,
                ))
                new_count += 1

            except Exception as e:
                self.logger.error(f"Failed to fetch BTC 5m market {slug}: {e}")

        # Clean up expired markets
        now = int(time.time())
        expired = [s for s, d in self.active_markets.items() if d["window_end"] < now - 60]
        for slug in expired:
            expired_data = self.active_markets.pop(slug)
            cid = expired_data.get("condition_id", "")
            # Publish both EXPIRED and REMOVED so all agents clean up
            await self.bus.publish(Event(
                event_type=EventType.MARKET_EXPIRED,
                source=self.name,
                data={"slug": slug, "condition_id": cid},
            ))
            await self.bus.publish(Event(
                event_type=EventType.MARKET_REMOVED,
                source=self.name,
                data={"condition_id": cid, "slug": slug, "reason": "expired"},
            ))

        if new_count:
            self.logger.info(f"Discovered {new_count} new BTC 5m windows (active: {len(self.active_markets)})")
