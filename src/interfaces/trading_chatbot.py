"""
src/interfaces/trading_chatbot.py
═════════════════════════════════
Phase 7: Interactive Chatbot Integration & Manual Override Engine.

Provides an interactive conversational AI interface for the AlphaZero trading system.
Powered by the Universal LLM Gateway (local Ollama with gemma3/llama3 or any cloud API).

Supported Tool Capabilities:
  1. portfolio_status()      — Real-time open positions, P&L, and margin allocation
  2. analyze_symbol(sym)     — Quantitative breakdown: Trend Velocity P(Rise), RSI, VWAP, ATR
  3. market_regime()         — Current NEXUS regime, India VIX, Options PCR, and Market Breadth
  4. execute_trade(...)      — EventBus manual trade override bypassing normal scheduling
  5. get_signals()           — Latest high-conviction signals from TITAN and Ensemble
"""

from __future__ import annotations
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..agents.llm_provider import LLMProvider

logger = logging.getLogger("TradingChatbot")

_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"


class TradingChatbot:
    """
    Conversational AI assistant for AlphaZero Capital.
    """

    def __init__(self, agents: Optional[Dict[str, Any]] = None, event_bus: Optional[Any] = None):
        self.agents = agents or {}
        self.event_bus = event_bus
        self.llm = LLMProvider.create()
        logger.info(f"TradingChatbot initialized with LLM: {self.llm}")

    def chat(self, user_message: str) -> Dict[str, Any]:
        """
        Processes a user message, runs appropriate quantitative tools,
        and generates an intelligent financial response.
        """
        user_message_clean = user_message.strip()
        lower_msg = user_message_clean.lower()

        # ── 1. Tool Routing & Intent Detection ──
        tool_results: Dict[str, Any] = {}
        tool_executed = None

        # Check for trade execution intent: "buy 10 shares of RELIANCE" or "sell 5 INFY"
        trade_match = re.search(r"\b(buy|sell)\s+(\d+)\s+(?:shares?\s+of\s+)?([a-zA-Z0-9_\-\.]+)", lower_msg)
        if trade_match:
            action = trade_match.group(1).upper()
            qty = int(trade_match.group(2))
            sym = trade_match.group(3).upper()
            tool_executed = "execute_trade"
            tool_results["execution"] = self._tool_execute_trade(sym, action, qty)

        # Check for symbol analysis intent: "analyze RELIANCE", "what about TCS", "predict HDFCBANK"
        elif any(k in lower_msg for k in ["analyze", "prediction", "predict", "forecast", "look at", "check"]) and len(user_message_clean.split()) <= 6:
            # Extract ticker symbol
            words = [w.strip("?,.!") for w in user_message_clean.split()]
            candidate_syms = [w.upper() for w in words if len(w) >= 3 and w.upper() not in ["WHAT", "ABOUT", "ANALYZE", "CHECK", "PREDICT", "FORECAST", "LOOK", "TELL", "TODAY", "STOCK"]]
            if candidate_syms:
                sym = candidate_syms[-1]
                tool_executed = "analyze_symbol"
                tool_results["analysis"] = self._tool_analyze_symbol(sym)

        # Check for portfolio status: "positions", "portfolio", "pnl", "profit", "holding"
        elif any(k in lower_msg for k in ["portfolio", "positions", "holdings", "pnl", "p&l", "profit", "loss"]):
            tool_executed = "portfolio_status"
            tool_results["portfolio"] = self._tool_get_portfolio()

        # Check for market regime: "regime", "market", "vix", "nifty", "trend"
        elif any(k in lower_msg for k in ["regime", "market", "vix", "sentiment", "outlook"]):
            tool_executed = "market_regime"
            tool_results["market"] = self._tool_get_market_regime()

        # Check for active signals: "signals", "candidates", "picks", "recommendations"
        elif any(k in lower_msg for k in ["signals", "picks", "candidates", "ideas", "opportunities"]):
            tool_executed = "get_signals"
            tool_results["signals"] = self._tool_get_signals()

        # ── 2. LLM Synthesis ──
        system_prompt = (
            "You are AlphaZero AI, an elite institutional quantitative trading intelligence assistant. "
            "You help the trader manage their portfolio, analyze NSE Indian equities, interpret market regimes, "
            "and execute algorithmic strategies. Be precise, concise, and provide actionable mathematical insights. "
            "Always include relevant metrics (P&L, VIX, confidence, win rate, or prices) when available."
        )

        context_str = json.dumps(tool_results, indent=2, default=str) if tool_results else "No specific tool output."
        prompt = (
            f"User Query: {user_message_clean}\n\n"
            f"Trading System Live Context:\n{context_str}\n\n"
            "Provide a clear, professional quantitative response to the user."
        )

        try:
            if self.llm.is_available():
                response_text = self.llm.complete(prompt=prompt, system=system_prompt, max_tokens=600)
            else:
                response_text = self._fallback_response(tool_executed, tool_results, user_message_clean)
        except Exception as e:
            logger.error(f"Chatbot LLM completion error: {e}")
            response_text = self._fallback_response(tool_executed, tool_results, user_message_clean)

        return {
            "status": "ok",
            "query": user_message_clean,
            "response": response_text,
            "tool_executed": tool_executed,
            "tool_data": tool_results,
            "timestamp": datetime.now().isoformat(),
        }

    # ── Tool Implementations ──
    def _tool_get_portfolio(self) -> Dict[str, Any]:
        """Returns active portfolio summary."""
        try:
            from ..risk.active_portfolio import get_active_portfolio
            ap = get_active_portfolio()
            positions = [
                {
                    "symbol": p.get("symbol"),
                    "action": p.get("action", "BUY"),
                    "qty": p.get("quantity"),
                    "entry_price": p.get("entry_price"),
                    "current_price": p.get("current_price"),
                    "unrealized_pnl": p.get("unrealised_pnl", 0),
                    "stop_loss": p.get("stop_loss"),
                    "target": p.get("target"),
                    "strategy": p.get("strategy"),
                }
                for p in ap.open_positions.values()
            ]
            total_unrealized = sum(p.get("unrealized_pnl", 0) for p in positions)
            return {
                "open_positions_count": len(positions),
                "open_positions": positions,
                "total_unrealized_pnl": round(total_unrealized, 2),
                "realized_pnl": round(ap.realised_pnl, 2),
            }
        except Exception as e:
            return {"error": str(e), "open_positions_count": 0}

    def _tool_analyze_symbol(self, symbol: str) -> Dict[str, Any]:
        """Runs quantitative analysis on a specific symbol."""
        symbol = symbol.upper()
        res: Dict[str, Any] = {"symbol": symbol}
        try:
            from ..data.multi_source_data import MultiSourceData
            msd = MultiSourceData()
            quotes = msd.get_bulk_quotes([symbol])
            q = quotes.get(symbol, {})
            price = float(q.get("price", q.get("ltp", 0)))
            res["current_price"] = price
            res["change_pct"] = float(q.get("change_pct", 0))

            # Fetch candles for Trend Velocity Prediction
            candles = msd.get_candles(symbol, interval="15min", limit=40)
            if candles and len(candles) >= 15:
                import pandas as pd
                from ..data.trend_velocity_predictor import TrendVelocityPredictor
                data = [{"close": c.close, "high": c.high, "low": c.low, "open": c.open, "volume": c.volume} for c in candles]
                df = pd.DataFrame(data)
                pred = TrendVelocityPredictor.predict_direction(df, symbol=symbol)
                res["trend_prediction"] = pred
            else:
                res["trend_prediction"] = {"predicted_direction": "NEUTRAL", "rise_probability": 0.50}
        except Exception as e:
            res["error"] = str(e)
        return res

    def _tool_get_market_regime(self) -> Dict[str, Any]:
        """Returns current market regime, VIX, and breadth."""
        status_file = _LOG_DIR / "status.json"
        if status_file.exists():
            try:
                with open(status_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return {
                        "regime": data.get("regime", "TRENDING"),
                        "sentiment": data.get("sentiment", 0.5),
                        "india_vix": data.get("macro", {}).get("vix", 15.0),
                        "net_pnl": data.get("net_pnl", 0.0),
                        "win_rate": data.get("win_rate", 0.65),
                    }
            except Exception:
                pass
        return {"regime": "TRENDING", "india_vix": 14.5, "sentiment": 0.55}

    def _tool_get_signals(self) -> Dict[str, Any]:
        """Returns recent high-conviction candidate signals."""
        signals_file = _LOG_DIR / "signals.json"
        if signals_file.exists():
            try:
                with open(signals_file, "r", encoding="utf-8") as f:
                    sigs = json.load(f)
                    return {"active_signals": sigs[:5] if isinstance(sigs, list) else []}
            except Exception:
                pass
        return {"active_signals": []}

    def _tool_execute_trade(self, symbol: str, action: str, quantity: int) -> Dict[str, Any]:
        """Manual trade execution override."""
        try:
            from ..data.multi_source_data import MultiSourceData
            msd = MultiSourceData()
            quotes = msd.get_bulk_quotes([symbol])
            price = float(quotes.get(symbol, {}).get("price", 100.0))

            trade_signal = {
                "symbol": symbol,
                "action": action,
                "quantity": quantity,
                "price": price,
                "strategy": "MANUAL_CHAT_OVERRIDE",
                "stop_loss": round(price * 0.98 if action == "BUY" else price * 1.02, 2),
                "target": round(price * 1.05 if action == "BUY" else price * 0.95, 2),
                "timestamp": datetime.now().isoformat(),
            }

            # Execute via Mercury agent if available
            if self.agents.get("MERCURY") and hasattr(self.agents["MERCURY"], "execute_trade"):
                result = self.agents["MERCURY"].execute_trade(trade_signal)
                return {"executed": True, "details": result or trade_signal}

            return {"executed": True, "mode": "PAPER", "details": trade_signal}
        except Exception as e:
            return {"executed": False, "error": str(e)}

    def _fallback_response(self, tool_executed: Optional[str], data: Dict[str, Any], query: str) -> str:
        """Deterministic rule-based response when LLM is offline."""
        if tool_executed == "portfolio_status":
            p = data.get("portfolio", {})
            return (
                f"📊 **Portfolio Overview**\n"
                f"• Open Positions: {p.get('open_positions_count', 0)}\n"
                f"• Unrealized P&L: ₹{p.get('total_unrealized_pnl', 0):+,.2f}\n"
                f"• Realized P&L: ₹{p.get('realized_pnl', 0):+,.2f}"
            )
        elif tool_executed == "market_regime":
            m = data.get("market", {})
            return (
                f"🌊 **Market State**\n"
                f"• Regime: **{m.get('regime', 'TRENDING')}**\n"
                f"• India VIX: {m.get('india_vix', 15.0):.1f}\n"
                f"• System Win Rate: {m.get('win_rate', 0.65):.1%}"
            )
        elif tool_executed == "execute_trade":
            e = data.get("execution", {})
            return f"✅ **Manual Trade Executed**: {e.get('details', {})}"
        return f"AlphaZero AI received your request: '{query}'. System is running normally."
