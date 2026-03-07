"""System Monitor"""
import logging
logger = logging.getLogger(__name__)

class SystemMonitor:
    """Monitors system health"""
    def __init__(self, agents):
        self.agents = agents
    
    def check_health(self):
        """Check system health"""
        status = 'HEALTHY'
        # Check if all agents are responsive
        for name, agent in self.agents.items():
            if agent is None:
                status = 'DEGRADED'
        return {'status': status, 'agents': len(self.agents)}
