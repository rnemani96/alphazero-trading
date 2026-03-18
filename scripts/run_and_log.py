import subprocess
import os
import sys
from datetime import datetime

log_file = "logs/startup_debug.log"
print(f"Starting main.py and logging to {log_file}...")

with open(log_file, "w") as f:
    f.write(f"--- Startup Debug {datetime.now()} ---\n")
    f.flush()
    try:
        proc = subprocess.Popen(
            [sys.executable, "main.py"],
            stdout=f,
            stderr=subprocess.STDOUT,
            cwd=os.getcwd(),
            universal_newlines=True,
            bufsize=1 # Line buffered
        )
        print(f"Process started with PID {proc.pid}")
    except Exception as e:
        f.write(f"Failed to start: {e}\n")
        print(f"Failed to start: {e}")
