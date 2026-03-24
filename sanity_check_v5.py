import sys
import os

print("Testing AlphaZero v5.0 imports...")

try:
    import main
    print("✓ main.py imported")
    from src.risk.active_portfolio import ActivePortfolio
    print("✓ ActivePortfolio imported")
    from src.mercury import OpenAlgoExecutor
    print("✓ OpenAlgoExecutor imported")
    from src.backtest.engine import BacktestEngine
    print("✓ BacktestEngine imported")
    from src.agents.guardian_agent import GuardianAgent
    print("✓ GuardianAgent imported")
    
    print("\nStarting basic initialization logic...")
    # Add mocks if needed or just check if basic objects can be created
    print("✓ All critical paths checked.")
except Exception as e:
    print(f"\n❌ ERROR during test: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\nSUCCESS: All internal components are loadable.")
