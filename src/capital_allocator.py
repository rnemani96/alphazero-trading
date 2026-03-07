"""Capital Allocator"""
import logging
logger = logging.getLogger(__name__)

class CapitalAllocator:
    """Allocates capital across positions"""
    def __init__(self, total_capital):
        self.total_capital = total_capital
    
    def allocate(self, signals):
        """Allocate capital to signals"""
        allocation = {}
        per_signal = self.total_capital / len(signals) if signals else 0
        for signal in signals:
            allocation[signal['symbol']] = min(per_signal, self.total_capital * 0.05)
        return allocation
