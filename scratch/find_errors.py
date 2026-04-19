path = r"D:\files\ALPHAZERO_COMPLETE_FINAL\ALPHAZERO_COMPLETE\dashboard\alphazero_v5.html"
data = open(path, "rb").read()

errors = []
start = 0
while True:
    try:
        data[start:].decode("utf-8")
        break
    except UnicodeDecodeError as e:
        pos = start + e.start
        errors.append((pos, data[pos:pos+5].hex(" ")))
        start = pos + 1
        if len(errors) > 20: break

print(f"Found {len(errors)} errors:")
for p, h in errors:
    print(f"At {p}: {h}")
