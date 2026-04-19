from pathlib import Path

path = Path(r"D:\files\ALPHAZERO_COMPLETE_FINAL\ALPHAZERO_COMPLETE\dashboard\alphazero_v5.html")
try:
    content = path.read_text(encoding="utf-8")
    print("Successfully read with utf-8")
except UnicodeDecodeError as e:
    print(f"UnicodeDecodeError: {e}")
    # Try reading with errors='replace' to see what's there
    content = path.read_bytes()
    # Find the position
    pos = 77425
    snippet = content[max(0, pos-20):min(len(content), pos+20)]
    print(f"Bytes around {pos}: {snippet.hex(' ')}")
    try:
        print(f"Decoded snippet (replace): {snippet.decode('utf-8', errors='replace')}")
    except Exception as e2:
        print(f"Could not decode snippet: {e2}")
