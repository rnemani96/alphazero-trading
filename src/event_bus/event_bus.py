"""
Event Bus System for AlphaZero Capital
Enables agent-to-agent communication without direct dependencies

FIXES:
- Added start() and stop() methods (were missing, called in main.py)
- Added priority: int field to Event dataclass (was missing; two agents tried to use it)
- EventBus.publish() now uses a heapq priority queue so high-priority events
  (e.g. OPTIONS_FLOW priority=9, MTF-confirmed priority+1) are dispatched first
- BaseAgent.publish_event() accepts optional priority kwarg and passes it through
- Added thread-safe _lock for publish/subscribe operations
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Callable, Optional
import logging
import threading
import heapq

logger = logging.getLogger(__name__)


class EventType(Enum):
    SIGNAL_GENERATED    = "signal_generated"
    TRADE_EXECUTED      = "trade_executed"
    RISK_ALERT          = "risk_alert"
    REGIME_CHANGE       = "regime_change"
    NEWS_UPDATE         = "news_update"
    OPTIONS_FLOW        = "options_flow"
    EARNINGS_ANALYZED   = "earnings_analyzed"
    STRATEGY_DISCOVERED = "strategy_discovered"
    POSITION_OPENED     = "position_opened"
    POSITION_CLOSED     = "position_closed"
    STOP_LOSS_HIT       = "stop_loss_hit"
    TARGET_REACHED      = "target_reached"
    SYSTEM_COMMAND      = "system_command"


@dataclass
class Event:
    """
    Event data structure.

    Priority scale (higher = dispatched first):
        1  - low / background tasks
        5  - normal signals (default)
        7  - MTF-confirmed signals
        9  - Options flow / institutional smart-money signals
        10 - Emergency / kill-switch commands
    """
    type: EventType
    source_agent: str
    payload: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    correlation_id: Optional[str] = None
    priority: int = 5   # FIX: was missing — caused AttributeError in MTF & options agents

    def to_dict(self) -> Dict:
        return {
            'type':           self.type.value,
            'source_agent':   self.source_agent,
            'payload':        self.payload,
            'timestamp':      self.timestamp.isoformat(),
            'correlation_id': self.correlation_id,
            'priority':       self.priority,
        }

    def __lt__(self, other: 'Event') -> bool:
        # Inverted so heapq (min-heap) behaves as max-priority-first
        return self.priority > other.priority


class BaseAgent:
    """Base class for all agents."""

    def __init__(self, event_bus=None, config=None, name="BaseAgent"):
        self.event_bus = event_bus
        self.config    = config or {}
        self.name      = name
        self.logger    = logging.getLogger(f"Agent.{name}")
        self.is_active = True
        self.logger.info(f"{self.name} initialized")

    def publish_event(
        self,
        event_type: EventType,
        payload: Dict[str, Any],
        priority: int = 5          # FIX: priority kwarg now wired through
    ):
        if self.event_bus:
            event = Event(
                type=event_type,
                source_agent=self.name,
                payload=payload,
                priority=priority
            )
            self.event_bus.publish(event)
            self.logger.debug(f"Published event: {event_type.value} (priority={priority})")
        else:
            self.logger.warning(f"No event bus - cannot publish {event_type.value}")

    def subscribe(self, event_type: EventType, callback: Callable):
        if self.event_bus:
            self.event_bus.subscribe(event_type, callback)
        else:
            self.logger.warning("No event bus - cannot subscribe")

    def get_status(self) -> Dict[str, Any]:
        return {'name': self.name, 'active': self.is_active,
                'has_event_bus': self.event_bus is not None}

    def shutdown(self):
        self.is_active = False
        self.logger.info(f"{self.name} shutting down")


class EventBus:
    """
    Central priority event bus for agent communication.

    FIXES:
    - start() / stop() added (were missing)
    - Events dispatched in priority order via heapq
    - Thread-safe via _lock
    """

    def __init__(self):
        self.subscribers: Dict[EventType, List[Callable]] = {}
        self._pq: List[Event]    = []      # heapq priority queue
        self.events: List[Event] = []      # flat history
        self.max_history         = 10_000
        self._lock               = threading.Lock()
        self._running            = False
        logger.info("EventBus initialized")

    def start(self):
        self._running = True
        logger.info("EventBus started")

    def stop(self):
        self._running = False
        self._flush_queue()
        logger.info("EventBus stopped")

    def _flush_queue(self):
        while self._pq:
            event = heapq.heappop(self._pq)
            self._dispatch(event)

    def publish(self, event: Event):
        with self._lock:
            heapq.heappush(self._pq, event)
            self.events.append(event)
            if len(self.events) > self.max_history:
                self.events = self.events[-self.max_history:]
        # Synchronous dispatch of highest-priority pending event
        self._dispatch_top()
        logger.debug(
            f"Event: {event.type.value} from {event.source_agent} "
            f"(priority={event.priority})"
        )

    def _dispatch_top(self):
        with self._lock:
            if not self._pq:
                return
            event = heapq.heappop(self._pq)
        self._dispatch(event)

    def _dispatch(self, event: Event):
        if event.type in self.subscribers:
            for callback in self.subscribers[event.type]:
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"Error in subscriber callback: {e}", exc_info=True)

    def subscribe(self, event_type: EventType, callback: Callable):
        with self._lock:
            if event_type not in self.subscribers:
                self.subscribers[event_type] = []
            self.subscribers[event_type].append(callback)

    def get_events(
        self,
        event_type: Optional[EventType] = None,
        source_agent: Optional[str] = None,
        limit: int = 100
    ) -> List[Event]:
        filtered = self.events
        if event_type:
            filtered = [e for e in filtered if e.type == event_type]
        if source_agent:
            filtered = [e for e in filtered if e.source_agent == source_agent]
        return filtered[-limit:]

    def clear_history(self):
        with self._lock:
            self.events = []
            self._pq    = []
        logger.info("Event history cleared")

    def get_stats(self) -> Dict[str, Any]:
        event_counts: Dict[str, int] = {}
        by_priority:  Dict[int, int] = {}
        for e in self.events:
            event_counts[e.type.value]  = event_counts.get(e.type.value, 0) + 1
            by_priority[e.priority]     = by_priority.get(e.priority, 0) + 1
        return {
            'total_events':       len(self.events),
            'queued_events':      len(self._pq),
            'event_types':        len(self.subscribers),
            'event_counts':       event_counts,
            'priority_breakdown': by_priority,
            'total_subscribers':  sum(len(s) for s in self.subscribers.values()),
            'running':            self._running,
        }
