"""
scripts/watchdog.py  —  AlphaZero Capital
═══════════════════════════════════════════════════════════════════════════════
24/7 AUTONOMOUS PROCESS SUPERVISOR & SELF-HEALING WATCHDOG

Responsibilities:
  1. Spawns and supervises main.py trading engine.
  2. Detects unhandled exceptions, memory exhaustion, or network disconnect exits.
  3. Automatically restarts the engine within 5 seconds without manual intervention.
  4. Preserves all persistent state (ActivePortfolio, Recovery Engine, Bandit Allocator).
  5. Sends immediate real-time crash and recovery alerts to Telegram.
  6. Rate-limits restarts to prevent runaway crash loops during hard failures.
"""

from __future__ import annotations
import os
import sys
import time
import signal
import logging
import subprocess
from datetime import datetime
from pathlib import Path

# Paths
ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
WATCHDOG_LOG = LOG_DIR / "watchdog.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | Watchdog   | %(levelname)-5s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(WATCHDOG_LOG, encoding="utf-8")
    ]
)
logger = logging.getLogger("Watchdog")

# Settings
MAX_RAPID_CRASHES = 5
RAPID_CRASH_WINDOW = 300  # 5 minutes
RESTART_DELAY = 5         # seconds


def send_telegram_alert(message: str):
    """Send emergency alert via Telegram bot if configured."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        token = os.getenv("TELEGRAM_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if token and chat_id:
            import urllib.request
            import urllib.parse
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "Markdown"
            }).encode("utf-8")
            req = urllib.request.Request(url, data=data, method="POST")
            urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.debug("Failed to send Telegram watchdog alert: %s", e)


class ProcessSupervisor:
    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.crash_timestamps: list[float] = []
        self.running = True

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        logger.info("Shutdown signal received (%s). Terminating supervisor and child...", signum)
        self.running = False
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        sys.exit(0)

    def run(self):
        logger.info("=" * 70)
        logger.info("🛡️ AlphaZero Autonomous 24/7 Supervisor Active")
        logger.info("Supervising: %s/main.py", ROOT)
        logger.info("=" * 70)

        main_script = str(ROOT / "main.py")

        while self.running:
            now = time.time()
            # Clean old crash timestamps
            self.crash_timestamps = [t for t in self.crash_timestamps if now - t < RAPID_CRASH_WINDOW]

            if len(self.crash_timestamps) >= MAX_RAPID_CRASHES:
                alert_msg = (
                    f"🚨 *AlphaZero Supervisor Alert*: Process crashed {MAX_RAPID_CRASHES} times in {RAPID_CRASH_WINDOW//60} mins. "
                    "Pausing for 5 minutes before retrying to prevent system strain."
                )
                logger.error(alert_msg)
                send_telegram_alert(alert_msg)
                time.sleep(300)
                self.crash_timestamps.clear()

            logger.info("🚀 Launching AlphaZero Trading Engine: %s", main_script)
            start_time = time.time()

            try:
                # Launch main.py with inherited python environment and UTF-8 encoding
                child_env = os.environ.copy()
                child_env["PYTHONUTF8"] = "1"
                child_env["PYTHONIOENCODING"] = "utf-8"
                self.process = subprocess.Popen([sys.executable, main_script], cwd=str(ROOT), env=child_env)
                exit_code = self.process.wait()
                runtime = time.time() - start_time

                if not self.running:
                    break

                if exit_code == 0:
                    logger.info("Engine completed normally (exit code 0). Relaunching in %ds...", RESTART_DELAY)
                else:
                    self.crash_timestamps.append(time.time())
                    err_msg = (
                        f"⚠️ *AlphaZero Supervisor Alert*: Trading engine terminated unexpectedly "
                        f"(Exit Code: {exit_code}, Runtime: {runtime:.1f}s). "
                        f"Autonomous Self-Healing: Restarting in {RESTART_DELAY}s..."
                    )
                    logger.warning(err_msg)
                    send_telegram_alert(err_msg)

            except Exception as e:
                logger.error("Supervisor encountered an error while managing process: %s", e)
                send_telegram_alert(f"🚨 *Supervisor Error*: {e}")

            time.sleep(RESTART_DELAY)


if __name__ == "__main__":
    supervisor = ProcessSupervisor()
    supervisor.run()
