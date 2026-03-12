"""Simulation engine — fake order execution with real market data."""

import logging
import random
from datetime import datetime
from typing import Any

from polymarket_bot.models.market import OrderAction, OrderStatus

logger = logging.getLogger(__name__)


class SimulatedExchange:
    """Simulates the Polymarket exchange with a virtual balance.

    Uses real order book data but executes trades locally with
    simulated fills, slippage, and latency.
    """

    def __init__(self, starting_balance: float = 1000.0, capital_max: float = 0.0) -> None:
        self.balance = starting_balance
        self.starting_balance = starting_balance
        self.capital_max = capital_max  # 0 = unlimited
        self.total_spent: float = 0.0
        self.positions: dict[str, float] = {}  # token_id -> shares held
        self.order_counter = 0
        self.orders: dict[str, dict] = {}
        self.trade_history: list[dict] = []
        self.total_fees_paid: float = 0.0

        # Simulation parameters
        self.fill_probability: float = 0.85  # 85% chance order fills
        self.slippage_bps: float = 10.0  # 10 basis points avg slippage
        self.fee_rate: float = 0.001  # 0.1% taker fee

    def place_order(
        self,
        token_id: str,
        action: OrderAction,
        price: float,
        size: float,
    ) -> dict[str, Any]:
        """Simulate placing an order. Returns immediately with fill result."""
        self.order_counter += 1
        order_id = f"sim_{self.order_counter:06d}"

        # Simulate fill probability
        fills = random.random() < self.fill_probability

        if not fills:
            logger.info(f"[SIM] Order {order_id} NOT filled (simulated miss)")
            self.orders[order_id] = {
                "orderID": order_id,
                "status": "CANCELLED",
                "token_id": token_id,
                "side": action.value,
                "price": price,
                "size": size,
            }
            return {"orderID": order_id, "status": "CANCELLED"}

        # Apply slippage
        slippage = random.gauss(0, self.slippage_bps / 10000)
        if action == OrderAction.BUY:
            fill_price = min(price * (1 + abs(slippage)), 0.99)
        else:
            fill_price = max(price * (1 - abs(slippage)), 0.01)

        # Calculate cost and fees
        cost = fill_price * size
        fee = cost * self.fee_rate
        total_cost = cost + fee

        if action == OrderAction.BUY:
            if total_cost > self.balance:
                logger.warning(f"[SIM] Insufficient balance: need ${total_cost:.2f}, have ${self.balance:.2f}")
                return {"orderID": order_id, "status": "FAILED", "error": "insufficient_balance"}

            if self.capital_max > 0 and self.total_spent + total_cost > self.capital_max:
                logger.warning(
                    f"[SIM] Capital max ${self.capital_max:.2f} reached "
                    f"(spent: ${self.total_spent:.2f}, this: ${total_cost:.2f})"
                )
                return {"orderID": order_id, "status": "FAILED", "error": "capital_max_reached"}

            self.balance -= total_cost
            self.total_spent += total_cost
            self.positions[token_id] = self.positions.get(token_id, 0) + size
        else:
            current = self.positions.get(token_id, 0)
            if current < size:
                logger.warning(f"[SIM] Insufficient shares: need {size}, have {current}")
                return {"orderID": order_id, "status": "FAILED", "error": "insufficient_shares"}

            self.balance += cost - fee
            self.positions[token_id] = current - size

        self.total_fees_paid += fee

        trade = {
            "order_id": order_id,
            "token_id": token_id,
            "action": action.value,
            "price": price,
            "fill_price": fill_price,
            "size": size,
            "cost": cost,
            "fee": fee,
            "balance_after": self.balance,
            "timestamp": datetime.utcnow().isoformat(),
        }
        self.trade_history.append(trade)

        logger.info(
            f"[SIM] FILLED {action.value} {size:.1f}@{fill_price:.4f} "
            f"(requested {price:.4f}) | Cost: ${total_cost:.2f} | "
            f"Fee: ${fee:.4f} | Balance: ${self.balance:.2f}"
        )

        self.orders[order_id] = {
            "orderID": order_id,
            "status": "FILLED",
            **trade,
        }
        return {"orderID": order_id, "status": "FILLED"}

    def cancel_order(self, order_id: str) -> dict[str, Any]:
        if order_id in self.orders:
            self.orders[order_id]["status"] = "CANCELLED"
        return {"status": "CANCELLED"}

    def cancel_all(self) -> dict[str, Any]:
        for oid in self.orders:
            if self.orders[oid].get("status") == "OPEN":
                self.orders[oid]["status"] = "CANCELLED"
        return {"status": "OK"}

    def get_orders(self) -> list[dict]:
        return [o for o in self.orders.values() if o.get("status") == "OPEN"]

    @property
    def pnl(self) -> float:
        return self.balance - self.starting_balance

    @property
    def total_position_value(self) -> float:
        """Approximate value of held positions (assumes ~0.50 avg price)."""
        return sum(shares * 0.50 for shares in self.positions.values())

    def summary(self) -> dict:
        return {
            "balance": round(self.balance, 2),
            "starting_balance": self.starting_balance,
            "capital_max": self.capital_max,
            "total_spent": round(self.total_spent, 2),
            "pnl": round(self.pnl, 2),
            "pnl_pct": round(self.pnl / self.starting_balance * 100, 2),
            "total_trades": len(self.trade_history),
            "total_fees": round(self.total_fees_paid, 4),
            "positions": {k: round(v, 2) for k, v in self.positions.items() if v > 0},
            "num_positions": sum(1 for v in self.positions.values() if v > 0),
        }

    def print_summary(self) -> str:
        s = self.summary()
        lines = [
            "=" * 50,
            "SIMULATION SUMMARY",
            "=" * 50,
            f"Starting balance:  ${s['starting_balance']:.2f}",
            f"Current balance:   ${s['balance']:.2f}",
            f"P&L:               ${s['pnl']:.2f} ({s['pnl_pct']:.2f}%)",
            f"Total trades:      {s['total_trades']}",
            f"Total fees:        ${s['total_fees']:.4f}",
            f"Open positions:    {s['num_positions']}",
            "=" * 50,
        ]
        return "\n".join(lines)
