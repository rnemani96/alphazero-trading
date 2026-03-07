#!/bin/bash

# AlphaZero Capital - Startup Script

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 AlphaZero Capital v17.0 - Starting..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
    echo "✅ Virtual environment activated"
else
    echo "❌ Virtual environment not found!"
    echo "   Run ./install.sh first"
    exit 1
fi

# Check .env
if [ ! -f ".env" ]; then
    echo "❌ .env file not found!"
    echo "   Copy .env.template to .env and configure"
    exit 1
fi

# Load environment
export $(cat .env | grep -v '^#' | xargs)
echo "✅ Environment loaded"

# Check Redis
echo ""
echo "🔴 Checking Redis..."
if redis-cli ping &> /dev/null; then
    echo "✅ Redis is running"
else
    echo "⚠️  Redis not responding"
    echo "   Attempting to start Redis..."
    
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew services start redis 2>/dev/null || redis-server &
    elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
        sudo systemctl start redis 2>/dev/null || redis-server &
    fi
    
    sleep 2
    
    if redis-cli ping &> /dev/null; then
        echo "✅ Redis started"
    else
        echo "❌ Redis failed to start"
        echo "   Start manually: redis-server"
        exit 1
    fi
fi

# Create logs directory
mkdir -p logs

# Display configuration
echo ""
echo "📊 Configuration:"
echo "   Mode: ${MODE:-PAPER}"
echo "   AI Provider: ${LLM_PROVIDER:-Auto-detect}"
echo "   Capital: ₹${INITIAL_CAPITAL:-1000000}"
echo "   Options Flow: ${ENABLE_OPTIONS_FLOW:-true}"
echo "   Multi-Timeframe: ${ENABLE_MULTI_TIMEFRAME:-true}"
echo "   LLM Agents: ${ENABLE_LLM_AGENTS:-true}"
echo ""

# Check AI provider
echo "🤖 Checking AI Provider..."
if [ -n "$ANTHROPIC_API_KEY" ]; then
    echo "   ✅ Claude (Anthropic) available"
elif [ -n "$OPENAI_API_KEY" ]; then
    echo "   ✅ GPT-4 (OpenAI) available"
elif [ -n "$GOOGLE_API_KEY" ]; then
    echo "   ✅ Gemini (Google) available"
else
    echo "   ℹ️  No AI provider configured"
    echo "   Will use local model (free)"
fi
echo ""

# Start system
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎯 Starting Trading System..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📝 Logs: logs/alphazero.log"
echo "🛑 Stop: Press Ctrl+C"
echo ""

# Run main
python main.py

# Cleanup on exit
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "👋 AlphaZero Capital stopped"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
