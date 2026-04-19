from pathlib import Path

path = Path(r"D:\files\ALPHAZERO_COMPLETE_FINAL\ALPHAZERO_COMPLETE\dashboard\alphazero_v5.html")
out_path = Path(r"D:\files\ALPHAZERO_COMPLETE_FINAL\ALPHAZERO_COMPLETE\scratch\debug_out.txt")

try:
    content = path.read_bytes()
    pos = 77425
    snippet = content[max(0, pos-50):min(len(content), pos+50)]
    
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"Hex: {snippet.hex(' ')}\n")
        f.write(f"Decoded (replace): {snippet.decode('utf-8', errors='replace')}\n")
        f.write(f"Position character: {hex(content[pos]) if pos < len(content) else 'EOF'}\n")
except Exception as e:
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"Error: {str(e)}\n")
