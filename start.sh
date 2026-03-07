#!/usr/bin/env bash
# ============================================================
#  AlphaZero Capital v17 — One-Command Startup Script
#
#  What this does (in order):
#   1. Checks Python version (3.10+ required)
#   2. Creates a virtual environment called  .venv
#   3. Activates it
#   4. Upgrades pip and installs all requirements
#   5. Creates .env from template if not already present
#   6. Starts the trading engine  (main.py)
#   7. Starts the live dashboard  (dashboard/server.py)
#      → opens at http://localhost:8080
#
#  Usage:
#    chmod +x start.sh
#    ./start.sh                # paper trading (safe default)
#    ./start.sh --live         # LIVE trading  (real money!)
#
#  Stop everything:
#    Press Ctrl+C   (both processes shut down cleanly)
# ============================================================

set -e   # exit on first error

# ── Colours ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

log()  { echo -e "${CYAN}[AZ]${NC} $*"; }
ok()   { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
die()  { echo -e "${RED}[✗]${NC} $*"; exit 1; }

# ── Banner ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${CYAN}  ╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${CYAN}  ║    🚀  AlphaZero Capital  v17            ║${NC}"
echo -e "${BOLD}${CYAN}  ║    Autonomous NSE Trading System          ║${NC}"
echo -e "${BOLD}${CYAN}  ╚══════════════════════════════════════════╝${NC}"
echo ""

# ── Mode flag ────────────────────────────────────────────────────────────────
LIVE_FLAG=""
if [[ "$1" == "--live" ]]; then
    warn "LIVE mode requested — real money will be traded!"
    read -rp "  Type YES to confirm: " CONFIRM
    [[ "$CONFIRM" == "YES" ]] || die "Aborted."
    LIVE_FLAG="--live"
fi

# ── 1. Python check ───────────────────────────────────────────────────────────
log "Checking Python..."
PYTHON=""
for cmd in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        MAJOR="${VER%%.*}"; MINOR="${VER##*.}"
        if (( MAJOR >= 3 && MINOR >= 10 )); then
            PYTHON="$cmd"
            ok "Found $cmd ($VER)"
            break
        fi
    fi
done
[[ -n "$PYTHON" ]] || die "Python 3.10+ not found. Please install it first."

# ── 2. Virtual environment ────────────────────────────────────────────────────
VENV_DIR=".venv"
if [[ ! -d "$VENV_DIR" ]]; then
    log "Creating virtual environment in $VENV_DIR ..."
    "$PYTHON" -m venv "$VENV_DIR"
    ok "Virtual environment created"
else
    ok "Virtual environment already exists ($VENV_DIR)"
fi

# ── 3. Activate ───────────────────────────────────────────────────────────────
log "Activating virtual environment..."
if [[ -f "$VENV_DIR/bin/activate" ]]; then
    source "$VENV_DIR/bin/activate"          # Linux / macOS
elif [[ -f "$VENV_DIR/Scripts/activate" ]]; then
    source "$VENV_DIR/Scripts/activate"      # Windows Git Bash
else
    die "Could not find activate script in $VENV_DIR"
fi
ok "Virtual environment active  ($(python --version))"

# ── 4. Install requirements ───────────────────────────────────────────────────
log "Installing / updating requirements (this may take a few minutes first time)..."
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
ok "Requirements installed"

# ── 5. .env file ──────────────────────────────────────────────────────────────
if [[ ! -f ".env" ]]; then
    warn ".env not found — creating from template"
    cp .env.template .env
    echo ""
    warn "═══════════════════════════════════════════════════"
    warn "  ACTION REQUIRED:"
    warn "  Edit .env and add at least one AI provider key."
    warn "  The system runs in PAPER mode without a key."
    warn "  nano .env   OR   code .env"
    warn "═══════════════════════════════════════════════════"
    echo ""
else
    ok ".env found"
fi

# ── Ensure log directory ──────────────────────────────────────────────────────
mkdir -p logs

# ── 6. Launch trading engine ──────────────────────────────────────────────────
log "Starting trading engine..."
python main.py $LIVE_FLAG &
MAIN_PID=$!
ok "Trading engine started  (PID $MAIN_PID)"

# Give main.py a moment to write initial state before dashboard reads it
sleep 2

# ── 7. Launch dashboard ───────────────────────────────────────────────────────
log "Starting live dashboard..."
python dashboard/server.py &
DASH_PID=$!
ok "Dashboard started  (PID $DASH_PID)"

# ── Open browser (best-effort) ────────────────────────────────────────────────
PORT=$(python -c "from config.settings import settings; print(settings.DASHBOARD_PORT)" 2>/dev/null || echo "8080")
sleep 1
URL="http://localhost:$PORT"
echo ""
echo -e "${BOLD}${GREEN}  ╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}  ║  ✅  AlphaZero Capital is running!       ║${NC}"
echo -e "${BOLD}${GREEN}  ║                                           ║${NC}"
echo -e "${BOLD}${GREEN}  ║  Dashboard →  $URL          ║${NC}"
echo -e "${BOLD}${GREEN}  ║  Logs      →  logs/alphazero.log          ║${NC}"
echo -e "${BOLD}${GREEN}  ║                                           ║${NC}"
echo -e "${BOLD}${GREEN}  ║  Press Ctrl+C to stop everything          ║${NC}"
echo -e "${BOLD}${GREEN}  ╚══════════════════════════════════════════╝${NC}"
echo ""

# Try to open browser
if command -v xdg-open &>/dev/null; then
    xdg-open "$URL" &>/dev/null &
elif command -v open &>/dev/null; then
    open "$URL" &>/dev/null &
fi

# ── Wait and handle Ctrl+C ────────────────────────────────────────────────────
cleanup() {
    echo ""
    log "Shutting down..."
    kill "$MAIN_PID" 2>/dev/null && ok "Trading engine stopped"
    kill "$DASH_PID" 2>/dev/null && ok "Dashboard stopped"
    echo -e "${CYAN}Goodbye from AlphaZero Capital!${NC}"
    exit 0
}
trap cleanup SIGINT SIGTERM

# Keep script alive until both children exit or user presses Ctrl+C
wait "$MAIN_PID" "$DASH_PID"
