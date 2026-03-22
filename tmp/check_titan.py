import py_compile
try:
    py_compile.compile('src/agents/titan_agent.py', doraise=True)
    print("OK")
except Exception as e:
    print(e)
