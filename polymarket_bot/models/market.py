"""Market and order data models."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Side(str, Enum):
    YES = "YES"
    NO = "NO"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class OrderAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Token:
    """A single outcome token (YES or NO) in a market."""

    token_id: str
    side: Side
    price: float = 0.0
    best_bid: float = 0.0
    best_ask: float = 0.0


@dataclass
class Market:
    """A Polymarket binary market."""

    condition_id: str
    question: str
    slug: str = ""
    yes_token: Optional[Token] = None
    no_token: Optional[Token] = None
    active: bool = True
    end_date: Optional[datetime] = None
    volume_24h: float = 0.0
    liquidity: float = 0.0

    @property
    def combined_ask_cost(self) -> float:
        """Cost to buy both sides at their ask prices."""
        if self.yes_token and self.no_token:
            return self.yes_token.best_ask + self.no_token.best_ask
        return float("inf")

    @property
    def spread_profit(self) -> float:
        """Guaranteed profit per pair = $1 - combined ask cost."""
        return 1.0 - self.combined_ask_cost

    @property
    def is_profitable(self) -> bool:
        return self.spread_profit > 0


@dataclass
class Order:
    """An order placed on the CLOB."""

    order_id: str = ""
    market_condition_id: str = ""
    token_id: str = ""
    side: Side = Side.YES
    action: OrderAction = OrderAction.BUY
    price: float = 0.0
    size: float = 0.0
    filled_size: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    pair_order_id: str = ""  # Links YES/NO counterpart orders


@dataclass
class Position:
    """A held position in a market."""

    market_condition_id: str = ""
    market_question: str = ""
    yes_shares: float = 0.0
    no_shares: float = 0.0
    yes_avg_cost: float = 0.0
    no_avg_cost: float = 0.0
    total_invested: float = 0.0
    unrealized_pnl: float = 0.0

    @property
    def is_hedged(self) -> bool:
        """True if we hold both sides (the market maker position)."""
        return self.yes_shares > 0 and self.no_shares > 0

    @property
    def hedged_pairs(self) -> float:
        """Number of fully hedged pairs (guaranteed $1 payout each)."""
        return min(self.yes_shares, self.no_shares)

    @property
    def guaranteed_payout(self) -> float:
        """Guaranteed payout from hedged pairs."""
        return self.hedged_pairs * 1.0

    @property
    def guaranteed_profit(self) -> float:
        """Guaranteed profit from hedged positions."""
        cost_of_hedged = self.hedged_pairs * (self.yes_avg_cost + self.no_avg_cost)
        return self.guaranteed_payout - cost_of_hedged


@dataclass
class OrderBookLevel:
    """A single price level in the order book."""

    price: float
    size: float


@dataclass
class OrderBook:
    """Order book snapshot for a token."""

    token_id: str = ""
    side: Side = Side.YES
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else float("inf")

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid

    def depth_at_price(self, price: float, side: str = "ask") -> float:
        """Total size available at or better than a given price."""
        levels = self.asks if side == "ask" else self.bids
        total = 0.0
        for level in levels:
            if side == "ask" and level.price <= price:
                total += level.size
            elif side == "bid" and level.price >= price:
                total += level.size
        return total
