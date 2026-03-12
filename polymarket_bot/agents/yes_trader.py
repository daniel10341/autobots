"""Agent 5: YES Side Trader — Places and manages YES side buy orders."""

import asyncio
from datetime import datetime

from polymarket_bot.config import BotConfig
from polymarket_bot.core.base_agent import BaseAgent
from polymarket_bot.core.message_bus import MessageBus
from polymarket_bot.core.polymarket_client import PolymarketClient
from polymarket_bot.models.events import Event, EventType
from polymarket_bot.models.market import OrderAction


class YesTraderAgent(BaseAgent):
    """Manages the YES side of market maker positions.

    When a SPREAD_OPPORTUNITY is detected and risk-approved, this agent
    places BUY orders for YES tokens at the target price.
    """

    def __init__(self, config: BotConfig, message_bus: MessageBus, client: PolymarketClient) -> None:
        super().__init__("YesTrader", config, message_bus)
        self.client = client
        self.pending_orders: dict[str, dict] = {}  # condition_id -> order request
        self.active_orders: dict[str, dict] = {}  # order_id -> order info

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
        yes_token_id = event.data.get("yes_token_id", "")
        yes_price = event.data.get("yes_price", 0)
        size = event.data.get("size", 0)

        if not yes_token_id or yes_price <= 0 or size <= 0:
            return

        self.pending_orders[cid] = {
            "condition_id": cid,
            "token_id": yes_token_id,
            "price": yes_price,
            "size": size,
            "requested_at": datetime.utcnow().isoformat(),
        }
        self.logger.info(f"YES order queued: BUY {size}@{yes_price:.4f} for {cid[:12]}...")

    async def _handle_order_filled(self, event: Event) -> None:
        order_id = event.data.get("order_id", "")
        if order_id in self.active_orders:
            self.active_orders[order_id]["status"] = "FILLED"
            self.logger.info(f"YES order filled: {order_id}")

    async def _handle_risk_breach(self, event: Event) -> None:
        """Cancel pending orders if risk limits breached."""
        self.logger.warning("Risk breach — clearing pending YES orders")
        self.pending_orders.clear()

    async def _handle_emergency(self, event: Event) -> None:
        """Emergency: cancel all orders."""
        self.logger.warning("EMERGENCY — cancelling all YES orders")
        self.pending_orders.clear()
        await self._cancel_all_active()

    async def run_cycle(self) -> None:
        """Process pending orders and check active order status."""
        # Place pending orders
        for cid, order_req in list(self.pending_orders.items()):
            await self._place_order(cid, order_req)
            del self.pending_orders[cid]
            await asyncio.sleep(0.3)

        # Refresh stale active orders
        await self._check_active_orders()

    async def _place_order(self, condition_id: str, order_req: dict) -> None:
        """Place a YES BUY order."""
        dry_run = self.config.dry_run and not self.config.simulate

        if dry_run:
            order_id = f"dry_yes_{condition_id[:8]}_{datetime.utcnow().timestamp()}"
            self.logger.info(f"[DRY RUN] YES BUY {order_req['size']}@{order_req['price']:.4f}")
        else:
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.client.place_order,
                    order_req["token_id"],
                    OrderAction.BUY,
                    order_req["price"],
                    order_req["size"],
                )
                order_id = result.get("orderID", "")
                if not order_id:
                    self.logger.error(f"YES order failed: {result}")
                    await self.bus.publish(Event(
                        event_type=EventType.ORDER_FAILED,
                        source=self.name,
                        data={"condition_id": condition_id, "side": "YES", "error": str(result)},
                    ))
                    return
            except Exception as e:
                self.logger.error(f"YES order placement error: {e}")
                await self.bus.publish(Event(
                    event_type=EventType.ORDER_FAILED,
                    source=self.name,
                    data={"condition_id": condition_id, "side": "YES", "error": str(e)},
                ))
                return

        self.active_orders[order_id] = {
            "order_id": order_id,
            "condition_id": condition_id,
            "token_id": order_req["token_id"],
            "side": "YES",
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
        """Check status of active orders."""
        if self.config.dry_run and not self.config.simulate:
            return

        try:
            open_orders = await asyncio.get_event_loop().run_in_executor(
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
            self.logger.error(f"Failed to check order status: {e}")

    async def _cancel_all_active(self) -> None:
        """Cancel all active YES orders."""
        if self.config.dry_run and not self.config.simulate:
            self.active_orders.clear()
            return

        for oid in list(self.active_orders.keys()):
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, self.client.cancel_order, oid
                )
            except Exception as e:
                self.logger.error(f"Failed to cancel YES order {oid}: {e}")
        self.active_orders.clear()
