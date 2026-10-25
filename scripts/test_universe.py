"""
scripts/test_universe.py  —  AlphaZero Capital
Validates the dynamic NSE universe system end-to-end.
Run from project root:  python scripts/test_universe.py
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ── 1. Universe fetch ─────────────────────────────────────────────────────────
print("=" * 60)
print("1. Testing universe.py — live NSE fetch")
print("=" * 60)
from src.data.universe import (
    get_nifty500_symbols, get_sector_map, get_nse_sector_map,
    is_blacklisted, add_to_blacklist
)

syms = get_nifty500_symbols(use_cache=False)   # force fresh NSE download
print(f"  Symbols fetched from NSE : {len(syms)}")
print(f"  First 8                  : {syms[:8]}")

# Check blacklisted symbols are absent
BAD_SYMBOLS = ["AKZOINDIA", "GSPL", "JBCHEPHARM", "HEG", "GUJGASLTD",
               "HDFC", "TATAMOTORS", "RELINFRA", "ADANITRANS"]
print(f"\n  Checking known stale/delisted symbols are absent:")
for bad in BAD_SYMBOLS:
    present = bad in syms
    print(f"    {bad:20s}  in universe: {present}  | blacklisted: {is_blacklisted(bad)}")

# ── 2. Sector mapping ──────────────────────────────────────────────────────────
print()
print("=" * 60)
print("2. Testing sector mapping")
print("=" * 60)
sm = get_sector_map()
sector_counts = {}
for s, sec in sm.items():
    sector_counts[sec] = sector_counts.get(sec, 0) + 1

print(f"  Total mapped symbols     : {len(sm)}")
for sec, cnt in sorted(sector_counts.items(), key=lambda x: -x[1]):
    sample = [s for s, v in sm.items() if v == sec][:4]
    print(f"    {sec:12s} : {cnt:3d} symbols   e.g. {sample}")

# ── 3. config/sectors.py ──────────────────────────────────────────────────────
print()
print("=" * 60)
print("3. Testing config/sectors.py")
print("=" * 60)
from config.sectors import SECTORS, SYMBOL_TO_SECTOR, get_sector, get_symbols_in_sector
print(f"  Sector buckets           : {list(SECTORS.keys())}")
for sec in ["BANKING", "IT", "PHARMA", "AUTO", "ENERGY", "METALS", "FMCG", "FINANCE", "INFRA"]:
    syms_in = get_symbols_in_sector(sec)
    print(f"    {sec:10s}: {len(syms_in):3d} symbols  e.g. {syms_in[:4]}")

print(f"\n  get_sector('TCS')        : {get_sector('TCS')}")
print(f"  get_sector('HDFCBANK')   : {get_sector('HDFCBANK')}")
print(f"  get_sector('SUNPHARMA')  : {get_sector('SUNPHARMA')}")
print(f"  get_sector('RELIANCE')   : {get_sector('RELIANCE')}")
print(f"  get_sector('TATASTEEL')  : {get_sector('TATASTEEL')}")

# ── 4. Blacklist persistence ───────────────────────────────────────────────────
print()
print("=" * 60)
print("4. Testing auto-blacklist")
print("=" * 60)
add_to_blacklist("TESTDELISTED")
print(f"  TESTDELISTED blacklisted : {is_blacklisted('TESTDELISTED')}")
syms2 = get_nifty500_symbols(use_cache=True)
print(f"  TESTDELISTED in universe : {'TESTDELISTED' in syms2}")
print(f"  RELIANCE still present   : {'RELIANCE' in syms2}")

print()
print("ALL CHECKS COMPLETE")
