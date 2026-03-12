"""Base agent class — all 10 agents inherit from this."""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from polymarket_bot.config import BotConfig
from polymarket_bot.core.message_bus import MessageBus
from polymarket_bot.models.events import Event, EventType


class BaseAgent(ABC):
    """Abstract base class for all agents in the market maker bot.

    Provides lifecycle management, event handling, and health reporting.
    """

    def __init__(self, name: str, config: BotConfig, message_bus: MessageBus) -> None:
        self.name = name
        self.config = config
        self.bus = message_bus
        self.logger = logging.getLogger(f"agent.{name}")
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._started_at: Optional[datetime] = None
        self._last_heartbeat: Optional[datetime] = None
        self._error_count = 0
        self._cycle_count = 0

    async def start(self) -> None:
        """Start the agent's main loop."""
        self._running = True
        self._started_at = datetime.utcnow()
        self._setup_subscriptions()
        self._task = asyncio.create_task(self._run_loop())
        await self.bus.publish(Event(
            event_type=EventType.AGENT_STARTED,
            source=self.name,
            data={"agent": self.name},
        ))
        self.logger.info(f"{self.name} started")

    async def stop(self) -> None:
        """Stop the agent gracefully."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.bus.publish(Event(
            event_type=EventType.AGENT_STOPPED,
            source=self.name,
            data={"agent": self.name},
        ))
        self.logger.info(f"{self.name} stopped")

    async def _run_loop(self) -> None:
        """Main agent loop — calls run_cycle at the configured interval."""
        while self._running:
            try:
                await self.run_cycle()
                self._cycle_count += 1
                self._last_heartbeat = datetime.utcnow()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._error_count += 1
                self.logger.error(f"Cycle error: {e}", exc_info=True)
                await self.bus.publish(Event(
                    event_type=EventType.AGENT_ERROR,
                    source=self.name,
                    data={"error": str(e), "agent": self.name},
                ))

            await asyncio.sleep(self.cycle_interval)

    @abstractmethod
    async def run_cycle(self) -> None:
        """One iteration of the agent's work. Subclasses must implement."""
        ...

    @abstractmethod
    def _setup_subscriptions(self) -> None:
        """Set up event subscriptions. Subclasses must implement."""
        ...

    @property
    @abstractmethod
    def cycle_interval(self) -> float:
        """Seconds between cycles. Subclasses must implement."""
        ...

    @property
    def is_healthy(self) -> bool:
        """Check if the agent is running and responsive."""
        if not self._running:
            return False
        if self._last_heartbeat:
            elapsed = (datetime.utcnow() - self._last_heartbeat).total_seconds()
            return elapsed < self.cycle_interval * 3
        return True

    @property
    def status(self) -> dict:
        return {
            "name": self.name,
            "running": self._running,
            "healthy": self.is_healthy,
            "cycles": self._cycle_count,
            "errors": self._error_count,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "last_heartbeat": self._last_heartbeat.isoformat() if self._last_heartbeat else None,
        }
