"""
src/infra/ops.py  —  AlphaZero Capital
═══════════════════════════════════════
Infrastructure utilities (all were TODO):
  - Auto-restart via systemd service file generator
  - Log rotation (7-day rolling, compresses old logs)
  - Daily DB backup (evaluation.db + status.json → backups/)
  - Health check endpoint data provider

Run once to set up:
    python -m src.infra.ops --setup-systemd
    python -m src.infra.ops --backup
    python -m src.infra.ops --rotate-logs
"""

from __future__ import annotations

import os, gzip, shutil, json, logging, sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger("Ops")

_ROOT    = Path(__file__).resolve().parents[2]
_LOG_DIR = _ROOT / "logs"
_BAK_DIR = _ROOT / "backups"
_LOG_DIR.mkdir(exist_ok=True)
_BAK_DIR.mkdir(exist_ok=True)


# ── Log Rotation ──────────────────────────────────────────────────────────────

def rotate_logs(keep_days: int = 7):
    """
    Rotate logs/ directory:
    - Compress .log files older than `keep_days` into .log.gz
    - Delete compressed files older than 30 days
    """
    cutoff_compress = datetime.now().timestamp() - keep_days * 86400
    cutoff_delete   = datetime.now().timestamp() - 30 * 86400

    compressed = deleted = 0

    for log_file in _LOG_DIR.glob("*.log"):
        mtime = log_file.stat().st_mtime
        if mtime < cutoff_compress:
            gz_path = log_file.with_suffix(".log.gz")
            try:
                with open(log_file, 'rb') as f_in, gzip.open(gz_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
                log_file.unlink()
                compressed += 1
                logger.info(f"Compressed: {log_file.name} → {gz_path.name}")
            except Exception as e:
                logger.warning(f"Compress failed {log_file}: {e}")

    for gz_file in _LOG_DIR.glob("*.log.gz"):
        if gz_file.stat().st_mtime < cutoff_delete:
            try:
                gz_file.unlink()
                deleted += 1
            except Exception:
                pass

    logger.info(f"Log rotation: {compressed} compressed, {deleted} old archives deleted")
    return {"compressed": compressed, "deleted": deleted}


# ── Daily Backup ──────────────────────────────────────────────────────────────

def daily_backup():
    """
    Backup critical data files to backups/YYYY-MM-DD/:
      - logs/evaluation.db (LENS trade evaluation SQLite)
      - logs/status.json   (agent status)
      - logs/tracker.json  (system tracker)
      - data/cache/        (historical price cache)
    """
    today_dir = _BAK_DIR / date.today().isoformat()
    today_dir.mkdir(exist_ok=True)

    files_to_backup = [
        _LOG_DIR / "evaluation.db",
        _LOG_DIR / "status.json",
        _LOG_DIR / "tracker.json",
        _LOG_DIR / "backtest_results.json",
        _LOG_DIR / "walk_forward_results.json",
        _LOG_DIR / "nav_history.json",
        _LOG_DIR / "orders.json",
    ]

    backed_up = []
    for src in files_to_backup:
        if src.exists():
            dst = today_dir / src.name
            try:
                shutil.copy2(src, dst)
                backed_up.append(src.name)
            except Exception as e:
                logger.warning(f"Backup failed {src.name}: {e}")

    # Also backup the fundamentals DB
    fund_db = _ROOT / "data" / "cache" / "fundamentals.db"
    if fund_db.exists():
        try:
            shutil.copy2(fund_db, today_dir / "fundamentals.db")
            backed_up.append("fundamentals.db")
        except Exception:
            pass

    # Delete backups older than 30 days
    pruned = 0
    for old_dir in _BAK_DIR.iterdir():
        if old_dir.is_dir():
            try:
                bak_date = date.fromisoformat(old_dir.name)
                if (date.today() - bak_date).days > 30:
                    shutil.rmtree(old_dir)
                    pruned += 1
            except ValueError:
                pass

    logger.info(f"Backup complete: {len(backed_up)} files → {today_dir} | {pruned} old backups pruned")
    return {"backed_up": backed_up, "directory": str(today_dir), "pruned": pruned}


# ── Systemd Service File Generator ───────────────────────────────────────────

def generate_systemd_service(python_path: str = None,
                               working_dir: str = None) -> str:
    """
    Generate a systemd service file for auto-restart on Linux.
    Saves to alphazero.service in the project root.

    Usage:
        python -m src.infra.ops --setup-systemd
        sudo cp alphazero.service /etc/systemd/system/
        sudo systemctl daemon-reload
        sudo systemctl enable alphazero
        sudo systemctl start alphazero
    """
    python  = python_path or shutil.which("python3") or shutil.which("python") or "/usr/bin/python3"
    workdir = working_dir or str(_ROOT)
    user    = os.getenv('USER', 'ubuntu')

    service_content = f"""[Unit]
Description=AlphaZero Capital Trading System
After=network.target
Wants=network-online.target

[Service]
Type=simple
User={user}
WorkingDirectory={workdir}
ExecStart={python} main.py
Restart=on-failure
RestartSec=30
StartLimitIntervalSec=300
StartLimitBurst=5

# Environment
EnvironmentFile={workdir}/.env
StandardOutput=append:{workdir}/logs/systemd.log
StandardError=append:{workdir}/logs/systemd_error.log

# Ensure IST timezone (critical for NSE market hours)
Environment=TZ=Asia/Kolkata

[Install]
WantedBy=multi-user.target
"""

    service_path = _ROOT / "alphazero.service"
    service_path.write_text(service_content)
    logger.info(f"Systemd service file written → {service_path}")

    instructions = f"""
✅ Systemd service file created: {service_path}

To enable auto-restart on Linux:
  sudo cp {service_path} /etc/systemd/system/alphazero.service
  sudo systemctl daemon-reload
  sudo systemctl enable alphazero    # auto-start on boot
  sudo systemctl start alphazero     # start now
  sudo systemctl status alphazero    # check status
  journalctl -u alphazero -f         # live logs
"""
    print(instructions)
    return str(service_path)


def generate_pm2_config() -> str:
    """
    Generate PM2 ecosystem config for Node.js-based auto-restart.
    Works on Windows + Linux + Mac.

    Usage after installing PM2:
        npm install -g pm2
        pm2 start ecosystem.config.js
        pm2 save
        pm2 startup   # auto-start on boot
    """
    python  = shutil.which("python") or "python"
    workdir = str(_ROOT)

    config = f"""// ecosystem.config.js  — PM2 config for AlphaZero Capital
module.exports = {{
  apps: [{{
    name:           'alphazero-capital',
    script:         '{python}',
    args:           'main.py',
    cwd:            '{workdir}',
    watch:          false,
    autorestart:    true,
    restart_delay:  30000,   // 30s before restart
    max_restarts:   10,
    min_uptime:     '30s',
    env: {{
      TZ:   'Asia/Kolkata',
      MODE: 'PAPER',
    }},
    error_file:  '{workdir}/logs/pm2_error.log',
    out_file:    '{workdir}/logs/pm2_out.log',
    merge_logs:  true,
  }}]
}};
"""

    config_path = _ROOT / "ecosystem.config.js"
    config_path.write_text(config)
    logger.info(f"PM2 config written → {config_path}")

    print(f"""
✅ PM2 config created: {config_path}

To enable auto-restart (Windows / Linux / Mac):
  npm install -g pm2
  pm2 start ecosystem.config.js
  pm2 save
  pm2 startup
""")
    return str(config_path)


# ── Health Check Data ─────────────────────────────────────────────────────────

def get_health_status(agents: Dict = None, data_fetcher=None) -> Dict:
    """
    Collect system health data for GET /health endpoint.
    Returns JSON-serializable dict.
    """
    import psutil

    status = {
        "timestamp":  datetime.now().isoformat(),
        "healthy":    True,
        "cpu_pct":    psutil.cpu_percent(interval=0.1),
        "ram_pct":    psutil.virtual_memory().percent,
        "disk_pct":   psutil.disk_usage('/').percent,
        "agents":     {},
        "data":       {},
        "files":      {},
    }

    # Agent health
    if agents:
        for name, agent in agents.items():
            try:
                alive = hasattr(agent, 'is_alive') and agent.is_alive()
                status["agents"][name] = "OK" if alive else "DOWN"
            except Exception:
                status["agents"][name] = "UNKNOWN"

    # Data cache stats
    if data_fetcher:
        try:
            cache = data_fetcher.cache_info()
            status["data"]["cached_symbols"] = len(cache)
            status["data"]["cache_rows"]     = sum(cache.values())
        except Exception:
            pass

    # Critical file sizes
    for fname in ["evaluation.db", "status.json", "tracker.json"]:
        fpath = _LOG_DIR / fname
        if fpath.exists():
            status["files"][fname] = fpath.stat().st_size
        else:
            status["files"][fname] = 0

    # Mark unhealthy if RAM > 90% or disk > 85%
    if status["ram_pct"] > 90 or status["disk_pct"] > 85:
        status["healthy"] = False

    return status


# ── CLI entrypoint ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    args = sys.argv[1:]

    if "--setup-systemd" in args:
        generate_systemd_service()
        generate_pm2_config()

    elif "--backup" in args:
        result = daily_backup()
        print(json.dumps(result, indent=2))

    elif "--rotate-logs" in args:
        result = rotate_logs()
        print(json.dumps(result, indent=2))

    else:
        print("Usage: python -m src.infra.ops [--setup-systemd | --backup | --rotate-logs]")
