"""Agent 9: Execution Agent — Routes orders to YES/NO traders after risk approval."""

from datetime import datetime

from polymarket_bot.config import BotConfig
from polymarket_bot.core.base_agent import BaseAgent
from polymarket_bot.core.message_bus import MessageBus
from polymarket_bot.models.events import Event, EventType


class ExecutionAgent(BaseAgent):
    """Bridges risk approval to order placement.

    Flow: SPREAD_OPPORTUNITY -> Risk Manager -> RISK_CHECK_PASSED -> Execution -> PAIR_ORDER_REQUESTED
    The execution agent determines order sizing and dispatches paired orders
    to both YES and NO traders simultaneously.
    """

    def __init__(self, config: BotConfig, message_bus: MessageBus) -> None:
        super().__init__("Execution", config, message_bus)
        self.pending_executions: list[dict] = []
        self.execution_history: list[dict] = []

    @property
    def cycle_interval(self) -> float:
        return 2.0  # Fast cycle — execution should be responsive

    def _setup_subscriptions(self) -> None:
        self.bus.subscribe(EventType.RISK_CHECK_PASSED, self._handle_risk_approved)
        self.bus.subscribe(EventType.ORDER_PLACED, self._handle_order_placed)
        self.bus.subscribe(EventType.ORDER_FAILED, self._handle_order_failed)
        self.bus.subscribe(EventType.EMERGENCY_SHUTDOWN, self._handle_emergency)

    async def _handle_risk_approved(self, event: Event) -> None:
        """Risk manager approved an opportunity — queue for execution."""
        self.pending_executions.append(event.data)
        self.logger.info(
            f"Execution queued: {event.data.get('condition_id', '')[:12]}... "
            f"size={event.data.get('approved_size', 0)}"
        )

    async def _handle_order_placed(self, event: Event) -> None:
        """Track that an order was successfully placed."""
        pass  # Tracked by portfolio and risk agents

    async def _handle_order_failed(self, event: Event) -> None:
        """Log order failures for analysis."""
        self.logger.warning(f"Order failed: {event.data}")

    async def _handle_emergency(self, event: Event) -> None:
        self.pending_executions.clear()
        self.logger.warning("EMERGENCY — cleared pending executions")

    async def run_cycle(self) -> None:
        """Execute pending paired orders."""
        while self.pending_executions:
            execution = self.pending_executions.pop(0)
            await self._execute_pair(execution)

    async def _execute_pair(self, data: dict) -> None:
        """Send a PAIR_ORDER_REQUESTED event to trigger both YES and NO traders."""
        condition_id = data.get("condition_id", "")
        yes_token_id = data.get("yes_token_id", "")
        no_token_id = data.get("no_token_id", "")
        yes_price = data.get("yes_price", data.get("yes_ask", 0))
        no_price = data.get("no_price", data.get("no_ask", 0))
        size = data.get("approved_size", self.config.trading.default_order_size)

        if not condition_id or not yes_token_id or not no_token_id:
            self.logger.error(f"Invalid execution data: missing token IDs")
            return

        if yes_price <= 0 or no_price <= 0:
            self.logger.error(f"Invalid prices: YES={yes_price}, NO={no_price}")
            return

        combined_cost = yes_price + no_price
        profit_per_unit = 1.0 - combined_cost

        self.logger.info(
            f"EXECUTING PAIR: {condition_id[:12]}... | "
            f"YES@{yes_price:.4f} + NO@{no_price:.4f} = {combined_cost:.4f} | "
            f"Size: {size} | Profit/unit: ${profit_per_unit:.4f}"
        )

        # Dispatch to both traders via the bus
        await self.bus.publish(Event(
            event_type=EventType.PAIR_ORDER_REQUESTED,
            source=self.name,
            data={
                "condition_id": condition_id,
                "yes_token_id": yes_token_id,
                "no_token_id": no_token_id,
                "yes_price": yes_price,
                "no_price": no_price,
                "size": size,
                "combined_cost": combined_cost,
                "expected_profit": profit_per_unit * size,
            },
            priority=5,
        ))

        self.execution_history.append({
            "condition_id": condition_id,
            "yes_price": yes_price,
            "no_price": no_price,
            "size": size,
            "profit_per_unit": profit_per_unit,
            "executed_at": datetime.utcnow().isoformat(),
        })
