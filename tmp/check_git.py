import subprocess
try:
    result = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True)
    print(f"COMMIT_HASH:{result.stdout.strip()}")
except Exception as e:
    print(f"ERROR:{e}")
