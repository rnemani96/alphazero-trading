import os

def find_downloads():
    for root, dirs, files in os.walk(r'd:\files\ALPHAZERO_COMPLETE_FINAL\ALPHAZERO_COMPLETE'):
        for file in files:
            if file.endswith('.py'):
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        if 'download(' in content or 'yfinance' in content:
                            print(f"FOUND IN: {path}")
                except Exception as e:
                    pass

if __name__ == '__main__':
    find_downloads()
