import sys, traceback
try:
    import src.agents.titan_agent
    print("OK")
except SyntaxError as e:
    with open("err.txt", "w") as f:
        f.write(traceback.format_exc())
    print("SyntaxError")
except Exception as e:
    with open("err.txt", "w") as f:
        f.write(traceback.format_exc())
    print("Exception")
