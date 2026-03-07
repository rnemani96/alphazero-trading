#!/bin/bash

# AlphaZero Capital - Installation Script
# Installs all dependencies including TA-Lib

set -e  # Exit on error

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 AlphaZero Capital - Installation Script"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check Python version
echo "📌 Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "   Found: Python $python_version"

if ! python3 -c 'import sys; exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    echo "   ❌ Error: Python 3.10+ required"
    exit 1
fi
echo "   ✅ Python version OK"
echo ""

# Create virtual environment
echo "📦 Creating virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "   ✅ Virtual environment created"
else
    echo "   ℹ️  Virtual environment already exists"
fi
echo ""

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source venv/bin/activate
echo "   ✅ Activated"
echo ""

# Upgrade pip
echo "⬆️  Upgrading pip..."
pip install --upgrade pip setuptools wheel --quiet
echo "   ✅ Pip upgraded"
echo ""

# Install TA-Lib (if possible)
echo "📊 Installing TA-Lib..."
echo "   This might take a few minutes..."

# Detect OS
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    echo "   Detected: macOS"
    if command -v brew &> /dev/null; then
        echo "   Installing TA-Lib via Homebrew..."
        brew install ta-lib 2>/dev/null || echo "   ⚠️  Homebrew install failed (may already be installed)"
    else
        echo "   ⚠️  Homebrew not found. Install manually:"
        echo "      brew install ta-lib"
    fi
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    echo "   Detected: Linux"
    if command -v apt-get &> /dev/null; then
        echo "   Installing TA-Lib via apt..."
        sudo apt-get update -qq
        sudo apt-get install -y ta-lib 2>/dev/null || {
            echo "   ⚠️  apt install failed. Building from source..."
            wget -q http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
            tar -xzf ta-lib-0.4.0-src.tar.gz
            cd ta-lib/
            ./configure --prefix=/usr > /dev/null
            make > /dev/null
            sudo make install > /dev/null
            cd ..
            rm -rf ta-lib ta-lib-0.4.0-src.tar.gz
        }
    fi
fi

# Try to install TA-Lib Python wrapper
echo "   Installing TA-Lib Python wrapper..."
if pip install TA-Lib --quiet 2>/dev/null; then
    echo "   ✅ TA-Lib installed successfully"
else
    echo "   ⚠️  TA-Lib installation failed"
    echo "   📝 Will use pandas-ta as backup"
fi
echo ""

# Install main requirements
echo "📚 Installing Python dependencies..."
echo "   This will take 2-5 minutes..."

# Install requirements
pip install -r requirements.txt --quiet

echo "   ✅ All dependencies installed"
echo ""

# Create necessary directories
echo "📁 Creating directory structure..."
mkdir -p logs
mkdir -p data
mkdir -p data/raw
mkdir -p data/clean
mkdir -p data/features
mkdir -p models
echo "   ✅ Directories created"
echo ""

# Check for .env file
echo "⚙️  Checking configuration..."
if [ ! -f ".env" ]; then
    echo "   Creating .env from template..."
    cp .env.template .env
    echo "   ⚠️  IMPORTANT: Edit .env and add your API keys!"
    echo "   ✅ .env created"
else
    echo "   ✅ .env file found"
fi
echo ""

# Check Redis
echo "🔴 Checking Redis..."
if command -v redis-cli &> /dev/null; then
    if redis-cli ping &> /dev/null; then
        echo "   ✅ Redis is running"
    else
        echo "   ⚠️  Redis installed but not running"
        echo "      Start with: redis-server"
    fi
else
    echo "   ⚠️  Redis not found"
    echo "      Install:"
    echo "        macOS: brew install redis && brew services start redis"
    echo "        Ubuntu: sudo apt install redis-server && sudo systemctl start redis"
fi
echo ""

# Test imports
echo "🧪 Testing critical imports..."
python3 << PYEOF
import sys
success = []
failed = []

# Test imports
try:
    import numpy
    success.append('numpy')
except:
    failed.append('numpy')

try:
    import pandas
    success.append('pandas')
except:
    failed.append('pandas')

try:
    import pandas_ta
    success.append('pandas-ta')
except:
    failed.append('pandas-ta')

try:
    import talib
    success.append('TA-Lib')
except:
    failed.append('TA-Lib (will use pandas-ta)')

try:
    import anthropic
    success.append('anthropic')
except:
    pass  # Optional

try:
    import openai
    success.append('openai')
except:
    pass  # Optional

try:
    import redis
    success.append('redis')
except:
    failed.append('redis')

try:
    import streamlit
    success.append('streamlit')
except:
    failed.append('streamlit')

if success:
    print(f"   ✅ Working: {', '.join(success)}")

if failed:
    print(f"   ⚠️  Issues: {', '.join(failed)}")
    sys.exit(1)
PYEOF

if [ $? -eq 0 ]; then
    echo "   ✅ All imports successful"
else
    echo "   ❌ Some imports failed - check errors above"
fi
echo ""

# Summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Installation Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📝 Next steps:"
echo ""
echo "   1. Edit .env file with your API keys:"
echo "      nano .env"
echo ""
echo "   2. Choose an AI provider (at least one):"
echo "      • ANTHROPIC_API_KEY=sk-ant-...  (Claude - best quality)"
echo "      • OPENAI_API_KEY=sk-...         (GPT-4 - excellent)"
echo "      • GOOGLE_API_KEY=...            (Gemini - cheapest)"
echo "      • Or leave blank for local model (free)"
echo ""
echo "   3. Start the system:"
echo "      python main.py"
echo ""
echo "   4. Or use startup script:"
echo "      ./start.sh"
echo ""
echo "   5. View dashboard:"
echo "      streamlit run dashboard.py"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 Ready to trade!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
