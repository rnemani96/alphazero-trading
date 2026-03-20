import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from .llm_provider import LLMProvider

logger = logging.getLogger("LLMPostMortem")

_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_DIR.mkdir(exist_ok=True)
_POST_MORTEM_FILE = _LOG_DIR / "post_mortems.jsonl"

def analyze_stopped_out_trade(trade: Dict[str, Any], market_context: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Analyzes a trade that hit its stop loss using an LLM to determine the likely root cause.
    Returns a dictionary with the analysis results and logs it to a JSONL file.
    """
    llm = LLMProvider.create(provider='claude')
    
    if not llm.is_available():
        logger.warning("LLMPostMortem: LLM not available. Skipping analysis.")
        return {"error": "LLM not configured"}
        
    market_context = market_context or {}
    
    system_prompt = (
        "You are an expert quantitative trading analyst. Analyze the following failed stock trade "
        "that hit its stop loss. Determine the most likely root cause from these categories: "
        "[FALSE_BREAKOUT, MARKET_DRAG, SECTOR_WEAKNESS, VOLATILITY_SPIKE, NEWS_EVENT, POOR_ENTRY]. "
        "Respond ONLY with a valid JSON object in this exact format: "
        "{\"root_cause\": \"...\", \"reasoning\": \"A 1-sentence explanation\", \"confidence_score\": 0.85}"
    )
    
    prompt = f"""
    Trade Details:
    - Symbol: {trade.get('symbol')}
    - Strategy: {trade.get('strategy')}
    - Entry Price: {trade.get('entry_price')}
    - Exit Price: {trade.get('exit_price', trade.get('current_price'))}
    - Stop Loss: {trade.get('stop_loss')}
    - Target: {trade.get('target')}
    - Hold Duration: {trade.get('days_open', 0)} days
    
    Market Context at Exit:
    - Market Regime: {market_context.get('regime', 'UNKNOWN')}
    - VIX: {market_context.get('vix', 'UNKNOWN')}
    - Sector: {trade.get('sector', 'UNKNOWN')}
    """
    
    logger.info(f"🧠 LLMPostMortem: Analyzing stopped out trade for {trade.get('symbol')}...")
    
    try:
        response = llm.complete(prompt=prompt, system=system_prompt, max_tokens=200)
        
        # Clean up response to ensure it's valid JSON
        # Sometimes LLMs wrap json in markdown block
        json_str = response.strip()
        if json_str.startswith("```json"):
            json_str = json_str[7:]
        if json_str.startswith("```"):
            json_str = json_str[3:]
        if json_str.endswith("```"):
            json_str = json_str[:-3]
            
        analysis = json.loads(json_str.strip())
        
        # Enrich with trade metadata
        result = {
            "timestamp": datetime.now().isoformat(),
            "trade_id": f"{trade.get('symbol')}_{trade.get('opened_at')}",
            "symbol": trade.get('symbol'),
            "strategy": trade.get('strategy'),
            "pnl_pct": trade.get('pnl_pct'),
            "analysis": analysis
        }
        
        # Log to file
        with open(_POST_MORTEM_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(result) + "\n")
            
        logger.info(f"✅ LLMPostMortem: {trade.get('symbol')} failed due to {analysis.get('root_cause')} (Conf: {analysis.get('confidence_score')})")
        return result
        
    except Exception as e:
        logger.error(f"LLMPostMortem Failed: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    # Test
    mock_trade = {
        "symbol": "RELIANCE",
        "strategy": "TITAN_MOMENTUM",
        "entry_price": 2500,
        "exit_price": 2400,
        "stop_loss": 2420,
        "target": 2600,
        "days_open": 3,
        "pnl_pct": -4.0,
        "opened_at": "2026-03-15T10:00:00"
    }
    print(analyze_stopped_out_trade(mock_trade, {"regime": "VOLATILE", "vix": 23.5}))
