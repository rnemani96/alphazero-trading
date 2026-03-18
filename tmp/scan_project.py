import os
import ast
import traceback

def scan_project(root_dir):
    syntax_errors = []
    stubs = []
    
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Skip certain directories
        dirnames[:] = [d for d in dirnames if d not in ('.git', '__pycache__', 'venv', 'env', 'node_modules')]
        
        for file in filenames:
            if file.endswith('.py'):
                file_path = os.path.join(dirpath, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        source = f.read()
                except Exception as e:
                    print(f"Error reading {file_path}: {e}")
                    continue
                
                try:
                    tree = ast.parse(source, filename=file_path)
                except SyntaxError as e:
                    syntax_errors.append((file_path, e.lineno, str(e)))
                    continue
                except Exception as e:
                    syntax_errors.append((file_path, 'unknown', str(e)))
                    continue
                
                # Walk the AST to find stubs (pass or NotImplementedError)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Pass):
                        stubs.append((file_path, getattr(node, 'lineno', '?'), 'pass statement'))
                    elif isinstance(node, ast.Raise):
                        if isinstance(node.exc, ast.Call) and getattr(node.exc.func, 'id', '') == 'NotImplementedError':
                            stubs.append((file_path, getattr(node, 'lineno', '?'), 'NotImplementedError'))
                        elif isinstance(node.exc, ast.Name) and node.exc.id == 'NotImplementedError':
                            stubs.append((file_path, getattr(node, 'lineno', '?'), 'NotImplementedError'))

    print("=== Syntax Errors ===")
    if not syntax_errors:
        print("None found!")
    for f, line, err in syntax_errors:
        print(f"{f}:{line} - {err}")
        
    print("\n=== Stubs ===")
    if not stubs:
        print("None found!")
    for f, line, kind in stubs:
        print(f"{f}:{line} - {kind}")

if __name__ == '__main__':
    scan_project(r"d:\files\ALPHAZERO_COMPLETE_FINAL\ALPHAZERO_COMPLETE")
