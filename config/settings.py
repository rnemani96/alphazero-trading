"""Configuration Settings"""
import os
from dotenv import load_dotenv

load_dotenv()

# Trading mode
MODE = os.getenv('MODE', 'PAPER')

# AI Provider
LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'auto')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# Risk parameters
MAX_DAILY_LOSS_PCT = float(os.getenv('MAX_DAILY_LOSS_PCT', '0.02'))
MAX_POSITION_SIZE_PCT = float(os.getenv('MAX_POSITION_SIZE_PCT', '0.05'))
MAX_POSITIONS = int(os.getenv('MAX_POSITIONS', '10'))

# Capital
INITIAL_CAPITAL = float(os.getenv('INITIAL_CAPITAL', '1000000'))
