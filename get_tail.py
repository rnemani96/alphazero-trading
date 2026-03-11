import os
log_path = 'd:/files/ALPHAZERO_COMPLETE_FINAL/ALPHAZERO_COMPLETE/logs/alphazero.log'
try:
    with open(log_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        print(''.join(lines[-100:]))
except Exception as e:
    print(f"Error: {e}")
