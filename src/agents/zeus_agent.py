"""
ZEUS — COO Manager Agent
src/agents/zeus_agent.py

Role: Governance, health-monitoring, knowledge sharing.
ZEUS does NOT make trading decisions.

Responsibilities:
  - Heartbeat every 60 s; flags silent agents to GUARDIAN
  - Broadcasts knowledge_update events when SIGMA finds a pattern
  - Generates daily scorecard at 08:00 IST for Telegram
  - Tracks uptime KPI for every registered agent
"""

import logging
import threading
from datetime import datetime, time as dtime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("ZEUS")

# ── Graceful BaseAgent fallback ───────────────────────────────────────────────
try:
    from src.event_bus.event_bus import BaseAgent, EventType, Event
except ImportError:
    try:
        from ..event_bus.event_bus import BaseAgent, EventType, Event
    except ImportError:
        class BaseAgent:                                         # type: ignore
            def __init__(self, event_bus=None, config=None, name=""):
                self.event_bus = event_bus
                self.config    = config or {}
                self.name      = name
                self.is_active = True
            def publish_event(self, *a, **kw): pass
            def subscribe(self, *a, **kw): pass

        class EventType:                                         # type: ignore
            SYSTEM_COMMAND      = "system_command"
            STRATEGY_DISCOVERED = "strategy_discovered"

        class Event:                                             # type: ignore
            def __init__(self, **kw): pass


class ZeusAgent(BaseAgent):
    """
    COO Manager Agent.

    Usage in main.py / run_paper.py:
        zeus = Zeus(event_bus, config)
        zeus.run_cycle(self.agents)          # call each iteration
    """

    HEARTBEAT_INTERVAL = 60      # seconds between checks
    SILENCE_TIMEOUT    = 120     # seconds before agent flagged dead

    def __init__(self, event_bus=None, config: Optional[Dict] = None):
        super().__init__(event_bus=event_bus, config=config or {}, name="ZEUS")

        self._heartbeats:   Dict[str, datetime]   = {}
        self._lock          = threading.Lock()
        self._start_time    = datetime.now()
        self._cycles        = 0
        self._alerts_sent:  List[str]             = []
        self._scorecard:    Dict[str, Any]        = {}
        self._last_briefing: Optional[datetime]   = None

        logger.info("ZEUS online — governance & health-monitoring active")

    # ── Public API (called by main loop each iteration) ───────────────────────

    def run_cycle(self, agents: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main entry-point called by the orchestrator each iteration.
        Records heartbeats, checks silences, triggers knowledge sharing.
        """
        self._cycles += 1

        # 1. Record heartbeats for every living agent
        with self._lock:
            for name, agent in agents.items():
                if agent is not None:
                    self._heartbeats[name] = datetime.now()

        # 2. Check for silent agents every HEARTBEAT_INTERVAL
        if self._cycles % max(1, self.HEARTBEAT_INTERVAL // 15) == 0:
            self._check_agent_health(agents)

        # 3. Daily 08:00 IST briefing
        self._maybe_send_briefing(agents)

        return self.get_kpi()

    def get_kpi(self) -> Dict[str, Any]:
        health    = self._check_silence()
        alive     = sum(1 for v in health.values() if v)
        total     = len(health)
        uptime_s  = int((datetime.now() - self._start_time).total_seconds())
        return {
            "agents_alive":   alive,
            "agents_total":   total,
            "uptime_seconds": uptime_s,
            "cycles":         self._cycles,
            "status":         "OK" if alive == total else "DEGRADED",
            "health":         health,
        }

    # Convenience wrappers so old code that calls zeus.analyze() still works
    def analyze(self, *args, **kwargs) -> Dict[str, Any]:
        return self.get_kpi()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _check_silence(self) -> Dict[str, bool]:
        now = datetime.now()
        with self._lock:
            return {
                name: (now - ts).total_seconds() < self.SILENCE_TIMEOUT
                for name, ts in self._heartbeats.items()
            }

    def _check_agent_health(self, agents: Dict[str, Any]):
        silence = self._check_silence()
        dead    = [n for n, alive in silence.items() if not alive]
        if dead:
            logger.warning(f"ZEUS: silent agents detected — {dead}")
            # Publish system command so GUARDIAN can act
            try:
                self.publish_event(
                    EventType.SYSTEM_COMMAND,
                    {"command": "agent_silent", "agents": dead},
                    priority=8,
                )
            except Exception:
                pass
        else:
            alive = len(silence)
            if self._cycles % 20 == 0:
                logger.info(f"ZEUS health-check — {alive}/{alive} agents alive | "
                            f"uptime {int((datetime.now()-self._start_time).total_seconds())}s")

    def _maybe_send_briefing(self, agents: Dict[str, Any]):
        """Send daily 08:00 IST briefing via Telegram (if available)."""
        now = datetime.now()
        if (now.hour == 8 and now.minute < 1 and
                (self._last_briefing is None or
                 (now - self._last_briefing).total_seconds() > 3600)):
            kpi = self.get_kpi()
            msg = (
                f"🛡️ ZEUS Daily Briefing | {now.strftime('%d %b %Y')}\n"
                f"Agents: {kpi['agents_alive']}/{kpi['agents_total']} online\n"
                f"Uptime: {kpi['uptime_seconds']//3600}h\n"
                f"Status: {kpi['status']}"
            )
            logger.info(f"ZEUS briefing: {msg}")
            self._last_briefing = now

    def broadcast_knowledge(self, pattern: Dict[str, Any], source_agent: str):
        """
        Called when SIGMA / KARMA discovers a pattern.
        ZEUS validates and broadcasts to relevant subscribers.
        """
        logger.info(f"ZEUS knowledge-share: {source_agent} → {pattern.get('type','?')}")
        try:
            self.publish_event(
                EventType.STRATEGY_DISCOVERED,
                {"source": source_agent, "pattern": pattern,
                 "timestamp": datetime.now().isoformat()},
            )
        except Exception as e:
            logger.warning(f"ZEUS broadcast failed: {e}")


# Alias kept for legacy imports
Zeus = ZeusAgent
