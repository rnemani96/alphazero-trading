import ast
import os
import sys

errors = []
ok = 0

for root, dirs, files in os.walk("src"):
    dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git']]
    for fname in files:
        if fname.endswith(".py"):
            path = os.path.join(root, fname)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    src = f.read()
                ast.parse(src, filename=path)
                ok += 1
            except SyntaxError as e:
                errors.append(f"SYNTAX ERROR in {path}: Line {e.lineno} — {e.msg}")

# Also check main.py, run_paper.py, dashboard
for extra in ["main.py", "run_paper.py"]:
    if os.path.exists(extra):
        try:
            with open(extra, "r", encoding="utf-8", errors="replace") as f:
                src = f.read()
            ast.parse(src, filename=extra)
            ok += 1
        except SyntaxError as e:
            errors.append(f"SYNTAX ERROR in {extra}: Line {e.lineno} — {e.msg}")

for root, dirs, files in os.walk("dashboard"):
    dirs[:] = [d for d in dirs if d not in ['__pycache__']]
    for fname in files:
        if fname.endswith(".py"):
            path = os.path.join(root, fname)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    src = f.read()
                ast.parse(src, filename=path)
                ok += 1
            except SyntaxError as e:
                errors.append(f"SYNTAX ERROR in {path}: Line {e.lineno} — {e.msg}")

print(f"\n{'='*60}")
print(f"Syntax check complete: {ok} files OK, {len(errors)} errors")
if errors:
    print("\nERRORS FOUND:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
else:
    print("All files passed syntax check!")
