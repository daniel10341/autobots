"""Agent 8: Portfolio Agent — Tracks positions and P&L."""

from datetime import datetime

from polymarket_bot.config import BotConfig
from polymarket_bot.core.base_agent import BaseAgent
from polymarket_bot.core.message_bus import MessageBus
from polymarket_bot.models.events import Event, EventType
from polymarket_bot.models.market import Position


class PortfolioAgent(BaseAgent):
    """Tracks all positions, calculates P&L, and reports portfolio state.

    Maintains a real-time view of:
    - All YES/NO positions per market
    - Hedged pairs (guaranteed profit)
    - Unrealized and realized P&L
    """

    def __init__(self, config: BotConfig, message_bus: MessageBus) -> None:
        super().__init__("Portfolio", config, message_bus)
        self.positions: dict[str, Position] = {}
        self.realized_pnl: float = 0.0
        self.total_invested: float = 0.0
        self.balance: float = 0.0

    @property
    def cycle_interval(self) -> float:
        return self.config.agents.portfolio_update_interval

    def _setup_subscriptions(self) -> None:
        self.bus.subscribe(EventType.ORDER_FILLED, self._handle_order_filled)
        self.bus.subscribe(EventType.PRICE_UPDATED, self._handle_price_updated)
        self.bus.subscribe(EventType.BALANCE_UPDATED, self._handle_balance_updated)

    async def _handle_order_filled(self, event: Event) -> None:
        """Update positions when an order is filled."""
        cid = event.data.get("condition_id", "")
        side = event.data.get("side", "")
        price = float(event.data.get("price", 0))
        size = float(event.data.get("size", 0))
        question = event.data.get("question", "")

        if not cid or not side:
            return

        if cid not in self.positions:
            self.positions[cid] = Position(
                market_condition_id=cid,
                market_question=question,
            )

        pos = self.positions[cid]
        cost = price * size

        if side == "YES":
            # Update weighted average cost
            total_cost = pos.yes_avg_cost * pos.yes_shares + cost
            pos.yes_shares += size
            pos.yes_avg_cost = total_cost / pos.yes_shares if pos.yes_shares > 0 else 0
        elif side == "NO":
            total_cost = pos.no_avg_cost * pos.no_shares + cost
            pos.no_shares += size
            pos.no_avg_cost = total_cost / pos.no_shares if pos.no_shares > 0 else 0

        pos.total_invested = (pos.yes_avg_cost * pos.yes_shares) + (pos.no_avg_cost * pos.no_shares)
        self.total_invested = sum(p.total_invested for p in self.positions.values())

        await self.bus.publish(Event(
            event_type=EventType.POSITION_UPDATED,
            source=self.name,
            data={
                "condition_id": cid,
                "yes_shares": pos.yes_shares,
                "no_shares": pos.no_shares,
                "yes_avg_cost": pos.yes_avg_cost,
                "no_avg_cost": pos.no_avg_cost,
                "hedged_pairs": pos.hedged_pairs,
                "guaranteed_profit": pos.guaranteed_profit,
                "total_invested": pos.total_invested,
            },
        ))

    async def _handle_price_updated(self, event: Event) -> None:
        """Update unrealized P&L based on latest prices."""
        cid = event.data.get("condition_id", "")
        if cid not in self.positions:
            return

        pos = self.positions[cid]
        yes_bid = float(event.data.get("yes_bid", 0))
        no_bid = float(event.data.get("no_bid", 0))

        # Unrealized P&L = what we'd get if we sold everything now
        yes_value = pos.yes_shares * yes_bid
        no_value = pos.no_shares * no_bid
        current_value = yes_value + no_value
        pos.unrealized_pnl = current_value - pos.total_invested

    async def _handle_balance_updated(self, event: Event) -> None:
        self.balance = event.data.get("balance", 0)

    async def run_cycle(self) -> None:
        """Publish portfolio summary."""
        total_guaranteed_profit = sum(p.guaranteed_profit for p in self.positions.values())
        total_hedged_pairs = sum(p.hedged_pairs for p in self.positions.values())
        total_unrealized = sum(p.unrealized_pnl for p in self.positions.values())

        summary = {
            "num_markets": len(self.positions),
            "total_invested": self.total_invested,
            "total_hedged_pairs": total_hedged_pairs,
            "total_guaranteed_profit": total_guaranteed_profit,
            "total_unrealized_pnl": total_unrealized,
            "realized_pnl": self.realized_pnl,
            "total_pnl": total_guaranteed_profit + total_unrealized + self.realized_pnl,
            "balance": self.balance,
            "timestamp": datetime.utcnow().isoformat(),
        }

        await self.bus.publish(Event(
            event_type=EventType.PNL_UPDATED,
            source=self.name,
            data=summary,
        ))

        if self.positions:
            self.logger.info(
                f"Portfolio | Markets: {len(self.positions)} | "
                f"Invested: ${self.total_invested:.2f} | "
                f"Hedged pairs: {total_hedged_pairs:.1f} | "
                f"Guaranteed profit: ${total_guaranteed_profit:.2f} | "
                f"Unrealized: ${total_unrealized:.2f}"
            )
