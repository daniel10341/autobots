"""Agent 7: Risk Manager — Position limits, exposure caps, drawdown protection."""

from typing import Optional

from polymarket_bot.config import BotConfig
from polymarket_bot.core.base_agent import BaseAgent
from polymarket_bot.core.message_bus import MessageBus
from polymarket_bot.core.polymarket_client import PolymarketClient
from polymarket_bot.models.events import Event, EventType


class RiskManagerAgent(BaseAgent):
    """Enforces risk limits across the entire bot.

    Monitors:
    - Per-market exposure limits
    - Total portfolio exposure
    - Max open orders
    - Capital max (hard spending cap)
    - Drawdown thresholds

    Publishes RISK_CHECK_PASSED/FAILED and can trigger EMERGENCY_SHUTDOWN.
    """

    def __init__(self, config: BotConfig, message_bus: MessageBus, client: Optional[PolymarketClient] = None) -> None:
        super().__init__("RiskManager", config, message_bus)
        self.client = client
        self.positions: dict[str, dict] = {}
        self.open_orders: dict[str, dict] = {}
        self.total_invested: float = 0.0
        self.total_pnl: float = 0.0
        self.starting_balance: float = 0.0
        self.max_drawdown_pct: float = 0.10  # 10% max drawdown triggers shutdown

    @property
    def total_spent(self) -> float:
        """Get total spent from the sim exchange (single source of truth).

        This avoids drift between RiskManager's tracking and the actual
        simulator state, especially when config changes (like capital_max)
        are applied from the dashboard.
        """
        if self.client and self.client.sim_exchange:
            return self.client.sim_exchange.total_spent
        return self._fallback_spent

    _fallback_spent: float = 0.0

    @property
    def cycle_interval(self) -> float:
        return self.config.agents.risk_check_interval

    def _setup_subscriptions(self) -> None:
        self.bus.subscribe(EventType.SPREAD_OPPORTUNITY, self._handle_opportunity)
        self.bus.subscribe(EventType.ORDER_PLACED, self._handle_order_placed)
        self.bus.subscribe(EventType.ORDER_FILLED, self._handle_order_filled)
        self.bus.subscribe(EventType.ORDER_CANCELLED, self._handle_order_cancelled)
        self.bus.subscribe(EventType.POSITION_UPDATED, self._handle_position_updated)
        self.bus.subscribe(EventType.PNL_UPDATED, self._handle_pnl_updated)
        self.bus.subscribe(EventType.BALANCE_UPDATED, self._handle_balance_updated)

    async def _handle_opportunity(self, event: Event) -> None:
        """Validate a spread opportunity against risk limits."""
        cid = event.data.get("condition_id", "")
        yes_price = event.data.get("yes_ask", 0)
        no_price = event.data.get("no_ask", 0)
        combined = yes_price + no_price

        trading = self.config.trading
        order_size = trading.default_order_size
        cost_per_pair = combined * order_size

        # Check per-market limit
        current_exposure = self.positions.get(cid, {}).get("total_invested", 0)
        if current_exposure + cost_per_pair > trading.max_position_per_market:
            self.logger.info(f"Risk BLOCKED: market {cid[:12]}... at exposure limit")
            await self.bus.publish(Event(
                event_type=EventType.RISK_CHECK_FAILED,
                source=self.name,
                data={"condition_id": cid, "reason": "per_market_limit"},
            ))
            return

        # Check total exposure
        if self.total_invested + cost_per_pair > trading.max_total_exposure:
            self.logger.info("Risk BLOCKED: total exposure limit reached")
            await self.bus.publish(Event(
                event_type=EventType.RISK_CHECK_FAILED,
                source=self.name,
                data={"condition_id": cid, "reason": "total_exposure_limit"},
            ))
            return

        # Check capital max (hard spending cap) — reads live from config
        capital_max = trading.capital_max
        if capital_max > 0 and self.total_spent + cost_per_pair > capital_max:
            self.logger.info(
                f"Risk BLOCKED: capital max ${capital_max:.2f} would be exceeded "
                f"(spent: ${self.total_spent:.2f}, this order: ${cost_per_pair:.2f})"
            )
            await self.bus.publish(Event(
                event_type=EventType.RISK_CHECK_FAILED,
                source=self.name,
                data={"condition_id": cid, "reason": "capital_max"},
            ))
            return

        # Check open order count
        if len(self.open_orders) >= trading.max_open_orders:
            self.logger.info("Risk BLOCKED: too many open orders")
            await self.bus.publish(Event(
                event_type=EventType.RISK_CHECK_FAILED,
                source=self.name,
                data={"condition_id": cid, "reason": "max_open_orders"},
            ))
            return

        # Passed all checks
        self.logger.info(f"Risk APPROVED: {cid[:12]}... cost=${cost_per_pair:.2f}")
        await self.bus.publish(Event(
            event_type=EventType.RISK_CHECK_PASSED,
            source=self.name,
            data={
                "condition_id": cid,
                "approved_size": order_size,
                "yes_price": yes_price,
                "no_price": no_price,
                **event.data,
            },
            priority=5,
        ))

    async def _handle_order_placed(self, event: Event) -> None:
        oid = event.data.get("order_id", "")
        if oid:
            self.open_orders[oid] = event.data

    async def _handle_order_filled(self, event: Event) -> None:
        oid = event.data.get("order_id", "")
        self.open_orders.pop(oid, None)
        # Fallback tracking for non-simulation mode
        if not (self.client and self.client.sim_exchange):
            cost = event.data.get("price", 0) * event.data.get("size", 0)
            if cost > 0:
                self._fallback_spent += cost

    async def _handle_order_cancelled(self, event: Event) -> None:
        oid = event.data.get("order_id", "")
        self.open_orders.pop(oid, None)

    async def _handle_position_updated(self, event: Event) -> None:
        cid = event.data.get("condition_id", "")
        self.positions[cid] = event.data

    async def _handle_pnl_updated(self, event: Event) -> None:
        self.total_pnl = event.data.get("total_pnl", 0)
        self.total_invested = event.data.get("total_invested", 0)

    async def _handle_balance_updated(self, event: Event) -> None:
        balance = event.data.get("balance", 0)
        if self.starting_balance == 0 and balance > 0:
            self.starting_balance = balance

    async def run_cycle(self) -> None:
        """Periodic risk checks — look for drawdown breaches."""
        # Check drawdown
        if self.starting_balance > 0 and self.total_pnl < 0:
            drawdown_pct = abs(self.total_pnl) / self.starting_balance
            if drawdown_pct >= self.max_drawdown_pct:
                self.logger.critical(
                    f"DRAWDOWN BREACH: {drawdown_pct:.1%} loss — triggering emergency shutdown!"
                )
                await self.bus.publish(Event(
                    event_type=EventType.EMERGENCY_SHUTDOWN,
                    source=self.name,
                    data={
                        "reason": "max_drawdown",
                        "drawdown_pct": drawdown_pct,
                        "total_pnl": self.total_pnl,
                    },
                    priority=10,
                ))
                return

        self.logger.debug(
            f"Risk OK | Invested: ${self.total_invested:.2f} | "
            f"Spent: ${self.total_spent:.2f} | "
            f"PnL: ${self.total_pnl:.2f} | Open orders: {len(self.open_orders)}"
        )
