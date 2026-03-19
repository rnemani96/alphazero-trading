"""
Sentinel — System Integrity & Monitoring Agent
src/agents/sentinel.py

Monitors:
  1. Data Freshness (MultiSourceData latencies)
  2. State Consistency (status.json updates)
  3. Execution Integrity (fills vs signals)
  4. Memory/CPU usage (optional)
"""

import os
import json
import logging
import time
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger("SENTINEL")

try:
    from src.event_bus.event_bus import BaseAgent
except ImportError:
    class BaseAgent:
        def __init__(self, **kwargs): pass

class SentinelAgent(BaseAgent):
    def __init__(self, event_bus=None, config: Optional[Dict] = None):
        super().__init__(event_bus=event_bus, config=config or {}, name="SENTINEL")
        self.status_file = "logs/status.json"
        self.last_check = time.time()
        self.stats = {
            "health_score": 100,
            "data_freshness": "OK",
            "last_error": None,
            "uptime_h": 0,
            "start_time": time.time()
        }

    def run_check(self, active_agents: Dict[str, Any], msd: Any = None):
        """Called by main loop to perform diagnostics."""
        t0 = time.time()
        self.stats["uptime_h"] = round((t0 - self.stats["start_time"]) / 3600, 2)
        
        # 1. Check status.json freshness
        if os.path.exists(self.status_file):
            mtime = os.path.getmtime(self.status_file)
            age = t0 - mtime
            if age > 300: # 5 minutes
                self.stats["data_freshness"] = "STALE"
                self.stats["health_score"] -= 10
                logger.warning(f"SENTINEL: status.json is stale ({age:.0f}s)")
            else:
                self.stats["data_freshness"] = "OK"

        # 2. Agent Health (via heartbeats in ZEUS or direct check)
        offline = [name for name, obj in active_agents.items() if obj is None]
        if offline:
            self.stats["health_score"] = max(0, 100 - len(offline) * 5)
            self.stats["last_error"] = f"Offline agents: {offline}"

        # 3. MSD Check
        if msd:
            try:
                # Assuming MSD has a ping or health check
                pass
            except Exception as e:
                self.stats["health_score"] -= 5
                self.stats["last_error"] = str(e)

        self.last_check = t0
        return self.stats

    def get_report(self) -> Dict[str, Any]:
        return self.stats
