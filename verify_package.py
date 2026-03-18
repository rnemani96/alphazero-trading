#!/usr/bin/env python3
"""Verify package completeness"""
import os, sys

files = {
    'main.py': 'Main orchestrator',
    'requirements.txt': 'Dependencies',
    '.env.template': 'Config template',
    'install.sh': 'Installer',
    'start.sh': 'Startup',
    'README.md': 'Documentation',
    'src/agents/options_flow_agent.py': 'Options Flow (v16)',
    'src/agents/multi_timeframe_agent.py': 'Multi-Timeframe (v16)',
    'src/agents/llm_earnings_analyzer.py': 'Earnings Analyzer (v17)',
    'src/agents/llm_strategy_generator.py': 'Strategy Generator (v17)',
    'src/risk/trailing_stop_manager.py': 'Trailing Stops',
    'src/llm/llm_provider.py': 'Multi-AI Provider',
}

print("\n🔍 AlphaZero Capital - Package Verification\n" + "="*70)
all_good = True
for path, desc in files.items():
    if os.path.exists(path):
        size = os.path.getsize(path)
        print(f"✅ {desc:40} ({size:,} bytes)")
    else:
        print(f"❌ {desc:40} MISSING")
        all_good = False

py_files = sum(1 for r, d, fs in os.walk('src') for f in fs if f.endswith('.py'))
print(f"\n📊 Python files: {py_files}")
print("="*70)
if all_good:
    print("✅ Package verification PASSED!\n")
else:
    print("❌ Package verification FAILED\n")

sys.exit(0 if all_good else 1)
