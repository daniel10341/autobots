"""Event system for inter-agent communication."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EventType(str, Enum):
    # Market events
    MARKET_DISCOVERED = "MARKET_DISCOVERED"
    MARKET_UPDATED = "MARKET_UPDATED"
    MARKET_EXPIRED = "MARKET_EXPIRED"
    MARKET_REMOVED = "MARKET_REMOVED"

    # Price events
    PRICE_UPDATED = "PRICE_UPDATED"
    SPREAD_OPPORTUNITY = "SPREAD_OPPORTUNITY"
    SPREAD_CLOSED = "SPREAD_CLOSED"

    # Order book events
    ORDERBOOK_UPDATED = "ORDERBOOK_UPDATED"
    LIQUIDITY_CHANGED = "LIQUIDITY_CHANGED"

    # Order events
    ORDER_REQUESTED = "ORDER_REQUESTED"
    ORDER_PLACED = "ORDER_PLACED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_FAILED = "ORDER_FAILED"
    PAIR_ORDER_REQUESTED = "PAIR_ORDER_REQUESTED"

    # Risk events
    RISK_CHECK_PASSED = "RISK_CHECK_PASSED"
    RISK_CHECK_FAILED = "RISK_CHECK_FAILED"
    RISK_LIMIT_BREACH = "RISK_LIMIT_BREACH"
    EMERGENCY_SHUTDOWN = "EMERGENCY_SHUTDOWN"

    # Portfolio events
    POSITION_UPDATED = "POSITION_UPDATED"
    PNL_UPDATED = "PNL_UPDATED"
    BALANCE_UPDATED = "BALANCE_UPDATED"

    # System events
    AGENT_STARTED = "AGENT_STARTED"
    AGENT_STOPPED = "AGENT_STOPPED"
    AGENT_ERROR = "AGENT_ERROR"
    HEALTH_CHECK = "HEALTH_CHECK"
    SHUTDOWN_REQUESTED = "SHUTDOWN_REQUESTED"


@dataclass
class Event:
    """An event passed between agents via the message bus."""

    event_type: EventType
    source: str  # Agent name that produced this event
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    priority: int = 0  # Higher = more urgent

    def __str__(self) -> str:
        return f"[{self.event_type.value}] from {self.source}: {self.data}"
