import json
import sys

def main():
    try:
        from main import _build_universe
        u = _build_universe()
        with open("univ.json", "w") as f:
            json.dump(u, f, indent=2)
        print("OK")
    except Exception as e:
        with open("univ.json", "w") as f:
            f.write(str(e))

if __name__ == "__main__":
    main()
