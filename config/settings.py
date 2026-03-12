"""
AlphaZero Capital - Master Configuration
config/settings.py

BUG FIX: DASHBOARD_PORT changed from 8080 → 8000 to match React vite.config.js
         which proxies /api calls to http://localhost:8000
"""

import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

# Load .env from project root (one level up from config/)
_ENV_PATH = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(_ENV_PATH, override=False)   # don't override already-set env vars


@dataclass
class Settings:
    # ── Trading Mode ───────────────────────────────────────────────────────
    MODE: str = os.getenv('MODE', 'PAPER')          # PAPER | LIVE

    # ── AI Providers ───────────────────────────────────────────────────────
    LLM_PROVIDER: str        = os.getenv('LLM_PROVIDER', 'auto')
    ANTHROPIC_API_KEY: str   = os.getenv('ANTHROPIC_API_KEY', '')
    OPENAI_API_KEY: str      = os.getenv('OPENAI_API_KEY', '')
    GOOGLE_API_KEY: str      = os.getenv('GOOGLE_API_KEY', '')
    OPENROUTER_API_KEY: str  = os.getenv('OPENROUTER_API_KEY', '')

    # ── Broker / OpenAlgo ──────────────────────────────────────────────────
    OPENALGO_API_KEY: str    = os.getenv('OPENALGO_API_KEY', '')
    OPENALGO_URL: str        = os.getenv('OPENALGO_URL', 'http://127.0.0.1:5000')

    # ── Market Data ────────────────────────────────────────────────────────
    # Alpha Vantage — secondary data source (after OpenAlgo, before yfinance)
    # Free tier: 25 requests/day  |  Premium: higher limits
    ALPHA_VANTAGE_KEY: str   = os.getenv(
        'ALPHA_VANTAGE_KEY',
        os.getenv('ALPHAVANTAGE_API_KEY',    # support both common spellings
        os.getenv('ALPHA_VANTAGE_API_KEY', ''))
    )

    # ── Telegram Alerts ────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str  = os.getenv('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID: str    = os.getenv('TELEGRAM_CHAT_ID', '')

    # ── Email Reporting ────────────────────────────────────────────────────
    EMAIL_SENDER: str        = os.getenv('EMAIL_SENDER', '')
    EMAIL_PASSWORD: str      = os.getenv('EMAIL_PASSWORD', '')
    EMAIL_RECIPIENT: str     = os.getenv('EMAIL_RECIPIENT', '')
    EMAIL_SMTP_HOST: str     = os.getenv('EMAIL_SMTP_HOST', 'smtp.gmail.com')
    EMAIL_SMTP_PORT: int     = int(os.getenv('EMAIL_SMTP_PORT', '587'))

    # ── Capital ────────────────────────────────────────────────────────────
    INITIAL_CAPITAL: float   = float(os.getenv('INITIAL_CAPITAL', '1000000'))

    # ── Risk Parameters ────────────────────────────────────────────────────
    MAX_DAILY_LOSS_PCT: float      = float(os.getenv('MAX_DAILY_LOSS_PCT',      '0.02'))
    MAX_POSITION_SIZE_PCT: float   = float(os.getenv('MAX_POSITION_SIZE_PCT',   '0.05'))
    MAX_SECTOR_EXPOSURE_PCT: float = float(os.getenv('MAX_SECTOR_EXPOSURE_PCT', '0.30'))
    MAX_POSITIONS: int             = int(os.getenv('MAX_POSITIONS',             '10'))
    MAX_TRADES_PER_DAY: int        = int(os.getenv('MAX_TRADES_PER_DAY',        '20'))
    CONSECUTIVE_LOSS_LIMIT: int    = int(os.getenv('CONSECUTIVE_LOSS_LIMIT',    '3'))

    # ── Trailing Stops ─────────────────────────────────────────────────────
    ACTIVATION_PROFIT_PCT: float   = float(os.getenv('ACTIVATION_PROFIT_PCT', '0.02'))
    TRAIL_ATR_MULTIPLIER: float    = float(os.getenv('TRAIL_ATR_MULTIPLIER',  '1.5'))
    TRAIL_PCT: float               = float(os.getenv('TRAIL_PCT',             '0.03'))

    # ── Timing ─────────────────────────────────────────────────────────────
    ITERATION_INTERVAL: int        = int(os.getenv('ITERATION_INTERVAL', '900'))   # 15 min

    # ── Stock Universe ─────────────────────────────────────────────────────
    SYMBOLS: List[str] = field(default_factory=lambda: [
        sym.strip()
        for sym in os.getenv(
            'SYMBOLS',
            'RELIANCE,TCS,HDFCBANK,INFY,ICICIBANK,KOTAKBANK,HINDUNILVR,SBIN,BHARTIARTL,ITC,'
            'WIPRO,HCLTECH,AXISBANK,LT,MARUTI,BAJFINANCE,BAJAJFINSV,TATAMOTORS,TATASTEEL,'
            'SUNPHARMA,NTPC,POWERGRID,TECHM,ULTRACEMCO,ASIANPAINT,HINDALCO,JSWSTEEL,ONGC,'
            'COALINDIA,GRASIM,DRREDDY,CIPLA,DIVISLAB,ADANIPORTS,SIEMENS,NESTLEIND,BRITANNIA,'
            'M&M,BAJAJ-AUTO,HEROMOTOCO,BIOCON,DABUR,MUTHOOTFIN,CHOLAFIN,INDUSTOWER,LTIM,'
            'VEDL,TITAN,INDUSINDBK,APOLLOHOSP'
        ).split(',')
        if sym.strip()
    ])

    # ── Dashboard ─────────────────────────────────────────────────────────
    # FIX: Changed default from 8080 → 8000 to match React vite.config.js proxy
    DASHBOARD_HOST: str  = os.getenv('DASHBOARD_HOST', '0.0.0.0')
    DASHBOARD_PORT: int  = int(os.getenv('DASHBOARD_PORT', '8000'))

    def to_dict(self) -> dict:
        """Return all settings as a plain dict (safe for logging — masks keys)."""
        d = {}
        for k, v in self.__dict__.items():
            if any(secret in k for secret in ('KEY', 'TOKEN', 'PASSWORD', 'SECRET')):
                d[k] = '***' if v else ''
            else:
                d[k] = v
        return d


# Singleton — import this everywhere
settings = Settings()
