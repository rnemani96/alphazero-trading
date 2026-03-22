import ast
import os
from pathlib import Path

def extract_info(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return f"Error reading {file_path}: {e}"

    try:
        tree = ast.parse(content)
    except SyntaxError as e:
        return f"Syntax error in {file_path}: {e}"

    results = []
    
    # Check for module docstring
    module_doc = ast.get_docstring(tree)
    if module_doc:
        results.append(f"  *Description*: {module_doc.splitlines()[0]}")

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_name = node.name
            class_doc = ast.get_docstring(node)
            results.append(f"### Class: `{class_name}`")
            if class_doc:
                results.append(f"  * {class_doc.splitlines()[0]}")
            
            methods = []
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    method_name = item.name
                    method_doc = ast.get_docstring(item)
                    methods.append(f"  - `{method_name}()`" + (f": {method_doc.splitlines()[0]}" if method_doc else ""))
            
            if methods:
                results.extend(methods)
        
        elif isinstance(node, ast.FunctionDef):
            func_name = node.name
            func_doc = ast.get_docstring(node)
            results.append(f"### Function: `{func_name}()`")
            if func_doc:
                results.append(f"  * {func_doc.splitlines()[0]}")
                
    return "\n".join(results)

def main():
    root_dir = Path(r"d:\files\ALPHAZERO_COMPLETE_FINAL\ALPHAZERO_COMPLETE")
    output_path = root_dir / "tmp" / "project_structure_report.md"
    
    report = ["# AlphaZero Capital - Project Structure Reference\n"]
    
    # Sort files to make it organized
    all_files = []
    for root, dirs, files in os.walk(root_dir):
        # Skip node_modules and hidden dirs
        if "node_modules" in root or ".git" in root or "__pycache__" in root:
            continue
            
        for name in files:
            if name.endswith(".py"):
                all_files.append(Path(root) / name)
                
    all_files.sort()
    
    current_root = None
    for file_path in all_files:
        rel_path = file_path.relative_to(root_dir)
        dir_name = os.path.dirname(rel_path)
        
        if dir_name != current_root:
            report.append(f"\n## Directory: `{dir_name if dir_name else 'Root'}`\n")
            current_root = dir_name
            
        report.append(f"### File: `{os.path.basename(rel_path)}`")
        info = extract_info(file_path)
        if info:
            report.append(info)
        report.append("\n---\n")
        
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
        
    print(f"Report generated at: {output_path}")

if __name__ == "__main__":
    main()
