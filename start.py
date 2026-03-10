"""
AlphaZero Capital v2 — Single-Command Launcher
Usage:
    python start.py              ← starts backend + opens dashboard
    python start.py --no-browser ← starts backend only (headless / server)
    python start.py --check      ← only check dependencies, don't start
"""
import os
import sys
import time
import signal
import shutil
import argparse
import subprocess
import webbrowser
import threading
from pathlib import Path

ROOT = Path(__file__).parent

# ── Colours ──────────────────────────────────────────────────────────────────
def green(s):  return f"\033[92m{s}\033[0m"
def yellow(s): return f"\033[93m{s}\033[0m"
def red(s):    return f"\033[91m{s}\033[0m"
def bold(s):   return f"\033[1m{s}\033[0m"
def dim(s):    return f"\033[2m{s}\033[0m"

BANNER = f"""
{bold('╔══════════════════════════════════════════════════════╗')}
{bold('║')}   {green('AlphaZero Capital v2.0')}  ·  NSE India               {bold('║')}
{bold('║')}   Autonomous Trading System  ·  12 Agents           {bold('║')}
{bold('╚══════════════════════════════════════════════════════╝')}
"""

# ── Dependency check ──────────────────────────────────────────────────────────
REQUIRED = {
    "fastapi":    "fastapi>=0.109.0",
    "uvicorn":    "uvicorn[standard]>=0.27.0",
    "yfinance":   "yfinance>=0.2.36",
    "websockets": "websockets>=12.0",
    "pandas":     "pandas>=2.1.0",
    "numpy":      "numpy>=1.26.0",
    "requests":   "requests>=2.31.0",
    "dotenv":     "python-dotenv>=1.0.0",
}

def check_deps() -> list[str]:
    missing = []
    for module, pip_name in REQUIRED.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pip_name)
    return missing

def install_missing(missing: list[str]):
    print(yellow(f"\n⚡ Installing {len(missing)} missing packages..."))
    cmd = [sys.executable, "-m", "pip", "install", "--quiet"] + missing
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(red("❌ pip install failed. Run manually:"))
        print(f"   pip install {' '.join(missing)}")
        sys.exit(1)
    print(green("✅ Packages installed\n"))

# ── .env setup ────────────────────────────────────────────────────────────────
def ensure_env():
    env_file      = ROOT / ".env"
    env_template  = ROOT / ".env.template"
    if not env_file.exists():
        if env_template.exists():
            shutil.copy(env_template, env_file)
            print(yellow("⚠  .env created from template — edit it to add OpenAlgo key if needed"))
        else:
            env_file.write_text(
                "MODE=PAPER\n"
                "OPENALGO_HOST=http://localhost:5000\n"
                "OPENALGO_KEY=\n"
                "REDIS_URL=redis://localhost:6379\n"
            )
            print(yellow("⚠  Default .env created"))
    print(green("✅ .env ready"))

# ── Ensure log / model dirs ───────────────────────────────────────────────────
def ensure_dirs():
    for d in ["logs", "models", "data/cache"]:
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    print(green("✅ Directories ready (logs/, models/, data/cache/)"))

# ── Ensure __init__.py files ──────────────────────────────────────────────────
def ensure_packages():
    for pkg in ["src", "src/agents", "src/data", "src/dashboard", "src/utils"]:
        init = ROOT / pkg / "__init__.py"
        init.parent.mkdir(parents=True, exist_ok=True)
        if not init.exists():
            init.write_text("")
    print(green("✅ Python packages initialised"))

# ── Backend process ───────────────────────────────────────────────────────────
def start_backend() -> subprocess.Popen:
    cmd = [
        sys.executable, "-m", "uvicorn",
        "src.dashboard.backend:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--log-level", "warning",
    ]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)

    # Stream logs with prefix
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    def _stream():
        for line in proc.stdout:
            tag = green("[BACKEND]") if "INFO" in line else (red("[BACKEND]") if "ERROR" in line else dim("[BACKEND]"))
            print(f"  {tag}  {line.rstrip()}")
    t = threading.Thread(target=_stream, daemon=True)
    t.start()
    return proc

def wait_for_backend(timeout=20) -> bool:
    """Poll localhost:8000 until ready or timeout."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen("http://localhost:8000/", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False

# ── Redis check (optional) ────────────────────────────────────────────────────
def check_redis():
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, socket_connect_timeout=1)
        r.ping()
        print(green("✅ Redis connected"))
    except Exception:
        print(yellow("⚠  Redis not running — event bus will use in-process queue"))
        print(dim("   To start Redis: docker run -d -p 6379:6379 redis"))

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="AlphaZero Capital launcher")
    parser.add_argument("--no-browser", action="store_true",  help="Don't open browser")
    parser.add_argument("--check",      action="store_true",  help="Only check deps")
    parser.add_argument("--port",       type=int, default=8000)
    args = parser.parse_args()

    print(BANNER)

    # ── 1. Check & install deps ──────────────────────────────────────────────
    print(bold("Checking dependencies..."))
    missing = check_deps()
    if missing:
        print(yellow(f"  Missing: {', '.join(missing)}"))
        answer = input("  Auto-install? [Y/n] ").strip().lower()
        if answer != "n":
            install_missing(missing)
        else:
            print(red("Cannot start without dependencies.")); sys.exit(1)
    else:
        print(green("✅ All dependencies present"))

    if args.check:
        print(green("\n✅ All checks passed. Ready to start.")); return

    # ── 2. Setup ─────────────────────────────────────────────────────────────
    ensure_env()
    ensure_dirs()
    ensure_packages()
    check_redis()

    # ── 3. Start backend ─────────────────────────────────────────────────────
    print(bold("\nStarting AlphaZero backend..."))
    backend = start_backend()

    print(dim("  Waiting for backend to be ready..."), end="", flush=True)
    ready = wait_for_backend(timeout=25)
    if not ready:
        print(red("\n❌ Backend did not start. Check logs above."))
        backend.terminate(); sys.exit(1)
    print(f"\r  {green('✅ Backend ready')}")

    # ── 4. Print access info ─────────────────────────────────────────────────
    url = f"http://localhost:{args.port}"
    print(f"""
  {bold('AlphaZero is running!')}

  {green('Dashboard')}  →  {url}
  {green('API Docs')}   →  {url}/docs
  {green('WS Feed')}    →  ws://localhost:{args.port}/ws

  {dim('Press Ctrl+C to stop all processes.')}
""")

    # ── 5. Open browser ──────────────────────────────────────────────────────
    if not args.no_browser:
        time.sleep(0.5)
        webbrowser.open(url)

    # ── 6. Keep alive, handle shutdown ───────────────────────────────────────
    def _shutdown(sig, frame):
        print(f"\n{yellow('Shutting down AlphaZero...')}")
        backend.terminate()
        try: backend.wait(timeout=5)
        except subprocess.TimeoutExpired: backend.kill()
        print(green("Goodbye.")); sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # Keep main thread alive
    while True:
        if backend.poll() is not None:
            print(red("\n❌ Backend crashed. Check logs above."))
            sys.exit(1)
        time.sleep(2)


if __name__ == "__main__":
    main()
