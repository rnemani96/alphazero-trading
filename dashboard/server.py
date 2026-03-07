"""
AlphaZero Capital - Dashboard Server
dashboard/server.py

Serves the live trading dashboard at http://localhost:8080
- GET /           → dashboard.html
- GET /api/status → live JSON state (polled by dashboard every 5 s)
- GET /api/health → quick health check

Run:
    python dashboard/server.py
"""

import os
import sys
import json
import logging
from datetime import datetime

# Make sure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask, jsonify, send_from_directory, Response

# Live state reader
try:
    from src.monitoring.state import read as read_state
except ImportError:
    def read_state():
        state_file = os.path.join(os.path.dirname(__file__), '..', 'logs', 'status.json')
        try:
            with open(state_file) as f:
                return json.load(f)
        except Exception:
            return {'system': {'status': 'STARTING'}}

try:
    from config.settings import settings
    HOST = settings.DASHBOARD_HOST
    PORT = settings.DASHBOARD_PORT
except ImportError:
    HOST = '0.0.0.0'
    PORT = 8080

logging.basicConfig(level=logging.INFO, format='%(asctime)s [DASH] %(message)s')
logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    static_folder=os.path.dirname(__file__),
    static_url_path=''
)

DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    """Serve the main dashboard HTML."""
    return send_from_directory(DASHBOARD_DIR, 'dashboard.html')


@app.route('/api/status')
def api_status():
    """Return live system state as JSON — polled by dashboard every 5 s."""
    state = read_state()
    resp = jsonify(state)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


@app.route('/api/health')
def api_health():
    """Quick health check endpoint."""
    return jsonify({
        'status': 'ok',
        'server': 'AlphaZero Dashboard',
        'time':   datetime.now().isoformat()
    })


@app.after_request
def add_cors(response: Response) -> Response:
    """Allow local CORS for development."""
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    logger.info(f"🌐 Dashboard starting at http://localhost:{PORT}")
    logger.info(f"   Open your browser: http://localhost:{PORT}")
    app.run(host=HOST, port=PORT, debug=False, use_reloader=False)
