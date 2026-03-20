import subprocess
import os

try:
    result = subprocess.run(['git', 'status'], capture_output=True, text=True, check=True)
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)
except Exception as e:
    print("Error:", e)
