from config.settings import settings
import os
from dotenv import load_dotenv

print(f"os.getenv('MAX_POSITIONS'): {os.getenv('MAX_POSITIONS')}")
print(f"settings.MAX_POSITIONS: {settings.MAX_POSITIONS}")

# Try loading explicitly
_ENV_PATH = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(_ENV_PATH, override=True)
print(f"After override, os.getenv('MAX_POSITIONS'): {os.getenv('MAX_POSITIONS')}")
