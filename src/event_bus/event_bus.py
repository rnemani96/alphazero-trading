"""
Event Bus System for AlphaZero Capital
Enables agent-to-agent communication without direct dependencies
"""

from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Callable, Optional
import logging

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Types of events in the system"""
    SIGNAL_GENERATED = "signal_generated"
    TRADE_EXECUTED = "trade_executed"
    RISK_ALERT = "risk_alert"
    REGIME_CHANGE = "regime_change"
    NEWS_UPDATE = "news_update"
    OPTIONS_FLOW = "options_flow"
    EARNINGS_ANALYZED = "earnings_analyzed"
    STRATEGY_DISCOVERED = "strategy_discovered"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    STOP_LOSS_HIT = "stop_loss_hit"
    TARGET_REACHED = "target_reached"
    SYSTEM_COMMAND = "system_command"


@dataclass
class Event:
    """Event data structure"""
    type: EventType
    source_agent: str
    payload: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    correlation_id: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'type': self.type.value,
            'source_agent': self.source_agent,
            'payload': self.payload,
            'timestamp': self.timestamp.isoformat(),
            'correlation_id': self.correlation_id
        }


class BaseAgent:
    """
    Base class for all agents
    
    All agents inherit from this to get common functionality:
    - Event bus connection
    - Logging
    - Configuration
    - Health checks
    """
    
    def __init__(self, event_bus=None, config=None, name="BaseAgent"):
        """
        Initialize base agent
        
        Args:
            event_bus: EventBus instance for communication
            config: Configuration dictionary
            name: Agent name for identification
        """
        self.event_bus = event_bus
        self.config = config or {}
        self.name = name
        self.logger = logging.getLogger(f"Agent.{name}")
        self.is_active = True
        
        self.logger.info(f"{self.name} initialized")
    
    def publish_event(self, event_type: EventType, payload: Dict[str, Any]):
        """
        Publish an event to the event bus
        
        Args:
            event_type: Type of event
            payload: Event data
        """
        if self.event_bus:
            event = Event(
                type=event_type,
                source_agent=self.name,
                payload=payload
            )
            self.event_bus.publish(event)
            self.logger.debug(f"Published event: {event_type.value}")
        else:
            self.logger.warning(f"No event bus - cannot publish {event_type.value}")
    
    def subscribe(self, event_type: EventType, callback: Callable):
        """
        Subscribe to events
        
        Args:
            event_type: Type of event to listen for
            callback: Function to call when event occurs
        """
        if self.event_bus:
            self.event_bus.subscribe(event_type, callback)
            self.logger.debug(f"Subscribed to {event_type.value}")
        else:
            self.logger.warning("No event bus - cannot subscribe")
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get agent status
        
        Returns:
            Dictionary with agent status
        """
        return {
            'name': self.name,
            'active': self.is_active,
            'has_event_bus': self.event_bus is not None
        }
    
    def shutdown(self):
        """Shutdown the agent"""
        self.is_active = False
        self.logger.info(f"{self.name} shutting down")


class EventBus:
    """
    Central event bus for agent communication
    
    Agents publish events to the bus and subscribe to events they care about.
    This decouples agents - they don't need direct references to each other.
    """
    
    def __init__(self):
        """Initialize the event bus"""
        self.subscribers: Dict[EventType, List[Callable]] = {}
        self.events: List[Event] = []
        self.max_history = 10000  # Keep last 10k events
        
        logger.info("EventBus initialized")

    def start(self):
        """Start the event bus (idempotent)."""
        self._running = True
        logger.info("EventBus started")

    def stop(self):
        """Stop the event bus and clear state."""
        self._running = False
        logger.info("EventBus stopped")
    
    def publish(self, event: Event):
        """
        Publish an event
        
        Args:
            event: Event to publish
        """
        # Store event
        self.events.append(event)
        
        # Trim history if needed
        if len(self.events) > self.max_history:
            self.events = self.events[-self.max_history:]
        
        # Notify subscribers
        if event.type in self.subscribers:
            for callback in self.subscribers[event.type]:
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"Error in subscriber callback: {e}", exc_info=True)
        
        logger.debug(f"Event published: {event.type.value} from {event.source_agent}")
    
    def subscribe(self, event_type: EventType, callback: Callable):
        """
        Subscribe to an event type
        
        Args:
            event_type: Type of event to subscribe to
            callback: Function to call when event occurs
        """
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        
        self.subscribers[event_type].append(callback)
        logger.debug(f"New subscriber for {event_type.value}")
    
    def get_events(
        self, 
        event_type: Optional[EventType] = None,
        source_agent: Optional[str] = None,
        limit: int = 100
    ) -> List[Event]:
        """
        Get events from history
        
        Args:
            event_type: Filter by event type
            source_agent: Filter by source agent
            limit: Maximum number of events to return
        
        Returns:
            List of events
        """
        filtered = self.events
        
        if event_type:
            filtered = [e for e in filtered if e.type == event_type]
        
        if source_agent:
            filtered = [e for e in filtered if e.source_agent == source_agent]
        
        return filtered[-limit:]
    
    def clear_history(self):
        """Clear event history"""
        self.events = []
        logger.info("Event history cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get event bus statistics
        
        Returns:
            Dictionary with stats
        """
        event_counts = {}
        for event in self.events:
            event_type = event.type.value
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
        
        return {
            'total_events': len(self.events),
            'event_types': len(self.subscribers),
            'event_counts': event_counts,
            'total_subscribers': sum(len(subs) for subs in self.subscribers.values())
        }


# Example usage
if __name__ == "__main__":
    # Create event bus
    bus = EventBus()
    
    # Create a sample agent
    agent = BaseAgent(event_bus=bus, name="TestAgent")
    
    # Subscribe to events
    def handle_signal(event: Event):
        print(f"Received signal: {event.payload}")
    
    bus.subscribe(EventType.SIGNAL_GENERATED, handle_signal)
    
    # Publish an event
    agent.publish_event(
        EventType.SIGNAL_GENERATED,
        {'symbol': 'RELIANCE', 'signal': 'BUY', 'confidence': 0.85}
    )
    
    # Get stats
    print(bus.get_stats())
    
    print("\n✅ EventBus test complete!")
