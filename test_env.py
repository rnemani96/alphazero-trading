import os
from dotenv import load_dotenv
print(f"CWD: {os.getcwd()}")
print(f"BEFORE: MAX_POSITIONS={os.getenv('MAX_POSITIONS')}")
load_dotenv()
print(f"AFTER default load_dotenv: MAX_POSITIONS={os.getenv('MAX_POSITIONS')}")
env_path = os.path.join(os.getcwd(), ".env")
print(f"Loading from: {env_path}")
load_dotenv(env_path, override=True)
print(f"AFTER explicit override: MAX_POSITIONS={os.getenv('MAX_POSITIONS')}")
