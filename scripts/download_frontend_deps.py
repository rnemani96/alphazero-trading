"""
Download React, ReactDOM, and Babel Standalone scripts for local serving.
Run once: python scripts/download_frontend_deps.py
"""
import os, urllib.request, ssl

STATIC_DIR = os.path.join(os.path.dirname(__file__), '..', 'dashboard', 'static')
os.makedirs(STATIC_DIR, exist_ok=True)

# Bypass SSL verification issues on some Windows setups
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

DEPS = {
    "react.production.min.js":     "https://unpkg.com/react@18/umd/react.production.min.js",
    "react-dom.production.min.js": "https://unpkg.com/react-dom@18/umd/react-dom.production.min.js",
    "babel.min.js":                "https://unpkg.com/@babel/standalone/babel.min.js",
}

for filename, url in DEPS.items():
    dest = os.path.join(STATIC_DIR, filename)
    if os.path.exists(dest):
        print(f"  ✓ {filename} already exists ({os.path.getsize(dest)//1024}KB)")
        continue
    print(f"  ↓ Downloading {filename} from {url}...")
    try:
        urllib.request.urlretrieve(url, dest)
        print(f"  ✓ {filename} saved ({os.path.getsize(dest)//1024}KB)")
    except Exception as e:
        print(f"  ✗ Failed to download {filename}: {e}")

print("\nDone! Scripts saved to dashboard/static/")
print("The backend serves them at /static/<filename>")
