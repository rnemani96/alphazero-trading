import ast

filename = r'd:\files\ALPHAZERO_COMPLETE_FINAL\ALPHAZERO_COMPLETE\src\agents\titan_agent.py'
with open(filename, 'r', encoding='utf-8') as f:
    source = f.read()

try:
    ast.parse(source)
    print("No syntax error found by AST parse.")
except SyntaxError as e:
    print(f"Syntax Error: {e.msg}")
    print(f"Line: {e.lineno}")
    print(f"Offset: {e.offset}")
    print(f"Text: {e.text}")
