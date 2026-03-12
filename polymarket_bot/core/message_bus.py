"""Async message bus for inter-agent communication."""

import asyncio
import logging
from collections import defaultdict
from typing import Callable, Coroutine, Any

from polymarket_bot.models.events import Event, EventType

logger = logging.getLogger(__name__)

# Type alias for event handlers
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class MessageBus:
    """Publish-subscribe message bus connecting all 10 agents.

    Agents subscribe to event types and publish events. The bus
    routes events to all subscribers asynchronously.
    """

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._running = False
        self._dispatch_task: asyncio.Task | None = None
        self._event_log: list[Event] = []
        self._max_log_size = 10000

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe a handler to an event type."""
        self._subscribers[event_type].append(handler)
        logger.debug(f"Subscribed handler to {event_type.value}")

    def subscribe_many(self, event_types: list[EventType], handler: EventHandler) -> None:
        """Subscribe a handler to multiple event types."""
        for et in event_types:
            self.subscribe(et, handler)

    async def publish(self, event: Event) -> None:
        """Publish an event to the bus."""
        await self._queue.put(event)

    def publish_sync(self, event: Event) -> None:
        """Non-async publish for use in sync contexts."""
        self._queue.put_nowait(event)

    async def start(self) -> None:
        """Start the message bus dispatch loop."""
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        logger.info("Message bus started")

    async def stop(self) -> None:
        """Stop the message bus."""
        self._running = False
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        logger.info("Message bus stopped")

    async def _dispatch_loop(self) -> None:
        """Main dispatch loop — routes events to subscribers."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            # Log the event
            self._event_log.append(event)
            if len(self._event_log) > self._max_log_size:
                self._event_log = self._event_log[-self._max_log_size // 2 :]

            # Dispatch to all subscribers
            handlers = self._subscribers.get(event.event_type, [])
            if not handlers:
                logger.debug(f"No handlers for {event.event_type.value}")
                continue

            tasks = []
            for handler in handlers:
                tasks.append(asyncio.create_task(self._safe_dispatch(handler, event)))

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_dispatch(self, handler: EventHandler, event: Event) -> None:
        """Dispatch an event to a handler with error protection."""
        try:
            await handler(event)
        except Exception as e:
            logger.error(f"Handler error for {event.event_type.value}: {e}", exc_info=True)

    @property
    def pending_count(self) -> int:
        return self._queue.qsize()

    @property
    def recent_events(self) -> list[Event]:
        return self._event_log[-50:]
