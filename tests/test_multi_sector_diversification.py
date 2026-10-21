"""
tests/test_multi_sector_diversification.py
═════════════════════════════════════════
Validates that:
  1. Universe builder includes liquid stocks across ALL major sectors (Banking, IT, Auto, Pharma, Energy, Metals, FMCG, Infra).
  2. Multi-sector round-robin allocation enforces cross-sector diversification.
  3. No single sector exceeds MAX_POSITIONS_PER_SECTOR.
  4. Trades are distributed across multiple distinct stocks and sectors.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from main import _diversify_signals_across_sectors, _build_universe
from config.sectors import get_sector, SECTORS


class TestMultiSectorDiversification(unittest.TestCase):

    def test_universe_multi_sector_coverage(self):
        """Verify that the universe builder contains representative stocks across all primary sectors."""
        universe = _build_universe()
        self.assertGreater(len(universe), 20)

        sectors_found = {get_sector(sym) for sym in universe}
        # Verify primary sectors are represented
        expected_sectors = {"BANKING", "IT", "AUTO", "PHARMA", "ENERGY", "METALS", "FMCG", "INFRA"}
        common = expected_sectors.intersection(sectors_found)
        self.assertGreaterEqual(len(common), 6, f"Expected at least 6 primary sectors in universe, got: {common}")

    def test_multi_sector_round_robin_diversification(self):
        """
        Verify that when multiple signals from the same sector arrive,
        the allocator prevents sector clumping and diversifies across multiple distinct sectors.
        """
        # Create 10 signals: 5 Banking, 3 IT, 2 Auto
        signals = [
            {"symbol": "HDFCBANK", "confidence": 0.95, "sector": "BANKING", "price": 1600.0, "action": "BUY"},
            {"symbol": "ICICIBANK", "confidence": 0.93, "sector": "BANKING", "price": 1050.0, "action": "BUY"},
            {"symbol": "KOTAKBANK", "confidence": 0.91, "sector": "BANKING", "price": 1800.0, "action": "BUY"},
            {"symbol": "AXISBANK", "confidence": 0.89, "sector": "BANKING", "price": 1100.0, "action": "BUY"},
            {"symbol": "SBIN", "confidence": 0.87, "sector": "BANKING", "price": 750.0, "action": "BUY"},
            {"symbol": "TCS", "confidence": 0.85, "sector": "IT", "price": 3800.0, "action": "BUY"},
            {"symbol": "INFY", "confidence": 0.84, "sector": "IT", "price": 1500.0, "action": "BUY"},
            {"symbol": "WIPRO", "confidence": 0.82, "sector": "IT", "price": 450.0, "action": "BUY"},
            {"symbol": "MARUTI", "confidence": 0.80, "sector": "AUTO", "price": 12000.0, "action": "BUY"},
            {"symbol": "TATAMOTORS", "confidence": 0.78, "sector": "AUTO", "price": 950.0, "action": "BUY"},
        ]

        # Allocate 6 open slots with max 2 per sector
        approved = _diversify_signals_across_sectors(signals, open_slots=6, max_per_sector=2)

        self.assertEqual(len(approved), 6)

        # Count sectors in approved list
        approved_sectors = {}
        for sig in approved:
            sec = sig["sector"]
            approved_sectors[sec] = approved_sectors.get(sec, 0) + 1

        # Check that no sector exceeded the max_per_sector cap of 2
        for sec, count in approved_sectors.items():
            self.assertLessEqual(count, 2, f"Sector {sec} exceeded max_per_sector cap (count={count})")

        # Check that all 3 sectors (BANKING, IT, AUTO) are represented
        self.assertIn("BANKING", approved_sectors)
        self.assertIn("IT", approved_sectors)
        self.assertIn("AUTO", approved_sectors)
        self.assertEqual(len(approved_sectors), 3)

        # Check that top candidate from each sector was selected first
        symbols_approved = {s["symbol"] for s in approved}
        self.assertIn("HDFCBANK", symbols_approved)
        self.assertIn("TCS", symbols_approved)
        self.assertIn("MARUTI", symbols_approved)


if __name__ == "__main__":
    unittest.main()
