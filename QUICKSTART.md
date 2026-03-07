# 🚀 Quick Start Guide

## In 60 Seconds:

```bash
# 1. Extract
tar -xzf alphazero_FINAL.tar.gz
cd alphazero_FINAL

# 2. Install
./install.sh

# 3. Configure
cp .env.template .env
nano .env  # Add at least ONE AI provider key

# 4. Run!
python main.py
```

## AI Provider Setup (Choose ONE):

### Option 1: Claude (Best Quality)
```bash
ANTHROPIC_API_KEY=sk-ant-your-key-here
```
Get key: https://console.anthropic.com/

### Option 2: GPT-4 (Excellent)
```bash
OPENAI_API_KEY=sk-your-key-here
```
Get key: https://platform.openai.com/api-keys

### Option 3: Gemini (Cheapest - $10/month)
```bash
GOOGLE_API_KEY=your-key-here
```
Get key: https://makersuite.google.com/app/apikey

### Option 4: Local Model (FREE!)
```bash
# Leave all API keys blank
# System will download and run Llama locally
```

## That's It!

System will:
- ✅ Initialize 16 agents
- ✅ Start paper trading
- ✅ Monitor markets every 15 min
- ✅ Generate signals
- ✅ Execute trades automatically

View dashboard: `streamlit run dashboard.py`

**You're now running an autonomous hedge fund!** 🎉
