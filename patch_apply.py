#!/usr/bin/env python3
"""
patch_apply.py — AlphaZero Capital Fix Patcher
═══════════════════════════════════════════════
Applies all Phase 1–10 fixes to your existing repository.

Usage:
    python patch_apply.py                    # dry-run: shows what will change
    python patch_apply.py --apply            # applies all fixes
    python patch_apply.py --apply --backup   # backs up originals first

This script:
  1. Creates missing __init__.py files
  2. Fixes DASHBOARD_PORT in config/settings.py
  3. Replaces titan_agent.py (removes broken numpy import)
  4. Replaces/updates market_data.py (adds next_market_open, AV priority)
  5. Replaces dashboard/backend.py (fixes imports)
  6. Adds src/tracker.py (Phase 8)
  7. Adds src/agents/llm_provider.py (compatibility shim)
  8. Adds src/backtest/engine.py (Phase 7)
  9. Updates main.py
 10. Creates .env.template
 11. Creates setup.bat (Windows)
 12. Updates requirements.txt
"""

import os
import sys
import shutil
import argparse
from pathlib import Path

ROOT = Path(__file__).parent
FIXES_DIR = Path(__file__).parent   # fixes are alongside this script

CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def msg(colour, icon, text):
    print(f"{colour}{icon} {text}{RESET}")


# ── Files to copy from fixes dir ──────────────────────────────────────────────
PATCH_MAP = {
    # Source (in this fixes package) → Destination (in repo)
    "requirements.txt":               "requirements.txt",
    ".env.template":                  ".env.template",
    "setup.bat":                      "setup.bat",
    "main.py":                        "main.py",
    "config/settings.py":             "config/settings.py",
    "src/__init__.py":                "src/__init__.py",
    "src/tracker.py":                 "src/tracker.py",
    "src/agents/__init__.py":         "src/agents/__init__.py",
    "src/agents/titan_agent.py":      "src/agents/titan_agent.py",
    "src/agents/llm_provider.py":     "src/agents/llm_provider.py",
    "src/data/__init__.py":           "src/data/__init__.py",
    "src/data/market_data.py":        "src/data/market_data.py",
    "src/risk/__init__.py":           "src/risk/__init__.py",
    "src/execution/__init__.py":      "src/execution/__init__.py",
    "src/monitoring/__init__.py":     "src/monitoring/__init__.py",
    "src/reporting/__init__.py":      "src/reporting/__init__.py",
    "src/event_bus/__init__.py":      "src/event_bus/__init__.py",
    "src/backtest/__init__.py":       "src/backtest/__init__.py",
    "src/backtest/engine.py":         "src/backtest/engine.py",
    "config/__init__.py":             "config/__init__.py",
    "dashboard/__init__.py":          "dashboard/__init__.py",
    "dashboard/backend.py":           "dashboard/backend.py",
}

# ── Inline patches (simple string replacements) ───────────────────────────────
# Applied ONLY when the fix file itself is not present but the original is.
INLINE_PATCHES = [
    # (file_path, old_string, new_string, description)
    (
        "src/agents/titan_agent.py",
        "from numpy import iterable",
        "# FIXED: numpy.iterable removed in 1.25+",
        "Remove broken numpy import",
    ),
    (
        "src/agents/titan_agent.py",
        "from src import data\n",
        "# FIXED: removed dead circular import\n",
        "Remove dead circular import",
    ),
    (
        "config/settings.py",
        "DASHBOARD_PORT: int  = int(os.getenv('DASHBOARD_PORT', '8080'))",
        "DASHBOARD_PORT: int  = int(os.getenv('DASHBOARD_PORT', '8000'))  # FIX: was 8080",
        "Fix DASHBOARD_PORT default 8080→8000",
    ),
]


def apply_fixes(dry_run: bool = True, backup: bool = False) -> int:
    print(f"\n{BOLD}{'DRY RUN' if dry_run else 'APPLYING FIXES'} — AlphaZero Capital Patcher{RESET}")
    print("=" * 60)

    changes = 0

    # ── 1. Copy fix files ────────────────────────────────────────────────────
    print(f"\n{BOLD}📁 File Patches:{RESET}")
    for src_rel, dst_rel in PATCH_MAP.items():
        src = FIXES_DIR / src_rel
        dst = ROOT / dst_rel

        if not src.exists():
            msg(YELLOW, "⚠", f"Fix source not found: {src_rel} — skip")
            continue

        dst.parent.mkdir(parents=True, exist_ok=True)
        action = "UPDATE" if dst.exists() else "CREATE"

        if not dry_run:
            if backup and dst.exists():
                bak = dst.with_suffix(dst.suffix + '.bak')
                shutil.copy2(dst, bak)
            shutil.copy2(src, dst)
            msg(GREEN, "✅", f"{action}: {dst_rel}")
        else:
            msg(CYAN, "🔍", f"Would {action}: {dst_rel}")
        changes += 1

    # ── 2. Inline patches (fallback) ─────────────────────────────────────────
    print(f"\n{BOLD}🔧 Inline Patches (fallback if file already replaced):{RESET}")
    for file_rel, old_str, new_str, desc in INLINE_PATCHES:
        target = ROOT / file_rel
        if not target.exists():
            continue
        content = target.read_text(encoding='utf-8')
        if old_str not in content:
            msg(GREEN, "✓", f"Already fixed: {desc}")
            continue
        if not dry_run:
            if backup:
                target.with_suffix(target.suffix + '.bak').write_text(content, encoding='utf-8')
            target.write_text(content.replace(old_str, new_str), encoding='utf-8')
            msg(GREEN, "✅", f"Patched: {desc}")
        else:
            msg(CYAN, "🔍", f"Would patch: {desc}")
        changes += 1

    # ── 3. Ensure .env exists ─────────────────────────────────────────────────
    env_file = ROOT / '.env'
    env_tmpl  = ROOT / '.env.template'
    if not env_file.exists() and env_tmpl.exists():
        if not dry_run:
            shutil.copy2(env_tmpl, env_file)
            msg(GREEN, "✅", "Created .env from template")
        else:
            msg(CYAN, "🔍", "Would create .env from .env.template")
        changes += 1

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    if dry_run:
        msg(YELLOW, "ℹ", f"Dry run complete — {changes} changes would be applied")
        msg(YELLOW, "→", "Run with --apply to actually apply fixes")
    else:
        msg(GREEN, "🎉", f"All done! {changes} changes applied")
        print("\nNext steps:")
        print("  1. Edit .env with your API keys")
        print("  2. Run:  python main.py")
        print("  3. Dashboard opens at http://localhost:8000")

    return 0


def main():
    parser = argparse.ArgumentParser(description='AlphaZero Capital Fix Patcher')
    parser.add_argument('--apply',  action='store_true', help='Apply fixes (default: dry run)')
    parser.add_argument('--backup', action='store_true', help='Backup originals as .bak files')
    args = parser.parse_args()

    sys.exit(apply_fixes(dry_run=not args.apply, backup=args.backup))


if __name__ == '__main__':
    main()
