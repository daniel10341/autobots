"""Agent 6: NO Side Trader — Places and manages NO side buy orders."""

import asyncio
from datetime import datetime

from polymarket_bot.config import BotConfig
from polymarket_bot.core.base_agent import BaseAgent
from polymarket_bot.core.message_bus import MessageBus
from polymarket_bot.core.polymarket_client import PolymarketClient
from polymarket_bot.models.events import Event, EventType
from polymarket_bot.models.market import OrderAction


class NoTraderAgent(BaseAgent):
    """Manages the NO side of market maker positions.

    Mirror of YesTraderAgent — places BUY orders for NO tokens when
    a spread opportunity is risk-approved.
    """

    def __init__(self, config: BotConfig, message_bus: MessageBus, client: PolymarketClient) -> None:
        super().__init__("NoTrader", config, message_bus)
        self.client = client
        self.pending_orders: dict[str, dict] = {}
        self.active_orders: dict[str, dict] = {}

    @property
    def cycle_interval(self) -> float:
        return self.config.trading.order_refresh_interval

    def _setup_subscriptions(self) -> None:
        self.bus.subscribe(EventType.PAIR_ORDER_REQUESTED, self._handle_pair_order)
        self.bus.subscribe(EventType.ORDER_FILLED, self._handle_order_filled)
        self.bus.subscribe(EventType.RISK_LIMIT_BREACH, self._handle_risk_breach)
        self.bus.subscribe(EventType.EMERGENCY_SHUTDOWN, self._handle_emergency)

    async def _handle_pair_order(self, event: Event) -> None:
        """Receive order request from execution agent."""
        cid = event.data.get("condition_id", "")
        no_token_id = event.data.get("no_token_id", "")
        no_price = event.data.get("no_price", 0)
        size = event.data.get("size", 0)

        if not no_token_id or no_price <= 0 or size <= 0:
            return

        order_req = {
            "condition_id": cid,
            "token_id": no_token_id,
            "price": no_price,
            "size": size,
            "requested_at": datetime.utcnow().isoformat(),
        }
        self.logger.info(f"NO order: BUY {size}@{no_price:.4f} for {cid[:12]}...")
        # Execute immediately rather than waiting for next cycle
        await self._place_order(cid, order_req)

    async def _handle_order_filled(self, event: Event) -> None:
        order_id = event.data.get("order_id", "")
        if order_id in self.active_orders:
            self.active_orders[order_id]["status"] = "FILLED"
            self.logger.info(f"NO order filled: {order_id}")

    async def _handle_risk_breach(self, event: Event) -> None:
        self.logger.warning("Risk breach — clearing pending NO orders")
        self.pending_orders.clear()

    async def _handle_emergency(self, event: Event) -> None:
        self.logger.warning("EMERGENCY — cancelling all NO orders")
        self.pending_orders.clear()
        await self._cancel_all_active()

    async def run_cycle(self) -> None:
        """Check active order status periodically."""
        await self._check_active_orders()

    async def _place_order(self, condition_id: str, order_req: dict) -> None:
        """Place a NO BUY order."""
        dry_run = self.config.dry_run and not self.config.simulate

        if dry_run:
            order_id = f"dry_no_{condition_id[:8]}_{datetime.utcnow().timestamp()}"
            self.logger.info(f"[DRY RUN] NO BUY {order_req['size']}@{order_req['price']:.4f}")
        else:
            try:
                result = await asyncio.get_running_loop().run_in_executor(
                    None,
                    self.client.place_order,
                    order_req["token_id"],
                    OrderAction.BUY,
                    order_req["price"],
                    order_req["size"],
                )
                order_id = result.get("orderID", "")
                if not order_id:
                    self.logger.error(f"NO order failed: {result}")
                    await self.bus.publish(Event(
                        event_type=EventType.ORDER_FAILED,
                        source=self.name,
                        data={"condition_id": condition_id, "side": "NO", "error": str(result)},
                    ))
                    return
            except Exception as e:
                self.logger.error(f"NO order placement error: {e}")
                await self.bus.publish(Event(
                    event_type=EventType.ORDER_FAILED,
                    source=self.name,
                    data={"condition_id": condition_id, "side": "NO", "error": str(e)},
                ))
                return

        self.active_orders[order_id] = {
            "order_id": order_id,
            "condition_id": condition_id,
            "token_id": order_req["token_id"],
            "side": "NO",
            "price": order_req["price"],
            "size": order_req["size"],
            "status": "OPEN",
            "placed_at": datetime.utcnow().isoformat(),
            "dry_run": dry_run,
        }

        await self.bus.publish(Event(
            event_type=EventType.ORDER_PLACED,
            source=self.name,
            data=self.active_orders[order_id],
        ))

    async def _check_active_orders(self) -> None:
        if self.config.dry_run and not self.config.simulate:
            return

        try:
            open_orders = await asyncio.get_running_loop().run_in_executor(
                None, self.client.get_open_orders
            )
            open_ids = {o.get("id") for o in open_orders}

            for oid, info in list(self.active_orders.items()):
                if info["status"] == "OPEN" and oid not in open_ids:
                    info["status"] = "FILLED"
                    await self.bus.publish(Event(
                        event_type=EventType.ORDER_FILLED,
                        source=self.name,
                        data=info,
                    ))
        except Exception as e:
            self.logger.error(f"Failed to check NO order status: {e}")

    async def _cancel_all_active(self) -> None:
        if self.config.dry_run and not self.config.simulate:
            self.active_orders.clear()
            return

        for oid in list(self.active_orders.keys()):
            try:
                await asyncio.get_running_loop().run_in_executor(
                    None, self.client.cancel_order, oid
                )
            except Exception as e:
                self.logger.error(f"Failed to cancel NO order {oid}: {e}")
        self.active_orders.clear()
