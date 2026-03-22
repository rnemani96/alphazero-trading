"""
AlphaZero Capital - Master Configuration  (v3.0)
config/settings.py

All system-wide settings loaded from environment variables (.env file).

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

    # ── Upstox Native API ──────────────────────────────────────────────────
    # Get from https://developer.upstox.com → Create App
    UPSTOX_API_KEY: str      = os.getenv('UPSTOX_API_KEY', '')
    UPSTOX_API_SECRET: str   = os.getenv('UPSTOX_API_SECRET', '')
    UPSTOX_REDIRECT_URI: str = os.getenv('UPSTOX_REDIRECT_URI', 'http://127.0.0.1:5000/callback')
    # Access token refreshed daily via OAuth2 — store in env or auto-refresh via OpenAlgo
    UPSTOX_ACCESS_TOKEN: str = os.getenv('UPSTOX_ACCESS_TOKEN', '')

    # ── Market Data Sources ────────────────────────────────────────────────
    # Alpha Vantage  — https://www.alphavantage.co/support/#api-key  (free: 5 req/min)
    ALPHA_VANTAGE_KEY: str   = os.getenv('ALPHA_VANTAGE_KEY', '')

    # Twelve Data    — https://twelvedata.com/pricing                (free: 55 req/min)
    TWELVE_DATA_KEY: str     = os.getenv('TWELVE_DATA_KEY', '')

    # Finnhub        — https://finnhub.io/register                   (free: 60 req/min)
    FINNHUB_KEY: str         = os.getenv('FINNHUB_KEY', '')

    # NSE Direct     — public API, no key needed; enable/disable scraping
    NSE_DIRECT_ENABLED: bool = os.getenv('NSE_DIRECT_ENABLED', 'true').lower() == 'true'

    # Stooq          — free, no key needed
    STOOQ_ENABLED: bool      = os.getenv('STOOQ_ENABLED', 'true').lower() == 'true'

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

    # ── Portfolio Management ────────────────────────────────────────────────
    # Once a swing/positional position is open, hold it until target OR stop hit.
    # New stocks are NOT added until a slot frees up (configurable).
    HOLD_UNTIL_TARGET: bool       = os.getenv('HOLD_UNTIL_TARGET', 'true').lower() == 'true'
    DEFAULT_TARGET_PCT: float     = float(os.getenv('DEFAULT_TARGET_PCT',  '6.0'))  # 6% default target
    DEFAULT_SL_PCT: float         = float(os.getenv('DEFAULT_SL_PCT',      '2.5'))  # 2.5% default SL
    MAX_SWING_DAYS: int           = int(os.getenv('MAX_SWING_DAYS',        '30'))   # force close after N days
    MAX_POSITIONAL_DAYS: int      = int(os.getenv('MAX_POSITIONAL_DAYS',   '90'))

    # ── Trailing Stops ─────────────────────────────────────────────────────
    ACTIVATION_PROFIT_PCT: float  = float(os.getenv('ACTIVATION_PROFIT_PCT', '0.02'))
    TRAIL_ATR_MULTIPLIER: float   = float(os.getenv('TRAIL_ATR_MULTIPLIER',  '1.5'))
    TRAIL_PCT: float              = float(os.getenv('TRAIL_PCT',             '0.03'))

    # ── Timing ─────────────────────────────────────────────────────────────
    ITERATION_SLEEP_SEC: int      = int(os.getenv('ITERATION_SLEEP_SEC',   '900'))  # 15 min default
    MARKET_OPEN_HOUR: int         = int(os.getenv('MARKET_OPEN_HOUR',       '9'))
    MARKET_OPEN_MIN: int          = int(os.getenv('MARKET_OPEN_MIN',        '15'))
    MARKET_CLOSE_HOUR: int        = int(os.getenv('MARKET_CLOSE_HOUR',      '15'))
    MARKET_CLOSE_MIN: int         = int(os.getenv('MARKET_CLOSE_MIN',       '30'))

    # ── Data Cache ─────────────────────────────────────────────────────────
    DATA_CACHE_TTL: int           = int(os.getenv('DATA_CACHE_TTL',        '15'))   # seconds for quotes
    CANDLE_CACHE_TTL: int         = int(os.getenv('CANDLE_CACHE_TTL',      '300'))  # seconds for candles
    MIN_HOLDING_TIME_M: int       = int(os.getenv('MIN_HOLDING_TIME_M',    '10'))   # minutes before evaluation
    TITAN_MIN_AGREEMENT: int      = int(os.getenv('TITAN_MIN_AGREEMENT',   '1'))    # strategy agreement for TITAN

    # ── Training ───────────────────────────────────────────────────────────
    TRAINING_ENABLED: bool        = os.getenv('TRAINING_ENABLED', 'true').lower() == 'true'
    TRAINING_HOUR: int            = int(os.getenv('TRAINING_HOUR',         '21'))   # 9 PM IST
    KARMA_MODEL_PATH: str         = os.getenv('KARMA_MODEL_PATH', 'models/karma_ppo.zip')

    # ── Dashboard / Backend ────────────────────────────────────────────────
    BACKEND_HOST: str             = os.getenv('BACKEND_HOST', '0.0.0.0')
    BACKEND_PORT: int             = int(os.getenv('BACKEND_PORT', '8001'))
    DASHBOARD_PORT: int           = int(os.getenv('DASHBOARD_PORT', '3000'))

    def data_source_summary(self) -> dict:
        """Return which data sources are active."""
        return {
            "upstox":        bool(self.UPSTOX_ACCESS_TOKEN or (self.UPSTOX_API_KEY and self.UPSTOX_API_SECRET)),
            "openalgo":      bool(self.OPENALGO_API_KEY),
            "alpha_vantage": bool(self.ALPHA_VANTAGE_KEY),
            "twelve_data":   bool(self.TWELVE_DATA_KEY),
            "finnhub":       bool(self.FINNHUB_KEY),
            "nse_direct":    self.NSE_DIRECT_ENABLED,
            "stooq":         self.STOOQ_ENABLED,
            "yfinance":      True,   # always available (no key required)
        }

    def __post_init__(self):
        active = [k for k, v in self.data_source_summary().items() if v]
        import logging
        logging.getLogger("Settings").info(
            "AlphaZero v4.0 | MODE=%s | Capital=₹%s | Data sources: %s",
            self.MODE, f"{self.INITIAL_CAPITAL:,.0f}", ", ".join(active)
        )


settings = Settings()
