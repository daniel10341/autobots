"""Agent 10: Monitoring Agent — Health checks, alerts, and logging dashboard."""

import json
from datetime import datetime
from pathlib import Path

from polymarket_bot.config import BotConfig
from polymarket_bot.core.base_agent import BaseAgent
from polymarket_bot.core.message_bus import MessageBus
from polymarket_bot.models.events import Event, EventType


class MonitorAgent(BaseAgent):
    """Monitors the health of all agents and provides a dashboard view.

    Tracks:
    - Agent health status (alive, cycle count, errors)
    - Recent events and alerts
    - System-wide metrics
    - Writes periodic status to a JSON file for external monitoring
    """

    def __init__(self, config: BotConfig, message_bus: MessageBus, all_agents: list) -> None:
        super().__init__("Monitor", config, message_bus)
        self.all_agents = all_agents  # References to all other agents
        self.alerts: list[dict] = []
        self.agent_errors: dict[str, int] = {}
        self.events_seen: int = 0
        self.status_file = Path("bot_status.json")

    @property
    def cycle_interval(self) -> float:
        return self.config.agents.health_check_interval

    def _setup_subscriptions(self) -> None:
        self.bus.subscribe(EventType.AGENT_STARTED, self._handle_agent_event)
        self.bus.subscribe(EventType.AGENT_STOPPED, self._handle_agent_event)
        self.bus.subscribe(EventType.AGENT_ERROR, self._handle_agent_error)
        self.bus.subscribe(EventType.EMERGENCY_SHUTDOWN, self._handle_emergency)
        self.bus.subscribe(EventType.ORDER_PLACED, self._count_event)
        self.bus.subscribe(EventType.ORDER_FILLED, self._count_event)
        self.bus.subscribe(EventType.ORDER_FAILED, self._handle_order_failed)
        self.bus.subscribe(EventType.SPREAD_OPPORTUNITY, self._count_event)
        self.bus.subscribe(EventType.PNL_UPDATED, self._handle_pnl)

    async def _handle_agent_event(self, event: Event) -> None:
        self.events_seen += 1
        self.logger.info(f"Agent event: {event.event_type.value} — {event.data.get('agent', '')}")

    async def _handle_agent_error(self, event: Event) -> None:
        self.events_seen += 1
        agent_name = event.data.get("agent", "unknown")
        self.agent_errors[agent_name] = self.agent_errors.get(agent_name, 0) + 1
        self.alerts.append({
            "level": "ERROR",
            "agent": agent_name,
            "message": event.data.get("error", ""),
            "timestamp": datetime.utcnow().isoformat(),
        })
        # Keep alerts bounded
        if len(self.alerts) > 500:
            self.alerts = self.alerts[-250:]

    async def _handle_emergency(self, event: Event) -> None:
        self.alerts.append({
            "level": "CRITICAL",
            "agent": event.source,
            "message": f"EMERGENCY SHUTDOWN: {event.data.get('reason', '')}",
            "timestamp": datetime.utcnow().isoformat(),
        })
        self.logger.critical(f"EMERGENCY SHUTDOWN triggered by {event.source}: {event.data}")

    async def _handle_order_failed(self, event: Event) -> None:
        self.events_seen += 1
        self.alerts.append({
            "level": "WARNING",
            "agent": event.source,
            "message": f"Order failed: {event.data.get('error', '')}",
            "timestamp": datetime.utcnow().isoformat(),
        })

    async def _count_event(self, event: Event) -> None:
        self.events_seen += 1

    async def _handle_pnl(self, event: Event) -> None:
        self.events_seen += 1
        self._last_pnl = event.data

    _last_pnl: dict = {}

    async def run_cycle(self) -> None:
        """Run health checks on all agents and write status."""
        agent_statuses = []
        unhealthy = []

        for agent in self.all_agents:
            status = agent.status
            agent_statuses.append(status)
            if not status.get("healthy", False) and status.get("running", False):
                unhealthy.append(status["name"])

        if unhealthy:
            self.logger.warning(f"Unhealthy agents: {', '.join(unhealthy)}")

        # Build dashboard
        dashboard = {
            "timestamp": datetime.utcnow().isoformat(),
            "agents": agent_statuses,
            "unhealthy_agents": unhealthy,
            "total_events": self.events_seen,
            "total_errors": sum(self.agent_errors.values()),
            "error_breakdown": self.agent_errors,
            "recent_alerts": self.alerts[-10:],
            "pnl": self._last_pnl,
            "message_bus_pending": self.bus.pending_count,
        }

        # Write to file for external monitoring
        try:
            self.status_file.write_text(json.dumps(dashboard, indent=2, default=str))
        except Exception as e:
            self.logger.error(f"Failed to write status file: {e}")

        # Log summary
        healthy_count = sum(1 for s in agent_statuses if s.get("healthy"))
        self.logger.info(
            f"Health: {healthy_count}/{len(agent_statuses)} agents healthy | "
            f"Events: {self.events_seen} | Errors: {sum(self.agent_errors.values())} | "
            f"Bus queue: {self.bus.pending_count}"
        )
