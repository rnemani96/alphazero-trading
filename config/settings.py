"""
AlphaZero Capital - Master Configuration
config/settings.py

All system-wide settings loaded from environment variables (.env file).
Moved from root settings.py into config/ as per project structure.

Usage:
    from config.settings import settings
    capital = settings.INITIAL_CAPITAL
"""

import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

# Load .env from project root
_ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(_ENV_PATH)


@dataclass
class Settings:
    # ── Trading Mode ───────────────────────────────────────────────────────
    MODE: str = os.getenv('MODE', 'PAPER')                  # PAPER | LIVE

    # ── AI Providers ───────────────────────────────────────────────────────
    LLM_PROVIDER: str        = os.getenv('LLM_PROVIDER', 'auto')
    ANTHROPIC_API_KEY: str   = os.getenv('ANTHROPIC_API_KEY', '')
    OPENAI_API_KEY: str      = os.getenv('OPENAI_API_KEY', '')
    GOOGLE_API_KEY: str      = os.getenv('GOOGLE_API_KEY', '')
    OPENROUTER_API_KEY: str  = os.getenv('OPENROUTER_API_KEY', '')

    # ── Broker / OpenAlgo ──────────────────────────────────────────────────
    OPENALGO_API_KEY: str    = os.getenv('OPENALGO_API_KEY', '')
    OPENALGO_URL: str        = os.getenv('OPENALGO_URL', 'http://127.0.0.1:5000')

    # ── Telegram Alerts ────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str  = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID: str    = os.getenv('TELEGRAM_CHAT_ID', '')

    # ── Capital ────────────────────────────────────────────────────────────
    INITIAL_CAPITAL: float   = float(os.getenv('INITIAL_CAPITAL', '1000000'))

    # ── Risk Parameters ────────────────────────────────────────────────────
    MAX_DAILY_LOSS_PCT: float     = float(os.getenv('MAX_DAILY_LOSS_PCT',     '0.02'))
    MAX_POSITION_SIZE_PCT: float  = float(os.getenv('MAX_POSITION_SIZE_PCT',  '0.05'))
    MAX_SECTOR_EXPOSURE_PCT: float= float(os.getenv('MAX_SECTOR_EXPOSURE_PCT','0.30'))
    MAX_POSITIONS: int            = int(os.getenv('MAX_POSITIONS',            '10'))
    MAX_TRADES_PER_DAY: int       = int(os.getenv('MAX_TRADES_PER_DAY',       '20'))
    CONSECUTIVE_LOSS_LIMIT: int   = int(os.getenv('CONSECUTIVE_LOSS_LIMIT',   '3'))

    # ── Trailing Stops ─────────────────────────────────────────────────────
    ACTIVATION_PROFIT_PCT: float  = float(os.getenv('ACTIVATION_PROFIT_PCT', '0.02'))
    TRAIL_ATR_MULTIPLIER: float   = float(os.getenv('TRAIL_ATR_MULTIPLIER',  '1.5'))
    TRAIL_PCT: float              = float(os.getenv('TRAIL_PCT',             '0.03'))

    # ── Timing ─────────────────────────────────────────────────────────────
    ITERATION_INTERVAL: int       = int(os.getenv('ITERATION_INTERVAL', '900'))   # seconds

    # ── Stock Universe ─────────────────────────────────────────────────────
    SYMBOLS: List[str] = field(default_factory=lambda: [
        sym.strip()
        for sym in os.getenv(
            'SYMBOLS',
            'RELIANCE,TCS,HDFCBANK,INFY,ICICIBANK,KOTAKBANK,SBIN,BHARTIARTL,ITC,HINDUNILVR'
        ).split(',')
        if sym.strip()
    ])

    # ── Dashboard ──────────────────────────────────────────────────────────
    DASHBOARD_HOST: str  = os.getenv('DASHBOARD_HOST', '0.0.0.0')
    DASHBOARD_PORT: int  = int(os.getenv('DASHBOARD_PORT', '8080'))

    def to_dict(self) -> dict:
        """Return all settings as a plain dict (safe for logging — masks keys)."""
        d = {}
        for k, v in self.__dict__.items():
            if 'KEY' in k or 'TOKEN' in k or 'PASSWORD' in k:
                d[k] = '***' if v else ''
            else:
                d[k] = v
        return d


# Singleton — import this everywhere
settings = Settings()
