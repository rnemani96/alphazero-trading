import ast
try:
    with open('src/agents/titan_agent.py', 'r', encoding='utf-8') as f:
        ast.parse(f.read(), filename='src/agents/titan_agent.py')
    print("NO SYNTAX ERROR")
except SyntaxError as e:
    import traceback
    traceback.print_exc()
