import ast
import traceback
try:
    with open("src/agents/titan_agent.py", "r", encoding="utf-8") as f:
        ast.parse(f.read(), filename="src/agents/titan_agent.py")
    with open("err_titan.txt", "w") as f:
        f.write("NO ERROR")
except SyntaxError as e:
    with open("err_titan.txt", "w") as f:
        f.write(traceback.format_exc())
